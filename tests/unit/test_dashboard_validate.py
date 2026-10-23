"""Arc CT, CT-2 (ROADMAP §3.50) — the dashboard's validator: accepted whole or refused whole.

Every refusal below is asserted by a token of ITS OWN sentence. ``accepted is False`` alone
proves nothing: a spec refused for a different reason than the one under test would pass as
proof of a rule that never ran.

The premise spec is the web's own fixture (``web/lib/dashboards/premise.fixture.json``), so the
browser's tests and these are held to the same spec.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from aughor.dashboards import validate as V

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "lib" / "dashboards" / "premise.fixture.json"
CARDS = {"c7f3a001", "c91b2002"}

needs_rules = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the dashboard's rules need node + validate.bundle.mjs")


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
    assert 'places the card "c91b2002", which is not a card of this dashboard' in said(verdict)
    assert "c7f3a001" not in said(verdict)          # the card it does hold is not named


@needs_rules
def test_a_condition_may_not_read_the_status_of_a_card_outside_the_canvas(premise):
    premise["elements"]["card-net"]["visible"] = {"$state": "/cards/feedbeef/status", "eq": "over"}
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert said(verdict) == ('A condition reads the status of the card "feedbeef", '
                             'which is not a card of this dashboard.')


@needs_rules
@pytest.mark.parametrize("title,figure", [
    ("Revenue up 12%", "12%"),
    ("Returns over 1,200 a week", "1,200"),
    ("Net revenue $2.4M", "$2.4M"),
    # A range's unit is its lower end's too, and a percentage may be written as a word. The
    # receipt's third run found "11-12%" read as "12%".
    ("Returns near 11-12%", "11-12%"),
    ("Returns between 11 and 12%", "11 and 12%"),
    ("Orders 1.2-1.5M a year", "1.2-1.5M"),
    ("Returns up 12 percent", "12 percent"),
])
def test_a_title_that_states_a_figure_is_refused(premise, title, figure):
    premise["elements"]["sec-headline"]["props"]["title"] = title
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert f'The title of "sec-headline" reads "{title}", which states a figure ({figure})' in said(verdict)
    assert "a figure belongs to a card" in said(verdict)


@needs_rules
@pytest.mark.parametrize("title", ["Top 6 categories", "Returns in 2026", "Week 3", "Headline", "Weeks 2-3"])
def test_a_rank_a_year_and_a_small_count_are_not_figures(premise, title):
    """The numerals law exempts them at the departure gate; a title is held to the same law."""
    premise["elements"]["sec-headline"]["props"]["title"] = title
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.ACCEPTED, said(verdict)


@needs_rules
@pytest.mark.parametrize("title", ["Revenue up 12%", "Top 1000 accounts", "Store 4521"])
def test_a_persons_own_title_is_their_own_word(premise, title):
    """The law is for text a model wrote. A person's title is said in their name — and a
    canvas called "Store 4521" is a canvas's name, not a claim about the data."""
    premise["elements"]["sec-headline"]["props"]["title"] = title
    assert V.check_spec(premise, known_cards=CARDS, model_written=False).status == V.ACCEPTED
    refused = V.check_spec(premise, known_cards=CARDS, model_written=True)
    assert refused.status == V.REFUSED and "states a figure" in said(refused)
    assert V.check_spec(premise, known_cards=CARDS).status == V.REFUSED      # unsaid is strict


@needs_rules
def test_whoever_wrote_it_a_card_outside_the_canvas_is_refused(premise):
    verdict = V.check_spec(premise, known_cards={"c7f3a001"}, model_written=False)
    assert verdict.status == V.REFUSED and 'places the card "c91b2002"' in said(verdict)


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
    ("watch", {"/tab": {"action": "x"}}, "A dashboard runs nothing without a click"),
    ("on", {"press": {"action": "x"}}, "A dashboard defines no action of its own"),
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
    assert 'A dashboard spec is an object with a "root"' in said(verdict)


def test_a_spec_that_is_not_json_is_refused_before_anything_runs(premise):
    premise["elements"]["card-net"]["props"]["card"] = {"a", "set"}
    verdict = V.check_spec(premise, known_cards=CARDS)
    assert verdict.status == V.REFUSED
    assert said(verdict).startswith("The spec is not JSON")


