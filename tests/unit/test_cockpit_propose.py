"""Arc CT, CT-5 (ROADMAP §3.50) — a cockpit asked for in a Data Canvas's chat, as ONE proposal.

Run against the REAL stores — the inbox, the card store, the Ledger and the canvas store,
each pointed at a temporary file by ``tests/conftest.py``; the metric store and the
trusted-query store, each test's own — and against the real rules, so these need node and
the bundle.

Two things are stood in for. The warehouse: ``doors.run_guarded`` is replaced by one that
answers from the query's own text, and counts its calls. And a canvas's findings, which the
explorer writes.

**No model is called.** What a model would write is written here by hand, as the argument
of the tool.

Every refusal is asserted by a token of its own sentence, and every "nothing was made" by
counting what the stores hold.
"""
from __future__ import annotations

import json
import shutil
import uuid
from types import SimpleNamespace

import pytest

from aughor.actions import inbox
from aughor.agent.cockpit_tool import cockpit_tools, draft_cockpit
from aughor.canvas.models import CanvasScope
from aughor.canvas.store import create_canvas
from aughor.cockpit import cards, propose, validate as V, versions
from aughor.dashboard import doors
from aughor.dashboard.models import DashboardCard
from aughor.kernel.flags import flag_overrides
from aughor.semantic.metrics import MetricDefinition, save_metric
from aughor.semantic.trusted_queries import TrustedQuery, save_trusted

needs_rules = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the cockpit's rules need node + validate.bundle.mjs")

pytestmark = needs_rules

CONN = "thelook"


@pytest.fixture
def on():
    with flag_overrides({"cockpit.composed": True}):
        yield


class Warehouse:
    """Stands in for the guard. A query holding ``GROUP BY`` answers with a table, one holding
    ``BROKEN`` is refused, and any other answers with one number."""

    def __init__(self):
        self.ran: list[tuple[str, str]] = []

    def __call__(self, connection_id, sql, *, query_id, schema=None):
        self.ran.append((query_id, sql))
        if "BROKEN" in sql:
            raise doors.GuardRefused("Query failed the trust guards, not pinned: no such column")
        if "GROUP BY" in sql:
            return SimpleNamespace(error=None, row_count=2, columns=["category", "n"],
                                   rows=[["Jeans", "4"], ["Tops", "9"]])
        return SimpleNamespace(error=None, row_count=1, columns=["_v"], rows=[["10.03"]])


#: Each canvas's findings, by canvas. One stand-in reads it for every desk a test makes: the
#: first cut gave each desk a stand-in of its own, and a second desk silently emptied the first.
FINDINGS: dict[str, list[dict]] = {}


@pytest.fixture
def warehouse(monkeypatch, tmp_path) -> Warehouse:
    # The metric and trusted-query stores are files the whole suite shares, and other tests
    # read them whole. The first cut saved into them: `test_metric_dedup` then read 168
    # metrics it had not expected, on the full run and on no targeted one. Each test here has
    # its own, as every other test that saves a metric does.
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    monkeypatch.setenv("AUGHOR_TRUSTED_QUERIES_PATH", str(tmp_path / "trusted_queries.json"))
    w = Warehouse()
    monkeypatch.setattr(doors, "run_guarded", w)
    FINDINGS.clear()
    monkeypatch.setattr("aughor.explorer.store.canvas_findings",
                        lambda canvas_id, include_invalid=False: list(FINDINGS.get(canvas_id, [])))
    return w


class Desk:
    """One canvas on theLook holding one card, with a metric, a draft metric, two trusted
    queries and two findings to make cards from. Every name is this test's own."""

    def __init__(self, monkeypatch=None, connection: str = CONN):
        tag = uuid.uuid4().hex[:6]
        self.tag = tag
        self.connection = connection
        self.canvas = create_canvas("Returns", [CanvasScope(connection_id=connection)])
        self.id = self.canvas.id
        self.held = f"net{tag}"
        cards.place(self.id, DashboardCard(id=self.held, kind="kpi", title="Net merchandise revenue",
                                           sql="SELECT 1"))

        self.metric = f"return_rate_{tag}"
        self.draft_metric = f"margin_{tag}"
        save_metric(MetricDefinition(
            name=self.metric, connection=connection, label="Return rate", unit="%",
            sql="SELECT 100.0 * COUNT(returned_at) / COUNT(*) FROM order_items",
            tables=["order_items"], status="approved", version=3))
        save_metric(MetricDefinition(
            name=self.draft_metric, connection=connection, label="Margin", sql="SELECT 1",
            tables=["order_items"], status="draft"))

        self.trusted = f"tq-{tag}"
        self.chain_owned = f"tq-chain-{tag}"
        save_trusted(TrustedQuery(
            id=self.trusted, connection_id=connection, question="Items returned by category",
            sql="SELECT category, COUNT(*) AS n FROM order_items GROUP BY category",
            tables=["order_items"], status="approved", version=2))
        save_trusted(TrustedQuery(
            id=self.chain_owned, connection_id=connection, question="A chain's own", sql="SELECT 1",
            status="approved", version=1, owner_automation="auto-1"))

        self.elsewhere = f"tq-elsewhere-{tag}"
        save_trusted(TrustedQuery(
            id=self.elsewhere, connection_id="another-connection", question="Another connection's",
            sql="SELECT 1", status="approved", version=1))

        self.finding = f"f-{tag}"
        self.bare_finding = f"f-bare-{tag}"
        self.findings = FINDINGS.setdefault(self.id, [
            {"id": self.finding, "finding": "Returns cluster in the first week after delivery",
             "sql": "SELECT week, COUNT(*) FROM order_items GROUP BY week"},
            {"id": self.bare_finding, "finding": "A fact from the profile", "sql": ""},
        ])

    # ── what a model would write ─────────────────────────────────────────────
    def cards(self) -> list[dict]:
        return [
            {"key": "return-rate", "metric": self.metric, "limit": {"critical": 12, "direction": "above"}},
            {"key": "by-category", "trusted_query": self.trusted, "title": "Returned, by category"},
            {"key": "first-week", "finding": self.finding},
        ]

    def spec(self) -> dict:
        return {
            "root": "cockpit", "state": {"tab": "overview"},
            "elements": {
                "cockpit": {"type": "Cockpit", "props": {"title": "Returns"}, "children": ["tabs"]},
                "tabs": {"type": "Tabs", "props": {"value": {"$bindState": "/tab"}},
                         "children": ["tab-overview", "tab-detail"]},
                "tab-overview": {"type": "Tab", "props": {"name": "overview", "label": "Overview"},
                                 "children": ["sec-alerts", "sec-headline"]},
                "sec-alerts": {"type": "Section", "props": {"title": "Needs a look"}, "children": ["alert"],
                               "visible": {"$state": "/cards/return-rate/status", "eq": "over"}},
                "alert": {"type": "Card", "props": {"card": "return-rate", "tone": "bad"}, "children": []},
                "sec-headline": {"type": "Section", "props": {"title": "Headline", "columns": 2},
                                 "children": ["c-rate", "c-net"]},
                "c-rate": {"type": "Card", "props": {"card": "return-rate"}, "children": []},
                "c-net": {"type": "Card", "props": {"card": self.held}, "children": [],
                          "visible": {"$state": "/range/status", "neq": "to_date"}},
                "tab-detail": {"type": "Tab", "props": {"name": "detail", "label": "Detail"},
                               "children": ["sec-detail"]},
                "sec-detail": {"type": "Section", "props": {"title": "Where and when"},
                               "children": ["c-cat", "c-week"]},
                "c-cat": {"type": "Card", "props": {"card": "by-category"}, "children": []},
                "c-week": {"type": "Card", "props": {"card": "first-week"}, "children": []},
            },
        }

    # ── what the stores hold ────────────────────────────────────────────────
    def held_cards(self) -> list[str]:
        return sorted(c.id for c in cards.cards_of(self.id))

    def pending(self) -> list:
        return [p for p in inbox.list_proposals(connection_id=self.connection, status="pending")
                if p.kind == propose.KIND and p.params.get("canvas_id") == self.id]

    def draft(self, **kw) -> propose.Drafted:
        kw.setdefault("mode", "new")
        if kw["mode"] == "new":
            kw.setdefault("spec", self.spec())
            kw.setdefault("cards", self.cards())
        return propose.draft(self.connection, self.id, **kw)


