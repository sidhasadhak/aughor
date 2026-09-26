"""SP-15 (§3.11) — the remedy beside the laws: one module, three readers.

The laws are READ from the gate module's own docstring, never copied — so the first thing
pinned is that the parser finds every guard's bullet (a bullet it cannot find is a silent
gap in every reader at once). Then: every guard has a remedy; a served held row carries
its remedy and a departed row carries none; `platform_help("re-measure")` answers with
law 1's sentence AND its remedy in one call — the wave's baseline could not in eight.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aughor.agent import platform_tools as pt
from aughor.api import app
from aughor.govern import departure_remedies as dr
from aughor.govern.departure import GUARD_LABELS, GUARDS
from aughor.govern.departure_store import record_departure

client = TestClient(app)


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))


# ── the laws are parsed, not retold ───────────────────────────────────────────────────

def test_every_guard_has_a_law_read_from_the_gate_docstring():
    told = dr.laws()
    missing = [g for g in GUARDS if g not in told]
    assert not missing, f"the docstring parser found no law bullet for {missing}"
    assert told["remeasure"]["law"] == "law 1"
    assert "every magnitude the text states must be in the measurement" in told["remeasure"]["sentence"]
    assert told["definition"]["law"] == "law 2"
    assert told["claims"]["law"] == "law 5"
    assert told["trust"]["law"] == ""                  # a guard the docstring numbers no law for
    # A sentence is one line of prose, not the docstring's wrapped lines.
    assert "\n" not in told["remeasure"]["sentence"]


def test_the_parser_reads_the_docstring_and_not_a_copy(monkeypatch):
    """Mutation: change the module's text and the law changes with it — proof the words
    are read from the one source rather than kept beside it."""
    from aughor.govern import departure as gate
    doc = gate.__doc__.replace("every magnitude the text states", "EVERY NUMBER THE TEXT STATES")
    monkeypatch.setattr(gate, "__doc__", doc)
    assert "EVERY NUMBER THE TEXT STATES" in dr.laws()["remeasure"]["sentence"]


def test_every_guard_has_a_remedy_with_meaning_action_and_doors():
    for g in GUARDS:
        told = dr.explain_guard(g)
        assert told is not None, f"no remedy for {g}"
        assert told["label"] == GUARD_LABELS[g]
        assert told["meaning"] and told["action"], g
        assert isinstance(told["doors"], list)
        assert set(told["doors"]) <= {"automation", "analysis", "semantic", "ask"}


def test_an_unknown_guard_gets_no_invented_remedy():
    assert dr.explain_guard("held_lines") is None
    assert dr.remedy_for_row({"guards": {"held_lines": "held"}, "checks": {}}) is None


# ── the served row carries it ─────────────────────────────────────────────────────────

def _held_row(**over):
    fields = dict(
        id="dep-held-1", org_id="default", kind="briefing", state="held", conn_id="c1",
        automation_id="auto-1", automation_name="The Look - Daily Briefing",
        actor="automation:auto-1", target="sb_1:#aughor_canvas",
        reasons=json.dumps(["re-measure: 1,648.08 not in analysis ecb56660"]),
        checks=json.dumps({"trust": "clean", "remeasure": "1,648.08 not in analysis ecb56660",
                           "definition": "cites metric revenue v1"}),
        guards=json.dumps({"trust": "passed", "remeasure": "held", "definition": "passed"}),
        text_preview="Revenue was 1,648.08 yesterday.", investigation_id="ecb56660",
    )
    fields.update(over)
    return record_departure(**fields)


def test_a_held_row_is_served_with_its_remedy_and_a_departed_row_without():
    held = _held_row()
    departed = _held_row(id="dep-ok-1", state="departed", reasons="[]",
                         guards=json.dumps({"trust": "passed", "remeasure": "passed"}))

    row = client.get(f"/departures/{held}").json()
    assert row["remedy"]["lead"] == dr.HOLD_LEAD
    assert [g["guard"] for g in row["remedy"]["guards"]] == ["remeasure"]
    told = row["remedy"]["guards"][0]
    assert told["outcome"] == "held"
    assert told["reason"] == "1,648.08 not in analysis ecb56660"     # THIS hold's sentence
    assert told["law"] == "law 1"
    assert told["doors"] == ["automation", "analysis", "ask"]

    ok = client.get(f"/departures/{departed}").json()
    assert "remedy" not in ok                                       # nothing to fix — absent, not empty

    listed = {d["id"]: d for d in client.get("/departures").json()["departures"]}
    assert "remedy" in listed[held] and "remedy" not in listed[departed]


def test_an_asked_guard_carries_a_remedy_too():
    row_id = _held_row(id="dep-owner", state="held_owner",
                       guards=json.dumps({"disagreement": "asked"}),
                       checks=json.dumps({"disagreement": "two readings of return_rate disagree"}))
    row = client.get(f"/departures/{row_id}").json()
    assert [g["guard"] for g in row["remedy"]["guards"]] == ["disagreement"]
    assert row["remedy"]["guards"][0]["outcome"] == "asked"


# ── platform_help knows the laws ──────────────────────────────────────────────────────

@pytest.mark.parametrize("asked", ["re-measure", "remeasure", "Re-measured", "measured"])
def test_help_answers_re_measure_with_law_one_and_its_remedy(asked):
    out = pt.platform_help("c1", {"topic": asked})
    assert out["topic"] == "remeasure"
    assert "note" not in out                                        # a known topic, not the overview
    assert "(law 1)" in out["help"]
    assert "every magnitude the text states must be in the measurement" in out["help"]
    assert "What to do:" in out["help"]
    assert "ask for it in the automation's question" in out["help"]


@pytest.mark.parametrize("asked,topic", [
    ("held", "departures"), ("departure gate", "departures"), ("hold", "departures"),
    ("claim type", "claims"), ("tie-out", "tie_out"), ("tie out", "tie_out"),
    ("probation", "probation"), ("definition", "definition"),
])
def test_help_aliases_reach_the_gate_and_its_guards(asked, topic):
    assert pt.platform_help("c1", {"topic": asked})["topic"] == topic


def test_the_departures_topic_names_every_guard_and_the_lead():
    out = pt.platform_help("c1", {"topic": "departures"})
    for g in GUARDS:
        assert GUARD_LABELS[g] in out["help"], g
    assert dr.HOLD_LEAD in out["help"]
    assert set(GUARDS) <= set(out["topics"])
