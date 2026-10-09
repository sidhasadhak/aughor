"""Arc OC-2 — the release: a change waits in a draft and reaches consumers only when a person publishes it
(ROADMAP §3.56).

Before: a declaration was served the moment its door wrote it — an explorer's proposal reached the agent before anyone
confirmed it, and moving a promise from five days to seven silently changed what every claim computed under it meant.
Behind `ontology.release`: the store routes a write by what it says (a verdict stays where it was measured, a change
waits in the draft); the draft reads as a diff classed by the compatibility catalogue, with what each change touches;
publishing is refused while a change would break something or a model's proposal is unconfirmed; and a release that
changes a meaning restates the claims computed under the old one. Off, a declaration is served when saved.

Hermetic: the overrides tree, its draft layer and the ledger are per test; the door flow measures on the seeded samples
warehouse, as the process suite does.
"""
from __future__ import annotations

import copy

import pytest

from aughor.ontology import compatibility as COMPAT
from aughor.ontology import overrides as OV
from aughor.ontology import release as R
from aughor.ontology.overrides import OntologyOverride, delete_override, find_override, save_override, viewing
from tests.unit.test_object_processes import FULFILMENT, PARAMS, door  # noqa: F401 — `door` is a fixture

CONN, SCHEMA = "release-t", "ecommerce"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_SEED_ROOT", tmp_path / "seed")
    monkeypatch.setattr(OV, "_DRAFT_ROOT", tmp_path / "ontology_overrides_draft")
    ledger = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: ledger))
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")     # the gate is on by default since 2026-10-04
    monkeypatch.setattr("aughor.automations.store.list_automations", lambda *a, **k: [])


def _releases(monkeypatch, on: bool) -> None:
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: on and name == "ontology.release")


def _rule(values: list[str], **fields) -> OntologyOverride:
    return OntologyOverride(target_kind="rule", target_id="dach", fields={
        "declared": True, "entity": "Customer", "kind": "value_set", "property": "country", "values": values,
        **fields})


def _published(kind: str, target_id: str):
    with viewing("published"):
        return find_override(CONN, SCHEMA, kind, target_id)


def _drafted(kind: str, target_id: str):
    with viewing("draft"):
        return find_override(CONN, SCHEMA, kind, target_id)


# ── off: served when saved ─────────────────────────────────────────────────────────────────────

def test_off_a_declaration_is_served_when_saved(monkeypatch):
    _releases(monkeypatch, False)
    with viewing("draft"):                                  # the view is never consulted while releases are off
        save_override(CONN, SCHEMA, _rule(["DE", "AT"]))
    assert _published("rule", "dach") is not None
    assert not OV._DRAFT_ROOT.exists()
    assert R.current(CONN, SCHEMA) is None


# ── on: the store routes a write by what it says ──────────────────────────────────────────────

def test_a_change_waits_in_the_draft_and_the_first_release_is_what_was_in_force(monkeypatch):
    _releases(monkeypatch, False)
    save_override(CONN, SCHEMA, _rule(["DE", "AT"]))        # published before releases were turned on
    _releases(monkeypatch, True)
    save_override(CONN, SCHEMA, _rule(["DE", "AT", "CH"]))
    assert _published("rule", "dach").fields["values"] == ["DE", "AT"]          # consumers still read the old
    assert _drafted("rule", "dach").fields["values"] == ["DE", "AT", "CH"]      # the editing screens read the new
    (first,) = R.releases(CONN, SCHEMA)
    assert first["number"] == 1 and first["elements"] == 1 and "turned on" in first["note"]


def test_a_verdict_written_back_stays_where_it_was_measured(monkeypatch):
    _releases(monkeypatch, False)
    save_override(CONN, SCHEMA, _rule(["DE", "AT"]))
    _releases(monkeypatch, True)
    measured = _published("rule", "dach")
    measured.binding = {"rule": {"bound": True, "admitted": 812}}
    save_override(CONN, SCHEMA, measured)                    # the published rule, counted again
    assert _published("rule", "dach").binding["rule"]["admitted"] == 812
    assert OV.draft_entries(CONN, SCHEMA) == []
    save_override(CONN, SCHEMA, _rule(["DE"]))               # a change…
    drafted = _drafted("rule", "dach")
    drafted.binding = {"rule": {"bound": True, "admitted": 640}}
    save_override(CONN, SCHEMA, drafted)                     # …and its own count: both stay in the draft
    assert _drafted("rule", "dach").binding["rule"]["admitted"] == 640
    assert _published("rule", "dach").binding["rule"]["admitted"] == 812