@pytest.fixture
def desk(monkeypatch, warehouse) -> Desk:
    return Desk(monkeypatch)


def said(drafted: propose.Drafted) -> str:
    return "\n".join(drafted.refusals)


def staged(desk: "Desk", **kw):
    """The proposal a draft staged. A draft that was refused fails HERE, by assertion and with
    its reasons — the first cut read `.proposal.params` and a refused draft failed the test
    with an AttributeError, which is a test that broke, not one that noticed."""
    out = desk.draft(**kw)
    assert out.staged is True, said(out)
    return out.proposal


def refused(desk: Desk, **kw) -> str:
    before = (desk.held_cards(), len(desk.pending()), versions.history(desk.id))
    out = desk.draft(**kw)
    assert out.staged is False and out.proposal is None
    assert (desk.held_cards(), len(desk.pending()), versions.history(desk.id)) == before
    return said(out)


# ── when the tool is offered ─────────────────────────────────────────────────

def _names(tools) -> list[str]:
    return [t.name for t in tools]


def test_off_the_tool_list_is_exactly_what_it_was(desk):
    """Flags are off by default and byte-identical when off."""
    from aughor.agent.converse_tools import converse_tools
    emit = lambda kind, payload: None   # noqa: E731
    with_canvas = converse_tools(CONN, emit=emit, canvas_id=desk.id)
    without = converse_tools(CONN, emit=emit)
    assert [t.as_wire() for t in with_canvas] == [t.as_wire() for t in without]
    assert "draft_cockpit" not in _names(with_canvas)
    assert cockpit_tools(CONN, emit=emit, canvas_id=desk.id) == []


def test_on_it_is_offered_in_a_canvas_on_a_turn_with_a_channel_and_nowhere_else(desk, on):
    from aughor.agent.converse_tools import converse_tools
    emit = lambda kind, payload: None   # noqa: E731
    assert _names(cockpit_tools(CONN, emit=emit, canvas_id=desk.id)) == ["draft_cockpit"]
    assert cockpit_tools(CONN, emit=emit, canvas_id=None) == []
    assert cockpit_tools(CONN, emit=emit, canvas_id="") == []
    assert cockpit_tools(CONN, emit=None, canvas_id=desk.id) == []

    offered = converse_tools(CONN, emit=emit, canvas_id=desk.id)
    assert _names(offered)[-1] == "draft_cockpit"
    assert _names(offered)[:-1] == _names(converse_tools(CONN, emit=emit))


def test_the_model_cannot_name_a_canvas_or_a_connection_or_a_query(desk, on):
    tool = cockpit_tools(CONN, emit=lambda k, p: None, canvas_id=desk.id)[0]
    assert len(tool.description) > 60
    text = json.dumps(tool.parameters)
    for never in ('"canvas_id"', '"canvas"', '"connection_id"', '"connection"', '"sql"'):
        assert never not in text
    assert set(tool.parameters["properties"]) == {"op", "cards", "spec", "patches", "reasoning"}


# ── options ──────────────────────────────────────────────────────────────────

def test_options_say_what_a_cockpit_here_may_be_made_of_and_cost_nothing(desk, warehouse):
    out = draft_cockpit(CONN, desk.id, {"op": "options"})

    assert out["available"] is True
    assert out["canvas"] == {"name": "Returns"}
    assert out["cockpit"] is None
    assert out["cards_in_canvas"] == [
        {"id": desk.held, "title": "Net merchandise revenue", "kind": "kpi", "has_limit": False}]
    offered = {m["metric"] for m in out["metrics"]}
    assert desk.metric in offered and desk.draft_metric not in offered
    assert {"metric": desk.metric, "label": "Return rate", "unit": "%"} in out["metrics"]
    queries = {t["trusted_query"] for t in out["trusted_queries"]}
    assert desk.trusted in queries and desk.chain_owned not in queries
    assert out["findings"] == [
        {"finding": desk.finding, "says": "Returns cluster in the first week after delivery"}]
    assert out["how_to_write_one"] == V.grammar()
    assert "- Section: " in out["how_to_write_one"]

    assert warehouse.ran == []
    assert desk.pending() == []
    # It carries no query: a writer chooses by name and never sees one to copy.
    assert "SELECT" not in json.dumps(out)


def test_options_show_the_cockpit_as_it_stands(desk):
    inbox.accept_proposal(staged(desk).id, actor="user1")
    out = propose.options(CONN, desk.id)
    assert out["cockpit"]["version"] == 1
    assert out["cockpit"]["spec"] == versions.latest(desk.id)["spec"]
    assert len(out["cards_in_canvas"]) == 4
    assert {c["title"]: c["has_limit"] for c in out["cards_in_canvas"]}["Return rate"] is True


