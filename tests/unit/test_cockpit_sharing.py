"""A cockpit published to a group or a role (docs/COCKPIT_CANVAS_2026-10-08.md, B5), and a change
asked for in words.

Identity is on in these tests, through the self-host headers, so that a group has members and a
role has holders: with identity off there is one operator and nothing to share with. Each desk is
an org of its own, so two tests never read each other's groups.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aughor.cockpit import cards, propose, sharing, validate as V, versions
from aughor.cockpit.home import Home
from aughor.dashboard.models import DashboardCard
from aughor.kernel.flags import flag_overrides
from aughor.metastore.models import user_principal
from aughor.org.context import using_org
from aughor.rbac.groups import add_member, upsert_group
from aughor.rbac.store import assign_role

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "lib" / "cockpit" / "premise.fixture.json"

needs_rules = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the cockpit's rules need node + validate.bundle.mjs")

AMIT, PRIYA, SAM = "amit@example.com", "priya@example.com", "sam@example.com"


class Office:
    """One org with a Sales group (Amit, Priya), Sam outside it, and Amit's cockpit on a connection."""

    def __init__(self):
        tag = uuid.uuid4().hex[:6]
        self.org = f"org{tag}"
        self.connection = f"conn{tag}"
        with using_org(self.org):
            self.sales = upsert_group(self.org, f"sales-{tag}", "Sales team").id
            add_member(self.org, self.sales, user_principal(AMIT))
            add_member(self.org, self.sales, user_principal(PRIYA))
            assign_role(self.org, AMIT, "analyst")
            assign_role(self.org, PRIYA, "viewer")
            assign_role(self.org, SAM, "viewer")
            self.home = Home(self.connection, AMIT, f"returns-{tag}")
            self.rate, self.net = f"rate{tag}", f"net{tag}"
            for cid, title in ((self.rate, "Return rate"), (self.net, "Net revenue")):
                cards.place(self.home, DashboardCard(id=cid, kind="kpi", title=title, sql="SELECT 1"))
            text = FIXTURE.read_text().replace("c7f3a001", self.rate).replace("c91b2002", self.net)
            self.spec = json.loads(text)
            self.spec["elements"]["note-1"] = {"type": "Note", "props": {"text": "Pipeline review Tuesdays."}, "children": []}
            self.spec["elements"]["sec-headline"]["children"].append("note-1")

    def keep(self):
        with using_org(self.org):
            return versions.keep(self.home, self.spec, approved_by=f"user:{AMIT}", source="a person's own hand",
                                 written_by_model=False)


def said(kept) -> str:
    return " ".join(getattr(kept, "sentences", None) or getattr(kept, "refusals", ()))


# ── who may publish where ─────────────────────────────────────────────────────────────────────

def test_a_member_may_publish_to_their_group_and_not_to_one_they_are_outside():
    o = Office()
    with using_org(o.org):
        hit, why = sharing.may_publish_to(AMIT, {"kind": "group", "name": "sales team"})
        assert hit == {"kind": "group", "id": o.sales, "name": "Sales team"} and why == ""
        hit, why = sharing.may_publish_to(SAM, {"kind": "group", "id": o.sales})
        assert hit is None and 'not a member of the group "Sales team"' in why
        hit, why = sharing.may_publish_to(AMIT, {"kind": "team", "name": "Sales"})
        assert hit is None and "a group or a role" in why


def test_a_role_needs_the_role_itself_or_the_permission_that_administers_roles():
    o = Office()
    with using_org(o.org):
        hit, why = sharing.may_publish_to(AMIT, {"kind": "role", "name": "Editor"})
        assert hit == {"kind": "role", "id": "analyst", "name": "Editor"}
        hit, why = sharing.may_publish_to(PRIYA, {"kind": "role", "name": "Editor"})
        assert hit is None and 'needs that role, or admin.manage_roles' in why
        hit, why = sharing.may_publish_to(AMIT, {"kind": "role", "name": "Regional managers"})
        assert hit is None and 'There is no role "Regional managers"' in why
        assign_role(o.org, SAM, "owner")
        hit, why = sharing.may_publish_to(SAM, {"kind": "role", "name": "Viewer"})
        assert hit == {"kind": "role", "id": "viewer", "name": "Viewer"}


# ── publishing is a version, and so is unpublishing ──────────────────────────────────────────

