"""Local file upload connector — CSV, Parquet, Excel materialized into DuckDB.

No external dependencies — DuckDB handles all file formats natively.

DSN:   local://  (sentinel; storage is vended by the control plane, tenant-scoped)

Storage layout (tenant-pathed, schema-aware)::

    data/uploads/{org_id}/{connection_id}/
        main/                       # default schema
            sales.csv
            sales.csv.import.json   # {"table_name","schema","column_types"}
        finance/
            ledger.parquet

The {org_id} segment is resolved via aughor.control_plane.vending.vend_storage (§5.1);
this connector never joins the upload root directly.
            ledger.parquet.import.json

Each *schema* is a sub-directory; each data file becomes one table inside that
schema. A sidecar ``*.import.json`` records the chosen table name and any
per-column type overrides so the in-memory DuckDB can be rebuilt identically on
every request (the connector is constructed fresh per request and reloads from
disk).

Typical use::

    conn = LocalUploadConnection(dsn="local://", connection_id="workspace")
    info = conn.analyze_file(Path("/tmp/sales.csv"))      # preview + type hints
    conn.ingest_file(Path("/tmp/sales.csv"),
                     table_name="sales", schema="finance",
                     column_types={"id": "BIGINT", "ts": "TIMESTAMP"})
    conn.execute("inv1", "SELECT * FROM finance.sales LIMIT 10")
"""
from __future__ import annotations

import json
import logging
import re
import threading
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from aughor.db.single_flight import single_flight_build
from aughor.connectors.base import Connector
from aughor.control_plane.contracts.execution import QueryResult
from aughor.control_plane.vending import STORAGE_ROOT, vend_storage
# Numbers stored as text ('₹1,099', '64%', '24,269') are re-typed at ingest. The
# detection primitives are shared with the runtime trust gate — see
# aughor.sql.numeric_text for why this matters and how the shape gate stays safe.
from aughor.sql.numeric_text import (
    COSTUME_CAST_TYPES as _COSTUME_CAST_TYPES,
    costume_clean_sql as _costume_clean_sql,
    costume_kind as _costume_kind,
    detect_costume as _detect_costume,
)

logger = logging.getLogger(__name__)

MAX_ROWS = 2000
# The managed-storage root; single source of truth lives in the vending seam.
# Paths are resolved per-connection via vend_storage() (tenant-scoped), not by
# joining this directly — kept as an alias for back-compat callers.
_UPLOAD_ROOT = STORAGE_ROOT
DEFAULT_SCHEMA = "main"

# A removed-seed tombstone: seed schemas/tables are re-materialized on every connector
# construction, so deleting one only sticks if we persist that it was removed and skip it on
# the next re-seed. Lives in the connection's upload dir alongside the user files.
_TOMBSTONE_FILE = "_removed_seeds.json"

# Serializes ATTACH/DETACH of the shared seed file. The connector is constructed
# fresh per request, so without this two concurrent requests race on the same
# samples.duckdb and one silently materializes nothing (missing-sample-data bug).
_SEED_LOCK = threading.Lock()

_SUPPORTED_EXTENSIONS = {
    ".csv":     "read_csv_auto",
    ".tsv":     "read_csv_auto",
    ".parquet": "read_parquet",
    ".parq":    "read_parquet",
    # `read_excel` does not exist — the function DuckDB ships in its `excel`
    # extension is `read_xlsx`. Every spreadsheet upload failed on
    # "Table Function with name read_excel does not exist", which the API then
    # reported as a bare "Analyze failed".
    ".xlsx":    "read_xlsx",
    ".xls":     "read_xlsx",
    ".json":    "read_json_auto",
}

# DuckDB reads UTF-8 and refuses anything else with "Invalid unicode (byte sequence
# mismatch) detected. This file is not utf-8 encoded", and a CSV exported from Excel
# on Windows is cp1252 — one accented character was enough to fail an upload.
#
# `latin-1` is DuckDB's name for the single-byte Western European family and decodes
# cp1252/ISO-8859-1 bytes; DuckDB rejects both of THOSE as encoding names, so do not
# "fix" this by adding them.
#
# The fallback CANNOT be an ordered try-list, which is what this was first written as.
# latin-1 maps every one of the 256 byte values to a character, so it never raises —
# it "succeeds" on a UTF-16 file and yields column names like `ÿþi\x00d\x00`. Trying
# encodings in turn therefore cannot distinguish them; the BOM can, and it is exactly
# what UTF-16 writers emit for this purpose.
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")

_NOT_UTF8 = "not utf-8 encoded"


def _fallback_encoding(path: Path) -> str:
    """The encoding to retry a non-UTF-8 CSV with."""
    try:
        with path.open("rb") as fh:
            head = fh.read(2)
    except OSError:
        return "latin-1"
    return "utf-16" if head in _UTF16_BOMS else "latin-1"


