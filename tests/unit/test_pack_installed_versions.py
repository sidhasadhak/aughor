"""Arc FA, FA-6 (ROADMAP §3.60) — packs as products: the installed version, what a pack offered, and the upgrade
(`aughor/packs/upgrade.py`, flag `packs.installed_versions`).

What these hold. Off, a bind stores the caller's version and nothing else, and the upgrade doors are closed. On, a
bind records the MANIFEST's version (never the caller's), who bound it and a snapshot of what the pack offered. The
diff against a newer version lists what was added, changed and removed, each item a person declined marked with the
version it was declined in — read from the three stores that keep a decline (the vocabulary's tombstone, the inbox's
rejected proposal, the explorer's withdrawn proposal). The upgrade proposes only new and changed items, never an
unchanged one a person declined, and records the new snapshot.

Run against the real stores (each redirected by `tests/conftest.py`); no model is called and no warehouse is read —
the alert backtests replay a series handed in.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.actions import inbox
from aughor.kernel.flags import flag_overrides
from aughor.ontology import vocabulary as V
from aughor.packs import bindings as B
from aughor.packs import upgrade as U
from aughor.packs.models import (
    ExpectedLink, ExpectedObject, ExpectedProcess, ExpectedStage, MetricBinds, Pack, PackManifest, PackMetric,
    PackMonitorPrior, PackOntology,
)

D0 = date(2026, 6, 1)
TODAY = D0 + timedelta(days=420)


def _conn() -> str:
    return "conn-" + uuid.uuid4().hex[:6]


def _series(sql: str):
    return ["day", "value"], [((D0 + timedelta(days=i)).isoformat(), 0.03) for i in range(420)], None


def _pack(version: int, *, aliases=("nim", "margin on earning assets"), low=0.02, high=0.09, formula="SUM(a) / SUM(b)",
          extra_metric: bool = False) -> Pack:
    metrics = [PackMetric(name="net_interest_margin", title="Net interest margin", aliases=list(aliases),
                          formula=formula, unit="ratio", binds=MetricBinds())]
    if extra_metric:
        metrics.append(PackMetric(name="cost_of_funds", title="Cost of funds", formula="SUM(c) / SUM(d)", unit="ratio"))
    return Pack(
        manifest=PackManifest(id="fa6-test", name="FA-6 test", version=version, status="active"),
        metrics=metrics,
        monitors=[PackMonitorPrior(id="nim_band", metric="net_interest_margin", unit="ratio", low=low, high=high,
                                   measured_on=["fdic-financials-2025-q2"])],
        ontology=PackOntology(
            objects=[ExpectedObject(name="Account"), ExpectedObject(name="Holder")],
            links=[ExpectedLink(from_object="Account", to_object="Holder", via="holder_id", verb="belongs to")],
            processes=[ExpectedProcess(name="opening", object="Account",
                                       stages=[ExpectedStage(name="applied"), ExpectedStage(name="opened")])]))


def _registered(monkeypatch):
    metric = SimpleNamespace(name="net_interest_margin", label="NIM", status="approved", sql="SUM(a) / SUM(b)",
                             tables=["bank.quarterly"], filters=[], unit="ratio")
    monkeypatch.setattr("aughor.semantic.metrics.get_metric",
                        lambda name, path=None, connection_id=None: metric if name == "net_interest_margin" else None)
    monkeypatch.setattr("aughor.settling.sampler.time_tables", lambda cid: [("bank.quarterly", "as_of", 400)])
    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda cid: None)


def _bind(pack: Pack, conn: str, by: str = "user:ana") -> dict:
    """What the bind door does with the flag on: the manifest's version, who, and the snapshot."""
    B.save_binding(pack.id, conn, {"account": {"table": "accounts"}}, version=pack.manifest.version, verified=True,
                   installed=U.install_record(pack, by=by))
    return B.load_install(pack.id, conn)


