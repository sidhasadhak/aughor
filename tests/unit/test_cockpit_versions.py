"""Arc CT, CT-3 (ROADMAP §3.50) — a cockpit's spec kept as versions, its cards at canvas scope.

Run against the REAL stores — the Ledger, the card store and the canvas store — each pointed
at a temporary file by ``tests/conftest.py``. The validator is the real one too, so these
need node and the bundle, as the chart tests do.

Every refusal is asserted by a token of its own sentence, and every "nothing was written" by
counting the history, never by the returned status alone.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from aughor.canvas.models import CanvasScope
from aughor.canvas.store import create_canvas
from aughor.cockpit import cards, validate as V, versions
from aughor.dashboard import store as card_store
from aughor.dashboard.models import DashboardCard
from aughor.org.context import using_org

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "lib" / "cockpit" / "premise.fixture.json"

needs_rules = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the cockpit's rules need node + validate.bundle.mjs")


class Desk:
    """One canvas with two cards, and the premise spec written for THOSE cards. Card ids are
    unique to each test, because a card's id is its own across the whole store."""

    def __init__(self, connection: str = "thelook", name: str = "Returns"):
        tag = uuid.uuid4().hex[:6]
        self.connection = connection
        self.canvas = create_canvas(name, [CanvasScope(connection_id=connection)])
        self.rate, self.net = f"rate{tag}", f"net{tag}"
        text = FIXTURE.read_text().replace("c7f3a001", self.rate).replace("c91b2002", self.net)
        self._spec = json.loads(text)
        for cid, title in ((self.rate, "Return rate"), (self.net, "Net merchandise revenue")):
            cards.place(self.id, DashboardCard(id=cid, kind="kpi", title=title, sql="SELECT 1"))

    @property
    def id(self) -> str:
        return self.canvas.id

    def spec(self) -> dict:
        return json.loads(json.dumps(self._spec))

    def keep(self, spec=None, **kw) -> versions.Kept:
        kw.setdefault("approved_by", "user1")
        kw.setdefault("source", "a person's own hand")
        return versions.keep(self.id, self.spec() if spec is None else spec, **kw)


@pytest.fixture
def desk() -> Desk:
    return Desk()


def said(kept: versions.Kept) -> str:
    return "\n".join(kept.sentences)


# ── keeping ───────────────────────────────────────────────────────────────────

@needs_rules
def test_the_first_spec_kept_is_version_one(desk):
    out = desk.keep(note="the first cut")

    assert out.status == versions.KEPT and out.kept is True, said(out)
    assert out.version == 1 and out.artifact_id

    latest = versions.latest(desk.id)
    assert latest["version"] == 1 and latest["current"] is True and latest["retired"] is False
    assert latest["spec"] == desk.spec()
    assert latest["approved_by"] == "user1"
    assert latest["source"] == "a person's own hand"
    assert latest["note"] == "the first cut"
    assert latest["vocabulary_version"] == 1
    assert latest["cards"] == [desk.rate, desk.net]
    assert latest["changes"] == {"added": sorted(desk.spec()["elements"]), "removed": [], "changed": []}
    assert latest["kept_at"]


@needs_rules
def test_the_artifact_carries_its_canvas_its_connection_and_its_lineage(desk):
    from aughor.kernel.ledger import Ledger

    first = desk.keep()
    edited = desk.spec()
    edited["elements"]["sec-headline"]["props"]["title"] = "At a glance"
    second = desk.keep(edited)

    row = Ledger.default().artifact_by_id(second.artifact_id)
    assert row["kind"] == "cockpit"
    assert row["natural_key"] == f"cockpit:{desk.id}"
    assert row["canvas_id"] == desk.id and row["conn_id"] == "thelook"
    edges = Ledger.default()._conn.execute(
        "SELECT relation, ref, detail FROM lineage WHERE artifact_id = ?", (second.artifact_id,)).fetchall()
    assert [tuple(e) for e in edges] == [("supersedes", first.artifact_id, "the spec changed")]


@needs_rules
def test_approving_the_same_spec_again_writes_nothing(desk):
    first = desk.keep()
    again = desk.keep(approved_by="user2", note="approved a second time")

    assert again.status == versions.UNCHANGED and again.kept is False
    assert again.version == 1 and again.artifact_id == first.artifact_id
    assert len(versions.history(desk.id)) == 1
    assert versions.latest(desk.id)["approved_by"] == "user1"      # the first approval stands


@needs_rules
def test_the_same_spec_with_its_keys_in_another_order_is_the_same_spec(desk):
    desk.keep()
    shuffled = desk.spec()
    shuffled["elements"] = dict(reversed(list(shuffled["elements"].items())))
    assert desk.keep(shuffled).status == versions.UNCHANGED
    assert len(versions.history(desk.id)) == 1