def _quote(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _reader_expr(path: Path, *, encoding: str | None = None) -> str:
    """The DuckDB table-function call that reads `path`."""
    reader = _SUPPORTED_EXTENSIONS.get(path.suffix.lower(), "read_csv_auto")
    if encoding and reader == "read_csv_auto":
        return f"read_csv('{_quote(path)}', encoding='{encoding}')"
    return f"{reader}('{_quote(path)}')"


def _ensure_excel_extension(con) -> None:
    """Load DuckDB's `excel` extension, which is where `read_xlsx` lives.

    Best-effort: a machine with no extension repository access still reads every
    other format, and the spreadsheet path fails with DuckDB's own message rather
    than an import error from here.
    """
    try:
        con.execute("INSTALL excel")
    except Exception:
        logger.debug("duckdb excel extension install skipped", exc_info=True)
    try:
        con.execute("LOAD excel")
    except Exception:
        logger.debug("duckdb excel extension load failed", exc_info=True)


#: (source path, size, mtime) → the UTF-8 copy already produced for it.
#
# The cache is the whole point, not an optimisation. This connector is constructed
# fresh on every connection open and re-reads every uploaded file, so an uncached
# transcode re-encodes each non-UTF-8 file EVERY time — for a 96 MB CSV that is a
# ~96 MB write per open, into a new temp directory nobody deletes. Thirty-four of
# them (2.7 GB) accumulated before this was caught, and the API died with them.
_TRANSCODE_CACHE: dict[tuple[str, int, int], Path] = {}
_TRANSCODE_LOCK = threading.Lock()

#: connection id → (signature it was built from, the materialized DuckDB).
#
# One entry per connection, replaced when the signature changes. Not an LRU: there is
# exactly one workspace per connection, so this holds as many databases as there are
# upload-backed connections, and a stale one is dropped the moment its files change.
_BASE_DBS: dict[str, tuple[tuple, "duckdb.DuckDBPyConnection"]] = {}
_BASE_LOCK = threading.Lock()


def _shared_base(conn_id: str, upload_dir: Path, signature: tuple, *, build):
    """The materialized database for this connection, building it only when the
    files it was built from have changed.

    The lock is held ACROSS the build, deliberately. Two connections opening at once
    on a cold cache would otherwise both materialize the whole workspace — the exact
    duplicated work this exists to remove — and the second would then evict the
    first's database while cursors were still reading from it. Serializing means the
    second waits for a build it can use.

    A SUPERSEDED DATABASE IS RELEASED, NEVER CLOSED
    ------------------------------------------------
    This used to call `stale.close()`, on the reasoning that "DuckDB keeps the
    database alive while a cursor references it, so a request already mid-flight is
    not pulled out from under". The first half is true. The conclusion is not:
    closing the parent invalidates its cursors immediately, whoever is using them.

    Measured directly — one reader thread, one `close()` from another:

        close the parent while a cursor reads  →  SIGSEGV (or a raised Error;
                                                  it is a race, so it varies)
        drop the last reference instead        →  the reader never notices

    Both crash modes were seen in CI on the same day: a SIGSEGV and a SIGABRT, each
    with one thread inside `close()` and another inside `execute`. Intermittent
    precisely because it needs the close to land mid-query. A dead interpreter takes
    the whole process with it, which on serverless is every route at once.

    Dropping the reference is enough, and is what the original comment believed
    closing would do: the cursor holds the database open, so it stays valid until the
    last one goes, and is then collected. Verified in isolation — a cursor whose
    parent is unreferenced and garbage-collected keeps reading correctly.
    """
    with _BASE_LOCK:
        cached = _BASE_DBS.get(conn_id)
        if cached is not None and cached[0] == signature:
            return cached[1]
        con = build()
        # Replacing the entry drops this dict's reference to the superseded database.
        # That is the whole eviction: no `close()`, because live cursors are still
        # reading from it and closing would invalidate them under load.
        _BASE_DBS[conn_id] = (signature, con)
    return con


def evict_base(conn_id: str) -> bool:
    """Drop a connection's materialized database. Returns whether one was held.

    Released rather than closed, for the same reason as `_shared_base`: an evict can
    land while another thread is mid-query on a cursor, and closing the parent
    invalidates that cursor immediately. Popping the entry is the eviction — the next
    open builds a fresh database, and this one lives exactly as long as the cursors
    still reading it.
    """
    with _BASE_LOCK:
        return _BASE_DBS.pop(conn_id, None) is not None


def _transcode_to_utf8(path: Path) -> Path | None:
    """A UTF-8 copy of `path`, or None if it could not be produced.

    The last resort, and the only one that cannot be defeated by the file. DuckDB's
    `encoding=` accepts a short list of names and still parses the bytes itself, so a
    file it dislikes for any reason stays unreadable. Decoding in Python does not
    have that problem: cp1252 with `errors="replace"` maps every byte sequence to
    SOMETHING, so the read always succeeds and at worst a few undecodable characters
    become U+FFFD — visible in the preview, and far better than refusing the upload.

    cp1252 rather than latin-1 because it is the encoding Excel on Windows actually
    writes, and it decodes the 0x80-0x9F range (curly quotes, en dashes, €) that
    latin-1 maps to control characters — the range the file that prompted this
    actually contains.

    Keyed on (path, size, mtime) so an edited or replaced file transcodes again
    rather than serving a stale copy, and written under ONE directory per process so
    the copies are findable and bounded instead of scattered across /tmp.
    """
    import codecs
    import tempfile

    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_size, int(stat.st_mtime))

    with _TRANSCODE_LOCK:
        cached = _TRANSCODE_CACHE.get(key)
        if cached is not None and cached.exists():
            return cached

    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        text = raw.decode("utf-16", errors="replace")
    else:
        text = raw.decode("cp1252", errors="replace")

    try:
        root = Path(tempfile.gettempdir()) / "aughor-utf8"
        # One sub-directory per (file, size, mtime) so distinct files never collide
        # on name, and a re-transcode of the same file reuses its slot.
        import hashlib
        stamp = hashlib.sha1(f"{key}".encode()).hexdigest()[:12]
        out_dir = root / stamp
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / path.name
        out.write_text(text, encoding="utf-8")
    except OSError:
        logger.debug("utf-8 transcode could not be written", exc_info=True)
        return None

    with _TRANSCODE_LOCK:
        _TRANSCODE_CACHE[key] = out
    logger.info("%s: transcoded to UTF-8 once (%.1f MB) — cached for reuse",
                path.name, stat.st_size / 1_048_576)
    return out


def readable_source(con, path: Path) -> str:
    """A reader expression that actually opens this file on `con`.

    Spreadsheets need an extension loaded first. For CSVs the encoding is only
    knowable by trying, because DuckDB decides while parsing, so this escalates:

      1. read it as-is (UTF-8, the overwhelmingly common case),
      2. re-read with DuckDB's own `encoding=`, chosen by BOM,
      3. transcode to UTF-8 ourselves and read that.

    Step 3 exists because step 2 is not guaranteed. A real 53-column export failed at
    BOTH 1 and 2 while a synthetic file of the same shape passed, and the failure was
    invisible: the old code discarded the fallback's error and re-reported the
    original UTF-8 one, so the logs said the retry had never been tried. Whatever that
    file did, decoding it in Python cannot fail — and if it somehow does, the message
    now names every attempt instead of only the first.

    Anything failing for a reason OTHER than encoding is re-raised untouched, so a
    genuinely broken file still reports what is wrong with it.
    """
    if path.suffix.lower() in (".xlsx", ".xls"):
        _ensure_excel_extension(con)
        return _reader_expr(path)

    src = _reader_expr(path)
    if path.suffix.lower() not in (".csv", ".tsv"):
        return src
    try:
        con.execute(f"SELECT * FROM {src} LIMIT 1").fetchall()
        return src
    except Exception as exc:
        if _NOT_UTF8 not in str(exc).lower():
            raise           # a genuinely broken file keeps its own error
        first_error = exc

    enc = _fallback_encoding(path)
    candidate = _reader_expr(path, encoding=enc)
    try:
        con.execute(f"SELECT * FROM {candidate} LIMIT 1").fetchall()
        logger.info("%s is not UTF-8; reading it as %s", path.name, enc)
        return candidate
    except Exception as retry_error:
        logger.info("%s: encoding=%s did not work either (%s) — transcoding",
                    path.name, enc, str(retry_error)[:200])

    utf8_copy = _transcode_to_utf8(path)
    if utf8_copy is not None:
        transcoded = _reader_expr(utf8_copy)
        try:
            con.execute(f"SELECT * FROM {transcoded} LIMIT 1").fetchall()
            logger.info("%s: read via a UTF-8 transcode", path.name)
            return transcoded
        except Exception as transcode_error:
            raise RuntimeError(
                f"{path.name} could not be read as UTF-8, as {enc}, or after "
                f"transcoding to UTF-8. Original error: {first_error}. "
                f"After transcoding: {transcode_error}"
            ) from transcode_error
    return src              # transcode unavailable — surface DuckDB's own message

# Allow-list of cast targets we let the UI request (prevents SQL injection via
# the column_types map — values are interpolated into CREATE TABLE ... AS).
_ALLOWED_CAST_TYPES = {
    "BIGINT", "INTEGER", "DOUBLE", "DECIMAL", "VARCHAR",
    "BOOLEAN", "DATE", "TIMESTAMP", "TIME",
}

# Tighter types we probe for, in preference order, when a column is VARCHAR.
_PROBE_TYPES = ["BIGINT", "DOUBLE", "BOOLEAN", "DATE", "TIMESTAMP"]


