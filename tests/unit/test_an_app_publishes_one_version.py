"""An App publishes one version (Arc ED, ED-4; ROADMAP §3.58 and §6 item 52(a) — the user, 2026-10-24: *"Last
published version"*).

Before this a shared dashboard's readers read every keep the moment it was made: an edit carried the audience to the
next version (``dashboards/versions.py``, "an edit does not unpublish"). Now (part of the platform since 2026-10-28)
each version says where it stands on the platform's one publication axis (``kernel/lifecycle.py``) — a keep is a draft, a
publish published, an unpublish or a retire archived — and a reader reads the version last published. Who it reaches
is still the newest version's audience, so unpublishing reaches nobody at once.

The falsifier (§3.58): a reader reads a version its owner never published.

Identity is on through the self-host headers where HTTP is driven, as in ``test_dashboard_sharing.py``: with identity
off there is one operator and nobody to share with. Each office is an org of its own.
"""
from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aughor.cards.models import StoredCard
from aughor.dashboards import cards, propose, sharing, validate as V, versions
from aughor.dashboards.home import Home
from aughor.kernel.ledger import Ledger
from aughor.metastore.models import user_principal
from aughor.org.context import using_org
from aughor.rbac.groups import add_member, upsert_group
from aughor.rbac.store import assign_role

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "lib" / "dashboards" / "premise.fixture.json"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the dashboard's rules need node + validate.bundle.mjs")

AMIT, PRIYA, SAM = "amit@example.com", "priya@example.com", "sam@example.com"


class Office:
    """One org with a Sales group (Amit, Priya), Sam outside it, and Amit's dashboard "Returns" on a connection."""

    def __init__(self):
        tag = uuid.uuid4().hex[:6]
        self.org = f"org{tag}"
        self.connection = f"conn{tag}"
        with using_org(self.org):
            self.sales_id = upsert_group(self.org, f"sales-{tag}", "Sales team").id
            add_member(self.org, self.sales_id, user_principal(AMIT))
            add_member(self.org, self.sales_id, user_principal(PRIYA))
            assign_role(self.org, AMIT, "analyst")
            assign_role(self.org, PRIYA, "analyst")
            assign_role(self.org, SAM, "viewer")
            self.id = f"returns-{tag}"
            self.home = Home(self.connection, AMIT, self.id)
            rate, net = f"rate{tag}", f"net{tag}"
            for cid, title in ((rate, "Return rate"), (net, "Net revenue")):
                cards.place(self.home, StoredCard(id=cid, kind="kpi", title=title, sql="SELECT 1"))
            self.spec = json.loads(FIXTURE.read_text().replace("c7f3a001", rate).replace("c91b2002", net))
        self.sales = {"kind": "group", "id": self.sales_id, "name": "Sales team"}

    def keep(self, headline: str = "") -> versions.Kept:
        """Keep the dashboard, its headline section titled ``headline`` when one is given."""
        with using_org(self.org):
            now = versions.latest(self.home)
            spec = copy.deepcopy(now["spec"] if now and now.get("spec") else self.spec)
            if headline:
                spec["elements"]["sec-headline"]["props"]["title"] = headline
            return versions.keep(self.home, spec, approved_by=f"user:{AMIT}", source="a person's own hand",
                                 written_by_model=False)

    def publish(self, to=None) -> versions.Kept:
        with using_org(self.org):
            return versions.publish(self.home, [self.sales] if to is None else to, approved_by=f"user:{AMIT}")

    def read(self, reader: str = PRIYA) -> dict:
        with using_org(self.org):
            return app_in(sharing.read_shared(self.connection, AMIT, self.id, reader=reader))

    def latest(self) -> dict:
        with using_org(self.org):
            return versions.latest(self.home)

    def states(self) -> list:
        with using_org(self.org):
            return [v.get("state") for v in versions.history(self.home)]

    def payloads(self) -> list[dict]:
        return [r["payload"] for r in Ledger.default().artifact_versions(self.home.key, limit=100)]