def _client() -> TestClient:
    from aughor.routers.packs import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── off ──────────────────────────────────────────────────────────────────────────────────────

def test_off_the_bind_stores_the_callers_version_and_nothing_else_and_the_upgrade_doors_are_closed(monkeypatch):
    monkeypatch.setattr("aughor.routers.connections.open_connection_for",
                        lambda cid: (_ for _ in ()).throw(RuntimeError("unreachable")))
    conn = _conn()
    client = _client()
    with flag_overrides({U.FLAG: False}):
        r = client.post("/packs/banking/bind", json={"connection_id": conn, "bindings": {}, "version": 7})
        assert r.status_code == 200, r.text
        body = r.json()
        # the response carries exactly the keys it always did
        assert set(body) == {"org_id", "pack_id", "connection_id", "schema", "version", "bindings", "verified",
                             "updated_at", "missing", "dry_run_errors", "arrival"}
        assert body["version"] == 7
        assert B.load_binding("banking", conn)["version"] == 7
        install = B.load_install("banking", conn)
        assert install["bound_by"] == "" and install["offered"] == {}
        assert client.get(f"/packs/banking/upgrade?connection_id={conn}").status_code == 404
        assert client.post("/packs/banking/upgrade", json={"connection_id": conn}).status_code == 404
        assert client.get("/packs/banking/installs").status_code == 404


def test_off_the_store_writes_the_row_exactly_as_before():
    conn = _conn()
    rec = B.save_binding("banking", conn, {"r": {"table": "t"}}, version=3, verified=True)
    assert set(rec) == {"org_id", "pack_id", "connection_id", "schema", "version", "bindings", "verified", "updated_at"}
    assert B.load_binding("banking", conn) == {k: rec[k] for k in rec}
    # a later plain bind leaves what an install recorded as it stands — and replaces the version, as it always did
    B.save_binding("banking", conn, {}, version=2, installed={"bound_by": "user:ana", "offered": {"version": 2, "items": {}}})
    B.save_binding("banking", conn, {}, version=1)
    after = B.load_install("banking", conn)
    assert after["version"] == 1 and after["bound_by"] == "user:ana" and after["offered"]["version"] == 2


# ── on: the bind records the manifest's version ──────────────────────────────────────────────

def test_on_the_bind_records_the_manifests_version_who_bound_it_and_what_the_pack_offered(monkeypatch):
    monkeypatch.setattr("aughor.routers.connections.open_connection_for",
                        lambda cid: (_ for _ in ()).throw(RuntimeError("unreachable")))
    from aughor.packs.loader import load_pack
    from aughor.packs.roots import pack_dir
    banking = load_pack(pack_dir("banking"))
    conn = _conn()
    client = _client()
    with flag_overrides({U.FLAG: True}):
        # the caller says 9; the manifest says what it is
        r = client.post("/packs/banking/bind", json={"connection_id": conn, "bindings": {}, "version": 9})
        assert r.status_code == 200, r.text
        assert r.json()["version"] == banking.manifest.version != 9
        assert r.json()["bound_by"].startswith("user:")
        install = B.load_install("banking", conn)
        assert install["version"] == banking.manifest.version and install["bound_by"].startswith("user:")
        items = install["offered"]["items"]
        assert install["offered"]["version"] == banking.manifest.version and install["offered"]["at"]
        kinds = {i["kind"] for i in items.values()}
        assert kinds == {"term", "alert", "metric", "structure"}
        # an alert per bounded side of a measured prior, and none for the unmeasured one
        assert {"alert:net_interest_margin:below", "alert:net_interest_margin:above"} <= set(items)
        assert not any(k.startswith("alert:approval_rate") for k in items)
        assert "term:metric:net_interest_margin:nim" in items
        assert all(len(i["hash"]) == 16 for i in items.values())
        # the same pack read again is up to date: nothing added, changed or removed, and no upgrade
        up = client.get(f"/packs/banking/upgrade?connection_id={conn}")
        assert up.status_code == 200, up.text
        d = up.json()
        assert d["installed"] == d["available"] == banking.manifest.version and d["recorded"] is True
        assert d["added"] == d["changed"] == d["removed"] == [] and d["upgrade_available"] is False
        assert client.post("/packs/banking/upgrade", json={"connection_id": conn}).status_code == 409
        installs = client.get("/packs/banking/installs").json()
        row = next(i for i in installs["installs"] if i["connection_id"] == conn)
        assert row["installed"] == banking.manifest.version and row["recorded"] and row["behind"] is False
        assert client.get(f"/packs/banking/upgrade?connection_id={_conn()}").status_code == 404