@needs_rules
def test_an_edit_is_the_next_version_and_the_one_before_is_kept(desk):
    desk.keep()
    edited = desk.spec()
    edited["elements"]["sec-headline"]["props"]["title"] = "At a glance"
    del edited["elements"]["alert-rate"]
    edited["elements"]["sec-headline"]["children"] = ["card-rate", "card-net"]
    out = desk.keep(edited, source="proposal:p_42", note="no alert card")

    assert out.status == versions.KEPT and out.version == 2

    newest, first = versions.history(desk.id)
    assert (newest["version"], newest["current"]) == (2, True)
    assert (first["version"], first["current"]) == (1, False)       # superseded, not deleted
    assert newest["changes"] == {"added": [], "removed": ["alert-rate"], "changed": ["sec-headline"]}
    assert newest["source"] == "proposal:p_42"
    assert "spec" not in newest                                       # a history is a list, not a dump

    assert versions.version(desk.id, 1)["spec"] == desk.spec()
    assert versions.version(desk.id, 2)["spec"] == edited
    assert versions.version(desk.id, 3) is None


# ── refusing ──────────────────────────────────────────────────────────────────

@needs_rules
def test_a_spec_the_rules_refuse_is_not_kept(desk):
    desk.keep()
    bad = desk.spec()
    bad["elements"]["card-rate"]["watch"] = {"/tab": {"action": "anything"}}
    out = desk.keep(bad)

    assert out.status == versions.REFUSED and out.kept is False
    assert out.version is None and out.artifact_id == ""
    assert "A cockpit runs nothing without a click" in said(out)
    assert len(versions.history(desk.id)) == 1
    assert versions.latest(desk.id)["spec"] == desk.spec()


@needs_rules
def test_a_card_this_canvas_does_not_hold_is_refused_by_name(desk):
    other = Desk()
    spec = desk.spec()
    spec["elements"]["card-net"]["props"]["card"] = other.net
    out = desk.keep(spec)

    assert out.status == versions.REFUSED
    assert f'places the card "{other.net}", which this canvas does not hold' in said(out)
    assert versions.latest(desk.id) is None


@needs_rules
def test_a_card_the_same_approval_is_about_to_create_counts_as_held(desk):
    spec = desk.spec()
    spec["elements"]["card-net"]["props"]["card"] = "newcard01"
    assert desk.keep(spec).status == versions.REFUSED
    assert desk.keep(spec, also_known=["newcard01"]).status == versions.KEPT


@pytest.mark.parametrize("who,where,token", [
    ("", "a person's own hand", "the name of the person who approved it"),
    ("   ", "a person's own hand", "the name of the person who approved it"),
    ("user1", "", "where it came from"),
])
def test_a_spec_is_kept_with_who_approved_it_and_where_it_came_from(desk, who, where, token):
    out = desk.keep(approved_by=who, source=where)
    assert out.status == versions.REFUSED
    assert token in said(out)
    assert versions.latest(desk.id) is None


def test_a_canvas_that_does_not_exist_keeps_nothing(desk):
    out = versions.keep("nocanvas", desk.spec(), approved_by="user1", source="a person's own hand")
    assert out.status == versions.REFUSED
    assert 'The canvas "nocanvas" does not exist' in said(out)
    assert versions.latest("nocanvas") is None


def test_when_the_rules_cannot_run_nothing_is_kept(desk, monkeypatch):
    monkeypatch.setattr(V, "_node_bin", lambda: None)
    out = desk.keep()

    assert out.status == versions.NOT_CHECKED and out.kept is False
    assert "node was not found" in said(out)
    assert "Nothing is accepted unchecked" in said(out)
    assert versions.latest(desk.id) is None and versions.history(desk.id) == []


@needs_rules
def test_a_write_that_fails_is_said_not_swallowed(desk, monkeypatch):
    from aughor.kernel.ledger import Ledger

    def broken(self, *a, **kw):
        raise OSError("disk is full")

    monkeypatch.setattr(Ledger, "artifact_write", broken)
    out = desk.keep()

    assert out.status == versions.FAILED and out.kept is False
    assert "could not be kept: OSError: disk is full" in said(out)
    assert "Nothing was changed" in said(out)


# ── whose words the titles are ────────────────────────────────────────────────

@needs_rules
def test_a_models_title_is_held_to_the_numerals_law_and_a_persons_is_not(desk):
    spec = desk.spec()
    spec["elements"]["sec-headline"]["props"]["title"] = "Top 1000 accounts"

    by_model = desk.keep(spec, source="proposal:p_7")                 # unsaid is strict
    assert by_model.status == versions.REFUSED and "states a figure (1000)" in said(by_model)
    assert versions.latest(desk.id) is None

    by_person = desk.keep(spec, written_by_model=False)
    assert by_person.status == versions.KEPT
    assert versions.latest(desk.id)["written_by_model"] is False


