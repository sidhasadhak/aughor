"""Arc CT, CT-2 (ROADMAP §3.50) — the cockpit's validator: accepted whole or refused whole.

Every refusal below is asserted by a token of ITS OWN sentence. ``accepted is False`` alone
proves nothing: a spec refused for a different reason than the one under test would pass as
proof of a rule that never ran.

The premise spec is the web's own fixture (``web/lib/cockpit/premise.fixture.json``), so the
browser's tests and these are held to the same spec.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from aughor.cockpit import validate as V

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "lib" / "cockpit" / "premise.fixture.json"
CARDS = {"c7f3a001", "c91b2002"}

needs_rules = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the cockpit's rules need node + validate.bundle.mjs")


@pytest.fixture
def premise() -> dict:
    return json.loads(FIXTURE.read_text())


def said(verdict: V.SpecVerdict) -> str:
    return "\n".join(verdict.sentences)


# ── the premise ───────────────────────────────────────────────────────────────

@needs_rules
def test_the_premise_is_accepted_and_names_the_cards_it_places(premise):
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.ACCEPTED, said(verdict)
    assert verdict.accepted is True
    assert verdict.sentences == ()
    assert verdict.cards == ("c7f3a001", "c91b2002")
    assert verdict.as_dict() == {"status": "accepted", "accepted": True, "sentences": [],
                                 "cards": ["c7f3a001", "c91b2002"]}


# ── what only the platform knows ──────────────────────────────────────────────

@needs_rules
def test_a_card_this_canvas_does_not_hold_is_refused_by_name(premise):
    verdict = V.check_spec(premise, known_cards={"c7f3a001"})
    assert verdict.status == V.REFUSED
    assert verdict.cards == ()
    assert 'places the card "c91b2002", which this canvas does not hold' in said(verdict)
    assert "c7f3a001" not in said(verdict)          # the card it does hold is not named


@needs_rules
def test_a_condition_may_not_read_the_status_of_a_card_outside_the_canvas(premise):
    premise["elements"]["card-net"]["visible"] = {"$state": "/cards/feedbeef/status", "eq": "over"}
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert said(verdict) == ('A condition reads the status of the card "feedbeef", '
                             'which this canvas does not hold.')


@needs_rules
@pytest.mark.parametrize("title,figure", [
    ("Revenue up 12%", "12%"),
    ("Returns over 1,200 a week", "1,200"),
    ("Net revenue $2.4M", "$2.4M"),
])
def test_a_title_that_states_a_figure_is_refused(premise, title, figure):
    premise["elements"]["sec-headline"]["props"]["title"] = title
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert f'The title of "sec-headline" reads "{title}", which states a figure ({figure})' in said(verdict)
    assert "a figure belongs to a card" in said(verdict)


@needs_rules
@pytest.mark.parametrize("title", ["Top 6 categories", "Returns in 2026", "Week 3", "Headline"])
def test_a_rank_a_year_and_a_small_count_are_not_figures(premise, title):
    """The numerals law exempts them at the departure gate; a title is held to the same law."""
    premise["elements"]["sec-headline"]["props"]["title"] = title
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.ACCEPTED, said(verdict)


@needs_rules
def test_every_reason_is_said_not_only_the_first(premise):
    premise["elements"]["tab-watches"]["props"]["label"] = "Up 40%"
    verdict = V.check_spec(premise, known_cards=set())
    text = said(verdict)
    assert 'places the card "c7f3a001"' in text
    assert 'places the card "c91b2002"' in text
    assert 'reads the status of the card "c7f3a001"' in text
    assert 'The label of "tab-watches" reads "Up 40%"' in text


# ── what the spec says on its own, through the web's rules ────────────────────

@needs_rules
@pytest.mark.parametrize("field,value,token", [
    ("watch", {"/tab": {"action": "x"}}, "A cockpit runs nothing without a click"),
    ("on", {"press": {"action": "x"}}, "A cockpit defines no action of its own"),
    ("repeat", {"statePath": "/cards"}, "places each card by its id"),
])
def test_what_a_spec_may_not_carry(premise, field, value, token):
    premise["elements"]["card-rate"][field] = value
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert token in said(verdict)
    assert f'"card-rate" carries "{field}"' in said(verdict)


@needs_rules
def test_a_spec_cannot_seed_a_status_the_host_is_to_say(premise):
    premise["state"] = {"tab": "overview", "cards": {"c7f3a001": {"status": "over"}}}
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert "every card's status are the host's to say" in said(verdict)


@needs_rules
def test_a_figure_typed_into_a_card_is_refused(premise):
    premise["elements"]["card-net"]["props"] = {"card": "c91b2002", "value": "8.1M"}
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert '"card-net" has a problem with its props' in said(verdict)


@needs_rules
@pytest.mark.parametrize("spec", [None, 7, "spec", [], {}, {"root": "c"}])
def test_what_is_not_a_spec_is_refused(spec):
    verdict = V.check_spec(spec, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert 'A cockpit spec is an object with a "root"' in said(verdict)


def test_a_spec_that_is_not_json_is_refused_before_anything_runs(premise):
    premise["elements"]["card-net"]["props"]["card"] = {"a", "set"}
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert said(verdict).startswith("The spec is not JSON")


# ── the vocabulary has one home ───────────────────────────────────────────────

@needs_rules
def test_the_server_reads_the_vocabulary_the_web_declares():
    vocab = V.vocabulary()
    assert vocab["version"] == 1
    assert vocab["components"] == ["Cockpit", "Tabs", "Tab", "Section", "Card"]
    assert vocab["range_statuses"] == ["final", "provisional", "to_date"]
    assert vocab["card_statuses"] == ["within", "over", "unmeasured", "withheld"]


@needs_rules
def test_a_cards_tones_are_the_answer_vocabularys_tones():
    """One scale of tones, not two: a cockpit card and an answer part mean the same by "bad"."""
    from aughor.agent.present_tool import TONES
    assert set(V.vocabulary()["tones"]) == set(TONES)


# ── the gate fails closed ─────────────────────────────────────────────────────

def _never_accepted(verdict: V.SpecVerdict, token: str) -> None:
    assert verdict.status == V.NOT_CHECKED
    assert verdict.accepted is False
    assert verdict.cards == ()
    assert token in said(verdict)
    assert "Nothing is accepted unchecked" in said(verdict)


def test_no_node_is_not_checked_never_accepted(premise, monkeypatch):
    monkeypatch.setattr(V, "_node_bin", lambda: None)
    _never_accepted(V.check_spec(premise, known_cards=CARDS), "node was not found")
    assert V.vocabulary() is None


def test_a_node_that_cannot_start_is_not_checked(premise, monkeypatch):
    monkeypatch.setenv("AUGHOR_NODE_BIN", "/nonexistent/node")
    _never_accepted(V.check_spec(premise, known_cards=CARDS), "FileNotFoundError")


def test_a_missing_bundle_is_not_checked_and_says_how_to_build_it(premise, monkeypatch, tmp_path):
    monkeypatch.setattr(V, "_BUNDLE", tmp_path / "validate.bundle.mjs")
    _never_accepted(V.check_spec(premise, known_cards=CARDS), "npm run build:cockpit-validate")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("script,token", [
    ("process.exit(3)", "the rules exited with 3"),
    ("process.stdout.write('not json')", "JSONDecodeError"),
    ("process.stdout.write('[1,2]')", "something that is not an object"),
    ("process.stdout.write('{\"issues\": []}')", "answered without a verdict"),
    ("process.stdout.write('{\"valid\": \"yes\", \"issues\": []}')", "answered without a verdict"),
])
def test_rules_that_misbehave_are_not_checked(premise, monkeypatch, tmp_path, script, token):
    """A broken bundle must never read as a spec that passed — including one that answers
    with something truthy where the verdict belongs."""
    bundle = tmp_path / "validate.bundle.mjs"
    bundle.write_text(script)
    monkeypatch.setattr(V, "_BUNDLE", bundle)
    _never_accepted(V.check_spec(premise, known_cards=CARDS), token)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_rules_that_hang_are_not_checked(premise, monkeypatch, tmp_path):
    bundle = tmp_path / "validate.bundle.mjs"
    bundle.write_text("setTimeout(() => {}, 60000)")
    monkeypatch.setattr(V, "_BUNDLE", bundle)
    monkeypatch.setattr(V, "_TIMEOUT_S", 1)
    _never_accepted(V.check_spec(premise, known_cards=CARDS), "TimeoutExpired")


# ── against the card store ────────────────────────────────────────────────────

@needs_rules
def test_the_canvas_is_asked_for_the_cards_it_holds(premise, monkeypatch):
    from aughor.dashboard import store
    from aughor.dashboard.models import DashboardCard

    asked = []

    def list_cards(connection_id=None, scope=None, scope_ref=None):
        asked.append((scope, scope_ref))
        return [DashboardCard(id="c7f3a001", scope="canvas", scope_ref="cv_returns")]

    monkeypatch.setattr(store, "list_cards", list_cards)

    verdict = V.check_spec_for_canvas(copy.deepcopy(premise), "cv_returns")
    assert asked == [("canvas", "cv_returns")]
    assert verdict.status == V.REFUSED
    assert 'places the card "c91b2002"' in said(verdict)

    # A card the same proposal is about to create counts as held.
    verdict = V.check_spec_for_canvas(premise, "cv_returns", also_known=["c91b2002"])
    assert verdict.status == V.ACCEPTED, said(verdict)