def test_options_on_a_canvas_of_another_connection(desk):
    out = propose.options("another-connection", desk.id)
    assert out["available"] is False
    assert "not in a Data Canvas of this connection" in out["summary"]


def test_options_offer_only_what_reads_the_canvas_own_tables(monkeypatch, warehouse):
    desk = Desk(monkeypatch)
    narrow = create_canvas("Orders only", [CanvasScope(connection_id=CONN, tables=["thelook.orders"])])
    out = propose.options(CONN, narrow.id)
    assert desk.metric not in {m["metric"] for m in out["metrics"]}
    assert desk.trusted not in {t["trusted_query"] for t in out["trusted_queries"]}


# ── a new cockpit ────────────────────────────────────────────────────────────

def test_a_draft_is_one_proposal_and_changes_nothing(desk, warehouse):
    frames: list[tuple[str, dict]] = []
    out = draft_cockpit(CONN, desk.id, {"op": "new", "spec": desk.spec(), "cards": desk.cards(),
                                        "reasoning": "Alerts first, detail behind a tab."},
                        emit=lambda kind, payload: frames.append((kind, payload)))

    assert out["staged"] is True
    [p] = desk.pending()
    assert out["proposal_id"] == p.id and out["expires_at"] == p.expires_at
    assert p.kind == "cockpit_draft" and p.connection_id == CONN
    assert p.action_id == "cockpit:Returns"            # the canvas's name: it is what an inbox row reads
    assert p.reasoning == "Alerts first, detail behind a tab."
    assert frames == [("proposal_staged", {"proposal_id": p.id, "kind": "cockpit_draft",
                                           "connection_id": CONN, "action_id": p.action_id})]
    assert out["summary"] == (
        f'Drafted the cockpit "Returns": 2 tabs, 3 sections, 4 cards (3 new) (proposal {p.id}). '
        "Nothing is changed yet. A person approves it on the card, all of it or none of it, and it then "
        "appears in this canvas's Cockpit tab.")

    # Nothing is made until a person approves.
    assert desk.held_cards() == [desk.held]
    assert versions.latest(desk.id) is None


def test_a_card_is_read_from_its_record_and_run_before_it_is_offered(desk, warehouse):
    p = staged(desk)
    rate, cat, week = p.params["cards"]

    assert rate["from"] == "metric" and rate["name"] == desk.metric and rate["version"] == 3
    assert rate["sql"] == "SELECT 100.0 * COUNT(returned_at) / COUNT(*) FROM order_items"
    assert rate["kind"] == "kpi" and rate["title"] == "Return rate"
    assert rate["limit"] == {"critical": 12.0, "direction": "above"}

    assert cat["from"] == "trusted_query" and cat["name"] == desk.trusted and cat["version"] == 2
    assert cat["kind"] == "chart" and cat["title"] == "Returned, by category" and cat["limit"] == {}

    assert week["from"] == "finding" and week["name"] == desk.finding
    assert week["kind"] == "chart" and week["title"] == "Returns cluster in the first week after delivery"

    assert [q for q, _ in warehouse.ran] == [
        "cockpit-draft:return-rate", "cockpit-draft:by-category", "cockpit-draft:first-week"]
    assert [sql for _, sql in warehouse.ran] == [rate["sql"], cat["sql"], week["sql"]]


def test_the_spec_places_each_new_card_by_the_id_it_will_be_made_with(desk):
    p = staged(desk)
    ids = {c["key"]: c["id"] for c in p.params["cards"]}
    assert len(set(ids.values())) == 3 and all(len(i) == 8 for i in ids.values())
    els = p.params["spec"]["elements"]

    assert els["alert"]["props"] == {"card": ids["return-rate"], "tone": "bad"}
    assert els["c-rate"]["props"]["card"] == ids["return-rate"]
    assert els["c-cat"]["props"]["card"] == ids["by-category"]
    assert els["c-week"]["props"]["card"] == ids["first-week"]
    assert els["c-net"]["props"]["card"] == desk.held
    # …and where a condition reads its status.
    assert els["sec-alerts"]["visible"] == {"$state": f"/cards/{ids['return-rate']}/status", "eq": "over"}
    assert els["c-net"]["visible"] == {"$state": "/range/status", "neq": "to_date"}
    # The names the writer gave are gone from the spec that is kept.
    assert "return-rate" not in json.dumps(p.params["spec"])
    assert p.params["base_version"] is None and p.params["mode"] == "new" and p.params["patches"] == []


def test_the_card_says_what_is_arranged_in_words(desk):
    d = staged(desk).detail
    assert d["canvas_name"] == "Returns" and d["title"] == "Returns"
    assert d["mode"] == "new" and d["replaces_version"] is None
    # A new cockpit is all of it new, so no line is marked as added: `change` is "" throughout.
    assert d["outline"] == [
        {"tab": "Overview", "change": "", "sections": [
            {"title": "Needs a look", "change": "", "shown": '"Return rate" is over its limit', "cards": [
                {"title": "Return rate", "new": True, "change": "", "tone": "bad", "shown": ""}]},
            {"title": "Headline", "change": "", "shown": "", "cards": [
                {"title": "Return rate", "new": True, "change": "", "tone": "", "shown": ""},
                {"title": "Net merchandise revenue", "new": False, "change": "", "tone": "",
                 "shown": "the range is not to date"}]},
        ]},
        {"tab": "Detail", "change": "", "sections": [
            {"title": "Where and when", "change": "", "shown": "", "cards": [
                {"title": "Returned, by category", "new": True, "change": "", "tone": "", "shown": ""},
                {"title": "Returns cluster in the first week after delivery", "new": True, "change": "",
                 "tone": "", "shown": ""}]},
        ]},
    ]
    assert d["counts"] == {"tabs": 2, "sections": 3, "cards": 4, "new": 3}
    assert d["changes"]["added"] == sorted(desk.spec()["elements"]) and d["changes"]["removed"] == []


def test_a_condition_is_said_as_it_is_written():
    titles = {"a1": "Return rate"}
    say = lambda cond: propose._said(cond, titles)   # noqa: E731
    assert say({"$state": "/cards/a1/status", "neq": "within"}) == '"Return rate" is not within its limit'
    assert say({"$state": "/cards/a1/status", "eq": "over", "not": True}) == '"Return rate" is not over its limit'
    assert say({"$state": "/cards/a1/status", "neq": "over", "not": True}) == '"Return rate" is over its limit'
    assert say({"$state": "/range/status", "eq": "standing"}) == "the range is standing, with none chosen"
    assert say([{"$state": "/range/status", "eq": "final"}, {"$state": "/cards/zz/status", "eq": "withheld"}]) \
        == 'the range is final and "zz" is withheld'
    assert say({"$or": [{"$state": "/range/status", "eq": "final"}, {"$state": "/range/status", "eq": "provisional"}]}) \
        == "(the range is final or the range is provisional)"


