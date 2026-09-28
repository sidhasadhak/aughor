"""Arc CT, CT-7 and CT-10 (ROADMAP §3.50) — a person's cockpits over HTTP.

The flag is off by default, and off it must change nothing: the routes answer 404 and the
Briefing's own card routes answer exactly as they did. On, one route calls a model — the
draft for an area — and every other route calls none.

Identity is off in the suite, so every request is the same person ("default"). Each desk is
therefore on a connection of its own: a person's cards and cockpits are keyed by connection,
and two tests must not read each other's.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aughor.cockpit import cards, compose, host, validate as V, versions
from aughor.cockpit.home import FIRST, Home, approver
from aughor.dashboard import store as card_store
from aughor.dashboard.models import DashboardCard
from aughor.kernel.flags import flag_overrides

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "lib" / "cockpit" / "premise.fixture.json"

needs_rules = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the cockpit's rules need node + validate.bundle.mjs")

ME = "default"          # identity is off: the one operator


@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


@pytest.fixture
def on():
    with flag_overrides({"cockpit.composed": True}):
        yield


class Desk:
    """A person's cockpit-to-be on a connection of its own, with three cards of theirs."""

    def __init__(self, with_cards: bool = True, connection: str = ""):
        tag = uuid.uuid4().hex[:6]
        self.connection = connection or f"conn{tag}"
        self.cockpit_id = f"returns-{tag}"
        self.home = Home(self.connection, ME, self.cockpit_id)
        self.rate, self.net, self.chart = f"rate{tag}", f"net{tag}", f"cat{tag}"
        if with_cards:
            for cid, kind, title in ((self.rate, "kpi", "Return rate"), (self.net, "kpi", "Net merchandise revenue"),
                                     (self.chart, "chart", "Items returned by category")):
                cards.place(self.home, DashboardCard(id=cid, kind=kind, title=title, sql="SELECT 1"))
        text = FIXTURE.read_text().replace("c7f3a001", self.rate).replace("c91b2002", self.net)
        self.spec = json.loads(text)

    @property
    def path(self) -> str:
        return f"/cockpits/{self.cockpit_id}"

    @property
    def q(self) -> dict:
        return {"connection_id": self.connection}


@pytest.fixture
def desk() -> Desk:
    return Desk()


# ── off ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("get", "/cockpits", None),
    ("get", "/cockpits/{id}", None),
    ("put", "/cockpits/{id}", {"spec": {}}),
    ("post", "/cockpits/start", None),
    ("post", "/cockpits/draft", {"area": "returns"}),
    ("post", "/cockpits/move", {"canvas_id": "cv1"}),
    ("post", "/cockpits/{id}/restore", {"version": 1}),
    ("post", "/cockpits/{id}/retire", {}),
])
def test_off_every_route_answers_404_and_nothing_is_kept(client, desk, method, path, body):
    r = getattr(client, method)(path.format(id=desk.cockpit_id), params=desk.q,
                                **({"json": body} if body is not None else {}))
    assert r.status_code == 404
    assert "cockpit.composed" in r.json()["detail"]
    assert versions.latest(desk.home) is None


def test_off_the_briefings_cards_answer_exactly_as_they_do_on(client, desk):
    """Byte-identical when off: the flag adds routes of its own and touches no other answer."""
    card_store.upsert_card(DashboardCard(connection_id=desk.connection, scope="connection",
                                         scope_ref=desk.connection, kind="kpi", title="Pinned"))
    params = {"connection_id": desk.connection, "scope": "connection", "scope_ref": desk.connection}
    off = client.get("/cards", params=params)
    with flag_overrides({"cockpit.composed": True}):
        on = client.get("/cards", params=params)
    assert off.status_code == on.status_code == 200
    assert off.content == on.content


def test_the_flag_is_registered_off_and_queued_to_graduate():
    from aughor.kernel import flags
    assert flags.flag_enabled("cockpit.composed") is False
    assert flags.flag_disposition("cockpit.composed") == "graduation_queue"


# ── the person's cockpits ─────────────────────────────────────────────────────

@needs_rules
def test_the_list_is_the_persons_cockpits_and_what_they_may_start_from(client, desk, on):
    card_store.upsert_card(DashboardCard(connection_id=desk.connection, scope="connection",
                                         scope_ref=desk.connection, kind="kpi", title="Pinned"))
    empty = client.get("/cockpits", params=desk.q).json()
    assert empty == {"person": ME, "cockpits": [], "shared_cards": 1, "own_cards": 3, "from_canvases": []}

    client.put(desk.path, params=desk.q, json={"spec": desk.spec})
    listed = client.get("/cockpits", params=desk.q).json()["cockpits"]
    assert [(c["cockpit_id"], c["title"], c["version"], c["retired"]) for c in listed] == [
        (desk.cockpit_id, "Returns", 1, False)]
    assert client.get("/cockpits", params={"connection_id": "elsewhere"}).json()["cockpits"] == []


