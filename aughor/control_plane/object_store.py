"""Durable mirroring for vended storage — the Blob half of Invariant #2.

The upload architecture already has the right shape: the FILES under a vended
capability's root (data files, ``.meta.json`` sidecars, the tombstone) are the
durable truth, and the in-memory DuckDB rebuilds from them on every connect
(``LocalUploadConnection._reload_existing_files``). On a serverless deployment that
root sits under ``/tmp`` and vanishes with the instance — so this module mirrors it
against a durable object store:

- :func:`mirror_down` — before a connection rebuilds, fetch every remote object
  missing (or differing) locally. A cold instance re-materializes the workspace
  from Blob exactly as a warm one does from disk.
- :func:`mirror_up` — after a mutation, upload changed local files and delete
  remote strays. Deletions propagate because drops rewrite the TOMBSTONE (a local
  file that mirrors up) and remove data files (which become strays remotely).

Backend selection is by configuration, not code: ``BLOB_READ_WRITE_TOKEN`` present
(what Vercel injects when a Blob store is connected to the project) → the Vercel
Blob REST API over httpx; absent → both calls are no-ops and the local filesystem
is simply durable, which is what local/container deployments already have. The
same availability contract as every other seam: absence degrades, a configured
backend that fails RAISES from the operation (an outage is worth surfacing) — but
callers on the upload path wrap with tolerate(), because a failed mirror must not
take file ingestion down with it.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_BLOB_API = "https://blob.vercel-storage.com"
TOKEN_ENV = "BLOB_READ_WRITE_TOKEN"


def available() -> bool:
    """Whether a durable object store is configured for this process."""
    return bool(os.environ.get(TOKEN_ENV))


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ[TOKEN_ENV]}"}


def _client():
    import httpx
    return httpx.Client(timeout=30.0)


def list_remote(prefix: str) -> dict[str, dict]:
    """Remote objects under ``prefix`` as {relative_path: {url, size}}."""
    if not available():
        return {}
    out: dict[str, dict] = {}
    cursor = None
    with _client() as c:
        while True:
            params = {"prefix": prefix, "limit": "1000"}
            if cursor:
                params["cursor"] = cursor
            r = c.get(_BLOB_API, params=params, headers=_headers())
            r.raise_for_status()
            body = r.json()
            for b in body.get("blobs", []):
                rel = b["pathname"][len(prefix):].lstrip("/")
                if rel:
                    out[rel] = {"url": b["url"], "size": int(b.get("size", -1))}
            cursor = body.get("cursor")
            if not body.get("hasMore"):
                break
    return out


def mirror_down(local_root: Path, prefix: str) -> int:
    """Fetch remote objects missing (or size-differing) under ``local_root``.
    Returns the number of files written. No-op without a configured store."""
    if not available():
        return 0
    remote = list_remote(prefix)
    n = 0
    with _client() as c:
        for rel, meta in remote.items():
            dest = local_root / rel
            if dest.exists() and dest.stat().st_size == meta["size"]:
                continue
            r = c.get(meta["url"], headers=_headers())
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            n += 1
    if n:
        logger.info("object_store: materialized %d object(s) under %s", n, local_root)
    return n


def mirror_up(local_root: Path, prefix: str) -> int:
    """Upload changed local files under ``local_root``; delete remote strays.
    Returns files uploaded + strays deleted. No-op without a configured store."""
    if not available():
        return 0
    remote = list_remote(prefix)
    local: dict[str, Path] = {
        p.relative_to(local_root).as_posix(): p
        for p in local_root.rglob("*") if p.is_file()
    }
    n = 0
    with _client() as c:
        for rel, path in local.items():
            meta = remote.get(rel)
            if meta is not None and meta["size"] == path.stat().st_size:
                continue
            r = c.put(
                f"{_BLOB_API}/{prefix}/{rel}",
                content=path.read_bytes(),
                headers={**_headers(),
                         "x-add-random-suffix": "0",
                         "x-allow-overwrite": "1",
                         # The store is PRIVATE (uploads are tenant data; a public
                         # store is readable by anyone holding the unguessable URL).
                         # Header name is the SDK's own: x-vercel-blob-access.
                         "x-vercel-blob-access": "private"},
            )
            r.raise_for_status()
            n += 1
        strays = [meta["url"] for rel, meta in remote.items() if rel not in local]
        if strays:
            r = c.post(f"{_BLOB_API}/delete", json={"urls": strays}, headers=_headers())
            r.raise_for_status()
            n += len(strays)
    if n:
        logger.info("object_store: mirrored %d change(s) from %s", n, local_root)
    return n