def test_sections_with_no_tabs(desk):
    spec = {"root": "c", "elements": {
        "c": {"type": "Cockpit", "props": {"title": "Returns"}, "children": ["s"]},
        "s": {"type": "Section", "props": {"title": "Headline"}, "children": ["k"]},
        "k": {"type": "Card", "props": {"card": desk.held}, "children": []}}}
    p = staged(desk, spec=spec, cards=[])
    assert p.detail["outline"] == [{"tab": "", "change": "", "sections": [
        {"title": "Headline", "change": "", "shown": "", "cards": [
            {"title": "Net merchandise revenue", "new": False, "change": "", "tone": "", "shown": ""}]}]}]
    assert p.params["cards"] == []
    out = draft_cockpit(CONN, desk.id, {"op": "new", "spec": {**spec, "elements": {
        **spec["elements"], "s": {**spec["elements"]["s"], "props": {"title": "At a glance"}}}}})
    assert 'Drafted the cockpit "Returns": 1 section, 1 card (proposal' in out["summary"]


# ── what a draft is refused for ──────────────────────────────────────────────

def _one(desk: Desk, card: dict, place: bool = True) -> dict:
    """A draft of one new card, placed in a cockpit of one section."""
    key = card.get("key") if isinstance(card, dict) else None
    spec = {"root": "c", "elements": {
        "c": {"type": "Cockpit", "props": {"title": "Returns"}, "children": ["s"]},
        "s": {"type": "Section", "props": {"title": "Headline"}, "children": ["k"]},
        "k": {"type": "Card", "props": {"card": key if place and isinstance(key, str) and key else desk.held},
              "children": []}}}
    return {"spec": spec, "cards": [card]}


@pytest.mark.parametrize("card,sentence", [
    (lambda d: {"key": "k1", "metric": "no_such_metric"}, 'There is no metric named "no_such_metric" on this connection.'),
    (lambda d: {"key": "k1", "metric": d.draft_metric}, "is draft. A card is made from an approved metric."),
    (lambda d: {"key": "k1", "trusted_query": "tq-nowhere"}, 'There is no trusted query "tq-nowhere" on this connection.'),
    (lambda d: {"key": "k1", "trusted_query": d.chain_owned}, "belongs to an automation and is not in the catalogue"),
    # It exists and is approved, on a connection that is not this canvas's.
    (lambda d: {"key": "k1", "trusted_query": d.elsewhere}, 'There is no trusted query "tq-elsewhere-'),
    (lambda d: {"key": "k1", "finding": "f-nowhere"}, 'This canvas has no finding "f-nowhere".'),
    (lambda d: {"key": "k1", "finding": d.bare_finding}, "has no query behind it, so no card can be made from it"),
    (lambda d: {"key": "k1", "metric": d.metric, "sql": "SELECT 1"},
     'The card "k1" carries sql. A card names what it is made from; its query is read from that record, never written here.'),
    (lambda d: {"key": "k1", "metric": d.metric, "finding": d.finding},
     'The card "k1" names metric, finding to be made from. It is made from exactly one of: metric, trusted_query, finding.'),
    (lambda d: {"key": "k1"}, 'The card "k1" names nothing to be made from.'),
    (lambda d: {"key": "9lives", "metric": d.metric}, 'Card 1 of the draft is named "9lives". A name begins with a letter'),
    (lambda d: {"metric": d.metric}, 'Card 1 of the draft is named "". A name begins with a letter'),
    (lambda d: {"key": d.held, "metric": d.metric}, "is already the id of a card in this canvas"),
    (lambda d: {"key": "k1", "metric": d.metric, "title": "Return rate above 12%"},
     'The title of the card "k1" reads "Return rate above 12%", which states a figure (12%).'),
    (lambda d: {"key": "k1", "trusted_query": d.trusted, "limit": {"critical": 5}},
     'The card "k1" draws a chart, and a limit is set on a single figure.'),
    (lambda d: {"key": "k1", "metric": d.metric, "limit": {"critical": "12"}},
     "The critical limit of the card \"k1\" is '12'. A limit is a number."),
    (lambda d: {"key": "k1", "metric": d.metric, "limit": {"critical": True}}, "A limit is a number."),
    (lambda d: {"key": "k1", "metric": d.metric, "limit": {"direction": "above"}},
     'The limit of the card "k1" names no "warning" and no "critical".'),
    (lambda d: {"key": "k1", "metric": d.metric, "limit": {"critical": 12, "direction": "sideways"}},
     'is crossed going "sideways". It is crossed going: above, below.'),
    (lambda d: {"key": "k1", "metric": d.metric, "limit": {"critical": 12, "monitor_id": "m1"}},
     'The limit of the card "k1" carries monitor_id.'),
    (lambda d: {"key": "k1", "metric": d.metric, "limit": [12]}, 'The limit of the card "k1" is not an object'),
    (lambda d: "return rate", "Card 1 of the draft is not an object."),
])
def test_a_card_that_may_not_be_made(desk, card, sentence):
    assert sentence in refused(desk, **_one(desk, card(desk)))


def test_a_card_that_cannot_be_run_is_refused_to_the_writer_not_shown_to_a_person(desk, monkeypatch):
    broken = f"broken_{desk.tag}"
    save_metric(MetricDefinition(name=broken, connection=CONN, label="Broken", sql="SELECT BROKEN FROM x",
                                 status="approved", version=1))
    text = refused(desk, **_one(desk, {"key": "k1", "metric": broken}))
    assert (f'The card "k1", made from the metric "{broken}", could not be run: '
            "Query failed the trust guards, not pinned: no such column") in text


def test_a_card_made_and_placed_nowhere(desk):
    text = refused(desk, **_one(desk, {"key": "k1", "metric": desk.metric}, place=False))
    assert text == 'The card "k1" is created and placed nowhere. Place it in a section, or leave it out.'


def test_two_cards_of_one_name(desk):
    spec = _one(desk, {"key": "k1", "metric": desk.metric})["spec"]
    text = refused(desk, spec=spec, cards=[{"key": "k1", "metric": desk.metric},
                                           {"key": "k1", "trusted_query": desk.trusted}])
    assert 'Two cards of the draft are named "k1".' in text