def test_a_cockpit_never_kept_is_404(client, desk, on):
    assert client.get(desk.path, params=desk.q).status_code == 404
    assert client.get("/cockpits/Not An Id", params=desk.q).status_code == 404


@needs_rules
def test_reading_writes_nothing(client, desk, on):
    from aughor.kernel.ledger import Ledger
    client.put(desk.path, params=desk.q, json={"spec": desk.spec})
    count = lambda: Ledger.default()._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]  # noqa: E731
    before = count()
    for _ in range(3):
        assert client.get(desk.path, params=desk.q).status_code == 200
        assert client.get("/cockpits", params=desk.q).status_code == 200
    assert count() == before


@needs_rules
def test_a_range_needs_the_briefings_own_flag(client, on):
    desk = Desk(connection="thelook")
    client.put(desk.path, params=desk.q, json={"spec": desk.spec})
    with flag_overrides({"briefing.ranges": False}):
        r = client.get(desk.path, params={**desk.q, "preset": "last_month"})
        assert r.status_code == 404 and "briefing.ranges" in r.json()["detail"]
        assert client.get(desk.path, params=desk.q).json()["ranges_on"] is False


@needs_rules
def test_a_range_is_read_for_the_cockpits_connection(client, on):
    desk = Desk(connection="thelook")
    client.put(desk.path, params=desk.q, json={"spec": desk.spec})
    with flag_overrides({"briefing.ranges": True}):
        r = client.get(desk.path, params={**desk.q, "preset": "last_month"})
        assert r.status_code == 200, r.text
        block = r.json()["range"]
        assert block["status"] == "final" and block["preset"] == "last_month"
        assert block["covers"] and block["start"] < block["last_day"]
        assert r.json()["ranges_on"] is True

        to_date = client.get(desk.path, params={**desk.q, "preset": "month_to_date"}).json()["range"]
        assert to_date["status"] == "to_date"

        bad = client.get(desk.path, params={**desk.q, "preset": "fortnight"})
        assert bad.status_code == 422 and "a range is one of" in bad.json()["detail"]
        assert client.get(desk.path, params={**desk.q, "start": "28/09/2026"}).status_code == 422


# ── the range's status, from its dates ────────────────────────────────────────

class _Spec:
    def __init__(self, preset, last_day, as_of, lag_days):
        self.preset, self.last_day, self.as_of, self.lag_days = preset, last_day, as_of, lag_days


@pytest.mark.parametrize("preset,last_day,lag,expected", [
    ("last_month", date(2026, 8, 31), 8, "final"),
    ("custom", date(2026, 9, 20), 8, "final"),             # the newest settled day itself
    ("custom", date(2026, 9, 21), 8, "provisional"),       # over, not settled
    ("custom", date(2026, 9, 27), 8, "provisional"),
    ("custom", date(2026, 9, 28), 8, "to_date"),           # today is in it
    ("custom", date(2026, 10, 3), 8, "to_date"),
    ("month_to_date", date(2026, 9, 20), 8, "to_date"),    # to date by its name, whatever its days
    ("year_to_date", date(2026, 9, 20), 8, "to_date"),
    ("custom", date(2026, 9, 27), 0, "final"),             # no lag: yesterday has settled
])
def test_a_ranges_status_is_read_off_its_dates(preset, last_day, lag, expected):
    assert host.status_of(_Spec(preset, last_day, date(2026, 9, 28), lag)) == expected


@needs_rules
def test_the_host_says_only_words_the_web_declares():
    """One list of statuses. The web's is the home; a word the host says and the rules do not
    know would make every condition on it a refusal."""
    assert list(host.RANGE_STATUSES) == V.vocabulary()["range_statuses"]


# ── keeping, by a person's own hand ───────────────────────────────────────────