# ── the diff, with what a person declined ────────────────────────────────────────────────────

def test_the_diff_lists_added_changed_and_removed_and_marks_each_declined_item_with_its_version(monkeypatch):
    _registered(monkeypatch)
    conn = _conn()
    v1 = _pack(1)
    install = _bind(v1, conn)
    # the bind proposed v1's terms and alerts; a person declined one term and the alert below the band
    from aughor.packs.connect import alert_proposals_for, propose_terms
    propose_terms(v1, conn)
    staged = alert_proposals_for(v1, conn, run_sql=_series, today=TODAY)["staged"]
    below = next(s for s in staged if s["side"] == "below")
    above = next(s for s in staged if s["side"] == "above")
    V.decline_synonym(conn, "metric", "net_interest_margin", "nim", by="user:ana")
    assert inbox.reject_proposal(below["proposal_id"], actor="user:ana")
    assert inbox.reject_proposal(above["proposal_id"], actor="user:ana")

    # v2: a term added and one removed, the band's low moved (its high did not), a metric added, a recipe changed
    v2 = _pack(2, aliases=("nim", "earning asset margin"), low=0.025, formula="SUM(a) / NULLIF(SUM(b), 0)",
               extra_metric=True)
    d = U.diff(v2, install, connection_id=conn)
    assert (d["installed"], d["available"], d["recorded"], d["upgrade_available"]) == (1, 2, True, True)
    added = {r["key"]: r for r in d["added"]}
    changed = {r["key"]: r for r in d["changed"]}
    removed = {r["key"]: r for r in d["removed"]}
    kept = {r["key"]: r for r in d["kept_declined"]}
    # (the new metric's title is its own name, so it is no term)
    assert set(added) == {"term:metric:net_interest_margin:earning asset margin", "metric:cost_of_funds"}
    assert set(changed) == {"alert:nim_band:below", "metric:net_interest_margin"}
    assert set(removed) == {"term:metric:net_interest_margin:margin on earning assets"}
    # the declined term and the declined, unchanged high side stay declined — marked with the version they were declined in
    assert set(kept) == {"term:metric:net_interest_margin:nim", "alert:nim_band:above"}
    assert all(r["declined"] and r["declined_in"] == 1 and not r["will_offer"] for r in kept.values())
    # the low side was declined at v1 and has changed since: offered again, and said
    low = changed["alert:nim_band:below"]
    assert low["declined"] and low["declined_in"] == 1 and low["will_offer"] and "changed since" in low["why"]
    assert low["was"] == "fires below 0.02 ratio" and low["said"] == "fires below 0.025 ratio"
    # a metric recipe and a removed item are never proposed, and say why
    assert not changed["metric:net_interest_margin"]["will_offer"] and changed["metric:net_interest_margin"]["why"] == U.METRIC_NOTE
    assert removed["term:metric:net_interest_margin:margin on earning assets"]["why"] == U.REMOVED_NOTE
    assert d["counts"]["added"]["term"] == 1 and d["counts"]["kept_declined"]["alert"] == 1
    assert d["not_read"] == {"structure": "no ontology is built for this connection, so what a person withdrew cannot be read"}


