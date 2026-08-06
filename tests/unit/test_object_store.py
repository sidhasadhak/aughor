"""The durable-upload seam: no-op without a store, correct mirror semantics with one.

The wire protocol was proven against a real private Vercel Blob store on
2026-08-06 (put/list/get/delete round-trip, stray deletion, cold materialization);
these tests pin the semantics with a mock transport so CI needs no token.
"""
from __future__ import annotations

import json

import httpx
import pytest

from aughor.control_plane import object_store as O


def test_absent_store_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(O.TOKEN_ENV, raising=False)
    (tmp_path / "x.csv").write_text("a\n1\n")
    assert not O.available()
    assert O.mirror_up(tmp_path, "p") == 0
    assert O.mirror_down(tmp_path, "p") == 0
    assert O.list_remote("p") == {}


class _FakeBlob:
    """Just enough of the Blob REST API: list, put, delete, download."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}       # pathname -> content
        self.put_headers: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.lstrip("/")
        if request.method == "GET" and not path:                 # list
            prefix = request.url.params.get("prefix", "")
            blobs = [{"url": f"https://fake.blob/{p}", "pathname": p, "size": len(v)}
                     for p, v in self.objects.items() if p.startswith(prefix)]
            return httpx.Response(200, json={"blobs": blobs, "hasMore": False})
        if request.method == "GET" and path.startswith("fake-download/"):
            p = path[len("fake-download/"):]
            return httpx.Response(200, content=self.objects[p])
        if request.method == "POST" and path == "delete":        # delete by urls
            for url in json.loads(request.content)["urls"]:
                p = url.split("/fake-download/", 1)[-1] if "/fake-download/" in url \
                    else url.split("https://fake.blob/", 1)[-1]
                self.objects.pop(p, None)
            return httpx.Response(200, json={})
        if request.method == "PUT":                              # upload
            self.put_headers.append(dict(request.headers))
            self.objects[path] = request.content
            return httpx.Response(200, json={"url": f"https://fake.blob/{path}",
                                             "pathname": path})
        return httpx.Response(404)


@pytest.fixture()
def fake_blob(monkeypatch):
    fake = _FakeBlob()
    monkeypatch.setenv(O.TOKEN_ENV, "test-token")

    def _client():
        transport = httpx.MockTransport(fake.handler)
        return httpx.Client(transport=transport,
                            base_url="https://blob.vercel-storage.com")

    monkeypatch.setattr(O, "_client", _client)
    # download URLs in the fake point at fake.blob — route them through the handler
    monkeypatch.setattr(O, "_BLOB_API", "https://blob.vercel-storage.com")
    orig_list = O.list_remote

    def list_with_downloadable_urls(prefix):
        out = orig_list(prefix)
        for rel, meta in out.items():
            meta["url"] = f"https://blob.vercel-storage.com/fake-download/{prefix}/{rel}"
        return out

    monkeypatch.setattr(O, "list_remote", list_with_downloadable_urls)
    return fake


def test_mirror_up_uploads_marks_private_and_deletes_strays(tmp_path, fake_blob):
    (tmp_path / "main").mkdir()
    (tmp_path / "main" / "a.csv").write_text("a,b\n1,2\n")
    (tmp_path / "t.json").write_text("{}")
    assert O.mirror_up(tmp_path, "uploads/o/c") == 2
    assert set(fake_blob.objects) == {"uploads/o/c/main/a.csv", "uploads/o/c/t.json"}
    assert all(h.get("x-vercel-blob-access") == "private" for h in fake_blob.put_headers)

    (tmp_path / "main" / "a.csv").unlink()          # a drop → remote stray must go
    assert O.mirror_up(tmp_path, "uploads/o/c") == 1
    assert set(fake_blob.objects) == {"uploads/o/c/t.json"}


def test_mirror_up_skips_unchanged_files(tmp_path, fake_blob):
    (tmp_path / "a.csv").write_text("a\n1\n")
    assert O.mirror_up(tmp_path, "p") == 1
    assert O.mirror_up(tmp_path, "p") == 0          # same size → no re-upload


def test_mirror_down_materializes_a_cold_root(tmp_path, fake_blob):
    src = tmp_path / "src"
    (src / "main").mkdir(parents=True)
    (src / "main" / "a.csv").write_text("a,b\n1,2\n")
    O.mirror_up(src, "uploads/o/c")

    cold = tmp_path / "cold"
    assert O.mirror_down(cold, "uploads/o/c") == 1
    assert (cold / "main" / "a.csv").read_text() == "a,b\n1,2\n"
    assert O.mirror_down(cold, "uploads/o/c") == 0  # already materialized


def test_connection_persists_after_ingest_and_delete(tmp_path, monkeypatch):
    """The wiring: ingest mirrors up; delete funnels through the tombstone hook."""
    calls: list[str] = []
    from aughor.control_plane import object_store as store_mod
    monkeypatch.setattr(store_mod, "mirror_up", lambda root, prefix: calls.append(prefix) or 1)
    monkeypatch.setattr(store_mod, "mirror_down", lambda root, prefix: 0)
    monkeypatch.setenv("AUGHOR_UPLOAD_DIR", str(tmp_path / "uploads"))
    import importlib
    from aughor.control_plane import vending
    importlib.reload(vending)
    from aughor.connectors.file import local_upload
    importlib.reload(local_upload)

    csv = tmp_path / "probe.csv"
    csv.write_text("a,b\n1,2\n")
    conn = local_upload.LocalUploadConnection(connection_id="blobtest")
    conn.ingest_file(csv, table_name="probe")
    assert len(calls) >= 1 and all("blobtest" in p for p in calls)
    n = len(calls)
    conn.delete_table("probe")
    assert len(calls) > n                            # the drop mirrored too