@needs_rules
def test_a_spec_is_kept_and_then_read(client, desk, on):
    r = client.put(desk.path, params=desk.q, json={"spec": desk.spec, "note": "the first cut"})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "kept", "kept": True, "version": 1, "cockpit_id": desk.cockpit_id,
                        "artifact_id": r.json()["artifact_id"], "sentences": []}

    body = client.get(desk.path, params=desk.q).json()
    assert (body["connection_id"], body["owner"], body["cockpit_id"]) == (desk.connection, ME, desk.cockpit_id)
    assert body["cockpit"]["version"] == 1 and body["cockpit"]["spec"] == desk.spec
    assert body["cockpit"]["approved_by"] == "person"            # identity is off in the suite
    assert body["cockpit"]["source"] == "a person's own hand"
    assert body["cockpit"]["note"] == "the first cut"
    assert [h["version"] for h in body["history"]] == [1] and "spec" not in body["history"][0]
    assert sorted(c["id"] for c in body["cards"]) == sorted([desk.rate, desk.net, desk.chart])
    assert all(c["own"] is True for c in body["cards"])
    assert body["range"]["status"] == "standing"

    again = client.put(desk.path, params=desk.q, json={"spec": desk.spec})
    assert again.status_code == 200 and again.json()["status"] == "unchanged"


def test_an_identified_person_is_named_by_their_id():
    assert approver("u_42") == "user:u_42"
    assert approver(ME) == "person"


@needs_rules
def test_a_refusal_is_an_error_that_carries_its_reasons(client, desk, on):
    bad = json.loads(json.dumps(desk.spec))
    bad["elements"]["card-rate"]["watch"] = {"/tab": {"action": "anything"}}
    r = client.put(desk.path, params=desk.q, json={"spec": bad})

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["status"] == "refused" and detail["kept"] is False and detail["version"] is None
    assert any("A cockpit runs nothing without a click" in s for s in detail["sentences"])
    assert versions.latest(desk.home) is None


def test_when_the_rules_cannot_run_the_answer_is_503_never_200(client, desk, on, monkeypatch):
    monkeypatch.setattr(V, "_node_bin", lambda: None)
    r = client.put(desk.path, params=desk.q, json={"spec": desk.spec})
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "not_checked"
    assert any("Nothing is accepted unchecked" in s for s in r.json()["detail"]["sentences"])
    assert versions.latest(desk.home) is None


@needs_rules
def test_a_person_may_put_a_number_in_their_own_title(client, desk, on):
    spec = json.loads(json.dumps(desk.spec))
    spec["elements"]["sec-headline"]["props"]["title"] = "Top 1000 accounts"
    r = client.put(desk.path, params=desk.q, json={"spec": spec})
    assert r.status_code == 200, r.text
    assert client.get(desk.path, params=desk.q).json()["cockpit"]["written_by_model"] is False


# ── "My cockpit", started from the cards pinned before cockpits had names ────

class _C:
    def __init__(self, id, kind, title):
        self.id, self.kind, self.title = id, kind, title


def test_the_first_cockpit_groups_the_cards_by_kind_in_a_fixed_order():
    spec = compose.default_spec("Returns", [
        _C("n1", "note", "Read me"), _C("k2", "kpi", "Net revenue"), _C("c1", "chart", "By category"),
        _C("k1", "kpi", "Return rate"), _C("w1", "watch", "Rate over 12%"), _C("x1", "sankey", "Flows"),
    ])
    root = spec["elements"]["cockpit"]
    assert spec["root"] == "cockpit" and root["props"] == {"title": "Returns"}
    assert root["children"] == ["sec-figures", "sec-charts", "sec-watches", "sec-notes"]
    el = spec["elements"]
    assert el["sec-figures"] == {"type": "Section", "props": {"title": "Figures", "columns": 2},
                                 "children": ["card-k2", "card-k1"]}          # by title, not by id
    assert el["sec-charts"]["children"] == ["card-c1", "card-x1"]              # an unknown kind draws with the charts
    assert el["card-k1"] == {"type": "Card", "props": {"card": "k1"}, "children": []}
    assert "state" not in spec                                                  # no tabs, so nothing to open


def test_the_first_cockpit_keeps_the_order_the_person_arranged():
    spec = compose.default_spec("My cockpit", [_C("k1", "kpi", "Alpha"), _C("k2", "kpi", "Beta"),
                                               _C("k3", "kpi", "Gamma")], order=["k3", "k1"])
    assert spec["elements"]["sec-figures"]["children"] == ["card-k3", "card-k1", "card-k2"]


