"""The Record is read inside the workspace the reader is in (2026-10-13).

Its ledgers span every connection, and its doors filtered only by org: a reader in theLook's workspace was listed
LuxExperience's claims and corrections, and could open them. The gate is the one every other door applies —
`accessible_catalog_ids`, read ambiently from the ``X-Aughor-Workspace`` header — so a claim about a connection
outside the workspace is neither listed, counted nor opened there; an entry about no connection is an
organisation-wide fact and stays in every workspace; with no workspace the Record is unscoped, as before.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from aughor.record import claims as C
from aughor.routers import record as R
from aughor.workspace import store as WS
from aughor.workspace.context import workspace_scope


@pytest.fixture(autouse=True)
def _own_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")


def _claim(conn: str, text: str) -> str:
    about = C.About(kind="connection", key=conn) if conn else C.About(kind="type", key="OrderItem")
    claim = C.Claim(kind="observation", tier="measured", about=about,
                    statement=C.Statement(text=text, metric="revenue", value=2.53, unit="M"), as_of="2026-10-01",
                    warrants=[C.Warrant(kind="run", ref="receipt-1", detail="SELECT 1")],
                    author="analyst", author_kind="agent", extra={"investigation_id": "inv-" + uuid.uuid4().hex[:6]})
    return C.book(claim, key=C.claim_key("observation", "answer", conn or "org", uuid.uuid4().hex[:8]), conn_id=conn or None)


def _workspace_of(conn: str) -> str:
    ws = "ws-" + uuid.uuid4().hex[:6]
    WS.create_workspace(name="Only " + conn, workspace_id=ws, connection_ids=[conn])
    return ws


def test_a_claim_about_a_connection_outside_the_workspace_is_neither_listed_nor_opened_there():
    here, there = "conn-" + uuid.uuid4().hex[:6], "conn-" + uuid.uuid4().hex[:6]
    mine, theirs, everyones = _claim(here, "APAC revenue was 2.53M"), _claim(there, "EMEA revenue was 1.10M"), _claim("", "Returns rose")
    ws = _workspace_of(here)

    with workspace_scope(ws):
        listed = {c["id"] for c in R.list_record_claims(limit=1000)}
        assert mine in listed and everyones in listed
        assert theirs not in listed
        with pytest.raises(HTTPException) as refused:
            R.get_record_claim(theirs)
        assert refused.value.status_code == 404
        assert R.get_record_claim(mine)["id"] == mine

    # No workspace on the request: unscoped, exactly as before.
    assert {mine, theirs, everyones} <= {c["id"] for c in R.list_record_claims(limit=1000)}


def test_corrections_count_only_what_the_workspace_lists():
    here, there = "conn-" + uuid.uuid4().hex[:6], "conn-" + uuid.uuid4().hex[:6]
    for conn in (here, there):
        C.mark_wrong(_claim(conn, "APAC revenue was 2.53M"), by="person:ana", corrected="APAC revenue was 2.72M")
    ws = _workspace_of(here)

    with workspace_scope(ws):
        out = R.record_corrections(limit=500)
    restated = [e for e in out["entries"] if e["kind"] == "restatement"]
    assert {e["connection_id"] for e in restated} <= {here, ""}
    assert any(e["connection_id"] == here for e in restated)
    assert out["counts"]["restatement"] == len(restated)      # the count and the list describe the same rows