# ── the vocabulary has one home ───────────────────────────────────────────────

@needs_rules
def test_the_server_reads_the_vocabulary_the_web_declares():
    vocab = V.vocabulary()
    assert vocab["version"] == 10                # 3: the ontology's pieces (Arc OC-4); 4: a dashboard from an object; 5: sizes one grade at a time (Arc AP-1); 6: the wiring (AP-2, AP-3); 7: the structure and the picker's pieces (AP-4); 8: variables (AP-8); 9: sets read whole (AP-8b); 10: yes-no, lists, sums, queries (AP-8c)
    assert vocab["components"] == ["Cockpit", "Tabs", "Tab", "Section", "Card", "Note", "Image",
                                   "ProcessBoard", "ObjectTable", "ObjectDetail", "ActionButton",
                                   "ObjectFilters", "ObjectFigure", "ObjectChart", "ActionButtons",
                                   "ObjectList", "ObjectMap", "ObjectTimeline", "ChooseOne", "ObjectSearch", "Drawer"]
    # the server's own lists of pieces are the web's, read from it — a piece the web adds is checked here or refused
    from aughor.dashboards import app_pieces, pieces
    assert list(pieces.PIECES) == vocab["components"][7:]
    assert list(app_pieces.PIECES) == vocab["components"][-6:]
    assert vocab["sizes"] == ["small", "wide", "tall", "large", "full", "hero"]
    assert vocab["range_statuses"] == ["standing", "final", "provisional", "to_date"]
    assert vocab["card_statuses"] == ["within", "over", "unmeasured", "withheld"]


@needs_rules
def test_the_server_holds_a_section_on_the_grid_to_the_same_rules(premise):
    """Arc AP-1 — sizes one grade at a time: the server keeps a section on the grid only when each element says its w
    and h within what its kind may take — the browser's own rule, run here from the same file."""
    gridded = copy.deepcopy(premise)
    gridded["elements"]["sec-headline"]["props"] = {"title": "Headline", "grid": 12}
    for key, (w, h) in {"alert-rate": (3, 4), "card-rate": (3, 4), "card-net": (6, 6)}.items():
        gridded["elements"][key]["props"].update({"w": w, "h": h})
    verdict = V.check_spec(gridded, known_cards=CARDS)
    assert verdict.status == V.ACCEPTED, said(verdict)

    too_wide = copy.deepcopy(gridded)
    too_wide["elements"]["card-net"]["props"]["h"] = 17          # a card is at most 16 rows
    refused = V.check_spec(too_wide, known_cards=CARDS)
    assert refused.status == V.REFUSED
    assert 'The card "card-net" takes 6 × 17. A Card takes 2 to 12 columns and 2 to 16 rows' in said(refused)

    unsaid = copy.deepcopy(gridded)
    del unsaid["elements"]["card-rate"]["props"]["w"]
    assert 'does not say its w' in said(V.check_spec(unsaid, known_cards=CARDS))


@needs_rules
def test_a_cards_tones_are_the_answer_vocabularys_tones():
    """One scale of tones, not two: a dashboard card and an answer part mean the same by "bad"."""
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
    _never_accepted(V.check_spec(premise, known_cards=CARDS), "npm run build:dashboard-validate")


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
def test_the_card_store_is_asked_for_the_persons_cards_and_the_connections(premise, monkeypatch):
    from aughor.dashboards.home import Home
    from aughor.cards import store
    from aughor.cards.models import StoredCard

    asked = []

    def list_cards(connection_id=None, scope=None, scope_ref=None):
        asked.append((connection_id, scope, scope_ref))
        return [StoredCard(id="c7f3a001", scope=scope, scope_ref=scope_ref)] if scope == "user" else []

    monkeypatch.setattr(store, "list_cards", list_cards)

    home = Home("thelook", "u1", "returns")
    verdict = V.check_spec_for_home(copy.deepcopy(premise), home)
    assert sorted(asked) == [("thelook", "connection", "thelook"), ("thelook", "user", "u1")]
    assert verdict.status == V.REFUSED
    assert 'places the card "c91b2002"' in said(verdict)

    # A card the same proposal is about to create counts as held.
    verdict = V.check_spec_for_home(premise, home, also_known=["c91b2002"])
    assert verdict.status == V.ACCEPTED, said(verdict)