@needs_rules
def test_my_cockpit_is_started_from_the_pinned_cards_in_the_persons_order(client, on):
    desk = Desk(with_cards=False)
    pins = [card_store.upsert_card(DashboardCard(connection_id=desk.connection, scope="connection",
                                                 scope_ref=desk.connection, kind="kpi", title=t, sql="SELECT 1"))
            for t in ("Alpha", "Beta", "Gamma")]
    card_store.set_layout(desk.connection, ME, {pins[2].id: {"x": 0, "y": 0}, pins[0].id: {"x": 4, "y": 0},
                                                pins[1].id: {"x": 0, "y": 3}})
    r = client.post("/cockpits/start", params=desk.q)
    assert r.status_code == 200, r.text
    assert r.json()["cockpit_id"] == FIRST and r.json()["version"] == 1

    kept = client.get(f"/cockpits/{FIRST}", params=desk.q).json()["cockpit"]
    assert kept["source"] == "started from the cards pinned in the Briefing"
    assert kept["written_by_model"] is False
    assert kept["spec"]["elements"]["cockpit"]["props"]["title"] == "My cockpit"
    assert kept["spec"]["elements"]["sec-figures"]["children"] == [
        f"card-{pins[2].id}", f"card-{pins[0].id}", f"card-{pins[1].id}"]     # top row left to right, then down

    again = client.post("/cockpits/start", params=desk.q)
    assert again.status_code == 409 and "already have" in again.json()["detail"]["sentences"][0]


def test_with_nothing_pinned_there_is_nothing_to_start_from_and_it_says_so(client, on):
    empty = Desk(with_cards=False)
    r = client.post("/cockpits/start", params=empty.q)
    assert r.status_code == 422
    assert r.json()["detail"]["sentences"] == [
        "There are no pinned cards to start from. Name an area to draft a cockpit instead."]
    assert versions.latest(Home(empty.connection, ME, FIRST)) is None


# ── going back, and retiring ──────────────────────────────────────────────────

@needs_rules
def test_going_back_and_retiring_over_http(client, desk, on):
    client.put(desk.path, params=desk.q, json={"spec": desk.spec})
    edited = json.loads(json.dumps(desk.spec))
    edited["elements"]["sec-headline"]["props"]["title"] = "At a glance"
    assert client.put(desk.path, params=desk.q, json={"spec": edited}).json()["version"] == 2

    back = client.post(f"{desk.path}/restore", params=desk.q, json={"version": 1})
    assert back.status_code == 200 and back.json()["version"] == 3
    assert client.get(desk.path, params=desk.q).json()["cockpit"]["spec"] == desk.spec

    missing = client.post(f"{desk.path}/restore", params=desk.q, json={"version": 9})
    assert missing.status_code == 422 and "has no version 9" in missing.json()["detail"]["sentences"][0]

    gone = client.post(f"{desk.path}/retire", params=desk.q, json={"note": "replaced"})
    assert gone.status_code == 200 and gone.json()["version"] == 4
    body = client.get(desk.path, params=desk.q).json()
    assert body["cockpit"]["retired"] is True and body["cockpit"]["spec"] is None
    assert [h["version"] for h in body["history"]] == [4, 3, 2, 1]


# ── the draft for an area: the one route that calls a model ──────────────────

def test_the_draft_route_hands_the_area_and_the_person_to_the_drafter(client, desk, on, monkeypatch):
    asked = []

    def drafter(connection_id, owner, area, *, schema=None):
        asked.append((connection_id, owner, area, schema))
        return {"staged": False, "sentences": ["stub"]}

    monkeypatch.setattr("aughor.cockpit.ask.draft_for_area", drafter)
    r = client.post("/cockpits/draft", params=desk.q, json={"area": "Returns and refunds", "schema_name": "thelook"})
    assert r.status_code == 200 and r.json() == {"staged": False, "sentences": ["stub"]}
    assert asked == [(desk.connection, ME, "Returns and refunds", "thelook")]


# ── moving a canvas's cockpit here ────────────────────────────────────────────

class Canvas:
    """A canvas on the desk's connection whose cockpit was kept before the home moved: its
    cards at canvas scope, its spec under the canvas's own key — three versions of it."""

    def __init__(self, desk: Desk):
        from aughor.canvas.models import CanvasScope
        from aughor.canvas.store import create_canvas
        from aughor.kernel.ledger import Ledger
        self.canvas = create_canvas("E-Commerce", [CanvasScope(connection_id=desk.connection)])
        self.id = self.canvas.id
        tag = uuid.uuid4().hex[:6]
        self.rate, self.net = f"crate{tag}", f"cnet{tag}"
        for cid, title in ((self.rate, "Return rate"), (self.net, "Net merchandise revenue")):
            card_store.upsert_card(DashboardCard(id=cid, connection_id=desk.connection, scope="canvas",
                                                 scope_ref=self.id, kind="kpi", title=title, sql="SELECT 1"))
        self.spec = json.loads(FIXTURE.read_text().replace("c7f3a001", self.rate).replace("c91b2002", self.net))
        for n in (1, 2, 3):
            Ledger.default().artifact_write("cockpit", versions.canvas_key(self.id), {
                "spec": self.spec, "retired": False, "approved_by": "person", "source": f"proposal p{n}",
                "note": "", "vocabulary_version": 1, "written_by_model": True,
                "cards": [self.rate, self.net], "changes": {"added": [], "removed": [], "changed": []}},
                conn_id=desk.connection, canvas_id=self.id)