@needs_rules
def test_publishing_is_a_version_that_reaches_the_group_and_unpublishing_is_one_too():
    o = Office()
    assert o.keep().kept
    with using_org(o.org):
        sales = {"kind": "group", "id": o.sales, "name": "Sales team"}
        out = versions.publish(o.home, [sales], approved_by=f"user:{AMIT}")
        assert out.kept and out.version == 2
        latest = versions.latest(o.home)
        assert latest["published_to"] == [sales] and latest["published_by"] == f"user:{AMIT}"
        assert latest["source"] == "published to Sales team" and latest["spec"] == versions.version(o.home, 1)["spec"]
        assert versions.publish(o.home, [sales], approved_by=f"user:{AMIT}").status == versions.UNCHANGED

        # Priya is in Sales: she sees it. Sam is not. Amit does not see his own among "shared with you".
        assert [c["cockpit_id"] for c in sharing.shared_with(o.connection, PRIYA)] == [o.home.cockpit_id]
        assert sharing.shared_with(o.connection, SAM) == []
        assert sharing.shared_with(o.connection, AMIT) == []
        got = sharing.read_shared(o.connection, AMIT, o.home.cockpit_id, reader=PRIYA)
        assert got["cockpit"]["version"] == 2
        with pytest.raises(sharing.Refused, match="not shared with you"):
            sharing.read_shared(o.connection, AMIT, o.home.cockpit_id, reader=SAM)

        # An edit carries the audience; unpublishing is the next version and reaches nobody.
        edited = json.loads(json.dumps(latest["spec"]))
        edited["elements"]["sec-headline"]["props"]["title"] = "At a glance"
        kept = versions.keep(o.home, edited, approved_by=f"user:{AMIT}", source="a person's own hand", written_by_model=False)
        assert kept.kept and versions.latest(o.home)["published_to"] == [sales]
        off = versions.publish(o.home, [], approved_by=f"user:{AMIT}")
        assert off.kept and off.version == 4
        assert versions.latest(o.home)["published_to"] == [] and versions.latest(o.home)["source"] == "unpublished"
        assert sharing.shared_with(o.connection, PRIYA) == []


@needs_rules
def test_a_reader_starts_a_cockpit_of_their_own_from_a_published_one():
    o = Office()
    assert o.keep().kept
    with using_org(o.org):
        versions.publish(o.home, [{"kind": "group", "id": o.sales, "name": "Sales team"}], approved_by=f"user:{AMIT}")
        out = sharing.copy_for(o.connection, AMIT, o.home.cockpit_id, reader=PRIYA, approved_by=f"user:{PRIYA}")
        assert out["kept"].kept, said(out["kept"])
        mine = Home(o.connection, PRIYA, out["cockpit_id"])
        copied = versions.latest(mine)
        placed = [el["props"]["card"] for el in copied["spec"]["elements"].values() if el["type"] == "Card"]
        # Amit's own cards were copied into Priya's, under new ids; the note's stamp stays Amit's.
        assert o.rate not in placed and o.net not in placed
        own = {c.id: c for c in cards.own(mine)}
        assert set(placed) <= set(own) and all(f"copied:{o.rate}" in c.links or f"copied:{o.net}" in c.links for c in own.values())
        assert copied["spec"]["elements"]["note-1"]["props"]["author"] == f"user:{AMIT}"
        assert copied["source"].startswith('started from "Returns", published by user:amit@example.com')
        assert copied["published_to"] == []
        # Amit's is untouched.
        assert versions.latest(o.home)["version"] == 2
        with pytest.raises(sharing.Refused):
            sharing.copy_for(o.connection, AMIT, o.home.cockpit_id, reader=SAM, approved_by=f"user:{SAM}")


# ── in words ──────────────────────────────────────────────────────────────────────────────────

@needs_rules
def test_a_publish_asked_for_in_words_is_a_proposal_and_kept_it_publishes():
    o = Office()
    assert o.keep().kept
    with using_org(o.org):
        refused = propose.propose_publish(o.home, [{"kind": "group", "name": "Finance"}])
        assert not refused.staged and 'not a member of the group "Finance"' in said(refused)
        staged = propose.propose_publish(o.home, [{"kind": "group", "name": "Sales team"}])
        assert staged.staged
        assert staged.proposal.kind == "cockpit_publish" and staged.proposal.detail["to"] == ["Sales team"]
        ok, out = propose.accept_publish(dict(staged.proposal.params), connection_id=o.connection, approved_by=f"user:{PRIYA}")
        assert not ok and "only they can publish it" in out
        ok, out = propose.accept_publish(dict(staged.proposal.params), connection_id=o.connection, approved_by=f"user:{AMIT}")
        assert ok and out["version"] == 2 and out["to"] == ["Sales team"]
        assert sharing.shared_with(o.connection, PRIYA)[0]["published_by"] == f"user:{AMIT}"
        # Proposed against a version that has moved on, it is not published.
        again = propose.propose_publish(o.home, [{"kind": "role", "name": "Editor"}])
        versions.publish(o.home, [], approved_by=f"user:{AMIT}")
        ok, out = propose.accept_publish(dict(again.proposal.params), connection_id=o.connection, approved_by=f"user:{AMIT}")
        assert not ok and "has changed since this was proposed" in out


