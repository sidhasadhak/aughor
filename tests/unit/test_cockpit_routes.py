"""Arc CT, CT-4 (ROADMAP §3.50) — a Data Canvas's cockpit over HTTP.

The flag is off by default, and off it must change nothing: the routes answer 404 and the
canvas's own routes answer exactly as they did. On, no route calls a model.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aughor.canvas.models import CanvasScope
from aughor.canvas.store import create_canvas
from aughor.cockpit import cards, compose, host, validate as V, versions
from aughor.dashboard.models import DashboardCard
from aughor.kernel.flags import flag_overrides

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "lib" / "cockpit" / "premise.fixture.json"

needs_rules = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the cockpit's rules need node + validate.bundle.mjs")


@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


@pytest.fixture
def on():
    with flag_overrides({"cockpit.composed": True}):
        yield


class Desk:
    def __init__(self, with_cards: bool = True, name: str = "Returns"):
        tag = uuid.uuid4().hex[:6]
        self.canvas = create_canvas(name, [CanvasScope(connection_id="thelook")])
        self.id = self.canvas.id
        self.rate, self.net, self.chart = f"rate{tag}", f"net{tag}", f"cat{tag}"
        if with_cards:
            cards.place(self.id, DashboardCard(id=self.rate, kind="kpi", title="Return rate", sql="SELECT 1"))
            cards.place(self.id, DashboardCard(id=self.net, kind="kpi", title="Net merchandise revenue", sql="SELECT 1"))
            cards.place(self.id, DashboardCard(id=self.chart, kind="chart", title="Items returned by category", sql="SELECT 1"))
        text = FIXTURE.read_text().replace("c7f3a001", self.rate).replace("c91b2002", self.net)
        self.spec = json.loads(text)


@pytest.fixture
def desk() -> Desk:
    return Desk()


# ── off ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("get", "/canvases/{id}/cockpit", None),
    ("put", "/canvases/{id}/cockpit", {"spec": {}}),
    ("post", "/canvases/{id}/cockpit/start", None),
    ("post", "/canvases/{id}/cockpit/restore", {"version": 1}),
    ("post", "/canvases/{id}/cockpit/retire", {}),
])
def test_off_every_route_answers_404_and_nothing_is_kept(client, desk, method, path, body):
    r = getattr(client, method)(path.format(id=desk.id), **({"json": body} if body is not None else {}))
    assert r.status_code == 404
    assert "cockpit.composed" in r.json()["detail"]
    assert versions.latest(desk.id) is None


def test_off_the_canvas_answers_exactly_as_it_does_on(client, desk):
    """Byte-identical when off: the flag adds routes of its own and touches no other answer."""
    off = client.get(f"/canvases/{desk.id}")
    with flag_overrides({"cockpit.composed": True}):
        on = client.get(f"/canvases/{desk.id}")
    assert off.status_code == on.status_code == 200
    assert off.content == on.content


def test_the_flag_is_registered_off_and_queued_to_graduate():
    from aughor.kernel import flags
    assert flags.flag_enabled("cockpit.composed") is False
    assert flags.flag_disposition("cockpit.composed") == "graduation_queue"


# ── reading ───────────────────────────────────────────────────────────────────

def test_a_canvas_with_no_cockpit_reads_as_none_with_its_cards(client, desk, on):
    r = client.get(f"/canvases/{desk.id}/cockpit")
    assert r.status_code == 200
    body = r.json()
    assert body["cockpit"] is None and body["history"] == []
    assert body["canvas_id"] == desk.id and body["connection_id"] == "thelook"
    assert sorted(c["id"] for c in body["cards"]) == sorted([desk.rate, desk.net, desk.chart])
    assert body["range"]["status"] == "standing" and body["range"]["preset"] is None


def test_a_canvas_that_does_not_exist_is_404(client, on):
    assert client.get("/canvases/nocanvas/cockpit").status_code == 404


def test_reading_writes_nothing(client, desk, on):
    from aughor.kernel.ledger import Ledger
    count = lambda: Ledger.default()._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]  # noqa: E731
    before = count()
    for _ in range(3):
        assert client.get(f"/canvases/{desk.id}/cockpit").status_code == 200
    assert count() == before


def test_a_range_needs_the_briefings_own_flag(client, desk, on):
    with flag_overrides({"briefing.ranges": False}):
        r = client.get(f"/canvases/{desk.id}/cockpit", params={"preset": "last_month"})
        assert r.status_code == 404 and "briefing.ranges" in r.json()["detail"]
        assert client.get(f"/canvases/{desk.id}/cockpit").json()["ranges_on"] is False


def test_a_range_is_read_for_the_canvass_connection(client, desk, on):
    with flag_overrides({"briefing.ranges": True}):
        r = client.get(f"/canvases/{desk.id}/cockpit", params={"preset": "last_month"})
        assert r.status_code == 200, r.text
        block = r.json()["range"]
        assert block["status"] == "final" and block["preset"] == "last_month"
        assert block["covers"] and block["start"] < block["last_day"]
        assert r.json()["ranges_on"] is True

        to_date = client.get(f"/canvases/{desk.id}/cockpit", params={"preset": "month_to_date"}).json()["range"]
        assert to_date["status"] == "to_date"

        bad = client.get(f"/canvases/{desk.id}/cockpit", params={"preset": "fortnight"})
        assert bad.status_code == 422 and "a range is one of" in bad.json()["detail"]
        assert client.get(f"/canvases/{desk.id}/cockpit", params={"start": "28/09/2026"}).status_code == 422


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
    r = client.put(f"/canvases/{desk.id}/cockpit", json={"spec": desk.spec, "note": "the first cut"})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "kept", "kept": True, "version": 1,
                        "artifact_id": r.json()["artifact_id"], "sentences": []}

    body = client.get(f"/canvases/{desk.id}/cockpit").json()
    assert body["cockpit"]["version"] == 1 and body["cockpit"]["spec"] == desk.spec
    assert body["cockpit"]["approved_by"] == "person"            # identity is off in the suite
    assert body["cockpit"]["source"] == "a person's own hand"
    assert body["cockpit"]["note"] == "the first cut"
    assert [h["version"] for h in body["history"]] == [1] and "spec" not in body["history"][0]

    again = client.put(f"/canvases/{desk.id}/cockpit", json={"spec": desk.spec})
    assert again.status_code == 200 and again.json()["status"] == "unchanged"


@needs_rules
def test_an_identified_person_is_named(client, desk, on):
    from aughor.org.context import reset_user_id, set_user_id
    token = set_user_id("u_42")
    try:
        assert versions.keep(desk.id, desk.spec, approved_by=__import__(
            "aughor.routers.cockpit", fromlist=["_person"])._person(), source="a person's own hand").kept
    finally:
        reset_user_id(token)
    assert versions.latest(desk.id)["approved_by"] == "user:u_42"


@needs_rules
def test_a_refusal_is_an_error_that_carries_its_reasons(client, desk, on):
    bad = json.loads(json.dumps(desk.spec))
    bad["elements"]["card-rate"]["watch"] = {"/tab": {"action": "anything"}}
    r = client.put(f"/canvases/{desk.id}/cockpit", json={"spec": bad})

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["status"] == "refused" and detail["kept"] is False and detail["version"] is None
    assert any("A cockpit runs nothing without a click" in s for s in detail["sentences"])
    assert client.get(f"/canvases/{desk.id}/cockpit").json()["cockpit"] is None


def test_when_the_rules_cannot_run_the_answer_is_503_never_200(client, desk, on, monkeypatch):
    monkeypatch.setattr(V, "_node_bin", lambda: None)
    r = client.put(f"/canvases/{desk.id}/cockpit", json={"spec": desk.spec})
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "not_checked"
    assert any("Nothing is accepted unchecked" in s for s in r.json()["detail"]["sentences"])
    assert versions.latest(desk.id) is None


# ── starting one, without a model ─────────────────────────────────────────────

def test_the_first_cockpit_groups_the_cards_by_kind_in_a_fixed_order():
    class C:
        def __init__(self, id, kind, title):
            self.id, self.kind, self.title = id, kind, title
    spec = compose.default_spec("Returns", [
        C("n1", "note", "Read me"), C("k2", "kpi", "Net revenue"), C("c1", "chart", "By category"),
        C("k1", "kpi", "Return rate"), C("w1", "watch", "Rate over 12%"), C("x1", "sankey", "Flows"),
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


@needs_rules
def test_starting_keeps_a_spec_the_rules_accept(client, desk, on):
    r = client.post(f"/canvases/{desk.id}/cockpit/start")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "kept" and r.json()["version"] == 1

    kept = client.get(f"/canvases/{desk.id}/cockpit").json()["cockpit"]
    assert kept["source"] == "started from this canvas's cards"
    assert sorted(kept["cards"]) == sorted([desk.rate, desk.net, desk.chart])
    assert kept["spec"]["elements"]["cockpit"]["children"] == ["sec-figures", "sec-charts"]
    assert V.check_spec_for_canvas(kept["spec"], desk.id).accepted

    assert client.post(f"/canvases/{desk.id}/cockpit/start").json()["status"] == "unchanged"


@needs_rules
@pytest.mark.parametrize("name", ["Store 4521", "Top 1000 accounts", "482913", "Growth 12%"])
def test_a_canvas_named_with_a_number_starts_its_cockpit(client, on, name):
    """The first cut refused this: the canvas's name became the cockpit's title, the title was
    held to the numerals law, and a name holding a number "stated a figure". It showed as a
    test that failed one run in six, its canvas names being random. A canvas's name is a
    person's word."""
    desk = Desk(name=name)
    r = client.post(f"/canvases/{desk.id}/cockpit/start")
    assert r.status_code == 200, r.text
    kept = client.get(f"/canvases/{desk.id}/cockpit").json()["cockpit"]
    assert kept["spec"]["elements"]["cockpit"]["props"]["title"] == name
    assert kept["written_by_model"] is False


