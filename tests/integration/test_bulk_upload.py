"""Bulk CSV import — POST /connections/{conn}/files/bulk ingests many files into
one schema in a single request, with partial-success semantics: one unreadable
file must not sink the whole batch.

Hermetic: the storage root (the vending seam) is redirected to a tmp dir so the
real data/uploads layout is never touched.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.platform import vending


@pytest.fixture
def isolated_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    return tmp_path


def _csv(name: str, body: str):
    return ("files", (name, body, "text/csv"))


def test_bulk_upload_lands_every_file_in_one_schema(client: TestClient, isolated_uploads):
    files = [
        _csv("sales.csv", "id,amount\n1,10\n2,20\n"),
        _csv("regions.csv", "code,name\nDE,Germany\nUS,United States\n"),
    ]
    r = client.post(
        "/connections/workspace/files/bulk",
        files=files,
        data={"schema": "bulk_test"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["schema"] == "bulk_test"
    assert body["added"] == 2 and body["failed"] == 0
    tables = {row["table_name"] for row in body["results"] if row["status"] == "ok"}
    assert tables == {"sales", "regions"}


def test_bulk_upload_partial_success(client: TestClient, isolated_uploads):
    """A bad file is reported as an error; the good files still land."""
    files = [
        _csv("good.csv", "a,b\n1,2\n"),
        ("files", ("broken.xyz", "not a real format", "application/octet-stream")),
    ]
    r = client.post(
        "/connections/workspace/files/bulk",
        files=files,
        data={"schema": "bulk_partial"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["added"] == 1 and body["failed"] == 1
    by_name = {row["filename"]: row for row in body["results"]}
    assert by_name["good.csv"]["status"] == "ok"
    assert by_name["broken.xyz"]["status"] == "error"
    assert by_name["broken.xyz"]["error"]


def test_bulk_upload_defaults_to_main_schema(client: TestClient, isolated_uploads):
    r = client.post(
        "/connections/workspace/files/bulk",
        files=[_csv("nums.csv", "n\n1\n2\n")],
    )
    assert r.status_code == 201, r.text
    assert r.json()["schema"] == "main"