def app_in(body: dict) -> dict:
    """The version a read answers with — under the field name stored rows and the API carry."""
    return body["cockpit"]


def headline_of(entry: dict) -> str:
    return entry["spec"]["elements"]["sec-headline"]["props"]["title"]


# ── the falsifier ─────────────────────────────────────────────────────────────────────────────

def test_a_reader_reads_the_version_last_published_until_its_owner_publishes_again():
    o = Office()
    assert o.keep().kept
    assert o.publish().version == 2
    assert o.read()["version"] == 2

    # Two changes kept since: each is the owner's draft, and the reader still reads version 2.
    assert o.keep("At a glance").version == 3
    assert o.keep("The week at a glance").version == 4
    read = o.read()
    assert read["version"] == 2 and headline_of(read) == "Headline"
    assert o.read(reader=AMIT)["version"] == 2           # the owner, reading as a reader, reads it too
    with using_org(o.org):
        listed = sharing.shared_with(o.connection, PRIYA)
    assert [(c["version"], c["title"]) for c in listed] == [(2, "Returns")]
    mine = o.latest()
    assert mine["version"] == 4 and mine["state"] == "draft" and mine["published_version"] == 2
    assert mine["published_to"] == [o.sales]               # who it reaches is unchanged by a keep

    # Publishing to the same audience publishes the draft: the reader now reads the newest change.
    out = o.publish()
    assert out.kept and out.version == 5
    read = o.read()
    assert read["version"] == 5 and headline_of(read) == "The week at a glance"
    assert o.latest()["state"] == "published" and o.latest()["published_version"] == 5
    assert o.publish().status == versions.UNCHANGED        # nothing kept since: nothing to publish
    assert o.states() == ["published", "draft", "draft", "published", "draft"]


def test_unpublishing_reaches_nobody_at_once_and_retiring_too():
    o = Office()
    assert o.keep().kept and o.publish().kept
    assert o.keep("At a glance").kept                      # v3, a draft
    off = o.publish(to=[])
    assert off.kept and off.version == 4
    assert o.latest()["state"] == "archived" and o.latest()["published_version"] is None
    with using_org(o.org):
        assert sharing.shared_with(o.connection, PRIYA) == []
    with pytest.raises(sharing.Refused, match="not shared with you"):
        o.read()                                           # version 2 is still published, and reaches nobody

    assert o.publish().version == 5
    assert headline_of(o.read()) == "At a glance"

    with using_org(o.org):
        assert versions.retire(o.home, approved_by=f"user:{AMIT}").kept
    with pytest.raises(sharing.Refused, match="retired"):
        o.read()
    assert o.states()[0] == "archived" and o.latest()["published_version"] is None


def test_a_reader_starts_their_own_from_the_published_version_not_the_draft():
    o = Office()
    assert o.keep().kept and o.publish().kept
    assert o.keep("At a glance").kept
    with using_org(o.org):
        out = sharing.copy_for(o.connection, AMIT, o.id, reader=PRIYA, approved_by=f"user:{PRIYA}")
        assert out["kept"].kept, out["kept"].sentences
        theirs = versions.latest(Home(o.connection, PRIYA, out["cockpit_id"]))
    assert headline_of(theirs) == "Headline" and "(version 2)" in theirs["source"]


def test_a_publish_asked_for_in_words_may_publish_a_draft_to_the_same_audience():
    o = Office()
    assert o.keep().kept and o.publish().kept
    with using_org(o.org):
        same = propose.propose_publish(o.home, [{"kind": "group", "name": "Sales team"}])
    assert not same.staged and "already published to Sales team" in " ".join(same.refusals)

    assert o.keep("At a glance").kept
    with using_org(o.org):
        staged = propose.propose_publish(o.home, [{"kind": "group", "name": "Sales team"}])
        assert staged.staged
        ok, out = propose.accept_publish(dict(staged.proposal.params), connection_id=o.connection,
                                         approved_by=f"user:{AMIT}")
    assert ok and out["version"] == 4
    assert headline_of(o.read()) == "At a glance"


