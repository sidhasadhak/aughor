"""Unit tests for the /ask cross-source federation plumbing (Rec 2 answer-path).

Covers the candidate gathering and the federated SSE emission in isolation — the full /ask stream stays
byte-identical when the flag is off (proven by the rest of the suite), so these test the new branch's parts.
"""
from __future__ import annotations

import asyncio

import aughor.routers.investigations as inv
from aughor.agent.connection_selector import ConnectionSelection
from aughor.agent.federated_planner import FederatedAnswer
from aughor.platform.contracts.execution import QueryResult


def _collect(agen) -> list[str]:
    async def _run():
        return [ev async for ev in agen]
    return asyncio.run(_run())


# ── _federation_candidates ───────────────────────────────────────────────────

def test_candidates_put_current_first_and_include_visible(monkeypatch):
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}])
    monkeypatch.setattr("aughor.security.authz.org_visible_conn_ids", lambda: None)
    cands = inv._federation_candidates("c2")
    assert cands[0] == "c2"                       # the current connection leads
    assert set(cands) == {"c1", "c2", "c3"}


def test_candidates_filtered_to_org_visible(monkeypatch):
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}])
    monkeypatch.setattr("aughor.security.authz.org_visible_conn_ids", lambda: {"c1", "c2"})
    cands = inv._federation_candidates("c1")
    assert set(cands) == {"c1", "c2"}             # c3 not visible to this org → excluded


def test_candidates_are_capped(monkeypatch):
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": f"c{i}"} for i in range(40)])
    monkeypatch.setattr("aughor.security.authz.org_visible_conn_ids", lambda: None)
    assert len(inv._federation_candidates("c0", cap=15)) == 15


# ── _stream_federated ────────────────────────────────────────────────────────

def test_stream_federated_emits_route_and_table(monkeypatch):
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": "c1", "name": "Orders"}, {"id": "c2", "name": "CRM"}])
    result = QueryResult(hypothesis_id="x", sql="-- foreach join",
                         columns=["order_id", "region"], rows=[["1", "EU"], ["2", "US"]], row_count=2)
    monkeypatch.setattr("aughor.agent.federated_planner.answer_federated",
                        lambda q, cids, **kw: FederatedAnswer(result, None, []))
    sel = ConnectionSelection(conn_ids=["c1", "c2"], matched={"c1": ["order"], "c2": ["region"]}, multi_source=True)

    evs = _collect(inv._stream_federated("orders by region", sel))
    blob = "".join(evs)

    assert '"depth": "federated"' in blob                 # a federated route receipt
    assert '"Orders"' in blob and '"CRM"' in blob          # source names surfaced (route + tables_used)
    assert "region" in blob and "EU" in blob               # the merged table rows
    assert evs[-1].startswith("event: done") or '"done"' in evs[-1] or "done" in evs[-1]


def test_stream_federated_surfaces_error_without_table(monkeypatch):
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": "c1", "name": "Orders"}, {"id": "c2", "name": "CRM"}])
    errored = QueryResult(hypothesis_id="x", sql="", columns=[], rows=[], row_count=0,
                          error="plan failed validation: step 1 join key 'x' not found")
    monkeypatch.setattr("aughor.agent.federated_planner.answer_federated",
                        lambda q, cids, **kw: FederatedAnswer(errored, None, ["step 1 ..."]))
    sel = ConnectionSelection(conn_ids=["c1", "c2"], matched={"c1": ["order"], "c2": ["region"]}, multi_source=True)

    blob = "".join(_collect(inv._stream_federated("q", sel)))

    assert "unavailable" in blob                          # honest error headline
    assert '"rows"' not in blob                            # no phantom table on failure