def test_more_cards_than_a_draft_may_make(desk, warehouse):
    many = [{"key": f"k{i}", "metric": desk.metric} for i in range(propose.MAX_NEW_CARDS + 1)]
    text = refused(desk, spec=desk.spec(), cards=many)
    assert f"The draft creates {propose.MAX_NEW_CARDS + 1} cards. A draft creates at most {propose.MAX_NEW_CARDS}" in text
    assert warehouse.ran == []


def test_a_spec_the_rules_refuse_is_refused_in_the_rules_own_words(desk):
    spec = desk.spec()
    spec["elements"]["c-net"]["on"] = {"press": {"action": "anything"}}
    assert 'The element "c-net" carries "on". A cockpit defines no action of its own' in refused(desk, spec=spec)


def test_a_card_the_canvas_does_not_hold(desk):
    spec = desk.spec()
    spec["elements"]["c-net"]["props"] = {"card": "ghost"}
    del spec["elements"]["c-net"]["visible"]
    assert refused(desk, spec=spec) == 'The cockpit places the card "ghost", which this canvas does not hold.'


def test_a_title_that_states_a_figure(desk):
    spec = desk.spec()
    spec["elements"]["sec-headline"]["props"]["title"] = "Returns up 14%"
    assert 'reads "Returns up 14%", which states a figure (14%)' in refused(desk, spec=spec)


def test_the_reasoning_is_a_models_text_and_states_no_figure(desk):
    """It is shown to the person approving, and kept as the version's note in the history."""
    text = refused(desk, reasoning="The return rate is 10.03%, so its alert comes first.")
    assert text == ("The reasoning states a figure (10.03%). Say why the cockpit is arranged this way; "
                    "a figure is a card's to show, where it is measured.")
    # A year, a rank and a small count are not claims about the data, here as at the departure gate.
    assert staged(desk, reasoning="Three tabs, as asked in 2026: alerts first.").reasoning \
        == "Three tabs, as asked in 2026: alerts first."


def test_a_refusal_names_everything_in_one_round(desk, warehouse):
    """The writer is a model, and each round it spends learning of one fault is a model call."""
    spec = desk.spec()
    spec["elements"]["alert"]["props"]["tone"] = "loud"                                  # a prop
    spec["elements"]["tab-detail"]["children"] = ["sec-detail", "c-net"]                 # the shape
    spec["elements"]["sec-headline"]["children"] = ["c-rate"]
    draft_cards = desk.cards()
    draft_cards[1] = {"key": "by-category", "trusted_query": "tq-nowhere"}                # a card
    draft_cards[2] = {"key": "first-week", "finding": desk.finding, "sql": "SELECT 1"}   # another

    text = refused(desk, spec=spec, cards=draft_cards)

    assert 'There is no trusted query "tq-nowhere" on this connection.' in text
    assert 'The card "first-week" carries sql.' in text
    assert '"alert" has a problem with "tone"' in text
    assert 'tab "tab-detail" holds "c-net". A Tab holds: Section' in text
    # A card that was refused is not ALSO called a card the canvas does not hold.
    assert "does not hold" not in text
    # The card that could be made was still run, so a fault in it would have been told too.
    assert [q for q, _ in warehouse.ran] == ["cockpit-draft:return-rate"]


def test_a_card_that_was_refused_is_not_also_called_a_card_the_canvas_does_not_hold(desk):
    """The spec is sound and places three new cards; one of them may not be made. The rules
    accept the spec, so what the platform knows is asked of it — and the refused card's name
    is still in it."""
    draft_cards = desk.cards()
    draft_cards[1] = {"key": "by-category", "trusted_query": "tq-nowhere"}
    text = refused(desk, spec=desk.spec(), cards=draft_cards)
    assert text == 'There is no trusted query "tq-nowhere" on this connection.'


def test_what_only_the_platform_knows_is_told_in_the_same_refusal_as_the_rules(desk):
    """ROADMAP §3.50's own example, from CT-3: "a spec with a refused field, a figure in a
    title and a card it does not hold is told of the field alone"."""
    spec = desk.spec()
    spec["elements"]["c-rate"]["on"] = {"press": {"action": "anything"}}                 # the rules'
    spec["elements"]["sec-headline"]["props"]["title"] = "Returns up 14%"                # the platform's
    spec["elements"]["c-net"]["props"] = {"card": "ghost"}                                # the platform's
    spec["elements"]["sec-detail"]["visible"] = {"$state": "/cards/phantom/status", "eq": "over"}
    text = refused(desk, spec=spec)
    assert 'The element "c-rate" carries "on".' in text
    assert 'reads "Returns up 14%", which states a figure (14%)' in text
    assert 'The cockpit places the card "ghost", which this canvas does not hold.' in text
    assert 'A condition reads the status of the card "phantom", which this canvas does not hold.' in text
    # …and the cards the draft does make are not among the ones it is said not to hold.
    assert text.count("does not hold") == 2


def test_a_prop_the_rules_refused_is_not_told_again_by_the_platform(desk):
    spec = desk.spec()
    spec["elements"]["c-net"]["props"] = {"card": "not an id!"}
    text = refused(desk, spec=spec)
    assert '"c-net" has a problem with "card"' in text
    assert "does not hold" not in text


def test_a_refusal_speaks_in_the_names_the_writer_gave(desk):
    spec = desk.spec()
    spec["elements"]["sec-alerts"]["visible"] = {"$state": "/cards/return-rate/status", "eq": "breached"}
    text = refused(desk, spec=spec)
    assert 'compares "/cards/return-rate/status" with "breached"' in text


@pytest.mark.parametrize("kw,sentence", [
    ({"mode": "new", "spec": None, "cards": []}, 'A new cockpit carries its whole "spec".'),
    ({"mode": "new", "spec": "a cockpit about returns", "cards": []}, 'A new cockpit carries its whole "spec".'),
    ({"mode": "new", "patches": [{"op": "remove", "path": "/root"}]}, 'A new cockpit carries its whole "spec", not "patches".'),
    ({"mode": "rewrite"}, 'A cockpit is drafted "new" or as an "edit".'),
    ({"mode": "new", "cards": {"key": "k1"}}, '"cards" is a list of the cards to create.'),
])
def test_a_draft_that_is_not_one(desk, kw, sentence):
    assert sentence in refused(desk, **kw)