# ── the versions kept before App versions ────────────────────────────────────────────────────

def _unstamped(payload: dict, state, by: str) -> dict:
    """A version as it was kept before App versions began: no publication state on it."""
    return {k: v for k, v in payload.items() if k != "_lifecycle"}


def test_versions_kept_before_app_versions_read_as_their_readers_read_them(monkeypatch):
    o = Office()
    with monkeypatch.context() as m:
        m.setattr(versions, "_stamped", _unstamped)
        assert o.keep().kept and o.publish().kept
        assert o.keep("At a glance").kept                      # read at once by its readers, then
    assert o.read()["version"] == 3                            # …and still, now that an App has versions
    assert o.latest()["state"] == "published" and o.publish().status == versions.UNCHANGED
    assert o.keep("The week at a glance").kept                 # a draft now
    assert o.read()["version"] == 3
    assert o.states() == ["draft", "published", "published", "draft"]


# ── the platform's generic lifecycle doors ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


def test_the_lifecycle_doors_read_an_apps_versions_and_refuse_to_write_one(client):
    o = Office()
    assert o.keep().kept and o.publish().kept and o.keep("At a glance").kept
    q = {"natural_key": o.home.key}
    hist = client.get(f"/lifecycle/{versions.KIND}/history", params=q)
    assert hist.status_code == 200, hist.text
    body = hist.json()
    assert (body["published_version"], body["editor_version"]) == (2, 3)
    assert [r["state"] for r in body["revisions"]] == ["draft", "published", "draft"]

    # A version written by the generic door would hold no spec: an App its readers read empty.
    for door in ("publish", "revert"):
        refused = client.post(f"/lifecycle/{versions.KIND}/{door}", params={**q, "to_version": 1})
        assert refused.status_code == 409 and "dashboard's own doors" in refused.json()["detail"]
    assert o.latest()["version"] == 3 and o.latest()["spec"]


# ── over HTTP ─────────────────────────────────────────────────────────────────────────────────

def _as(org: str, user: str) -> dict:
    return {"X-Aughor-Org": org, "X-Aughor-User": user}


def test_over_http_a_reader_reads_the_published_version_and_the_owner_is_told_which(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.setenv("AUGHOR_TIER", "enterprise")
    o = Office()
    q = {"connection_id": o.connection}
    assert o.keep().kept
    to = {"to": [{"kind": "group", "name": "Sales team"}]}
    pub = client.post(f"/dashboards/{o.id}/publish", params=q, headers=_as(o.org, AMIT), json=to)
    assert pub.status_code == 200 and pub.json()["version"] == 2, pub.text
    assert o.keep("At a glance").kept

    read = client.get(f"/dashboards/shared/{AMIT}/{o.id}", params=q, headers=_as(o.org, PRIYA))
    assert read.status_code == 200, read.text
    assert app_in(read.json())["version"] == 2 and headline_of(app_in(read.json())) == "Headline"
    mine = client.get(f"/dashboards/{o.id}", params=q, headers=_as(o.org, AMIT))
    assert mine.status_code == 200, mine.text
    kept = app_in(mine.json())
    assert (kept["version"], kept["state"], kept["published_version"]) == (3, "draft", 2)
    assert [v["state"] for v in mine.json()["history"]] == ["draft", "published", "draft"]

    again = client.post(f"/dashboards/{o.id}/publish", params=q, headers=_as(o.org, AMIT), json=to)
    assert again.status_code == 200 and again.json()["version"] == 4, again.text
    read = client.get(f"/dashboards/shared/{AMIT}/{o.id}", params=q, headers=_as(o.org, PRIYA))
    assert app_in(read.json())["version"] == 4 and headline_of(app_in(read.json())) == "At a glance"