def test_a_withdrawal_waits_in_the_draft_as_a_marker(monkeypatch):
    _releases(monkeypatch, False)
    save_override(CONN, SCHEMA, _rule(["DE", "AT"]))
    _releases(monkeypatch, True)
    assert delete_override(CONN, SCHEMA, "rule", "dach")
    assert _published("rule", "dach") is not None and _drafted("rule", "dach") is None
    ((kind, target_id, drafted, withdrawn),) = OV.draft_entries(CONN, SCHEMA)
    assert (kind, target_id, drafted, withdrawn.fields["values"]) == ("rule", "dach", None, ["DE", "AT"])
    save_override(CONN, SCHEMA, _rule(["DE", "AT", "CH"]))   # declared again in the draft: no longer withdrawn
    assert _drafted("rule", "dach").fields["values"] == ["DE", "AT", "CH"]


def test_a_change_put_back_as_published_leaves_the_draft_and_a_background_count_never_does(monkeypatch):
    _releases(monkeypatch, False)
    save_override(CONN, SCHEMA, _rule(["DE", "AT"]))
    _releases(monkeypatch, True)
    with viewing("draft"):
        save_override(CONN, SCHEMA, _rule(["DE"]))
    with viewing("published"):                               # the hourly measure pass counts the published rule
        measured = find_override(CONN, SCHEMA, "rule", "dach")
        measured.binding = {"rule": {"bound": True, "admitted": 812}}
        save_override(CONN, SCHEMA, measured)
    assert _drafted("rule", "dach").fields["values"] == ["DE"]               # the person's change is kept
    with viewing("draft"):
        save_override(CONN, SCHEMA, _rule(["DE", "AT"]))     # …and put back as it was published
    assert OV.draft_entries(CONN, SCHEMA) == []
    with viewing("draft"):
        assert delete_override(CONN, SCHEMA, "rule", "dach")
        save_override(CONN, SCHEMA, _rule(["DE", "AT"]))     # a withdrawal taken back the same way
    assert OV.draft_entries(CONN, SCHEMA) == [] and _drafted("rule", "dach") is not None


def test_a_draft_copy_that_says_what_is_published_is_no_change(monkeypatch):
    # e.g. a shipped seed update that now says what the draft said: nothing waits to be published
    import yaml
    _releases(monkeypatch, False)
    save_override(CONN, SCHEMA, _rule(["DE", "AT"]))
    _releases(monkeypatch, True)
    copy_path = OV._path(CONN, SCHEMA, "rule", "dach", OV._DRAFT_ROOT)
    copy_path.parent.mkdir(parents=True)
    copy_path.write_text(yaml.safe_dump(_rule(["DE", "AT"]).model_dump()))
    assert R.changes(CONN, SCHEMA) == []


def test_what_a_declaration_said_on_a_day_is_what_was_published_never_a_draft(monkeypatch):
    from aughor.ontology import history as H
    _releases(monkeypatch, False)
    save_override(CONN, SCHEMA, _rule(["DE", "AT"], ))
    _releases(monkeypatch, True)
    save_override(CONN, SCHEMA, _rule(["DE", "AT", "CH"]))  # drafted, never in force
    states = [v["state"] for v in H.versions(CONN, SCHEMA, "rule", "dach")]
    assert states == ["drafted", "declared"]
    now = H.as_of(CONN, SCHEMA, "rule", "dach", "2999-01-01")
    assert now["fields"]["values"] == ["DE", "AT"]


# ── the diff, publishing and what it restates ─────────────────────────────────────────────────

def _book(text: str, *, metric: str = "", object_set: str = "") -> str:
    from aughor.record.claims import Claim, Statement, Warrant, book, claim_key
    claim = Claim(kind="observation", tier="measured", statement=Statement(text=text, metric=metric,
                                                                           object_set=object_set, value=1.0),
                  warrants=[Warrant(kind="run", ref="rcpt-1")], as_of="2026-10-01")
    key = claim_key("release-t", text[:12])
    book(claim, key=key, conn_id=CONN)
    return key


def test_a_meaning_change_names_what_it_touches_and_publishing_restates_it(monkeypatch):
    from aughor.record.claims import latest
    _releases(monkeypatch, False)
    save_override(CONN, SCHEMA, _rule(["DE", "AT"]))
    _releases(monkeypatch, True)
    touched = _book("DACH revenue was 1,744 on 1 October", object_set="dach")
    untouched = _book("total revenue was 9,000 on 1 October", metric="revenue")
    save_override(CONN, SCHEMA, _rule(["DE", "AT", "CH"]))
    (row,) = R.changes(CONN, SCHEMA)
    assert (row["change"], row["class"]) == ("changed", "MEANING")
    assert any("what it admits changed (values)" in r["why"] for r in row["reasons"])
    assert [c["key"] for c in row["touches"]["claims"]] == [touched]
    made = R.publish(CONN, SCHEMA, by="person:ana")
    assert made["number"] == 2 and made["previous"] == f"{CONN}/{SCHEMA}@1"
    assert _published("rule", "dach").fields["values"] == ["DE", "AT", "CH"]
    assert OV.draft_entries(CONN, SCHEMA) == []
    restated = latest(touched)
    assert restated.definition_version == f"{CONN}/{SCHEMA}@1"       # computed under the release before…
    assert restated.extra["definition_changed"]["to_release"] == f"{CONN}/{SCHEMA}@2"   # …and it says so
    assert restated.supersedes                                       # a restatement: the old version kept
    assert "definition_changed" not in latest(untouched).extra