def test_the_tool_tells_the_writer_to_repair_and_try_again(desk):
    out = draft_cockpit(CONN, desk.id, {"op": "new", "spec": desk.spec(), "cards": [
        {"key": "return-rate", "metric": desk.draft_metric}]})
    assert out["staged"] is False and "could_not_check" not in out
    assert out["summary"].startswith("Nothing staged. Repair every point below and draft it again. ")
    assert out["refused"][0] == f'The metric "{desk.draft_metric}" is draft. A card is made from an approved metric.'
    assert draft_cockpit(CONN, desk.id, {"op": "publish"})["summary"] \
        == 'Nothing staged: "publish" is not one of options, new, edit.'


def test_when_the_rules_cannot_run_nothing_is_staged_and_trying_again_will_not_help(desk, monkeypatch):
    monkeypatch.setattr(V, "_node_bin", lambda: None)

    out = desk.draft()
    assert out.staged is False and out.not_checked is True
    assert "The cockpit's rules could not run: node was not found on this machine" in said(out)
    assert desk.pending() == []

    told = draft_cockpit(CONN, desk.id, {"op": "new", "spec": desk.spec(), "cards": desk.cards()})
    assert told["could_not_check"] is True
    assert told["summary"].startswith("Nothing staged, and drafting it again will not help: ")
    assert propose.options(CONN, desk.id)["available"] is False


def test_a_newer_draft_replaces_the_one_before_it_for_this_canvas_only(desk, monkeypatch, warehouse):
    other = Desk(monkeypatch)
    theirs = staged(other)
    first = staged(desk)

    again = desk.spec()
    again["elements"]["sec-headline"]["props"]["title"] = "At a glance"
    second = desk.draft(spec=again)

    assert second.replaced == (first.id,)
    assert [p.id for p in desk.pending()] == [second.proposal.id]
    gone = inbox.get_proposal(first.id)
    assert gone.status == "superseded" and gone.status_message == f"superseded by {second.proposal.id}"
    assert inbox.get_proposal(theirs.id).status == "pending"

    out = draft_cockpit(CONN, desk.id, {"op": "new", "spec": desk.spec(), "cards": desk.cards()})
    assert out["summary"].endswith(f" It replaces the earlier draft {second.proposal.id}.")


# ── approval ─────────────────────────────────────────────────────────────────

def accept(p, actor: str = "user1"):
    result, _grant = inbox.accept_proposal(p.id, actor=actor)
    return result


def test_approved_every_card_is_made_and_the_spec_is_kept_in_the_approvers_name(desk):
    p = staged(desk, reasoning="Alerts first.")
    result = accept(p)

    assert result.ok is True and result.status == "executed", result.message
    assert result.message == "cockpit 'Returns' kept as version 1 for the canvas 'Returns', with 3 new cards"
    ids = {c["key"]: c["id"] for c in p.params["cards"]}
    assert result.outcome["cards_created"] == [ids["return-rate"], ids["by-category"], ids["first-week"]]
    assert result.outcome["version"] == 1 and result.outcome["canvas_id"] == desk.id

    made = {c.id: c for c in cards.cards_of(desk.id)}
    assert sorted(made) == sorted([desk.held, *ids.values()])
    rate, cat, week = made[ids["return-rate"]], made[ids["by-category"]], made[ids["first-week"]]
    for card in (rate, cat, week):
        assert (card.scope, card.scope_ref, card.connection_id) == ("canvas", desk.id, CONN)
    assert rate.kind == "kpi" and rate.title == "Return rate"
    assert rate.sql == "SELECT 100.0 * COUNT(returned_at) / COUNT(*) FROM order_items"
    assert rate.thresholds == {"critical": 12.0, "direction": "above"}
    assert (rate.provenance.metric, rate.provenance.metric_version) == (desk.metric, 3)
    assert cat.kind == "chart" and cat.provenance.receipt_ref == f"trusted_query:{desk.trusted}:v2"
    assert cat.sql.startswith("SELECT category") and cat.thresholds == {}
    assert week.links == [desk.finding] and week.sql.startswith("SELECT week")

    kept = versions.latest(desk.id)
    assert kept["version"] == 1 and kept["spec"] == p.params["spec"]
    assert kept["approved_by"] == "user1"
    assert kept["source"] == f"proposal {p.id}"
    assert kept["note"] == "Alerts first."
    assert kept["written_by_model"] is True
    assert kept["cards"] == [ids["return-rate"], desk.held, ids["by-category"], ids["first-week"]]

    after = inbox.get_proposal(p.id)
    assert after.status == "executed" and after.resolved_by == "user1"
    assert after.outcome["version"] == 1


def test_the_approver_is_the_signed_in_user_where_there_is_one(desk, monkeypatch):
    """The accepting screen sends a name of its own. Where someone is signed in, the server
    knows who, and that is the name a cockpit is kept in."""
    monkeypatch.setattr("aughor.org.context.current_user_id", lambda: "u42")
    p = staged(desk)
    assert accept(p, actor="chat").ok is True
    assert versions.latest(desk.id)["approved_by"] == "user:u42"
    assert inbox.get_proposal(p.id).resolved_by == "chat"     # the inbox's own record, as it was


def nothing_was_made(desk: Desk, p, *, version=None) -> None:
    assert desk.held_cards() == [desk.held]
    latest = versions.latest(desk.id)
    assert (latest["version"] if latest else None) == version
    assert inbox.get_proposal(p.id).status == "failed"


def test_nobody_approved_it(desk, monkeypatch):
    p = staged(desk)
    real, made = cards.place, []
    monkeypatch.setattr(cards, "place", lambda *a, **kw: made.append(a) or real(*a, **kw))
    result = accept(p, actor="")
    # Keeping would refuse it too, further down. This is refused BEFORE a card is made.
    assert made == []
    assert result.ok is False
    assert "A cockpit is kept with the name of the person who approved it. None was given." in result.message
    nothing_was_made(desk, p)


def test_a_metric_changed_since_the_draft_refuses_all_of_it(desk):
    p = staged(desk)
    save_metric(MetricDefinition(
        name=desk.metric, connection=CONN, label="Return rate", unit="%",
        sql="SELECT 100.0 * COUNT(returned_at) / COUNT(*) FROM order_items",
        tables=["order_items"], status="approved", version=4))

    result = accept(p)
    assert result.ok is False and result.status == "dispatch_error"
    assert (f'The card "Return rate" was drafted from version 3 of the metric "{desk.metric}", '
            "which is now at version 4. Nothing was made. Ask for the cockpit again.") in result.message
    nothing_was_made(desk, p)


