"""IP-1 — data-quality plays reach the Verifier as rule-outs, and existing playbooks receive them.

The user's call (2026-09-17): when a deep analysis reports its metric moving, list that metric's known
inflation causes (it rose) or deflation causes (it fell) with their fixes, marked as not checked against the
data — deterministic, no model — and only then give existing playbooks the 486 plays (§6 item 21, answer 7).

The labels below are the ones stored on the builder's deployment on 2026-09-17 (202 deep reports, read-only):
the signed change labels the direction reads, and the metric labels the matcher names — including the three
"Total sales (order count)" reports a containment match paired with GMV.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from aughor.playbook import builder, rule_outs, store
from aughor.playbook.models import DATA_QUALITY_TAG, PlaybookEntry
from aughor.playbook.retriever import is_data_quality


@pytest.fixture()
def playbook(tmp_path, monkeypatch):
    path = tmp_path / "playbook.json"
    monkeypatch.setenv("AUGHOR_PLAYBOOK_PATH", str(path))
    return path


@pytest.fixture(scope="module")
def shipped_plays() -> list[PlaybookEntry]:
    return [p for e in builder._load_all_kb() if builder._has_causal_data(e)
            for p in builder._build_entries_for_kb(e)]


def _diagnostic_playbook(path, shipped_plays) -> None:
    """A playbook as every one seeded before IP-0 is: the diagnostic plays, and no data-quality play."""
    store.save_entries([p.model_copy(update={"status": "active"}) for p in shipped_plays
                        if not is_data_quality(p)], path)


# ── the plays carry their cause and fix ────────────────────────────────────────────────────────────────

def test_a_data_quality_play_carries_the_kb_cause_and_fix_verbatim():
    plays = builder._build_entries_for_kb({
        "id": "t_metric", "title": "T",
        "causal_relationships": [{"symptom": "t drops", "check_in_order": ["a"]}],
        "inflation_causes": [{"cause": " test orders ", "fix": " exclude test accounts "}, "duplicate rows"],
        "deflation_causes": [{"cause": "late refunds"}]})
    by_cause = {p.cause: p for p in plays if is_data_quality(p)}
    assert by_cause["test orders"].fix == "exclude test accounts"
    assert by_cause["duplicate rows"].fix == ""            # a bare string carries only its cause
    assert by_cause["late refunds"].fix == ""
    [diagnostic] = [p for p in plays if not is_data_quality(p)]
    assert (diagnostic.cause, diagnostic.fix) == ("", "")


def test_the_shipped_packages_give_486_checks_each_with_its_cause_and_459_with_a_fix(shipped_plays):
    checks = [p for p in shipped_plays if is_data_quality(p)]
    assert len(checks) == 486
    assert all(p.cause for p in checks)
    assert sum(bool(p.fix) for p in checks) == 459
    assert len({builder.stable_key(p.id) for p in shipped_plays}) == len(shipped_plays) == 878


def test_a_play_without_cause_or_fix_keeps_the_receipt_it_had_before_they_existed():
    play = PlaybookEntry(id="p", trigger_metric="m", trigger_condition="c", recommendation="r", tags=["x"])
    before = {k: getattr(play, k) for k in store._CONTENT_FIELDS}          # the pre-IP-1 fingerprint
    assert store.compute_receipt(play) == "pbk_" + hashlib.sha256(
        json.dumps(before, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert store.compute_receipt(play.model_copy(update={"fix": "f"})) != store.compute_receipt(play)


def test_changing_a_plays_status_through_the_api_keeps_its_cause_and_fix(playbook):
    from fastapi.testclient import TestClient

    from aughor.api import app

    store.save_entry(PlaybookEntry(id="kb_t_inflation_x_abc123", source_kb_id="t", trigger_metric="t",
                                   trigger_condition="T appears inflated", recommendation="Check x.",
                                   tags=[DATA_QUALITY_TAG, "inflation"], cause="x", fix="drop x"))
    client = TestClient(app)
    play = client.get("/playbook/kb_t_inflation_x_abc123").json()
    response = client.put("/playbook/kb_t_inflation_x_abc123", json={**play, "status": "deprecated"})
    assert response.status_code == 200, response.text
    kept = store.get_entry("kb_t_inflation_x_abc123")
    assert (kept.status, kept.cause, kept.fix) == ("deprecated", "x", "drop x")


# ── existing playbooks receive the checks, once ────────────────────────────────────────────────────────

def test_a_playbook_seeded_before_ip0_receives_the_486_checks_and_nothing_else_changes(playbook, shipped_plays):
    _diagnostic_playbook(playbook, shipped_plays)
    before = {e.id: e.model_dump() for e in store.list_entries(playbook)}
    assert len(before) == 392

    assert builder.top_up_data_quality(playbook) == {"added": 486, "filled": 0, "kept_deleted": 0}
    after = store.list_entries(playbook)
    assert len(after) == 878
    assert {e.id: e.model_dump() for e in after if e.id in before} == before     # diagnostic plays untouched
    assert builder.top_up_data_quality(playbook) == {"added": 0, "filled": 0, "kept_deleted": 0}


def test_a_check_a_person_deleted_stays_deleted(playbook, shipped_plays):
    _diagnostic_playbook(playbook, shipped_plays)
    builder.top_up_data_quality(playbook)
    gone = next(e for e in store.list_entries(playbook) if is_data_quality(e))
    assert store.delete_entry(gone.id, playbook)

    assert builder.top_up_data_quality(playbook) == {"added": 0, "filled": 0, "kept_deleted": 1}
    assert builder.stable_key(gone.id) not in {builder.stable_key(e.id) for e in store.list_entries(playbook)}


def test_a_check_seeded_without_its_fix_is_given_it_and_keeps_what_a_person_changed(playbook, shipped_plays):
    """A playbook seeded between IP-0 and IP-1 holds the checks without cause or fix."""
    bare = [p.model_copy(update={"cause": "", "fix": ""}) for p in shipped_plays]
    edited = next(p for p in bare if is_data_quality(p) and p.tags[-1] == "deflation")
    edited.recommendation, edited.status = "Our own wording.", "deprecated"
    store.save_entries(bare, playbook)
    version = store.get_entry(edited.id, playbook).version

    counts = builder.top_up_data_quality(playbook)
    assert counts == {"added": 0, "filled": 486, "kept_deleted": 0}
    held = store.get_entry(edited.id, playbook)
    source = next(p for p in shipped_plays if builder.stable_key(p.id) == builder.stable_key(edited.id))
    assert (held.recommendation, held.status) == ("Our own wording.", "deprecated")
    assert (held.cause, held.fix) == (source.cause, source.fix)
    assert held.version == version + 1                       # the advice changed, so the version moves
    assert builder.top_up_data_quality(playbook)["filled"] == 0


def test_an_empty_playbook_is_left_to_the_seed(playbook):
    assert builder.top_up_data_quality(playbook) == {"added": 0, "filled": 0, "kept_deleted": 0}
    assert not playbook.exists()


# ── the direction is the report's own signed change ────────────────────────────────────────────────────

@pytest.mark.parametrize("label, direction", [
    ("-$330K (-18.4% MoM)", "down"),
    ("+1,838.64 (+9.1%) net revenue, 2026-09-07 → 2026-09-08", "up"),
    ("-1,690 orders (97.5% decrease)", "down"),
    ("Total Change: +163 Orders", "up"),
    ("-€23,173 (MoM, -3.93%)", "down"),
    ("-0.82pp", "down"),
    ("+€39,945,224 (artifact of 56-month observation vs ~4-month comparison window)", "up"),
    ("−5.2%", "down"),
    ("1,807 orders on 2026-09-16", None),
    ("N/A", None),
    ("Not measurable — no comparison data exists", None),
    ("", None),
])
def test_the_direction_is_the_first_signed_number_in_the_change_label(label, direction):
    assert rule_outs.change_direction(label) == direction


# ── the metric is named, never guessed ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label, industry, expected", [
    ("total GMV", "retail", ["ec_gmv"]),
    ("GMV (gross merchandise value)", "retail", ["ec_gmv"]),
    ("Total GMV (EUR millions)", "retail", ["ec_gmv"]),
    ("gross margin %", "retail", ["fin_gross_margin"]),
    ("Brand Net Revenue (EUR)", "retail", ["ec_net_revenue"]),         # the industry's own entry first…
    ("Brand Net Revenue (EUR)", None, ["fin_recognized_revenue"]),     # …the shared one when none is known
    ("net revenue (sale price of order items)", "retail", ["ec_net_revenue"]),   # a definition, not a unit
    ("womenswear return rate", "retail", ["ec_return_rate"]),
    ("churn rate", "saas", ["saas_revenue_churn"]),
    ("churn rate", "retail", ["customer_churn_analysis"]),
    ("Total sales (order count)", "retail", []),                       # the bracket says it is a count
    ("Total sales volume (items)", "retail", []),                      # the head is volume, not sales
    ("revenue growth", "retail", []),                                  # a one-word alias names only itself
    ("order count", "retail", []),
    ("total GMV", "airline", []),                                      # another industry's entry is out of scope
    ("total GMV", "", []),                                             # known, uncurated: shared entries only
])
def test_a_metric_label_names_a_kb_entry_only_by_its_head(label, industry, expected):
    assert [m.kb_id for m in rule_outs.match_metric(label, industry)] == expected


# ── the rule-outs on a report ──────────────────────────────────────────────────────────────────────────

def _topped_up(playbook, shipped_plays) -> None:
    _diagnostic_playbook(playbook, shipped_plays)
    builder.top_up_data_quality(playbook)
    builder.activate_seeded()


def test_a_metric_that_fell_lists_its_deflation_causes_with_fixes_not_checked(playbook, shipped_plays):
    _topped_up(playbook, shipped_plays)
    found = rule_outs.rule_outs("total GMV", "-€239,911", "Prior 2 months", industry="retail")
    gmv = [p for p in shipped_plays if p.source_kb_id == "ec_gmv" and "deflation" in p.tags]

    assert found["direction"] == "down"
    assert found["note"] == rule_outs.NOT_CHECKED == "Not checked against your data."
    assert found["matched"] == ["Gross Merchandise Value (GMV)"]
    assert found["lead"] == ("Known ways Gross Merchandise Value (GMV) can read lower than it is. "
                             "Not checked against your data.")
    assert [(i["cause"], i["fix"]) for i in found["items"]] == [(p.cause, p.fix) for p in gmv]
    held = {e.id: e for e in store.list_entries(playbook)}
    for item in found["items"]:
        play = held[item["play_id"]]
        assert (item["version"], item["receipt"]) == (play.version, play.receipt) and "deflation" in play.tags


def test_a_metric_that_rose_lists_its_inflation_causes(playbook, shipped_plays):
    _topped_up(playbook, shipped_plays)
    found = rule_outs.rule_outs("total GMV", "+€39,945,224", "Prior 56 months", industry="retail")
    inflation = [p.cause for p in shipped_plays if p.source_kb_id == "ec_gmv" and "inflation" in p.tags]
    assert found["direction"] == "up"
    assert [i["cause"] for i in found["items"]] == inflation[:rule_outs.MAX_RULE_OUTS]


@pytest.mark.parametrize("label, change, basis", [
    ("total GMV", "N/A", "Prior 2 months"),                       # no move stated
    ("total GMV", "-€239,911", ""),                               # measured against nothing
    ("Total sales (order count)", "-689.9 orders (-93.1%)", "Prior 1 month"),   # names no entry
])
def test_no_rule_outs_without_a_stated_move_on_a_named_metric(playbook, shipped_plays, label, change, basis):
    _topped_up(playbook, shipped_plays)
    assert rule_outs.rule_outs(label, change, basis, industry="retail") is None


def test_a_check_a_person_deprecated_is_not_listed(playbook, shipped_plays):
    _topped_up(playbook, shipped_plays)
    first = rule_outs.rule_outs("GMV", "-€23,173 (MoM, -3.93%)", "May 2025 (MoM)", industry="retail")["items"][0]
    play = store.get_entry(first["play_id"])
    store.save_entry(play.model_copy(update={"status": "deprecated"}))
    again = rule_outs.rule_outs("GMV", "-€23,173 (MoM, -3.93%)", "May 2025 (MoM)", industry="retail")
    assert first["play_id"] not in [i["play_id"] for i in (again or {"items": []})["items"]]


def test_a_playbook_without_the_checks_lists_nothing(playbook, shipped_plays):
    _diagnostic_playbook(playbook, shipped_plays)
    assert rule_outs.rule_outs("total GMV", "-€239,911", "Prior 2 months", industry="retail") is None


def test_listing_a_check_journals_its_use_pinned_to_the_version(playbook, shipped_plays, monkeypatch):
    _topped_up(playbook, shipped_plays)
    used: list[tuple] = []
    monkeypatch.setattr(store, "emit_playbook_use",
                        lambda entry, conn_id=None, used_in=None: used.append((entry.id, conn_id, used_in)))
    found = rule_outs.rule_outs("total GMV", "-€239,911", "Prior 2 months", industry="retail", connection_id="c1")
    assert used == [(i["play_id"], "c1", "deep_analysis.rule_outs") for i in found["items"]]


# ── the Verifier owns them, and the deep report carries them ───────────────────────────────────────────

def test_the_verifier_attaches_the_rule_outs_to_the_finished_report(playbook, shipped_plays, monkeypatch):
    from aughor.agent import investigate
    from aughor.agent.verifier import Verifier

    _topped_up(playbook, shipped_plays)
    monkeypatch.setattr("aughor.business_profile.metric_kb.industry_scope", lambda conn, schema=None: "retail")
    report = {"metric": "total GMV", "total_change_label": "-€239,911", "comparison_basis": "Prior 2 months"}
    investigate._attach_rule_outs(report, {"connection_id": "c1", "scope_schema": ""})
    assert report["rule_outs"] == Verifier.rule_outs("total GMV", "-€239,911", "Prior 2 months",
                                                     industry="retail", connection_id="c1")

    quiet = {"metric": "total GMV", "total_change_label": "N/A", "comparison_basis": "Prior 2 months"}
    investigate._attach_rule_outs(quiet, {"connection_id": "c1"})
    assert "rule_outs" not in quiet


def test_a_failing_rule_out_leaves_the_report_as_it_was(monkeypatch):
    from aughor.agent import investigate
    from aughor.agent.verifier import Verifier

    def boom(*_a, **_k):
        raise RuntimeError("playbook unreadable")

    monkeypatch.setattr(Verifier, "rule_outs", staticmethod(boom))
    report = {"metric": "total GMV", "total_change_label": "-€239,911", "comparison_basis": "Prior 2 months"}
    investigate._attach_rule_outs(report, {"connection_id": ""})
    assert "rule_outs" not in report


# ── every surface that renders a deep report renders them, with the note ──────────────────────────────
# The lead sentence rides in the payload: the export document is platform code and may not import the
# playbook package (tests/unit/test_platform_agent_boundary.py), and one sentence means one wording.

_FOUND = {"direction": "down", "metric": "total GMV", "matched": ["Gross Merchandise Value (GMV)"],
          "note": rule_outs.NOT_CHECKED,
          "items": [{"cause": "Late orders not yet loaded", "fix": "Exclude the open period",
                     "play_id": "kb_a_1", "version": 1, "receipt": "pbk_a"},
                    {"cause": "Currency converted twice [fx]", "fix": "",
                     "play_id": "kb_b_1", "version": 1, "receipt": "pbk_b"}]}
_FOUND["lead"] = rule_outs.lead(_FOUND)


def test_the_lead_names_the_metric_the_direction_and_that_nothing_was_checked():
    assert rule_outs.lead(_FOUND) == ("Known ways Gross Merchandise Value (GMV) can read lower than it is. "
                                      "Not checked against your data.")
    assert "read higher" in rule_outs.lead({**_FOUND, "direction": "up"})


def test_the_exported_report_carries_them_before_the_recommendations():
    from aughor.export.document import build_export_doc

    inv = {"question": "why did GMV fall", "connection_id": "c", "kind": "investigation",
           "report": {"headline": "GMV fell", "executive_summary": "", "phases": [], "rule_outs": _FOUND,
                      "recommendations": [{"action": "Re-run the close"}]}}
    blocks = build_export_doc(inv).blocks
    headings = [b.text for b in blocks if b.kind == "heading"]
    assert headings.index("Rule out first") < headings.index("Recommendations")
    at = next(i for i, b in enumerate(blocks) if b.kind == "heading" and b.text == "Rule out first")
    assert blocks[at + 1].text == _FOUND["lead"]
    assert blocks[at + 2].items == ["Late orders not yet loaded — fix: Exclude the open period",
                                    "Currency converted twice [fx]"]


def test_the_cli_prints_them_before_the_actions_without_eating_brackets(monkeypatch):
    from rich.console import Console

    from aughor import cli

    recorded = Console(record=True, width=200)
    monkeypatch.setattr(cli, "console", recorded)
    cli._print_ada_report({"headline": "GMV fell", "rule_outs": _FOUND,
                           "recommendations": [{"action": "Re-run the close"}]}, 1.0)
    text = recorded.export_text()
    assert text.index("Rule out first") < text.index("Recommended Actions")
    assert _FOUND["lead"] in text
    assert "Fix: Exclude the open period" in text and "Currency converted twice [fx]" in text