# DuckDB scalar types we'll TRY_CAST to when reproducing a pinned schema contract
# on reload. Complex types (STRUCT/LIST/MAP/UNION) are deliberately excluded so a
# parquet/JSON column with a nested type passes through untouched — those formats
# carry their own schema and are already deterministic, and their type strings
# contain nested identifiers we must never interpolate into SQL.
_PINNABLE_BASE_TYPES = {
    "BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT",
    "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT", "UHUGEINT",
    "DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC",
    "VARCHAR", "TEXT", "STRING", "CHAR", "BLOB",
    "BOOLEAN", "BOOL", "DATE", "TIME", "TIMESTAMP",
    "TIMESTAMP WITH TIME ZONE", "TIMESTAMP_S", "TIMESTAMP_MS",
    "TIMESTAMP_NS", "TIME WITH TIME ZONE", "UUID",
}

# A bare scalar type name plus an optional numeric precision — e.g. BIGINT,
# VARCHAR, DECIMAL(18,3), TIMESTAMP WITH TIME ZONE. Anything with quotes, letters
# inside parens, or nested parens (STRUCT(a INT), col[]) fails to match and is
# passed through rather than cast. Defence in depth: contract types come from
# DuckDB's own DESCRIBE, not user input, but interpolation stays allow-listed.
_PINNABLE_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9 ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?$")

_SIDECAR_SUFFIX = ".import.json"


def _is_pinnable_type(t: str) -> bool:
    """True when ``t`` is a DuckDB scalar type safe to reproduce via TRY_CAST on reload."""
    s = str(t).strip().upper()
    if not _PINNABLE_TYPE_RE.match(s):
        return False
    return s.split("(", 1)[0].strip() in _PINNABLE_BASE_TYPES


def _is_data_file(f: Path) -> bool:
    """A real uploaded data file — not a sidecar config, and a supported type."""
    return (
        f.is_file()
        and not f.name.endswith(_SIDECAR_SUFFIX)
        and f.suffix.lower() in _SUPPORTED_EXTENSIONS
    )


def _safe_ident(name: str, fallback: str = "table") -> str:
    """Sanitize an arbitrary string into a safe lowercase SQL identifier."""
    s = re.sub(r"[^0-9a-zA-Z_]", "_", (name or "").strip()).lower()
    s = re.sub(r"_+", "_", s).strip("_")
    if not s or not re.match(r"[a-z_]", s[0]):
        s = f"{fallback}_{s}" if s else fallback
    return s[:63]


def uploaded_tables(connection_id: str, meta: dict | None = None) -> dict[str, list[str]] | None:
    """``{schema: [table, …]}`` for an uploads connection, read from its FILES.

    Opening the connection materializes every uploaded file into DuckDB — measured
    at 9.56s of a 9.87s `/catalog/tree` locally, 97% of it — and a catalog listing
    wants only the NAMES, which the upload directory and its sidecars already carry.
    This answers from those, touching no database.

    A module-level function rather than a method **on purpose**: a method would
    require constructing the connector, and construction is precisely the expensive
    thing. (Making construction lazy instead was tried and reverted: the shared
    database is closed on rebuild in the belief that live cursors pin it, and a
    connection that has not yet built its cursor pins nothing — parallel ingest
    segfaulted.)

    A **seeded** connection also materializes tables from a read-only seed database
    that no uploaded file describes, so those are merged in — read from the seed's
    own catalogue, which is a file open and one query. Only the `CREATE TABLE AS`
    copy is expensive, and naming a table does not require copying it.

    Returns ``None`` only when the question genuinely cannot be answered from
    metadata — storage would not resolve, or the seed catalogue would not open — so
    the caller falls back to querying rather than silently under-reporting.

    Tombstoned schemas and tables are excluded, because the materialized database
    excludes them too — the tombstone, not the file's presence, is the authority on
    what the user removed, and a listing that disagreed would resurrect deletions.
    """
    try:
        root = vend_storage(connection_id).root
    except Exception:
        logger.debug("uploaded_tables: storage vending failed for %s", connection_id,
                     exc_info=True)
        return None
    # The files under this root ARE the truth; on a serverless instance they arrive
    # from the object store first. Best-effort, exactly as the connector's own open is.
    try:
        from aughor.control_plane.object_store import mirror_down
        mirror_down(root, f"uploads/{connection_id}" if connection_id else "uploads")
    except Exception:
        logger.debug("uploaded_tables: mirror_down is best-effort", exc_info=True)

    removed_schemas: set = set()
    removed_tables: set = set()
    try:
        tomb = root / _TOMBSTONE_FILE
        if tomb.exists():
            data = json.loads(tomb.read_text())
            removed_schemas = set(data.get("schemas") or [])
            removed_tables = set(data.get("tables") or [])
    except Exception:
        logger.debug("uploaded_tables: tombstone unreadable; treating as empty",
                     exc_info=True)

    out: dict[str, list[str]] = {}
    try:
        dirs = sorted(root.iterdir())
    except FileNotFoundError:
        # Nothing uploaded yet. That is a real, EMPTY answer — not a failure to
        # answer. Returning None here would send the caller off to materialize the
        # database precisely for the connection that has nothing in it.
        return {}
    except OSError:
        logger.debug("uploaded_tables: upload root unreadable for %s", connection_id,
                     exc_info=True)
        return None
    for sdir in dirs:
        if not sdir.is_dir() or sdir.name in removed_schemas:
            continue
        for f in sorted(sdir.iterdir()):
            if not _is_data_file(f):
                continue
            cfg = LocalUploadConnection._read_sidecar(f)
            table = cfg.get("table_name") or _safe_ident(f.stem)
            if f"{sdir.name}.{table}" in removed_tables:
                continue
            out.setdefault(sdir.name, []).append(table)

    seed = (meta or {}).get("seed_duckdb")
    if seed:
        seeded = _seed_table_names(seed, removed_schemas, removed_tables)
        if seeded is None:
            return None            # cannot name the seed's tables — go and query
        for schema, tables in seeded.items():
            have = set(out.get(schema, ()))
            # Uploads override seeds on a name clash (as `_reload_existing_files`
            # does), so a name already contributed by a file is not added twice.
            out.setdefault(schema, []).extend(t for t in tables if t not in have)
    return out


def _seed_table_names(seed_path: str, removed_schemas: set, removed_tables: set):
    """What a seed database contributes, by NAME, without copying any of it.

    `_seed_from_duckdb` reads exactly this list and then does `CREATE TABLE … AS`
    per row. The copy is the cost; the catalogue query is a file open. Tombstoned
    entries are skipped here for the same reason they are skipped there.

    None means the catalogue could not be read at all — distinct from an empty seed,
    because the caller treats None as "fall back and query".
    """
    p = Path(seed_path)
    if not p.exists():
        return {}
    try:
        con = duckdb.connect(p.as_posix(), read_only=True)
        try:
            rows = con.execute(
                "SELECT schema_name, table_name FROM duckdb_tables() WHERE internal = false"
            ).fetchall()
        finally:
            con.close()
    except Exception:
        logger.debug("uploaded_tables: seed catalogue unreadable at %s", seed_path,
                     exc_info=True)
        return None
    named: dict[str, list[str]] = {}
    for schema, table in rows:
        if schema in removed_schemas or f"{schema}.{table}" in removed_tables:
            continue
        named.setdefault(schema, []).append(table)
    return named