@needs_rules
def test_a_canvas_cockpit_is_offered_and_moved_in_one_act(client, desk, on):
    cv = Canvas(desk)
    offered = client.get("/cockpits", params=desk.q).json()["from_canvases"]
    assert [(o["canvas_id"], o["title"], o["version"]) for o in offered] == [(cv.id, "Returns", 3)]

    r = client.post("/cockpits/move", params=desk.q, json={"canvas_id": cv.id})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["moved"] is True and out["title"] == "Returns" and out["version"] == 1
    assert out["cards_moved"] == 2 and out["sentences"] == []

    home = Home(desk.connection, ME, out["cockpit_id"])
    kept = versions.latest(home)
    assert kept["spec"] == cv.spec and kept["written_by_model"] is True
    assert kept["source"] == "moved from the canvas 'E-Commerce'"
    for cid in (cv.rate, cv.net):
        card = card_store.get_card(cid)
        assert (card.scope, card.scope_ref) == ("user", ME)                     # the same card, now theirs

    left = versions.canvas_latest(cv.id)
    assert left["retired"] is True and left["version"] == 4                   # superseded, not deleted
    assert left["note"] == "moved to the Briefing as 'Returns'"
    assert client.get("/cockpits", params=desk.q).json()["from_canvases"] == []

    twice = client.post("/cockpits/move", params=desk.q, json={"canvas_id": cv.id})
    assert twice.status_code == 422 and "already moved" in twice.json()["detail"]["sentences"][0]


@needs_rules
def test_a_move_that_cannot_be_kept_puts_the_cards_back(client, desk, on, monkeypatch):
    cv = Canvas(desk)
    monkeypatch.setattr(V, "_node_bin", lambda: None)
    r = client.post("/cockpits/move", params=desk.q, json={"canvas_id": cv.id})
    assert r.status_code == 422 and r.json()["detail"]["sentences"][-1] == "Nothing moved."
    for cid in (cv.rate, cv.net):
        card = card_store.get_card(cid)
        assert (card.scope, card.scope_ref) == ("canvas", cv.id)
    assert versions.canvas_latest(cv.id)["retired"] is False


def test_a_canvas_on_another_connection_is_not_moved_here(client, desk, on):
    cv = Canvas(desk)
    r = client.post("/cockpits/move", params={"connection_id": "elsewhere"}, json={"canvas_id": cv.id})
    assert r.status_code == 422 and "not on this connection" in r.json()["detail"]["sentences"][0]


# ── no model ──────────────────────────────────────────────────────────────────

@needs_rules
def test_no_route_but_the_draft_calls_a_model(client, on, monkeypatch):
    """What was kept is drawn, and a person's own edits are kept, at no model cost. Every model
    call in the product goes through one of LLMProvider's three methods, whoever built the
    provider and however it was imported, so that is where this stands guard."""
    from aughor.llm.provider import LLMProvider

    def spent(self, *a, **kw):
        raise AssertionError("a cockpit route called a model")

    for method in ("complete", "complete_with_tools", "complete_streaming"):
        assert hasattr(LLMProvider, method), f"LLMProvider.{method} is gone; this guard guards nothing"
        monkeypatch.setattr(LLMProvider, method, spent)

    desk = Desk(with_cards=False)
    card_store.upsert_card(DashboardCard(connection_id=desk.connection, scope="connection",
                                         scope_ref=desk.connection, kind="kpi", title="Pinned", sql="SELECT 1"))
    assert client.get("/cockpits", params=desk.q).status_code == 200
    assert client.post("/cockpits/start", params=desk.q).status_code == 200
    first = f"/cockpits/{FIRST}"
    assert client.get(first, params=desk.q).status_code == 200
    spec = client.get(first, params=desk.q).json()["cockpit"]["spec"]
    spec["elements"]["cockpit"]["props"]["title"] = "Mine"
    assert client.put(first, params=desk.q, json={"spec": spec}).status_code == 200
    assert client.post(f"{first}/restore", params=desk.q, json={"version": 1}).status_code == 200
    assert client.post(f"{first}/retire", params=desk.q, json={}).status_code == 200
    cv = Canvas(desk)
    assert client.post("/cockpits/move", params=desk.q, json={"canvas_id": cv.id}).status_code == 200