def test_the_upgrade_proposes_only_the_new_and_changed_and_never_an_unchanged_declined_item(monkeypatch):
    _registered(monkeypatch)
    conn = _conn()
    v1 = _pack(1)
    install = _bind(v1, conn)
    from aughor.packs.connect import alert_proposals_for, propose_terms
    propose_terms(v1, conn)
    staged = alert_proposals_for(v1, conn, run_sql=_series, today=TODAY)["staged"]
    by_side = {s["side"]: s["proposal_id"] for s in staged}
    V.decline_synonym(conn, "metric", "net_interest_margin", "nim", by="user:ana")
    assert inbox.reject_proposal(by_side["above"], actor="user:ana")       # declined, and v2 does not change it

    v2 = _pack(2, aliases=("nim", "margin on earning assets", "earning asset margin"), low=0.025)
    out = U.apply(v2, install, B.load_binding(v2.id, conn), by="user:ben", connection_id=conn,
                  run_sql=_series, today=TODAY)
    assert (out["from"], out["to"]) == (1, 2)
    # one new term, and no other: the declined one is not offered, the one still pending is not proposed twice
    assert out["terms"]["proposed"] == 1 and [t["synonym"] for t in out["terms"]["terms"]] == ["earning asset margin"]
    assert ("metric", "net_interest_margin", "nim") in V.declined_synonyms(conn)
    assert "nim" not in {s.synonym for s in V.synonyms_for(conn)}
    # the changed low side is staged under the new version; the unchanged high side a person declined is not
    assert [(s["side"], s["bound"]) for s in out["alerts"]["staged"]] == [("below", 0.025)]
    new = inbox.get_proposal(out["alerts"]["staged"][0]["proposal_id"])
    assert new.call_id == "prior:nim_band:below@v2" and new.detail["pack_version"] == 2
    # the v1 offer of the old band was still pending beside it: superseded, history intact
    assert out["alerts"]["superseded"] == [by_side["below"]]
    assert inbox.get_proposal(by_side["below"]).status == "superseded"
    assert inbox.get_proposal(by_side["above"]).status == "rejected"
    assert out["kept_declined"] == 2
    # the binding is v2 now, under who upgraded it, its roles kept, the decline carried with the version it was made in
    after = B.load_install(v2.id, conn)
    assert after["version"] == 2 and after["bound_by"] == "user:ben" and after["offered"]["upgraded_from"] == 1
    assert B.load_binding(v2.id, conn)["bindings"] == {"account": {"table": "accounts"}}
    items = after["offered"]["items"]
    assert items["term:metric:net_interest_margin:nim"]["declined_in"] == 1
    assert items["alert:nim_band:above"]["declined_in"] == 1
    assert "declined_in" not in items["alert:nim_band:below"]
    # and the next look says it is up to date — with the two declines still dated v1
    d = U.diff(v2, after, connection_id=conn)
    assert d["upgrade_available"] is False and d["added"] == d["changed"] == []
    assert {(r["key"], r["declined_in"]) for r in d["kept_declined"]} == {
        ("term:metric:net_interest_margin:nim", 1), ("alert:nim_band:above", 1)}