def test_a_query_changed_under_the_same_version_refuses_all_of_it(desk):
    p = staged(desk)
    save_trusted(TrustedQuery(
        id=desk.trusted, connection_id=CONN, question="Items returned by category",
        sql="SELECT category, COUNT(*) AS n FROM returns GROUP BY category", status="approved", version=2))
    result = accept(p)
    assert f'was drafted from the trusted query "{desk.trusted}", whose query has changed since.' in result.message
    nothing_was_made(desk, p)


def test_a_metric_no_longer_approved_refuses_all_of_it(desk):
    p = staged(desk)
    save_metric(MetricDefinition(name=desk.metric, connection=CONN, label="Return rate",
                                 sql="SELECT 1", status="deprecated", version=3))
    result = accept(p)
    assert f'The metric "{desk.metric}" is deprecated. A card is made from an approved metric.' in result.message
    nothing_was_made(desk, p)


def test_a_finding_gone_since_the_draft_refuses_all_of_it(desk):
    p = staged(desk)
    desk.findings.clear()
    result = accept(p)
    assert f'This canvas has no finding "{desk.finding}".' in result.message
    nothing_was_made(desk, p)


def test_a_cockpit_that_moved_on_since_the_draft_refuses_it(desk):
    p = staged(desk)
    by_hand = {"root": "c", "elements": {
        "c": {"type": "Cockpit", "props": {"title": "By hand"}, "children": ["s"]},
        "s": {"type": "Section", "props": {"title": "Headline"}, "children": ["k"]},
        "k": {"type": "Card", "props": {"card": desk.held}, "children": []}}}
    assert versions.keep(desk.id, by_hand, approved_by="user2", source="a person's own hand",
                         written_by_model=False).kept

    result = accept(p)
    assert ("The cockpit has changed since this was drafted: it was not yet made, and it is now version 1. "
            "Ask for it again.") in result.message
    nothing_was_made(desk, p, version=1)
    assert versions.latest(desk.id)["spec"] == by_hand


def test_all_or_nothing_when_the_spec_cannot_be_kept(desk, monkeypatch):
    p = staged(desk)
    seen: list[list[str]] = []

    def refuse(canvas_id, spec, **kw):
        seen.append(desk.held_cards())
        return versions.Kept(versions.FAILED, sentences=("The cockpit could not be kept: the disk is full.",))

    monkeypatch.setattr(versions, "keep", refuse)
    result = accept(p)

    assert len(seen) == 1 and len(seen[0]) == 4          # the cards HAD been made when the keep failed
    assert "The cockpit could not be kept: the disk is full. Nothing was kept." in result.message
    nothing_was_made(desk, p)


def test_all_or_nothing_when_a_card_cannot_be_made(desk, monkeypatch):
    p = staged(desk)
    real = cards.place
    calls: list[str] = []

    def second_fails(canvas_id, card, *, metric=None):
        calls.append(card.id)
        if len(calls) == 2:
            raise RuntimeError("the card store is locked")
        return real(canvas_id, card, metric=metric)

    monkeypatch.setattr(cards, "place", second_fails)
    result = accept(p)

    assert len(calls) == 2
    assert "The cockpit could not be made: the card store is locked. Nothing was kept." in result.message
    nothing_was_made(desk, p)


def test_a_card_id_taken_since_the_draft(desk):
    p = staged(desk)
    taken = p.params["cards"][0]["id"]
    elsewhere = create_canvas("Elsewhere", [CanvasScope(connection_id=CONN)])
    cards.place(elsewhere.id, DashboardCard(id=taken, kind="kpi", title="Someone else's", sql="SELECT 1"))

    result = accept(p)
    assert f'A card with the id "{taken}" already exists. Nothing was made.' in result.message
    nothing_was_made(desk, p)
    assert [c.id for c in cards.cards_of(elsewhere.id)] == [taken]


def test_it_is_approved_once(desk):
    p = staged(desk)
    assert accept(p).ok is True
    again = accept(p)
    assert again.ok is False and again.status == "already_resolved"
    assert len(versions.history(desk.id)) == 1 and len(desk.held_cards()) == 4


def test_it_is_audited_under_its_own_name(desk):
    assert inbox.gov_action_of(staged(desk)) == "cockpit.draft"


# ── an edit ──────────────────────────────────────────────────────────────────

@pytest.fixture
def standing(desk) -> Desk:
    """The desk, with its cockpit approved as version 1."""
    assert accept(staged(desk)).ok is True
    return desk


def test_an_edit_is_operations_against_the_cockpit_as_it_stands(standing):
    desk = standing
    before = versions.latest(desk.id)["spec"]
    patches = [
        {"op": "replace", "path": "/elements/sec-headline/props/title", "value": "At a glance"},
        {"op": "remove", "path": "/elements/sec-detail/children/1"},
        {"op": "remove", "path": "/elements/c-week"},
    ]
    out = draft_cockpit(CONN, desk.id, {"op": "edit", "patches": patches})

    [p] = desk.pending()
    assert out["summary"].startswith(
        'Drafted an edit to the cockpit "Returns", which stands at version 1: 2 tabs, 3 sections, 3 cards ')
    assert p.params["mode"] == "edit" and p.params["base_version"] == 1
    assert p.params["patches"] == patches and p.params["cards"] == []
    assert p.detail["replaces_version"] == 1
    assert p.detail["changes"] == {"added": [], "removed": ["c-week"],
                                   "changed": ["sec-detail", "sec-headline"]}
    assert p.params["spec"]["elements"]["sec-headline"]["props"]["title"] == "At a glance"
    assert versions.latest(desk.id)["spec"] == before          # nothing changed yet
    # The card says what moves, line by line, and nothing of what stays.
    marks = {(t["tab"], s["title"]): s["change"] for t in p.detail["outline"] for s in t["sections"]}
    assert marks == {("Overview", "Needs a look"): "", ("Overview", "At a glance"): "changed",
                     ("Detail", "Where and when"): "changed"}
    assert {t["tab"]: t["change"] for t in p.detail["outline"]} == {"Overview": "", "Detail": ""}
    assert {c["change"] for t in p.detail["outline"] for s in t["sections"] for c in s["cards"]} == {""}
    # …and what it takes off, by name and by where it was: the outline is of what will be.
    assert p.detail["taken_off"] == [
        {"what": "card", "title": "Returns cluster in the first week after delivery", "from": "Where and when"}]

    assert accept(p, actor="user2").ok is True
    latest = versions.latest(desk.id)
    assert latest["version"] == 2 and latest["approved_by"] == "user2"
    assert latest["spec"] == p.params["spec"]
    assert latest["changes"] == p.detail["changes"]
    assert [v["version"] for v in versions.history(desk.id)] == [2, 1]
    # The card the edit took off the cockpit is still the canvas's: an edit arranges, it does not delete.
    assert len(desk.held_cards()) == 4