@needs_rules
def test_going_back_holds_a_version_to_the_rule_it_was_first_held_to(desk):
    spec = desk.spec()
    spec["elements"]["sec-headline"]["props"]["title"] = "Top 1000 accounts"
    desk.keep(spec, written_by_model=False)
    desk.keep(desk.spec(), written_by_model=True, source="proposal:p_8")

    back = versions.restore(desk.id, 1, approved_by="user1")
    assert back.status == versions.KEPT, said(back)                   # a person's title, still theirs
    assert versions.latest(desk.id)["written_by_model"] is False


# ── going back, and retiring ──────────────────────────────────────────────────

@needs_rules
def test_going_back_is_the_next_version_not_a_deletion(desk):
    desk.keep()
    edited = desk.spec()
    edited["elements"]["sec-headline"]["props"]["title"] = "At a glance"
    desk.keep(edited)

    out = versions.restore(desk.id, 1, approved_by="user2")
    assert out.status == versions.KEPT and out.version == 3

    latest = versions.latest(desk.id)
    assert latest["spec"] == desk.spec()
    assert latest["source"] == "restored from version 1" and latest["approved_by"] == "user2"
    assert [h["version"] for h in versions.history(desk.id)] == [3, 2, 1]


@needs_rules
def test_going_back_to_where_you_are_writes_nothing(desk):
    desk.keep()
    assert versions.restore(desk.id, 1, approved_by="user1").status == versions.UNCHANGED
    assert len(versions.history(desk.id)) == 1


@needs_rules
def test_going_back_is_checked_against_the_canvas_as_it_is_today(desk):
    desk.keep()
    trimmed = desk.spec()
    del trimmed["elements"]["card-net"]
    trimmed["elements"]["sec-headline"]["children"] = ["alert-rate", "card-rate"]
    desk.keep(trimmed)
    card_store.delete_card(desk.net)                 # the card is gone since version 1

    out = versions.restore(desk.id, 1, approved_by="user1")
    assert out.status == versions.REFUSED
    assert f'places the card "{desk.net}", which this canvas does not hold' in said(out)
    assert versions.latest(desk.id)["version"] == 2


@needs_rules
def test_a_version_that_does_not_exist_cannot_be_gone_back_to(desk):
    desk.keep()
    out = versions.restore(desk.id, 7, approved_by="user1")
    assert out.status == versions.REFUSED and "has no version 7" in said(out)


@needs_rules
def test_retiring_is_a_version_that_says_so_and_the_history_stays(desk):
    desk.keep()
    out = versions.retire(desk.id, approved_by="user2", note="replaced by the finance one")

    assert out.status == versions.KEPT and out.version == 2
    latest = versions.latest(desk.id)
    assert latest["retired"] is True and latest["spec"] is None
    assert latest["approved_by"] == "user2" and latest["note"] == "replaced by the finance one"
    assert latest["changes"]["removed"] == sorted(desk.spec()["elements"])
    assert [(h["version"], h["retired"]) for h in versions.history(desk.id)] == [(2, True), (1, False)]
    assert versions.version(desk.id, 1)["spec"] == desk.spec()      # still readable

    assert versions.retire(desk.id, approved_by="user2").status == versions.UNCHANGED
    assert len(versions.history(desk.id)) == 2


@needs_rules
def test_a_retired_cockpit_comes_back_as_the_version_after(desk):
    desk.keep()
    versions.retire(desk.id, approved_by="user1")

    gone = versions.restore(desk.id, 2, approved_by="user1")
    assert gone.status == versions.REFUSED
    assert "Version 2 is the one that retired the cockpit" in said(gone)

    # The SAME spec as version 1 is a change now: what stands is a retirement.
    back = desk.keep()
    assert back.status == versions.KEPT and back.version == 3
    assert versions.latest(desk.id)["retired"] is False


def test_a_canvas_with_no_cockpit_has_none_to_retire(desk):
    out = versions.retire(desk.id, approved_by="user1")
    assert out.status == versions.REFUSED and "has no cockpit to retire" in said(out)
    assert versions.retire(desk.id, approved_by="").status == versions.REFUSED


# ── the tenant ────────────────────────────────────────────────────────────────

@needs_rules
def test_another_tenant_does_not_read_this_cockpit(desk):
    desk.keep()
    assert versions.latest(desk.id)["version"] == 1
    with using_org("acme"):
        assert versions.latest(desk.id) is None
        assert versions.history(desk.id) == []
        assert versions.version(desk.id, 1) is None