def test_a_binding_made_before_versions_were_recorded_says_so_and_its_upgrade_offers_nothing_twice(monkeypatch):
    _registered(monkeypatch)
    conn = _conn()
    v1 = _pack(1)
    B.save_binding(v1.id, conn, {}, version=1)            # as every binding was before the flag
    from aughor.packs.connect import alert_proposals_for, propose_terms
    propose_terms(v1, conn)
    first = alert_proposals_for(v1, conn, run_sql=_series, today=TODAY)["staged"]
    # a person declined a term and the band's high side before anything recorded which version offered them
    V.decline_synonym(conn, "metric", "net_interest_margin", "nim", by="user:ana")
    above = next(s["proposal_id"] for s in first if s["side"] == "above")
    assert inbox.reject_proposal(above, actor="user:ana")
    install = B.load_install(v1.id, conn)
    d = U.diff(v1, install, connection_id=conn)
    assert d["recorded"] is False and d["note"] == U.UNRECORDED and d["upgrade_available"] is True
    assert d["removed"] == [] and d["changed"] == [] and d["added"]
    added = {r["key"]: r for r in d["added"]}
    # declined, with no record of the version it was declined in — and not offered again, its content unchanged
    for key in ("term:metric:net_interest_margin:nim", "alert:nim_band:above"):
        assert added[key]["declined"] and added[key]["declined_in"] is None and not added[key]["will_offer"]
    out = U.apply(v1, install, B.load_binding(v1.id, conn), by="user:ana", connection_id=conn,
                  run_sql=_series, today=TODAY)
    # everything else was already proposed: nothing is proposed again, and the snapshot is recorded now
    assert out["terms"]["proposed"] == 0 and out["alerts"]["staged"] == []
    assert [s["side"] for s in out["alerts"]["already_staged"]] == ["below"]
    assert inbox.get_proposal(above).status == "rejected"
    assert len([p for p in inbox.list_proposals(connection_id=conn) if p.kind == "monitor_bundle"]) == 2
    assert B.load_install(v1.id, conn)["offered"]["version"] == 1


# ── the structure a person withdrew, from the explorer's record ──────────────────────────────

def test_a_withdrawn_structure_proposal_with_the_packs_provenance_is_read_as_declined_in_its_version():
    from aughor.ontology.drafts import DraftProposal, OntologyDraft, save_draft
    from aughor.ontology.models import OntologyEntity, OntologyGraph
    from aughor.packs.drafter import link_reason
    conn = _conn()
    pack = _pack(1)
    graph = OntologyGraph(connection_id=conn, schema_name="bank", schema_fingerprint="fp")
    graph.entities["Account"] = OntologyEntity(id="Account", display_name="Account", source_tables=["bank.accounts"],
                                               identity_key="account_id", grain_verified=True)
    lk = pack.ontology.links[0]
    save_draft(OntologyDraft(connection_id=conn, schema_name="bank", proposals={
        "process:opening": DraftProposal(key="process:opening", kind="process", status="proposed", sentence="",
                                         target={"process": "opening", "entity": "Account"},
                                         said={"id": "opening"}, provenance="pack:fa6-test@1"),
        "link:a-h": DraftProposal(key="link:a-h", kind="link", status="proposed", sentence="",
                                  target={"relationship": "gone"}, said={"reason": link_reason("fa6-test", lk)},
                                  provenance="pack:fa6-test@1"),
        # another pack's, and a model's: neither is this pack's decline
        "process:other": DraftProposal(key="process:other", kind="process", status="proposed", sentence="",
                                       target={"process": "opening"}, said={"id": "opening"}, provenance="pack:else@3"),
    }))
    stones, unread = U.declined(pack, conn, "bank", graph=graph)
    assert unread == {}
    assert stones["structure:process:opening"] == {"in": 1, "where": "ontology draft", "hash": None}
    assert stones["structure:link:Account>Holder"]["in"] == 1
    # the drafter's own reason is what the match reads, so the two cannot drift apart
    install = {"version": 1, "offered": U.install_record(pack, by="user:ana")["offered"], "bound_by": "user:ana"}
    d = U.diff(_pack(2), install, connection_id=conn, schema="bank", graph=graph)
    assert {r["key"] for r in d["kept_declined"]} >= {"structure:process:opening", "structure:link:Account>Holder"}


@pytest.mark.parametrize("flag", [U.FLAG])
def test_the_flag_is_registered_off_by_default(flag):
    from aughor.kernel.flags import FLAG_ENV, flag_disposition, flag_enabled
    assert flag in FLAG_ENV and flag_disposition(flag) == "graduation_queue"
    with flag_overrides({}):
        assert flag_enabled(flag) is False