def test_publishing_is_refused_while_a_change_would_break_something(monkeypatch):
    from aughor.automations.models import Automation, Condition, Effect
    _releases(monkeypatch, False)
    save_override(CONN, SCHEMA, OntologyOverride(target_kind="process", target_id="order_fulfilment",
                                                 fields={"declared": True, **copy.deepcopy(FULFILMENT)}))
    _releases(monkeypatch, True)
    watch = Automation(name="Delivery watch", conn_id=CONN,
                       conditions=[Condition(kind="promise_breached", config={"process": "order_fulfilment"})],
                       effects=[Effect(kind="investigate", config={"question": "why"})])
    monkeypatch.setattr("aughor.automations.store.list_automations", lambda *a, **k: [watch])
    monkeypatch.setattr("aughor.ontology.dependents._automations", lambda conn: [watch])
    monkeypatch.setattr(R, "_graph", lambda conn, schema: _fulfilment_graph())
    assert delete_override(CONN, SCHEMA, "process", "order_fulfilment")
    (row,) = R.changes(CONN, SCHEMA)
    assert row["class"] == "ERR" and "Delivery watch" in row["reasons"][0]["why"]
    with pytest.raises(R.ReleaseRefused, match="Delivery watch"):
        R.publish(CONN, SCHEMA, by="person:ana")
    assert _published("process", "order_fulfilment") is not None     # nothing moved
    assert R.discard(CONN, SCHEMA, kind="process", target_id="order_fulfilment") == 1
    assert OV.draft_entries(CONN, SCHEMA) == []


def _fulfilment_graph():
    from aughor.ontology.processes import process_fields, process_from_fields
    from tests.unit.test_object_processes import fresh_graph
    g = fresh_graph()
    g.processes["order_fulfilment"] = process_from_fields("order_fulfilment", process_fields(FULFILMENT))
    return g


def test_a_models_proposal_is_published_only_once_a_person_confirms_it(monkeypatch):
    _releases(monkeypatch, True)
    save_override(CONN, SCHEMA, _rule(["DE", "AT"], origin="model", provenance="model:x@1"))
    (row,) = R.changes(CONN, SCHEMA)
    assert row["class"] == "ERR" and "no person has confirmed it" in row["reasons"][0]["why"]
    with pytest.raises(R.ReleaseRefused, match="confirm"):
        R.publish(CONN, SCHEMA, by="person:ana")
    save_override(CONN, SCHEMA, _rule(["DE", "AT"], origin="human", provenance="model:x@1"))   # confirmed
    assert R.publish(CONN, SCHEMA, by="person:ana")["number"] == 2


def test_a_claim_names_the_release_it_was_computed_under(monkeypatch):
    from aughor.record.claims import latest
    _releases(monkeypatch, True)
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": SCHEMA})
    save_override(CONN, SCHEMA, _rule(["DE"]))               # the scope's first change: release 1 is recorded
    pinned = latest(_book("pinned revenue was 1 on 1 October", metric="revenue"))
    assert pinned.definition_version == f"{CONN}/{SCHEMA}@1"
    _releases(monkeypatch, False)
    off_key = _book("unpinned revenue was 1 on 1 October", metric="revenue")
    assert latest(off_key).definition_version == ""


# ── the catalogue ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind, before, after, expected, says", [
    ("link", {"name": "placed_by", "cardinality": "N:1"}, {"name": "placed_by", "cardinality": "N:N"}, "ERR",
     "to-one to to-many"),
    ("link", {"name": "placed_by"}, {"name": "ordered_by"}, "SAFE", "renamed, the same link"),
    ("entity", {"backing": {"kind": "query", "sql": "SELECT 1", "primary_key": "id"}},
     {"backing": {"kind": "query", "sql": "SELECT 1", "primary_key": "order_id"}}, "ERR", "primary_key"),
    ("entity", {"display_name": "Order"}, {"display_name": "Sales order"}, "SAFE", "display name"),
    ("entity", {"active_filter": "a"}, {"active_filter": "b"}, "MEANING", "what counts as one of its objects"),
    ("entity", {"mystery": 1}, {"mystery": 2}, "WARN", "does not class it"),
    ("action", {"params": [{"name": "amount", "data_type": "NUMERIC"}]}, {"params": []}, "ERR", "'amount' was removed"),
    ("action", {"submission_criteria": []}, {"submission_criteria": [{"expr": "amount < 10", "message": "cap"}]},
     "WARN", "criteria changed"),
    ("object_set", {"filter_sql": "a"}, {"filter_sql": "b"}, "MEANING", "filter sql"),
    ("metric", {"formula_sql": "SUM(a)"}, {"formula_sql": "SUM(b)"}, "MEANING", "formula sql"),
    ("rule", {"entity": "Customer"}, {"entity": "Order"}, "ERR", "another type"),
])
def test_the_catalogue_classes_a_change_by_what_it_does_to_readers(kind, before, after, expected, says):
    cls, reasons = COMPAT.classify(kind, before, after)
    assert cls == expected and any(says in r["why"] for r in reasons), reasons