class LocalUploadConnection(Connector):
    connector_category = "file"
    dialect = "duckdb"

    def __init__(
        self,
        dsn: str = "local://",
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self._connection_id = connection_id
        self._schema_name = schema_name
        # Storage is vended by the control plane, never addressed directly (Invariant
        # #2): the capability resolves the tenant-scoped path {root}/{org}/{conn}/...
        self._cap = vend_storage(connection_id)
        self._upload_dir = self._cap.root
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        (self._upload_dir / DEFAULT_SCHEMA).mkdir(exist_ok=True)
        # Durable-store materialization (Blob on Vercel; no-op locally): the files
        # under this root ARE the truth this connection rebuilds from, so a cold
        # instance fetches them before the tombstone load and file reload below.
        # Best-effort — an object-store outage must degrade to local-only, not
        # block the connection.
        try:
            from aughor.control_plane.object_store import mirror_down
            mirror_down(self._upload_dir, self._blob_prefix())
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "upload-store materialization is best-effort; local files serve",
                     counter="uploads.mirror_down", conn_id=connection_id or None)
        # Tables materialized from a read-only seed DB (e.g. the sample catalog).
        self._seed_path = (meta or {}).get("seed_duckdb")
        self._seeded: set[tuple[str, str]] = set()
        self._seed_failed: str | None = None  # reason string when seeding broke
        # Seed schemas/tables the user removed — loaded BEFORE seeding so re-seed skips them.
        self._removed_seed_schemas, self._removed_seed_tables = self._load_tombstone()

        # Materialize ONCE per (connection, file set) and hand out cursors after that.
        #
        # This connector is constructed fresh on every connection open, and it used to
        # rebuild the entire workspace each time: a new :memory: DuckDB, re-seeded, and
        # every uploaded file re-read into it. Measured at 4.7s for 58 tables, 99.8% of
        # it in `_reload_existing_files`, and 9.7s once a 96 MB CSV joined them. Every
        # catalog browse, every schema fetch, every explorer spawn paid that.
        #
        # A DuckDB cursor is the right sharing primitive here, verified rather than
        # assumed: cursors share the database but keep their OWN session, so
        # `search_path` — which this class sets differently per schema scope and which
        # exists to stop one schema's query resolving to a sibling's same-named table —
        # stays per-connection. Closing a cursor leaves the base and its siblings alive.
        base = _shared_base(self._connection_id, self._upload_dir, self._seed_signature(),
                            build=self._materialize)
        self._duckdb = base.cursor()
        # Alias the handle under the name the DuckDB intelligence-build path expects
        # (build_intelligence / profilers read ._conn). LocalUpload is DuckDB-backed,
        # so this lets it reuse DuckDBConnection.build_intelligence (see below).
        self._conn = self._duckdb
        self._set_search_path()         # per-cursor: resolve bare names for THIS scope

    def _seed_signature(self) -> tuple:
        """What the materialized database was built FROM.

        Any change here means the cached database no longer represents the files, so
        it is rebuilt. Size and mtime are included because a re-upload under the same
        name is the common edit, and a name-only key would serve the old table
        forever. The tombstone is included because removing a seed table changes what
        gets materialized without touching any data file.
        """
        parts: list[tuple] = []
        try:
            for f in sorted(self._upload_dir.rglob("*")):
                if not _is_data_file(f):
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                parts.append((str(f.relative_to(self._upload_dir)), st.st_size, int(st.st_mtime)))
        except OSError:
            logger.debug("upload dir scan failed; treating as empty", exc_info=True)
        tomb = self._upload_dir / _TOMBSTONE_FILE
        tomb_stamp = int(tomb.stat().st_mtime) if tomb.exists() else 0
        return (str(self._seed_path or ""), tomb_stamp, tuple(parts))

    def _materialize(self) -> "duckdb.DuckDBPyConnection":
        """Build the database this connection reads from — the expensive path."""
        con = duckdb.connect(":memory:")
        prev = getattr(self, "_duckdb", None)
        self._duckdb = con
        self._conn = con
        try:
            self._seed_from_duckdb()        # sample/demo tables (read-only)
            self._reload_existing_files()   # user uploads (override seeds on clash)
        finally:
            if prev is not None:
                self._duckdb = prev
                self._conn = prev
        return con

    def _set_search_path(self) -> None:
        """Point search_path so bare table names resolve to the RIGHT schema.

        Two regimes:
        • SCOPED (``schema_name`` set — a per-schema explorer pass or a schema-/
          canvas-scoped chat/ADA run): pin search_path to ONLY that schema so an
          unqualified ``FROM orders`` resolves to ``<schema>.orders`` and can NEVER
          silently leak to a sibling schema's same-named table (e.g. a missimi-scoped
          query reading ``netflix.orders``/``main.orders`` — the source of confidently
          wrong answers). Cross-schema reads must then be explicitly qualified.
        • UNSCOPED (no ``schema_name`` — the whole-Workspace surface): include every
          user schema so ``FROM order_items`` resolves to ``ecommerce.order_items``
          without fully-qualified names (the original runaway-error fix).

        Qualified names (``schema.table``) and system catalogs resolve regardless of
        search_path in both regimes."""
        try:
            if self._schema_name:
                # Scoped: bare names must stay inside the scope.
                self._duckdb.execute(f"SET search_path = '{self._schema_name}'")
                return
            schemas = [
                r[0] for r in self._duckdb.execute(
                    "SELECT DISTINCT schema_name FROM duckdb_tables() WHERE internal = false"
                ).fetchall()
            ]
            if "main" not in schemas:
                schemas.append("main")
            if schemas:
                self._duckdb.execute(f"SET search_path = '{','.join(schemas)}'")
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "search_path routing is best-effort; qualified names still resolve",
                     counter="workspace.search_path", conn_id=self._connection_id)

    @single_flight_build
    def build_intelligence(self) -> str:
        """Build the heavy intelligence (profiles + ontology + enrichment) for this
        uploaded/seeded Workspace.

        `build_intelligence` lives only on DuckDBConnection, not the Connector base,
        so without this override the explorer's Phase-8 ontology gate raises
        AttributeError and domain intelligence is silently skipped for every
        file/connector-framework connection. LocalUpload is DuckDB-backed (._conn is
        our in-memory handle), so we reuse the DuckDB implementation directly."""
        from aughor.db.connection import DuckDBConnection
        return DuckDBConnection.build_intelligence(self)

    def _seed_from_duckdb(self) -> None:
        """Materialize tables from a read-only seed DuckDB file into this
        in-memory database, preserving their original schema names. Used to fold
        the sample catalog into the Workspace so demo data and uploads coexist."""
        if not self._seed_path:
            return
        p = Path(self._seed_path)
        if not p.exists():
            self._seed_failed = f"seed file not found: {p}"
            logger.error("Seed DB missing for %s: %s", self._connection_id, p)
            return
        failed: list[str] = []
        try:
            with _SEED_LOCK:
                self._duckdb.execute(f"ATTACH '{p.as_posix()}' AS _seed (READ_ONLY)")
                try:
                    tbls = self._duckdb.execute(
                        "SELECT schema_name, table_name FROM duckdb_tables() "
                        "WHERE database_name = '_seed' AND internal = false"
                    ).fetchall()
                    if not tbls:
                        self._seed_failed = "seed DB attached but contains no tables"
                        logger.error("Seed DB %s has no tables (conn=%s)", p, self._connection_id)
                    for schema, table in tbls:
                        # Honor the removed-seed tombstone — a schema (or single table) the
                        # user deleted must not come back on this re-seed.
                        if schema in self._removed_seed_schemas or f"{schema}.{table}" in self._removed_seed_tables:
                            continue
                        try:
                            self._duckdb.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                            self._duckdb.execute(
                                f'CREATE TABLE "{schema}"."{table}" AS '
                                f'SELECT * FROM _seed."{schema}"."{table}"'
                            )
                            self._seeded.add((schema, table))
                        except Exception as exc:
                            failed.append(f"{schema}.{table}")
                            logger.error(
                                "Seed materialization failed for %s.%s (conn=%s): %s",
                                schema, table, self._connection_id, exc,
                            )
                finally:
                    self._duckdb.execute("DETACH _seed")
            if failed:
                self._seed_failed = f"failed to materialize: {', '.join(failed)}"
            logger.debug(
                "Seed materialized %d tables (%d failed) for conn=%s",
                len(self._seeded), len(failed), self._connection_id,
            )
        except Exception as exc:
            # Demo data is best-effort; never block the Workspace on a seed error —
            # but the failure must be visible (it presents as "sample data missing").
            self._seed_failed = f"seed attach failed: {exc}"
            logger.error(
                "Seed DB attach failed for conn=%s (%s): %s",
                self._connection_id, p, exc, exc_info=True,
            )
            try:
                self._duckdb.execute("DETACH _seed")
            except Exception:
                pass

    # ── Schema directories ──────────────────────────────────────────────────────

    def _schema_dir(self, schema: str) -> Path:
        return self._upload_dir / _safe_ident(schema, DEFAULT_SCHEMA)

    def list_schemas(self) -> list[str]:
        names = {DEFAULT_SCHEMA}
        for d in self._upload_dir.iterdir():
            if d.is_dir():
                names.add(d.name)
        return sorted(names)

    # ── Removed-seed tombstone ──────────────────────────────────────────────────

    def _load_tombstone(self) -> tuple[set, set]:
        """``(removed_schemas, removed_tables)`` the user deleted from the seed catalog.
        Fail-open to empty (a corrupt/absent tombstone never blocks the connection)."""
        schemas: set = set()
        tables: set = set()
        try:
            p = self._upload_dir / _TOMBSTONE_FILE
            if p.exists():
                data = json.loads(p.read_text())
                schemas = set(data.get("schemas") or [])
                tables = set(data.get("tables") or [])
        except Exception as exc:
            logger.debug("removed-seed tombstone load failed for %s: %s", self._connection_id, exc)
        return schemas, tables

    def _blob_prefix(self) -> str:
        """This connection's namespace in the durable object store — the same
        {org}/{conn} shape the vended local path uses."""
        return f"uploads/{self._cap.org_id}/{self._cap.conn_id}"

    def _persist_uploads(self) -> None:
        """Mirror the upload root to the durable store after a mutation. Deletions
        propagate as remote strays; the tombstone rides along as a regular file.
        Best-effort: a failed mirror must not fail the ingest/delete that worked
        locally — the next mutation (or instance) retries by construction."""
        try:
            from aughor.control_plane.object_store import mirror_up
            mirror_up(self._upload_dir, self._blob_prefix())
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "upload-store mirror is best-effort; local state is intact",
                     counter="uploads.mirror_up", conn_id=self._connection_id or None)

    def _save_tombstone(self) -> None:
        try:
            (self._upload_dir / _TOMBSTONE_FILE).write_text(json.dumps(
                {"schemas": sorted(self._removed_seed_schemas),
                 "tables": sorted(self._removed_seed_tables)}))
        except Exception as exc:
            logger.debug("removed-seed tombstone save failed for %s: %s", self._connection_id, exc)
        # Every drop/restore path funnels through here — the one mirror hook that
        # makes deletions durable (the tombstone rides up; removed files become strays).
        self._persist_uploads()

    def restore_seeds(self, schema: str | None = None) -> None:
        """Clear the tombstone (all, or one schema) so the sample catalog re-materializes on
        the next connector construction. The UI's 'restore sample data' affordance."""
        if schema is None:
            self._removed_seed_schemas.clear()
            self._removed_seed_tables.clear()
        else:
            s = _safe_ident(schema, "schema")
            self._removed_seed_schemas.discard(s)
            self._removed_seed_tables = {t for t in self._removed_seed_tables if not t.startswith(f"{s}.")}
        self._save_tombstone()

    def create_schema(self, name: str) -> str:
        schema = _safe_ident(name, "schema")
        self._schema_dir(schema).mkdir(parents=True, exist_ok=True)
        try:
            self._duckdb.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        except Exception:
            pass
        # Re-creating a schema the user previously removed is an explicit "bring it back" —
        # lift its tombstone so the seed (if any) returns on the next construction.
        if schema in self._removed_seed_schemas:
            self.restore_seeds(schema)
        return schema

    def drop_schema(self, name: str) -> None:
        schema = _safe_ident(name, "schema")
        if schema == DEFAULT_SCHEMA:
            raise ValueError("The default 'main' schema cannot be deleted.")
        d = self._schema_dir(schema)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        try:
            self._duckdb.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        except Exception:
            pass
        # Tombstone EVERY dropped schema — seed-backed OR uploaded — not just seeds. The
        # tombstone, not the `rmtree` above, is what keeps a schema gone: `ignore_errors=True`
        # can leave files behind and a restore-from-backup can re-create them, and
        # `_reload_existing_files` now honors the tombstone where a raw filesystem scan would
        # resurrect them (this closes the upload-resurrection gap, not just the seed one).
        self._removed_seed_schemas.add(schema)
        # A schema tombstone subsumes any table tombstones under it — drop the now-redundant ones.
        self._removed_seed_tables = {t for t in self._removed_seed_tables
                                     if not t.startswith(f"{schema}.")}
        self._save_tombstone()

    # ── Analyze (no persistence) ────────────────────────────────────────────────

    def analyze_file(self, file_path: Path, sample_rows: int = 20) -> dict:
        """Inspect a file and return inferred columns, a sample preview, a row
        count, and type-mismatch suggestions — without ingesting anything."""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. Supported: {sorted(_SUPPORTED_EXTENSIONS)}"
            )
        con = duckdb.connect(":memory:")
        src = readable_source(con, file_path)
        try:
            desc = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
            columns: list[dict] = []
            for row in desc:
                name, dtype = row[0], str(row[1])
                suggested = None
                costume = None
                if dtype.upper().startswith("VARCHAR"):
                    suggested = self._suggest_type(con, src, name)
                    # Only probe for decoration where a plain cast already failed, so the
                    # two detectors never contend for the same column.
                    if suggested is None:
                        costume = _detect_costume(con, src, name)
                        if costume:
                            suggested = costume["cast_to"]
                columns.append({
                    "name": name,
                    "detected_type": dtype,
                    "suggested_type": suggested,
                    # Surfaced so the import-review UI can say WHY a text column is about
                    # to become a number ("currency-formatted — e.g. ₹1,099").
                    "detected_format": (
                        {"kind": _costume_kind(costume["unit"]),
                         "unit": costume["unit"], "example": costume["sample"]}
                        if costume else None
                    ),
                })

            prev = con.execute(f"SELECT * FROM {src} LIMIT {int(sample_rows)}").fetchall()
            pcols = [d[0] for d in con.description] if con.description else []
            rows = [
                [None if v is None else str(v) for v in r]
                for r in prev
            ]
            try:
                total = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
            except Exception:
                total = len(rows)
        finally:
            con.close()

        return {
            "columns": columns,
            "preview": {"columns": pcols, "rows": rows},
            "row_count": total,
            "suggested_table_name": _safe_ident(file_path.stem),
        }

    @staticmethod
    def _suggest_type(con, src: str, col: str) -> str | None:
        """Return a tighter type if ≥95% of non-empty values cast cleanly."""
        c = col.replace('"', '""')
        probes = ", ".join(
            f'count(*) FILTER (WHERE try_cast("{c}" AS {t}) IS NOT NULL) AS p{i}'
            for i, t in enumerate(_PROBE_TYPES)
        )
        q = (
            f'SELECT count(*) FILTER (WHERE "{c}" IS NOT NULL '
            f"AND trim(CAST(\"{c}\" AS VARCHAR)) <> '') AS nn, {probes}, "
            # DuckDB's TRY_CAST('4.2' AS BIGINT) SUCCEEDS, truncating to 4 — so a rating
            # or price column probed in _PROBE_TYPES order was suggested as BIGINT, and
            # accepting that suggestion silently discarded the fractional part of every
            # value. Count the fractional values so BIGINT can be ruled out below.
            f'count(*) FILTER (WHERE try_cast("{c}" AS DOUBLE) IS NOT NULL '
            f'AND try_cast("{c}" AS DOUBLE) <> floor(try_cast("{c}" AS DOUBLE))) AS frac '
            f"FROM {src}"
        )
        try:
            res = con.execute(q).fetchone()
        except Exception:
            return None
        nn = res[0] or 0
        if nn == 0:
            return None
        fractional = res[len(_PROBE_TYPES) + 1] or 0
        threshold = 0.95 * nn
        for i, t in enumerate(_PROBE_TYPES):
            if (res[i + 1] or 0) >= threshold:
                if t == "BIGINT" and fractional:
                    continue          # would truncate — let DOUBLE win the probe order
                return t
        return None

    # ── File ingestion ─────────────────────────────────────────────────────────

    def ingest_file(
        self,
        file_path: Path,
        table_name: str | None = None,
        schema: str = DEFAULT_SCHEMA,
        column_types: dict | None = None,
    ) -> str:
        """Copy a file into the given schema dir and register it as a DuckDB
        table, applying any per-column type overrides. Returns the table name."""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. Supported: {sorted(_SUPPORTED_EXTENSIONS)}"
            )

        schema = _safe_ident(schema, DEFAULT_SCHEMA)
        sdir = self._schema_dir(schema)
        sdir.mkdir(parents=True, exist_ok=True)

        dest = sdir / file_path.name
        if file_path.resolve() != dest.resolve():
            shutil.copy2(file_path, dest)

        table_name = _safe_ident(table_name or file_path.stem)
        clean_types = self._clean_types(column_types)

        # Decorated numbers ('₹1,099', '64%') are re-typed automatically. Nothing else
        # in the platform does this: `column_types` is entirely caller-supplied, so a
        # file uploaded through the API — no import-review round-trip — kept every
        # price as text and every downstream metric read NULL.
        #
        # Detection runs over EVERY column, including ones the caller typed explicitly,
        # and the two are reconciled below. Skipping overridden columns looked like
        # "the user's decision wins", but it meant asking for the numeric type — which
        # is exactly what `analyze_file` now SUGGESTS and the import UI offers as a
        # one-click chip — fell through to a plain TRY_CAST over '₹1,099' and emptied
        # the column at ingest. The one action the UI recommends must not be the one
        # that destroys the data.
        transforms = self._reconcile_transforms(self._detect_costumes(dest), clean_types)

        # Materialize the table first (applying any user overrides), THEN pin the
        # result: DESCRIBE the created table to capture the full effective
        # {column: type} contract — a pinned schema hint. On reload we
        # reproduce these exact types instead of re-sniffing the file, which can
        # drift across DuckDB versions / sampling and silently re-type a column.
        self._register_file(dest, table_name, schema, clean_types,
                            column_transforms=transforms)
        contract = self._describe_contract(schema, table_name)

        # Persist the import config + the pinned contract + provenance, so reload
        # is deterministic and the table's origin is inspectable (surfaced by
        # list_files → the ontology / Hub).
        (sdir / f"{file_path.name}{_SIDECAR_SUFFIX}").write_text(
            json.dumps({
                "table_name": table_name,
                "schema": schema,
                "column_types": clean_types,
                "column_transforms": transforms,
                "schema_contract": contract,
                "source_file": file_path.name,
                "format": ext.lstrip("."),
                "created_by": "upload",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, indent=2)
        )
        # Ingesting is an explicit "bring it back" — lift any tombstone on this schema/table
        # so `_reload_existing_files` (which now honors tombstones) re-materializes it on the
        # next construction. Without this, a re-upload after a delete would vanish on restart.
        key = f"{schema}.{table_name}"
        if schema in self._removed_seed_schemas or key in self._removed_seed_tables:
            self._removed_seed_schemas.discard(schema)
            self._removed_seed_tables.discard(key)
            self._save_tombstone()
        self._persist_uploads()   # the staged file + sidecar just became the truth
        return table_name

    def _describe_contract(self, schema: str, table_name: str) -> dict:
        """The effective ``{column: duckdb_type}`` of a just-created table — the
        pinned schema contract. Best-effort: returns ``{}`` on any failure, in
        which case reload falls back to re-sniffing (today's behavior)."""
        try:
            desc = self._duckdb.execute(
                f'DESCRIBE "{schema}"."{table_name}"').fetchall()
            return {str(r[0]): str(r[1]) for r in desc}
        except Exception:
            return {}

    def _detect_costumes(self, path: Path, skip: set | None = None) -> dict:
        """``{column: {"cast_to", "unit", "sample"}}`` for every decorated-number column.

        Probed on a throwaway connection against the file itself, so detection sees the
        reader's raw output rather than an already-materialized table.
        """
        skip = skip or set()
        found: dict = {}
        con = duckdb.connect(":memory:")
        try:
            src = readable_source(con, path)
            for row in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall():
                name, dtype = row[0], str(row[1])
                if name in skip or not dtype.upper().startswith("VARCHAR"):
                    continue
                if self._suggest_type(con, src, name) is not None:
                    continue          # a plain cast already reaches it — not our column
                hit = _detect_costume(con, src, name)
                if hit:
                    found[name] = hit
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "costume detection is best-effort; columns stay as the reader "
                          "typed them on failure", counter="upload.costume_detect",
                     conn_id=self._connection_id or None)
        finally:
            con.close()
        if found:
            logger.info("Re-typed %d decorated-number column(s) in %s: %s",
                        len(found), path.name,
                        ", ".join(f"{c}→{v['cast_to']}" for c, v in found.items()))
        return found

    @staticmethod
    def _reconcile_transforms(transforms: dict, column_types: dict) -> dict:
        """Settle detected decoration against an explicit caller override.

        Three outcomes per column:
        • no override                → transform as detected.
        • override to a NUMERIC type → transform, casting to the type the caller asked
          for. They want a number, and stripping the decoration is the only way to get
          one; a plain cast over '₹1,099' yields NULL. This covers INTEGER and DECIMAL,
          not just the two types detection picks for itself — a person choosing INTEGER
          for a whole-rupee price means the same thing, and a real workspace was found
          in exactly that state: `actual_price` pinned INTEGER over currency text,
          1,465 rows, zero non-null.
        • override to anything else  → drop the transform. Asking for VARCHAR (or DATE)
          is a decision to keep the raw text, and it stands.
        """
        out = dict(transforms)
        for col, requested in (column_types or {}).items():
            if col not in out:
                continue
            t = str(requested).upper()
            if t in _COSTUME_CAST_TYPES:
                out[col] = {**out[col], "cast_to": t}
            else:
                out.pop(col)
        return out

    @staticmethod
    def _clean_types(column_types: dict | None) -> dict:
        if not column_types:
            return {}
        out = {}
        for col, t in column_types.items():
            tu = str(t).upper().strip()
            if tu in _ALLOWED_CAST_TYPES:
                out[col] = tu
        return out

    def _register_file(
        self,
        path: Path,
        table_name: str,
        schema: str = DEFAULT_SCHEMA,
        column_types: dict | None = None,
        schema_contract: dict | None = None,
        column_transforms: dict | None = None,
    ) -> None:
        src = readable_source(self._duckdb, path)
        select_sql = self._build_select(src, column_types, schema_contract,
                                        column_transforms)
        fq = f'"{schema}"."{table_name}"'
        try:
            self._duckdb.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            self._duckdb.execute(f"DROP TABLE IF EXISTS {fq}")
            self._duckdb.execute(f"CREATE TABLE {fq} AS {select_sql}")
        except Exception as e:
            raise RuntimeError(
                f"Failed to load {path.name} as table '{schema}.{table_name}': {e}"
            ) from e

    def _build_select(
        self,
        src: str,
        column_types: dict | None = None,
        schema_contract: dict | None = None,
        column_transforms: dict | None = None,
    ) -> str:
        """Build the SELECT that materializes a file into a table.

        Two regimes, chosen by which map is supplied:
        • ``schema_contract`` (reload): TRY_CAST every column whose pinned type is a
          safe scalar back to that exact type — reproduces the ingest-time schema
          deterministically, immune to ``read_*_auto`` re-sniffing drift. Columns
          with a complex/non-scalar pinned type pass through unchanged.
        • ``column_types`` (ingest): TRY_CAST only the user-overridden columns; the
          rest keep the reader's freshly-inferred type. (Original behavior.)

        ``column_transforms`` OUTRANKS both, and must: a decorated-number column is
        DOUBLE in the pinned contract, but the file on disk still holds '₹1,099'. A
        plain ``TRY_CAST(price AS DOUBLE)`` over that text yields NULL for every row,
        so honouring the contract alone would silently empty the column on the first
        reload — the ingest would look right and the restart would lose the data.
        The transform re-derives the value the way ingest did.
        """
        strict = bool(schema_contract)
        pin = schema_contract if strict else (column_types or {})
        tf = column_transforms or {}
        if not pin and not tf:
            return f"SELECT * FROM {src}"
        con = self._duckdb
        try:
            desc = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
            cols = [r[0] for r in desc]
        except Exception:
            return f"SELECT * FROM {src}"
        parts = []
        for name in cols:
            esc = name.replace('"', '""')
            spec = tf.get(name)
            if isinstance(spec, dict) and spec.get("cast_to") in _COSTUME_CAST_TYPES:
                parts.append(f'{_costume_clean_sql(name, spec["cast_to"])} AS "{esc}"')
                continue
            t = pin.get(name)
            cast_to = None
            if t:
                if strict:
                    cast_to = str(t) if _is_pinnable_type(t) else None
                elif str(t).upper() in _ALLOWED_CAST_TYPES:
                    cast_to = str(t).upper()
            if cast_to:
                parts.append(f'TRY_CAST("{esc}" AS {cast_to}) AS "{esc}"')
            else:
                parts.append(f'"{esc}"')
        return f"SELECT {', '.join(parts)} FROM {src}"

    def _reload_existing_files(self) -> None:
        """Re-register every file under every schema dir on startup — EXCEPT anything the
        user tombstoned. Without this skip a deleted schema/table whose backing file survived
        the delete silently re-materializes here: `drop_schema` uses `rmtree(ignore_errors=
        True)` (a lock / permission / disk-full leaves files behind), and a restore-from-backup
        re-creates them outright. The tombstone — not the file's mere presence — is the
        authority on what the user removed."""
        for sdir in sorted(self._upload_dir.iterdir()):
            if not sdir.is_dir():
                continue
            schema = sdir.name
            if schema in self._removed_seed_schemas:
                continue  # user deleted this schema — do not resurrect surviving files
            try:
                self._duckdb.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            except Exception:
                pass
            for f in sorted(sdir.iterdir()):
                if not _is_data_file(f):
                    continue
                cfg = self._read_sidecar(f)
                table_name = cfg.get("table_name") or _safe_ident(f.stem)
                if f"{schema}.{table_name}" in self._removed_seed_tables:
                    continue  # user deleted this table — do not resurrect a surviving file
                column_types = cfg.get("column_types") or {}
                # Prefer the pinned full contract (deterministic reload); old
                # sidecars without one fall back to overrides-only re-sniffing.
                schema_contract = cfg.get("schema_contract") or None
                # Decorated-number columns must be re-derived, not re-cast: the file on
                # disk still holds '₹1,099' while the contract says DOUBLE. Dropping this
                # on reload empties the column silently — ingest looks right, the first
                # restart loses the data.
                column_transforms = cfg.get("column_transforms") or None
                try:
                    self._register_file(f, table_name, schema, column_types,
                                        schema_contract=schema_contract,
                                        column_transforms=column_transforms)
                except Exception:
                    pass  # never break startup on one bad file

    @staticmethod
    def _read_sidecar(data_file: Path) -> dict:
        sc = data_file.with_name(f"{data_file.name}{_SIDECAR_SUFFIX}")
        if sc.exists():
            try:
                return json.loads(sc.read_text())
            except Exception:
                return {}
        return {}

    def list_files(self) -> list[dict]:
        """Metadata for all ingested files across schemas."""
        result = []
        for sdir in sorted(self._upload_dir.iterdir()):
            if not sdir.is_dir():
                continue
            schema = sdir.name
            for f in sorted(sdir.iterdir()):
                if not _is_data_file(f):
                    continue
                cfg = self._read_sidecar(f)
                result.append({
                    "filename": f.name,
                    "table_name": cfg.get("table_name") or _safe_ident(f.stem),
                    "schema": schema,
                    "size_bytes": f.stat().st_size,
                    "extension": f.suffix.lower(),
                    "column_types": cfg.get("column_types") or {},
                    "column_transforms": cfg.get("column_transforms") or {},
                    "schema_contract": cfg.get("schema_contract") or {},
                    "created_by": cfg.get("created_by"),
                    "created_at": cfg.get("created_at"),
                    "source_file": cfg.get("source_file"),
                })
        return result

    def delete_table(self, table: str, schema: str = DEFAULT_SCHEMA) -> None:
        """Remove a single table: drop it from DuckDB and delete its backing file(s).
        Matches by the table's resolved name (sidecar table_name, else the file stem)."""
        schema = _safe_ident(schema, DEFAULT_SCHEMA)
        tbl = _safe_ident(table, "table")
        sdir = self._schema_dir(schema)
        if sdir.exists():
            for f in list(sdir.iterdir()):
                if not _is_data_file(f):
                    continue
                cfg = self._read_sidecar(f)
                tname = cfg.get("table_name") or _safe_ident(f.stem)
                if tname == tbl:
                    if f.exists():
                        f.unlink()
                    sc = f.with_name(f"{f.name}{_SIDECAR_SUFFIX}")
                    if sc.exists():
                        sc.unlink()
        try:
            self._duckdb.execute(f'DROP TABLE IF EXISTS "{schema}"."{tbl}"')
        except Exception:
            pass
        # Tombstone the table — seed-backed OR uploaded — so a surviving backing file (or a
        # re-materialized seed) is not silently re-registered on the next construction.
        self._removed_seed_tables.add(f"{schema}.{tbl}")
        self._save_tombstone()

    def delete_file(self, filename: str, schema: str = DEFAULT_SCHEMA) -> None:
        schema = _safe_ident(schema, DEFAULT_SCHEMA)
        sdir = self._schema_dir(schema)
        path = sdir / Path(filename).name
        cfg = self._read_sidecar(path)
        table_name = cfg.get("table_name") or _safe_ident(path.stem)
        if path.exists():
            path.unlink()
        sc = path.with_name(f"{path.name}{_SIDECAR_SUFFIX}")
        if sc.exists():
            sc.unlink()
        try:
            self._duckdb.execute(f'DROP TABLE IF EXISTS "{schema}"."{table_name}"')
        except Exception:
            pass
        # Tombstone the table so a surviving copy of this file isn't re-registered on reload
        # (delete_file previously wrote NO tombstone at all — its sole protection against
        # resurrection was the unlink having succeeded).
        self._removed_seed_tables.add(f"{schema}.{table_name}")
        self._save_tombstone()

    # ── DatabaseConnection ABC ─────────────────────────────────────────────────

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        from aughor.db.connection import enforce_row_policy, security_pre, security_post

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked
        sql, _rp = enforce_row_policy(self, hypothesis_id, sql)   # RBAC row-policy (Rec 7); no-op off
        if _rp is not None:
            return _rp

        _t0 = time.monotonic()
        try:
            self._duckdb.execute(sql)
            rows_raw = self._duckdb.fetchall()
            columns = [d[0] for d in self._duckdb.description] if self._duckdb.description else []
            from aughor.db.connection import offer_typed_rows
            offer_typed_rows(
                rows_raw[:MAX_ROWS],
                truncated=len(rows_raw) > MAX_ROWS,
                types=[str(d[1]) for d in self._duckdb.description] if self._duckdb.description else [],
            )
            rows = [
                [str(v) if v is not None else "NULL" for v in row]
                for row in rows_raw[:MAX_ROWS]
            ]
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=columns, rows=rows, row_count=len(rows_raw),
            )
        except Exception as e:
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=[], rows=[], row_count=0, error=str(e),
            )
        elapsed_ms = (time.monotonic() - _t0) * 1000
        return security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def make_reader(self) -> "LocalUploadConnection":
        """Return a clone safe for use in a parallel thread.

        A cursor off the same database, not a rebuild. This used to re-seed and
        re-read every uploaded file per reader — so the parallelism that exists to
        make reads FASTER paid a full workspace materialization for each one, ~5s
        before a 96 MB CSV was added and ~10s after.

        The cursor gives the isolation that mattered: its own session, so this
        reader's `search_path` cannot be changed by the connection it came from,
        while the data underneath is shared rather than copied.
        """
        clone = LocalUploadConnection.__new__(LocalUploadConnection)
        clone._connection_id = self._connection_id
        clone._schema_name = self._schema_name
        clone._upload_dir = self._upload_dir
        clone._cap = getattr(self, "_cap", None)
        clone._seed_path = self._seed_path
        clone._seeded = set(self._seeded)
        clone._seed_failed = self._seed_failed
        # Copy as new sets so the clone honours the same removals without sharing the
        # parent's mutable state.
        clone._removed_seed_schemas = set(self._removed_seed_schemas)
        clone._removed_seed_tables = set(self._removed_seed_tables)
        clone._duckdb = self._duckdb.cursor()
        clone._conn = clone._duckdb
        clone._set_search_path()
        return clone

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            self._duckdb.execute(f"EXPLAIN {sql.rstrip(chr(59))}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def raw_execute(self, sql: str) -> tuple[list[str], list, list[str]]:
        """Execute a raw SQL query bypassing validation and security checks.
        Returns (column_names, rows, types)."""
        self._duckdb.execute(sql)
        rows = self._duckdb.fetchall()
        desc = self._duckdb.description or []
        columns = [d[0] for d in desc]
        types = [str(d[1]) for d in desc]
        return columns, rows, types

    def get_schema(self) -> str:
        parts: list[str] = []
        try:
            # Respect schema_name filter if set; otherwise list all non-system schemas.
            if self._schema_name:
                self._duckdb.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name",
                    [self._schema_name],
                )
            else:
                self._duckdb.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'temp') "
                    "AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name"
                )
            schema_table_rows = self._duckdb.fetchall()
            schemas_present = {s for s, _ in schema_table_rows}
            multi_schema = len(schemas_present) > 1
            for tschema, tname in schema_table_rows:
                try:
                    count = self._duckdb.execute(
                        f'SELECT COUNT(*) FROM "{tschema}"."{tname}"'
                    ).fetchone()[0]
                except Exception:
                    count = "?"
                # Emit schema-qualified names when there are multiple schemas or
                # the table lives outside the default schema so the LLM always
                # references the correct table.
                display_name = f"{tschema}.{tname}" if (multi_schema or tschema != DEFAULT_SCHEMA) else tname
                parts.append(f"TABLE: {display_name}  ({count:,} rows)")
                try:
                    cols = self._duckdb.execute(
                        f'DESCRIBE "{tschema}"."{tname}"'
                    ).fetchall()
                    from aughor.db.type_overrides import get_table_overrides
                    _overrides = get_table_overrides(self._connection_id or "", tname)
                    samples = self._column_samples(tschema, tname, [c[0] for c in cols])
                    for col in cols:
                        col_name, col_type = col[0], col[1]
                        if col_name in _overrides:
                            col_type = _overrides[col_name]
                        parts.append(f"  {col_name}  {col_type}"
                                     + samples.get(col_name, ""))
                except Exception:
                    parts.append("  # column info unavailable")
        except Exception as e:
            parts.append(f"# Schema introspection failed: {e}")
        return "\n".join(parts) or "(no files uploaded yet)"

    def _column_samples(self, schema: str, table: str, columns: list) -> dict:
        """``{column: " ~ e.g. 'a', 'b'"}`` — a few real values per column.

        One scan of the table's head serves every column, so this costs a single extra
        query per table. Best-effort: a table that won't sample renders exactly as it
        did before.
        """
        from aughor.db.schema_render import format_value_samples
        if not columns:
            return {}
        try:
            # Double every embedded quote. Column names come from a user-supplied CSV
            # header and are NEVER passed through `_safe_ident` (which guards only table
            # and schema names), so a header cell containing a `"` closes the identifier
            # and the rest of the cell executes as SQL on the workspace handle.
            quoted = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
            rows = self._duckdb.execute(
                f'SELECT {quoted} FROM "{schema}"."{table}" LIMIT 5'
            ).fetchall()
        except Exception:
            return {}
        out: dict = {}
        for i, col in enumerate(columns):
            suffix = format_value_samples([r[i] for r in rows])
            if suffix:
                out[col] = suffix
        return out

    def test(self) -> tuple[bool, str]:
        files = self.list_files()
        if not files:
            return True, "Local upload connector ready (no files uploaded yet)"
        names = [
            f["table_name"] if f["schema"] == DEFAULT_SCHEMA
            else f"{f['schema']}.{f['table_name']}"
            for f in files
        ]
        return True, f"Local upload: {len(files)} file(s) loaded as tables: {', '.join(names)}"

    def close(self) -> None:
        try:
            self._duckdb.close()
        except Exception:
            pass
