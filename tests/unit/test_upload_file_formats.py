"""Every file type the uploader ACCEPTS can actually be read.

The drop zone advertises "CSV · TSV · Parquet · Excel (xlsx/xls) · JSON", and two of
those could not be opened:

  * `.xlsx`/`.xls` mapped to `read_excel`, which is not a DuckDB function. The one
    that exists, in the `excel` extension, is `read_xlsx` — so every spreadsheet
    failed with "Table Function with name read_excel does not exist".
  * A CSV that is not UTF-8 was rejected outright. DuckDB says "This file is not
    utf-8 encoded", and a CSV exported from Excel on Windows is cp1252 — one
    accented character was enough.

Both surfaced identically in the UI as the string "Analyze failed", because the API
replaced the exception with a constant.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aughor.connectors.file.local_upload import LocalUploadConnection


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """A workspace connector rooted in tmp_path — this ingests, so it must not touch
    the real upload store."""
    from aughor.control_plane import vending

    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    c = LocalUploadConnection(dsn="local://", connection_id="upload_fmt_test")
    yield c
    try:
        c.close()
    except Exception:
        pass


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_utf8_csv_still_reads(conn, tmp_path) -> None:
    p = _write(tmp_path, "plain.csv", b"id,name\n1,alpha\n")
    info = conn.analyze_file(p)
    assert [c["name"] for c in info["columns"]] == ["id", "name"]


def test_latin1_csv_reads_and_keeps_its_characters(conn, tmp_path) -> None:
    """The reported failure. `café` in cp1252/latin-1 — what Excel on Windows
    writes — must survive, not merely parse."""
    p = _write(tmp_path, "accented.csv", "id,name\n1,café\n".encode("latin-1"))

    info = conn.analyze_file(p)

    assert [c["name"] for c in info["columns"]] == ["id", "name"]
    flat = str(info.get("preview") or info)
    assert "café" in flat, f"the accented value did not survive the decode: {flat}"


def test_utf16_csv_reads(conn, tmp_path) -> None:
    p = _write(tmp_path, "wide.csv", "id,name\n1,alpha\n".encode("utf-16"))
    info = conn.analyze_file(p)
    assert [c["name"] for c in info["columns"]] == ["id", "name"]


def test_latin1_csv_ingests_and_reads_back(conn, tmp_path) -> None:
    """Analyze and ingest build the reader separately — fixing one is not fixing
    the other."""
    p = _write(tmp_path, "accented2.csv", "id,name\n1,café\n".encode("latin-1"))

    conn.ingest_file(p, table_name="accented", schema="main")

    res = conn.execute("__test__", 'SELECT name FROM main."accented"')
    assert res.rows and res.rows[0][0] == "café"


def test_xlsx_reads(conn, tmp_path, duckdb_extension) -> None:
    """`read_excel` does not exist; `read_xlsx` does, once the extension loads.

    The fixture is written with xlsxwriter rather than openpyxl deliberately —
    openpyxl is not in this project's environment, so `importorskip` on it turned
    the ONE test covering the broken format into a permanent skip. A test that
    never runs would not have caught the bug it exists for.
    """
    duckdb_extension("excel")   # fetched from extensions.duckdb.org on first use
    xlsxwriter = pytest.importorskip("xlsxwriter")
    p = tmp_path / "book.xlsx"
    wb = xlsxwriter.Workbook(str(p))
    ws = wb.add_worksheet()
    ws.write_row(0, 0, ["id", "name"])
    ws.write_row(1, 0, [1, "alpha"])
    wb.close()

    info = conn.analyze_file(p)

    assert [c["name"] for c in info["columns"]] == ["id", "name"]


def test_a_broken_file_still_reports_its_own_error(conn, tmp_path) -> None:
    """The encoding fallback must not swallow unrelated failures — a file that is
    broken for some OTHER reason has to say so rather than be retried into a
    generic dead end."""
    p = _write(tmp_path, "nope.sqlite3", b"not a supported format")
    with pytest.raises(Exception) as exc:
        conn.analyze_file(p)
    assert "Unsupported file type" in str(exc.value)


def test_analyze_error_reaches_the_caller(tmp_path, monkeypatch) -> None:
    """The reason this took so long to find: the route replaced every exception
    with the constant "Analyze failed", so the UI could not distinguish a bad
    encoding from a missing extension from a corrupt file."""
    import inspect

    from aughor.routers import connections as route_mod

    src = inspect.getsource(route_mod.analyze_connection_file)
    assert 'detail=f"Analyze failed: {exc}"' in src, (
        "the analyze route is hiding its cause again — the message must carry the "
        "underlying error, not a constant")


def test_a_file_duckdb_refuses_in_every_encoding_is_transcoded(conn, tmp_path, monkeypatch) -> None:
    """The escalation's last step, and the reason it exists.

    A real 53-column export failed BOTH the plain read and the `encoding=` retry
    while a synthetic file of the same shape passed, so the retry cannot be assumed
    sufficient. Decoding in Python always produces something readable.

    Simulated by making DuckDB reject the `encoding=` form, since the point is what
    happens when that step does not save us.
    """
    from aughor.connectors.file import local_upload as lu

    p = _write(tmp_path, "stubborn.csv", "id,name\n1,café\n".encode("cp1252"))

    real_expr = lu._reader_expr

    def _sabotage(path, *, encoding=None):
        if encoding:
            return "read_csv('/definitely/not/here.csv')"   # the retry now fails
        return real_expr(path, encoding=None)

    monkeypatch.setattr(lu, "_reader_expr", _sabotage)

    info = conn.analyze_file(p)

    assert [c["name"] for c in info["columns"]] == ["id", "name"]
    assert "café" in str(info.get("preview") or info)


def test_cp1252_only_characters_survive(conn, tmp_path) -> None:
    """cp1252, not latin-1: the 0x80-0x9F range carries curly quotes, en dashes and
    the euro sign, which latin-1 maps to control characters. Excel writes cp1252."""
    p = _write(tmp_path, "curly.csv", 'id,name\n1,"€ smart–watch"\n'.encode("cp1252"))

    info = conn.analyze_file(p)

    flat = str(info.get("preview") or info)
    assert "€" in flat and "–" in flat, f"cp1252-only characters were lost: {flat}"


def test_the_transcode_happens_once_per_file(conn, tmp_path, monkeypatch) -> None:
    """The connector is rebuilt on EVERY connection open and re-reads every file, so
    an uncached transcode re-encodes the file each time — a ~96 MB write per open for
    the CSV that prompted this, into a temp directory nobody deletes. Thirty-four of
    them (2.7 GB) accumulated before it was caught.
    """
    from aughor.connectors.file import local_upload as lu

    lu._TRANSCODE_CACHE.clear()
    p = _write(tmp_path, "repeat.csv", "id,name\n1,café\n".encode("cp1252"))

    calls = {"n": 0}
    real_read = Path.read_bytes

    def counting_read(self):
        if self == p:
            calls["n"] += 1
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", counting_read)

    first = lu._transcode_to_utf8(p)
    second = lu._transcode_to_utf8(p)
    third = lu._transcode_to_utf8(p)

    assert first == second == third, "each call produced a different copy"
    assert calls["n"] == 1, f"the file was re-encoded {calls['n']} times, not cached"


def test_an_edited_file_is_transcoded_again(conn, tmp_path) -> None:
    """Cache on (path, size, mtime): re-uploading different content under the same
    name must not serve the previous copy."""
    import os
    from aughor.connectors.file import local_upload as lu

    lu._TRANSCODE_CACHE.clear()
    p = _write(tmp_path, "changing.csv", "id,name\n1,café\n".encode("cp1252"))
    first = lu._transcode_to_utf8(p)

    p.write_bytes("id,name\n1,café\n2,naïve\n".encode("cp1252"))
    os.utime(p, (0, 0))                       # force a distinct mtime
    second = lu._transcode_to_utf8(p)

    assert second != first, "an edited file served the stale transcode"
    assert "naïve" in second.read_text(encoding="utf-8")


# ── the workspace materializes once, not per connection ─────────────────────


def test_a_second_connection_reuses_the_materialized_workspace(tmp_path, monkeypatch) -> None:
    """The connector is built fresh on every connection open and used to rebuild the
    whole workspace each time — 4.7s for 58 tables, 9.7s once a 96 MB CSV joined
    them, paid by every catalog browse and every explorer spawn."""
    from aughor.control_plane import vending
    from aughor.connectors.file import local_upload as lu

    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    lu.evict_base("reuse_test")

    builds = {"n": 0}
    real = lu.LocalUploadConnection._materialize

    def counting(self):
        builds["n"] += 1
        return real(self)

    monkeypatch.setattr(lu.LocalUploadConnection, "_materialize", counting)

    a = lu.LocalUploadConnection(dsn="local://", connection_id="reuse_test")
    a.ingest_file(_write(tmp_path, "seed.csv", b"id,name\n1,alpha\n"),
                  table_name="seed", schema="main")

    # The ingest changed the files, so the NEXT open must rebuild — that is the
    # invalidation working, and counting it as reuse would hide a stale workspace.
    b = lu.LocalUploadConnection(dsn="local://", connection_id="reuse_test")
    builds["n"] = 0

    c = lu.LocalUploadConnection(dsn="local://", connection_id="reuse_test")
    d = lu.LocalUploadConnection(dsn="local://", connection_id="reuse_test")

    assert builds["n"] == 0, (
        f"the workspace was re-materialized {builds['n']} times with no file change")
    assert d.execute("__t__", "SELECT count(*) FROM main.seed").rows
    assert b.execute("__t__", "SELECT count(*) FROM main.seed").rows
    assert c.execute("__t__", "SELECT count(*) FROM main.seed").rows


def test_a_new_upload_invalidates_the_cached_workspace(tmp_path, monkeypatch) -> None:
    """Reuse must never serve a workspace that no longer matches its files."""
    from aughor.control_plane import vending
    from aughor.connectors.file import local_upload as lu

    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    lu.evict_base("inval_test")

    a = lu.LocalUploadConnection(dsn="local://", connection_id="inval_test")
    a.ingest_file(_write(tmp_path, "one.csv", b"id\n1\n"), table_name="one", schema="main")

    b = lu.LocalUploadConnection(dsn="local://", connection_id="inval_test")
    names = {r[0] for r in b.execute(
        "__t__", "SELECT table_name FROM information_schema.tables").rows}
    assert "one" in names, f"a table uploaded a moment ago was not visible: {sorted(names)}"


def test_each_connection_keeps_its_own_search_path(tmp_path, monkeypatch) -> None:
    """Cursors share the data but NOT the session. This is the property that makes
    sharing safe: `search_path` is scoped per connection precisely so one schema's
    query cannot resolve to a sibling's same-named table."""
    from aughor.control_plane import vending
    from aughor.connectors.file import local_upload as lu

    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    lu.evict_base("path_test")

    seed = lu.LocalUploadConnection(dsn="local://", connection_id="path_test")
    seed.ingest_file(_write(tmp_path, "a.csv", b"v\n1\n"), table_name="t", schema="alpha")
    seed.ingest_file(_write(tmp_path, "b.csv", b"v\n2\n"), table_name="t", schema="beta")

    ca = lu.LocalUploadConnection(dsn="local://", connection_id="path_test", schema_name="alpha")
    cb = lu.LocalUploadConnection(dsn="local://", connection_id="path_test", schema_name="beta")

    assert ca.execute("__t__", "SELECT v FROM t").rows[0][0] == "1"
    assert cb.execute("__t__", "SELECT v FROM t").rows[0][0] == "2", (
        "a shared database let one schema's bare table name resolve to another's")


def test_a_reader_clone_shares_rather_than_rebuilds(tmp_path, monkeypatch) -> None:
    """`make_reader` exists to make reads parallel; rebuilding per reader made each
    one pay a full workspace materialization."""
    from aughor.control_plane import vending
    from aughor.connectors.file import local_upload as lu

    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    lu.evict_base("reader_test")

    c = lu.LocalUploadConnection(dsn="local://", connection_id="reader_test")
    c.ingest_file(_write(tmp_path, "r.csv", b"id\n5\n"), table_name="r", schema="main")

    builds = {"n": 0}
    real = lu.LocalUploadConnection._materialize
    monkeypatch.setattr(lu.LocalUploadConnection, "_materialize",
                        lambda self: (builds.__setitem__("n", builds["n"] + 1), real(self))[1])

    reader = c.make_reader()

    assert builds["n"] == 0, "make_reader re-materialized the workspace"
    assert reader.execute("__t__", "SELECT id FROM main.r").rows[0][0] == "5"