@needs_rules
def test_a_person_may_put_a_number_in_their_own_title(client, desk, on):
    spec = json.loads(json.dumps(desk.spec))
    spec["elements"]["sec-headline"]["props"]["title"] = "Top 1000 accounts"
    r = client.put(f"/canvases/{desk.id}/cockpit", json={"spec": spec})
    assert r.status_code == 200, r.text
    assert client.get(f"/canvases/{desk.id}/cockpit").json()["cockpit"]["written_by_model"] is False


def test_a_canvas_with_no_cards_cannot_start_one_and_is_told_why(client, on):
    empty = Desk(with_cards=False)
    r = client.post(f"/canvases/{empty.id}/cockpit/start")
    assert r.status_code == 422
    assert r.json()["detail"]["sentences"] == [
        "This canvas holds no cards yet. A cockpit is made of cards; add one first."]
    assert versions.latest(empty.id) is None


# ── going back, and retiring ──────────────────────────────────────────────────

@needs_rules
def test_going_back_and_retiring_over_http(client, desk, on):
    client.put(f"/canvases/{desk.id}/cockpit", json={"spec": desk.spec})
    edited = json.loads(json.dumps(desk.spec))
    edited["elements"]["sec-headline"]["props"]["title"] = "At a glance"
    assert client.put(f"/canvases/{desk.id}/cockpit", json={"spec": edited}).json()["version"] == 2

    back = client.post(f"/canvases/{desk.id}/cockpit/restore", json={"version": 1})
    assert back.status_code == 200 and back.json()["version"] == 3
    assert client.get(f"/canvases/{desk.id}/cockpit").json()["cockpit"]["spec"] == desk.spec

    missing = client.post(f"/canvases/{desk.id}/cockpit/restore", json={"version": 9})
    assert missing.status_code == 422 and "has no version 9" in missing.json()["detail"]["sentences"][0]

    gone = client.post(f"/canvases/{desk.id}/cockpit/retire", json={"note": "replaced"})
    assert gone.status_code == 200 and gone.json()["version"] == 4
    body = client.get(f"/canvases/{desk.id}/cockpit").json()
    assert body["cockpit"]["retired"] is True and body["cockpit"]["spec"] is None
    assert [h["version"] for h in body["history"]] == [4, 3, 2, 1]


# ── no model ──────────────────────────────────────────────────────────────────

@needs_rules
def test_no_route_here_calls_a_model(client, desk, on, monkeypatch):
    """The tab draws what was approved. Every model call in the product goes through one of
    LLMProvider's three methods, whoever built the provider and however it was imported, so
    that is where this stands guard."""
    from aughor.llm.provider import LLMProvider

    def spent(self, *a, **kw):
        raise AssertionError("a cockpit route called a model")

    for method in ("complete", "complete_with_tools", "complete_streaming"):
        assert hasattr(LLMProvider, method), f"LLMProvider.{method} is gone; this guard guards nothing"
        monkeypatch.setattr(LLMProvider, method, spent)

    assert client.get(f"/canvases/{desk.id}/cockpit").status_code == 200
    assert client.post(f"/canvases/{desk.id}/cockpit/start").status_code == 200
    assert client.put(f"/canvases/{desk.id}/cockpit", json={"spec": desk.spec}).status_code == 200
    assert client.post(f"/canvases/{desk.id}/cockpit/restore", json={"version": 1}).status_code == 200
    assert client.post(f"/canvases/{desk.id}/cockpit/retire", json={}).status_code == 200