def test_an_edit_that_takes_off_a_section_and_a_tab_says_each_by_name(standing):
    p = staged(standing, mode="edit", patches=[
        {"op": "remove", "path": "/elements/tabs/children/1"},
        {"op": "remove", "path": "/elements/tab-detail"},
        {"op": "remove", "path": "/elements/sec-detail"},
        {"op": "remove", "path": "/elements/c-cat"},
        {"op": "remove", "path": "/elements/c-week"},
    ])
    assert sorted(p.detail["taken_off"], key=lambda r: (r["what"], r["title"])) == [
        {"what": "card", "title": "Returned, by category", "from": "Where and when"},
        {"what": "card", "title": "Returns cluster in the first week after delivery", "from": "Where and when"},
        {"what": "section", "title": "Where and when", "from": "Detail"},
        {"what": "tab", "title": "Detail", "from": ""},
    ]
    # Taken off the cockpit, and still the canvas's: an edit arranges, it deletes no card.
    assert accept(p).ok is True
    assert len(standing.held_cards()) == 4


def test_a_new_cockpit_takes_nothing_off(standing):
    spec = standing.spec()
    spec["elements"]["cockpit"]["props"]["title"] = "Returned goods"
    for el in spec["elements"].values():                  # it places the cards the canvas now holds
        if el["type"] == "Card" and el["props"]["card"] != standing.held:
            el["props"]["card"] = standing.held
        el.pop("visible", None)
    p = staged(standing, spec=spec, cards=[])
    assert p.detail["taken_off"] == [] and p.detail["replaces_version"] == 1


def test_an_edit_may_make_a_card_and_place_it_by_the_name_it_gave(standing, monkeypatch):
    desk = standing
    other = f"units_{desk.tag}"
    save_metric(MetricDefinition(name=other, connection=CONN, label="Units returned",
                                 sql="SELECT COUNT(returned_at) FROM order_items", status="approved", version=1))
    out = desk.draft(mode="edit", cards=[{"key": "units", "metric": other}], patches=[
        {"op": "add", "path": "/elements/c-units", "value": {
            "type": "Card", "props": {"card": "units"}, "children": [],
            "visible": {"$state": "/cards/units/status", "neq": "withheld"}}},
        {"op": "add", "path": "/elements/sec-headline/children/-", "value": "c-units"},
    ])
    assert out.staged, said(out)
    headline = out.proposal.detail["outline"][0]["sections"][1]
    assert (headline["title"], headline["change"]) == ("Headline", "changed")
    assert headline["cards"][-1] == {"title": "Units returned", "new": True, "change": "added", "tone": "",
                                     "shown": '"Units returned" is not withheld'}
    [card] = out.proposal.params["cards"]
    el = out.proposal.params["spec"]["elements"]["c-units"]
    assert el["props"]["card"] == card["id"] != "units"
    assert el["visible"] == {"$state": f"/cards/{card['id']}/status", "neq": "withheld"}

    assert accept(out.proposal).ok is True
    assert versions.latest(desk.id)["version"] == 2
    assert card["id"] in desk.held_cards()


@pytest.mark.parametrize("patches,sentence", [
    ([{"op": "remove", "path": "/elements/ghost"}],
     'Operation 1 of 1 is refused: "/elements/ghost" is not in the spec. Nothing was changed.'),
    ([{"op": "replace", "path": "/elements/sec-headline/props/title", "value": "Returns up 14%"}],
     'reads "Returns up 14%", which states a figure (14%)'),
    ([{"op": "remove", "path": "/elements/sec-detail/children/1"}], "orphaned_element"),
    ([{"op": "replace", "path": "/elements/cockpit/props/title", "value": "Returns"}],
     "The cockpit already reads this way. Nothing was drafted."),
    ([], "An edit is a list of operations, and this one holds none."),
    (None, "An edit is a list of operations, and this one holds none."),
])
def test_an_edit_that_is_refused(standing, patches, sentence):
    assert sentence in refused(standing, mode="edit", patches=patches)


def test_an_edit_carries_operations_not_a_spec(standing):
    text = refused(standing, mode="edit", spec=standing.spec(),
                   patches=[{"op": "replace", "path": "/elements/cockpit/props/title", "value": "Returned"}])
    assert 'An edit carries "patches", not a "spec".' in text


def test_there_is_nothing_to_edit(desk):
    assert refused(desk, mode="edit", patches=[{"op": "remove", "path": "/root"}]) \
        == 'This canvas has no cockpit to edit. Draft one with op "new".'


def test_a_retired_cockpit_is_not_edited_and_a_new_one_follows_it(standing):
    desk = standing
    assert versions.retire(desk.id, approved_by="user1").kept
    assert "This canvas has no cockpit to edit" in refused(
        desk, mode="edit", patches=[{"op": "replace", "path": "/elements/cockpit/props/title", "value": "X"}])

    spec = {"root": "c", "elements": {
        "c": {"type": "Cockpit", "props": {"title": "Returns again"}, "children": ["s"]},
        "s": {"type": "Section", "props": {"title": "Headline"}, "children": ["k"]},
        "k": {"type": "Card", "props": {"card": desk.held}, "children": []}}}
    p = staged(desk, spec=spec, cards=[])
    assert p.params["base_version"] == 2 and p.detail["replaces_version"] is None
    assert accept(p).ok is True
    assert versions.latest(desk.id)["version"] == 3


def test_an_edit_drafted_against_a_version_lands_on_that_version_or_not_at_all(standing):
    desk = standing
    p = staged(desk, mode="edit", patches=[
        {"op": "replace", "path": "/elements/sec-headline/props/title", "value": "At a glance"}])
    spec = versions.latest(desk.id)["spec"]
    spec["elements"]["cockpit"]["props"]["title"] = "Returned goods"
    assert versions.keep(desk.id, spec, approved_by="user2", source="a person's own hand",
                         written_by_model=False).kept

    result = accept(p)
    assert ("The cockpit has changed since this was drafted: it was version 1, and it is now version 2. "
            "Ask for it again.") in result.message
    assert versions.latest(desk.id)["version"] == 2
    assert versions.latest(desk.id)["spec"]["elements"]["sec-headline"]["props"]["title"] == "Headline"