def test_a_promise_moved_is_a_meaning_change_and_a_watched_one_dropped_breaks():
    before = copy.deepcopy(FULFILMENT)
    later = copy.deepcopy(FULFILMENT)
    later["stages"][2]["promise"]["within_days"] = 7
    cls, reasons = COMPAT.classify("process", before, later)
    assert cls == "MEANING" and any("within_days 5 → 7" in r["why"] for r in reasons)
    dropped = copy.deepcopy(FULFILMENT)
    del dropped["stages"][2]["promise"]
    assert COMPAT.classify("process", before, dropped)[0] == "MEANING"
    assert COMPAT.classify("process", before, dropped, watched_promises={"delivery"})[0] == "ERR"
    renamed = copy.deepcopy(FULFILMENT)
    renamed["stages"][2]["promise"]["name"] = "arrival"
    assert COMPAT.classify("process", before, renamed)[0] == "WARN"


def test_a_draft_that_does_not_bind_cannot_be_published():
    cls, reasons = COMPAT.classify("link", None, {"name": "x"}, binding={"link": {"bound": False, "note": "no keys meet"}})
    assert cls == "ERR" and "no keys meet" in reasons[-1]["why"]


# ── the doors, end to end ─────────────────────────────────────────────────────────────────────

def test_through_the_doors_consumers_read_the_published_release(door, client, monkeypatch):  # noqa: F811
    from aughor.record.claims import latest
    _releases(monkeypatch, True)
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": "ecommerce"})
    conn = PARAMS["connection_id"]
    draft = {**PARAMS, "ontology_view": "draft"}
    assert client.post("/ontology/processes", params=PARAMS, json=FULFILMENT).status_code == 200
    assert client.get("/ontology/processes", params=PARAMS).json()["processes"] == []          # consumers: nothing
    assert [p["id"] for p in client.get("/ontology/processes", params=draft).json()["processes"]] == \
        ["order_fulfilment"]                                                                     # the editor: the draft
    state = client.get("/ontology/release", params=PARAMS).json()
    assert state["enabled"] and state["published"]["number"] == 1
    assert [(c["target_id"], c["change"], c["class"]) for c in state["draft"]] == [("order_fulfilment", "added", "SAFE")]
    assert client.post("/ontology/release/publish", params=PARAMS).json()["number"] == 2
    assert [p["id"] for p in client.get("/ontology/processes", params=PARAMS).json()["processes"]] == \
        ["order_fulfilment"]

    claim_key = _book_on(conn, "late deliveries were 12% of orders in September", metric="delivery_breach_rate")
    assert latest(claim_key).definition_version == f"{conn}/ecommerce@2"
    longer = copy.deepcopy(FULFILMENT)
    longer["stages"][2]["promise"]["within_days"] = 7
    assert client.put("/ontology/processes/order_fulfilment", params=PARAMS, json=longer).status_code == 200
    published = client.get("/ontology/processes", params=PARAMS).json()["processes"][0]
    assert published["stages"][2]["promise"]["within_days"] == 5          # still five until it is published
    (change,) = client.get("/ontology/release", params=PARAMS).json()["draft"]
    assert change["class"] == "MEANING" and [c["key"] for c in change["touches"]["claims"]] == [claim_key]
    made = client.post("/ontology/release/publish", params=PARAMS).json()
    assert made["number"] == 3 and len(made["restated_claims"]) == 1
    assert latest(claim_key).extra["definition_changed"]["from_release"] == f"{conn}/ecommerce@2"
    assert client.post("/ontology/release/publish", params=PARAMS).status_code == 409   # nothing waits


def _book_on(conn: str, text: str, *, metric: str) -> str:
    from aughor.record.claims import Claim, Statement, Warrant, book, claim_key
    claim = Claim(kind="observation", tier="measured", statement=Statement(text=text, metric=metric, value=0.12),
                  warrants=[Warrant(kind="run", ref="rcpt-2")], as_of="2026-09-30")
    key = claim_key("release-door-t", text[:12])
    book(claim, key=key, conn_id=conn)
    return key