@needs_rules
def test_options_tell_the_writer_who_the_cockpit_may_be_published_to():
    o = Office()
    assert o.keep().kept
    with using_org(o.org):
        opts = propose.options(o.home)
        assert opts["may_publish_to"] == {"groups": ["Sales team"], "roles": ["Editor"]}
        assert opts["cockpit"]["published_to"] == []


def test_a_change_in_words_needs_a_cockpit_that_stands(monkeypatch):
    from aughor.cockpit import ask
    out = ask.edit_in_words("conn-x", AMIT, "nothing-here", "make the net sales card bigger")
    assert not out["staged"] and out["sentences"] == ["There is no cockpit here to change."]
    out = ask.edit_in_words("conn-x", AMIT, "nothing-here", "   ")
    assert not out["staged"] and "Say what to change" in out["sentences"][0]


# ── over HTTP ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


@pytest.fixture
def on():
    with flag_overrides({"cockpit.composed": True}):
        yield


def _as(org: str, user: str) -> dict:
    return {"X-Aughor-Org": org, "X-Aughor-User": user}


@needs_rules
def test_publish_read_as_a_reader_and_copy_over_http(client, on, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.setenv("AUGHOR_TIER", "enterprise")
    o = Office()
    assert o.keep().kept
    # Priya reads as a viewer; to start a cockpit of her own she needs to write, as an editor does.
    with using_org(o.org):
        assign_role(o.org, PRIYA, "analyst")
    q = {"connection_id": o.connection}
    me = client.get("/cockpits/audiences", params=q, headers=_as(o.org, AMIT))
    assert me.status_code == 200, me.text
    assert [g["name"] for g in me.json()["groups"]] == ["Sales team"]

    refused = client.post(f"/cockpits/{o.home.cockpit_id}/publish", params=q, headers=_as(o.org, AMIT),
                          json={"to": [{"kind": "group", "name": "Finance"}]})
    assert refused.status_code == 422 and "not a member" in refused.json()["detail"]["sentences"][0]
    pub = client.post(f"/cockpits/{o.home.cockpit_id}/publish", params=q, headers=_as(o.org, AMIT),
                      json={"to": [{"kind": "group", "name": "Sales team"}]})
    assert pub.status_code == 200, pub.text
    assert pub.json()["version"] == 2

    shared = client.get("/cockpits/shared", params=q, headers=_as(o.org, PRIYA)).json()["cockpits"]
    assert [c["title"] for c in shared] == ["Returns"] and shared[0]["owner"] == AMIT
    read = client.get(f"/cockpits/shared/{AMIT}/{o.home.cockpit_id}", params=q, headers=_as(o.org, PRIYA))
    assert read.status_code == 200, read.text
    assert read.json()["published_by"] == f"user:{AMIT}" and read.json()["cockpit"]["spec"]
    assert client.get(f"/cockpits/shared/{AMIT}/{o.home.cockpit_id}", params=q, headers=_as(o.org, SAM)).status_code == 404

    copied = client.post(f"/cockpits/shared/{AMIT}/{o.home.cockpit_id}/copy", params=q, headers=_as(o.org, PRIYA))
    assert copied.status_code == 200, copied.text
    assert copied.json()["version"] == 1 and copied.json()["title"] == "Returns"
    mine = client.get("/cockpits", params=q, headers=_as(o.org, PRIYA)).json()["cockpits"]
    assert [c["cockpit_id"] for c in mine] == [copied.json()["cockpit_id"]]

    off = client.post(f"/cockpits/{o.home.cockpit_id}/unpublish", params=q, headers=_as(o.org, AMIT))
    assert off.status_code == 200 and off.json()["version"] == 3
    assert client.get("/cockpits/shared", params=q, headers=_as(o.org, PRIYA)).json()["cockpits"] == []


def test_off_the_sharing_routes_answer_404(client):
    q = {"connection_id": "conn-off"}
    assert client.get("/cockpits/shared", params=q).status_code == 404
    assert client.get("/cockpits/audiences", params=q).status_code == 404
    assert client.post("/cockpits/returns-1/publish", params=q, json={"to": []}).status_code == 404
    assert client.post("/cockpits/returns-1/ask", params=q, json={"words": "x"}).status_code == 404