# ── cards, at canvas scope ────────────────────────────────────────────────────

def test_a_canvas_holds_its_own_cards_and_the_briefings_cockpit_does_not_see_them(desk):
    assert sorted(c.id for c in cards.cards_of(desk.id)) == sorted([desk.rate, desk.net])
    for c in cards.cards_of(desk.id):
        assert (c.scope, c.scope_ref, c.connection_id) == ("canvas", desk.id, "thelook")

    # What the Briefing's cockpit asks for — the connection's cards — holds none of them.
    theirs = {c.id for c in card_store.list_cards(scope="connection", scope_ref="thelook")}
    assert not theirs & {desk.rate, desk.net}


def test_the_briefings_arrangement_is_not_touched(desk):
    card_store.set_layout("thelook", "user1", {"kept1": {"x": 0, "y": 0, "w": 4, "h": 2}})
    Desk()
    assert card_store.get_layout("thelook", "user1") == {"kept1": {"x": 0, "y": 0, "w": 4, "h": 2}}


def test_another_canvas_holds_none_of_them(desk):
    other = Desk()
    assert {c.id for c in cards.cards_of(other.id)} == {other.rate, other.net}
    assert not {c.id for c in cards.cards_of(other.id)} & {desk.rate, desk.net}


def test_a_card_is_not_taken_from_where_it_already_lives(desk):
    other = Desk()
    with pytest.raises(cards.Refused, match=f'The card "{desk.rate}" already belongs to the canvas "{desk.id}"'):
        cards.place(other.id, DashboardCard(id=desk.rate, kind="kpi", title="Return rate"))
    assert card_store.get_card(desk.rate).scope_ref == desk.id

    pinned = card_store.upsert_card(DashboardCard(
        connection_id="thelook", scope="connection", scope_ref="thelook", kind="kpi", title="Pinned in the Briefing"))
    with pytest.raises(cards.Refused, match='already belongs to the connection "thelook"'):
        cards.place(desk.id, DashboardCard(id=pinned.id, kind="kpi", title="Pinned in the Briefing"))
    assert card_store.get_card(pinned.id).scope == "connection"


def test_placing_the_same_card_again_updates_it_where_it_is(desk):
    cards.place(desk.id, DashboardCard(id=desk.rate, kind="kpi", title="Return rate, by item"))
    assert card_store.get_card(desk.rate).title == "Return rate, by item"
    assert len(cards.cards_of(desk.id)) == 2


def test_a_card_is_kept_on_its_canvass_own_connection(desk):
    with pytest.raises(cards.Refused, match='reads the connection "superstore"; the canvas'):
        cards.place(desk.id, DashboardCard(kind="kpi", title="Sales", connection_id="superstore"))
    with pytest.raises(cards.Refused, match='The canvas "nocanvas" does not exist'):
        cards.place("nocanvas", DashboardCard(kind="kpi", title="Sales"))


class _Metric:
    def __init__(self, name, status, version):
        self.name, self.status, self.version = name, status, version


def test_a_card_made_from_an_approved_metric_records_which_one(desk):
    made = cards.place(desk.id, DashboardCard(kind="kpi", title="Return rate", sql="SELECT 1"),
                       metric=_Metric("return_rate", "approved", 3))
    kept = card_store.get_card(made.id)
    assert (kept.provenance.metric, kept.provenance.metric_version) == ("return_rate", 3)
    assert kept.model_dump()["provenance"]["metric"] == "return_rate"      # what GET /cards sends


@pytest.mark.parametrize("status", ["draft", "proposed", "deprecated", ""])
def test_a_metric_that_is_not_approved_makes_no_card(desk, status):
    before = len(cards.cards_of(desk.id))
    with pytest.raises(cards.Refused, match="A card is made from an approved metric"):
        cards.place(desk.id, DashboardCard(kind="kpi", title="Refund value"),
                    metric=_Metric("refund_value", status, 0))
    assert len(cards.cards_of(desk.id)) == before


def test_a_card_written_before_this_reads_with_no_metric(desk):
    """The provenance is a JSON column: a row from before CT-3 has neither field, and must
    read as "not made from a metric", not fail."""
    c = card_store._conn()
    c.execute("UPDATE dashboard_cards SET provenance_json = ? WHERE id = ?",
              ('{"origin_finding_id": "f_9", "receipt_ref": "r_1"}', desk.rate))
    c.commit()
    old = card_store.get_card(desk.rate)
    assert (old.provenance.origin_finding_id, old.provenance.receipt_ref) == ("f_9", "r_1")
    assert (old.provenance.metric, old.provenance.metric_version) == ("", 0)
