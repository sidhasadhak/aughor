"""Where a sheet's files live: the file a person brought, its typed rows, and the projection everyone reads.

    <state dir>/sheets/<org>/
        <sheet id>/original.csv     the file as brought, never changed
        <sheet id>/source.parquet   its rows, typed by the kinds chosen at import, each with its file row as ``_row``
        _staged/<token>/<file>      a file brought and read, waiting to become a sheet (gone after a day)
        projection.duckdb           what the Sheets connection reads — rebuilt from the rest, so never backed up

Under the generated-state directory (``db.paths.state_dir``), so a test's redirected state dir moves it with every other
store, and Arc SV's backups copy it (all of it but the projection).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
import uuid
from pathlib import Path

#: A staged file older than this is removed the next time a file is staged.
STAGED_TTL_S = 24 * 3600

_TOKEN = re.compile(r"^[0-9a-f]{16}$")


def _org() -> str:
    from aughor.org.context import current_org_id
    return current_org_id() or "default"


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", part or "")[:80] or "_"


def root(org_id: str = "") -> Path:
    from aughor.db.paths import state_dir
    return state_dir() / "sheets" / _safe(org_id or _org())


def sheet_dir(sheet_id: str, org_id: str = "") -> Path:
    return root(org_id) / _safe(sheet_id)


def source_parquet(sheet_id: str, org_id: str = "") -> Path:
    return sheet_dir(sheet_id, org_id) / "source.parquet"


def projection_path(org_id: str = "") -> Path:
    return root(org_id) / "projection.duckdb"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(data: bytes | Path, filename: str) -> str:
    """Keep a file a person brought until they make a sheet of it; its token. Copied, never moved: a file already
    uploaded to the Workspace stays where it was."""
    _sweep()
    token = uuid.uuid4().hex[:16]
    folder = root() / "_staged" / token
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / _safe(Path(filename).name)
    if isinstance(data, Path):
        shutil.copyfile(data, target)
    else:
        target.write_bytes(data)
    return token


def staged(token: str) -> Path | None:
    """The staged file for a token, or None when there is none (never staged, or swept)."""
    if not _TOKEN.match(token or ""):
        return None
    folder = root() / "_staged" / token
    files = [f for f in folder.iterdir() if f.is_file()] if folder.is_dir() else []
    return files[0] if files else None


def unstage(token: str) -> None:
    if _TOKEN.match(token or ""):
        shutil.rmtree(root() / "_staged" / token, ignore_errors=True)


def _sweep() -> None:
    base = root() / "_staged"
    if not base.is_dir():
        return
    cutoff = time.time() - STAGED_TTL_S
    for folder in base.iterdir():
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a staged file that cannot be read is swept next time", counter="sheets.staged_sweep")


def keep_original(sheet_id: str, path: Path) -> Path:
    """The file a sheet was made from, kept beside it as it was brought."""
    folder = sheet_dir(sheet_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"original{path.suffix.lower()}"
    shutil.copyfile(path, target)
    return target


def remove(sheet_id: str) -> None:
    """A removed sheet's files go — after its tombstone is written, never before."""
    shutil.rmtree(sheet_dir(sheet_id), ignore_errors=True)


def uploaded_files() -> list[dict]:
    """The files already uploaded to the Workspace connection, offered as the place to start a sheet. Read from the
    upload folders by name — the Workspace's own database is never built for this."""
    from aughor.connectors.file.local_upload import is_data_file
    from aughor.control_plane.vending import vend_storage
    from aughor.db.registry import WORKSPACE_ID
    base = vend_storage(WORKSPACE_ID).root
    out: list[dict] = []
    if not base.is_dir():
        return out
    for schema in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        for f in sorted(schema.iterdir()):
            # the upload door's own test: a data file, not its ``.import.json`` sidecar or the tombstone
            if is_data_file(f):
                try:
                    size = f.stat().st_size
                except OSError as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "an uploaded file that cannot be read is not offered", counter="sheets.uploads_list")
                    continue
                out.append({"schema": schema.name, "file": f.name, "size": size})
    return out


def upload_path(schema: str, filename: str) -> Path | None:
    """An uploaded Workspace file by schema and name, or None — never a path outside the upload folder."""
    from aughor.control_plane.vending import vend_storage
    from aughor.db.registry import WORKSPACE_ID
    base = vend_storage(WORKSPACE_ID).root.resolve()
    candidate = (base / schema / filename).resolve()
    if base not in candidate.parents or not candidate.is_file():
        return None
    return candidate
