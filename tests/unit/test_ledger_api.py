"""Phase 7 of the 2027 study, P7-1 — the ledger API (`aughor/routers/ledger.py`), service principals
(`aughor/security/service_principals.py`) and subscriptions to events out (`aughor/record/subscriptions.py`).

What these hold: a person mints a service principal and gets the key once; the key resolves a
principal named `service:<name>`, a wrong key resolves nothing and never falls through to the header
seam, and a service principal is held to the agent policy; a claim posted through the API carries its
author and is refused without a warrant, at a person's tier, or under another author's key; claims read
as recorded on a date; restatements read from a cursor; a subscription delivers a restatement to its
webhook through the notifications executor and records the delivery; the export is JSON lines; a
principal's record is a count of what became of its entries.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from aughor.record import claims as C
from aughor.record import subscriptions as S
from aughor.routers import ledger as R
from aughor.security import authz
from aughor.security import service_principals as SP


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _req(headers: dict, principal=None):
    return SimpleNamespace(headers=headers, state=SimpleNamespace(principal=principal))


PERSON = authz.Principal(user_id="ana", org_id="default")


# ── service principals ─────────────────────────────────────────────────────────────────────

def test_a_person_mints_a_service_principal_and_the_key_resolves_it_once_minted():
    name = "acme-" + uuid.uuid4().hex[:6]
    record, key = SP.mint(name, org_id="default", by="user:ana", note="Acme's forecaster", connections=["c1"])
    assert record["principal"] == f"service:{name}" and record["active"] and "key_hash" not in record and key
    assert SP.get(name)["created_by"] == "user:ana" and any(p["name"] == name for p in SP.list_principals("default"))
    p = SP.resolve(_req({SP.NAME_HEADER: name, SP.KEY_HEADER: key}))
    assert p is not None and p.user_id == f"service:{name}" and p.org_id == "default" and SP.is_service(p)
    assert SP.resolve(_req({SP.NAME_HEADER: name, SP.KEY_HEADER: key + "x"})) is None
    assert SP.resolve(_req({SP.NAME_HEADER: "nobody", SP.KEY_HEADER: key})) is None
    # the API's resolver: a service header present and wrong resolves NOTHING, even beside the header seam
    wrong = _req({SP.NAME_HEADER: name, SP.KEY_HEADER: "bad", authz.IDENTITY_ORG_HEADER: "default", authz.IDENTITY_USER_HEADER: "mallory"})
    assert authz.resolve_principal(wrong) is None
    good = authz.resolve_principal(_req({SP.NAME_HEADER: name, SP.KEY_HEADER: key}))
    assert good.user_id == f"service:{name}"
    from aughor.metastore.models import principal_kind
    assert principal_kind(f"service:{name}") == "service"
    # held to the agent policy whether or not it marked itself
    from aughor.rbac.agent_gate import is_agent_request
    assert is_agent_request(_req({}, principal=good)) and not is_agent_request(_req({}, principal=PERSON))
    assert SP.allowed_connection(name, "c1") and not SP.allowed_connection(name, "c2")
    # rotation is the same gesture; revocation closes the door and keeps the row
    _, key2 = SP.mint(name, org_id="default", by="user:ana")
    assert key2 != key and SP.resolve(_req({SP.NAME_HEADER: name, SP.KEY_HEADER: key})) is None
    assert SP.resolve(_req({SP.NAME_HEADER: name, SP.KEY_HEADER: key2})) is not None
    revoked = SP.revoke(name, by="user:ana", why="contract ended")
    assert revoked["active"] is False and SP.resolve(_req({SP.NAME_HEADER: name, SP.KEY_HEADER: key2})) is None
    with pytest.raises(SP.ServicePrincipalRefused, match="a person mints"):
        SP.mint("other", org_id="default", by="agent:analyst")
    with pytest.raises(SP.ServicePrincipalRefused, match="name is 2 to 63"):
        SP.mint("Bad Name", org_id="default", by="user:ana")


def test_the_door_mints_lists_and_revokes_and_an_agent_cannot_mint():
    name = "vendor-" + uuid.uuid4().hex[:6]
    out = R.mint_service_principal(R.ServicePrincipalIn(name=name, note="x"), principal=PERSON)
    assert out["key"] and out["present_as"][SP.NAME_HEADER] == name and out["created_by"] == "user:ana"
    assert any(p["name"] == name for p in R.list_service_principals()["principals"])
    service = authz.Principal(user_id=f"service:{name}", org_id="default")
    with pytest.raises(HTTPException) as e:
        R.mint_service_principal(R.ServicePrincipalIn(name="another"), principal=service)
    assert e.value.status_code == 403
    assert R.revoke_service_principal(name, why="done", principal=PERSON)["active"] is False


# ── posting claims ─────────────────────────────────────────────────────────────────────────

def _warrant():
    return [R.WarrantIn(kind="run", ref="rcpt-" + uuid.uuid4().hex[:6], detail="SELECT ...")]


def test_a_service_principal_posts_a_claim_with_its_warrant_and_the_laws_hold_at_the_door():
    conn, name = _conn(), "acme-" + uuid.uuid4().hex[:6]
    SP.mint(name, org_id="default", by="user:ana", connections=[conn])
    service = authz.Principal(user_id=f"service:{name}", org_id="default")
    body = R.ClaimIn(kind="observation", statement=R.StatementIn(text="Orders were 1,200 last week", metric="orders", value=1200),
                     tier="measured", about=R.AboutIn(kind="connection", key=conn), warrants=_warrant(), natural_key="orders-w40")
    view = R.post_claim(body, principal=service)
    assert view["author"] == f"service:{name}" and view["author_kind"] == "agent" and view["tier"] == "measured"
    assert view["extra"]["posted_via"] == "ledger_api" and view["restated"] is False and view["key"].startswith(f"claim:api:service:{name}:orders-w40")
    # no warrant at all → refused, whatever the tier
    with pytest.raises(HTTPException) as e:
        R.post_claim(R.ClaimIn(kind="said", statement=R.StatementIn(text="x"), about=R.AboutIn(kind="connection", key=conn)), principal=service)
    assert e.value.status_code == 422 and e.value.detail["code"] == "CLAIM_REFUSED" and "warrant" in e.value.detail["why"]
    # a person's tier → the claims' own law refuses it
    with pytest.raises(HTTPException) as e:
        R.post_claim(R.ClaimIn(kind="definition", statement=R.StatementIn(text="revenue is net of refunds"), tier="approved",
                               about=R.AboutIn(kind="connection", key=conn), warrants=_warrant()), principal=service)
    assert e.value.status_code == 422 and "person" in e.value.detail["why"]
    # measured without a run warrant → refused
    with pytest.raises(HTTPException) as e:
        R.post_claim(R.ClaimIn(kind="observation", statement=R.StatementIn(text="x"), tier="measured", about=R.AboutIn(kind="connection", key=conn),
                               warrants=[R.WarrantIn(kind="document", ref="doc-1")]), principal=service)
    assert "run warrant" in e.value.detail["why"]
    # a connection the principal was not minted for
    with pytest.raises(HTTPException) as e:
        R.post_claim(R.ClaimIn(kind="said", statement=R.StatementIn(text="x"), about=R.AboutIn(kind="connection", key=_conn()),
                               warrants=_warrant()), principal=service)
    assert e.value.status_code == 403 and e.value.detail["code"] == "AGENT_CONNECTION_DENIED"
    # restating under its own key is a new version; the same natural key from another author is that
    # author's own claim (the key carries the author), never a restatement of this one
    again = R.post_claim(body.model_copy(update={"statement": R.StatementIn(text="Orders were 1,310 last week", metric="orders", value=1310)}),
                         principal=service)
    assert again["restated"] is True and again["version"] == 2 and again["supersedes"] == view["id"]
    other = authz.Principal(user_id="service:rival", org_id="default")
    SP.mint("rival", org_id="default", by="user:ana")
    theirs = R.post_claim(body, principal=other)
    assert theirs["restated"] is False and theirs["version"] == 1 and theirs["key"].startswith("claim:api:service:rival:orders-w40")
    assert theirs["author"] == "service:rival" and R.read_claim(again["id"])["version"] == 2
    # reads: by author, by id, versions, and as recorded yesterday (before it existed)
    mine = R.read_claims(connection_id=conn, author=f"service:{name}")
    assert [c["id"] for c in mine] == [again["id"]]
    assert R.read_claim(again["id"])["statement"]["text"].startswith("Orders were 1,310")
    assert [v["version"] for v in R.read_claim_versions(view["id"])] == [2, 1]
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    assert R.read_claims(connection_id=conn, as_of=yesterday) == []
    # a person posts as a person; nobody (identity off) posts as the name given, an agent
    person = R.post_claim(R.ClaimIn(kind="said", statement=R.StatementIn(text="we said so"), about=R.AboutIn(kind="connection", key=conn),
                                    warrants=[R.WarrantIn(kind="attestation", ref="meeting-1")]), principal=PERSON)
    assert person["author"] == "user:ana" and person["author_kind"] == "person"
    nobody = R.post_claim(R.ClaimIn(kind="said", statement=R.StatementIn(text="a tool said so"), about=R.AboutIn(kind="connection", key=conn),
                                    warrants=_warrant(), author="tool:x"), principal=None)
    assert nobody["author"] == "tool:x" and nobody["author_kind"] == "agent"
    record = R.read_principal_record(f"service:{name}")
    assert record["n"] == 1 and record["by_kind"] == {"observation": 1} and record["restated"] == 1


# ── restatements, subscriptions, events out ────────────────────────────────────────────────

@pytest.fixture
def _webhooks(monkeypatch):
    """A public-looking URL and a webhook sink: the SSRF guard is a DNS resolution the sandbox cannot
    make, so it is answered here; `_post` is the one seam every send passes."""
    sent: list[dict] = []
    monkeypatch.setattr("aughor.util.url_guard.is_safe_webhook_url", lambda url: url.startswith("https://"))

    def _post(url, headers, payload):
        sent.append({"url": url, "headers": headers, "payload": payload})
        return 200, "", False, {}
    monkeypatch.setattr("aughor.notifications.executor._post", _post)
    return sent


def test_a_subscription_delivers_a_restatement_to_its_webhook_and_the_delivery_is_on_the_record(_webhooks):
    conn = _conn()
    sub = R.post_subscription(R.SubscriptionIn(url="https://hooks.example.com/aughor", kinds=["claim.restated", "outcome.booked"],
                                               connection_id=conn, headers={"Authorization": "Bearer s3cret"}), principal=PERSON)
    assert sub["active"] and sub["kinds"] == ["claim.restated", "outcome.booked"] and sub["headers"] == {"Authorization": "•••"}
    assert sub["url_host"] == "hooks.example.com" and sub["created_by"] == "user:ana"
    with pytest.raises(HTTPException) as e:
        R.post_subscription(R.SubscriptionIn(url="https://x.example.com", kinds=["claim.anything"]), principal=PERSON)
    assert e.value.status_code == 422 and "not subscribable" in e.value.detail
    with pytest.raises(HTTPException):
        R.post_subscription(R.SubscriptionIn(url="http://10.0.0.1/hook", kinds=["claim.restated"]), principal=PERSON)
    before = datetime.now(timezone.utc).isoformat()
    key = C.claim_key("observation", "answer", conn, "inv1")
    claim = C.Claim(kind="observation", tier="said", about=C.About(kind="connection", key=conn),
                    statement=C.Statement(text="Returns were 4% last week", metric="returns"), author="system", as_of="2026-10-01")
    first = C.book(claim, key=key, conn_id=conn)
    assert _webhooks == []                                   # a first booking is no restatement
    restated = claim.model_copy(deep=True)
    restated.statement = C.Statement(text="Restated: returns were 5% last week", metric="returns")
    second = C.book(restated, key=key, conn_id=conn)
    assert len(_webhooks) == 1
    body = _webhooks[0]["payload"]
    assert body["source"] == "aughor" and body["headline"] == "claim.restated" and _webhooks[0]["headers"]["Authorization"] == "Bearer s3cret"
    assert body["context"]["event"] == "claim.restated" and body["context"]["claim_id"] == second and body["context"]["supersedes"] == first
    assert body["context"]["connection_id"] == conn and body["recommendation"].startswith("Restated:")
    # the pull side: restatements since a cursor, with what was replaced
    out = R.read_restatements(since=before, connection_id=conn)
    assert [r["claim"]["id"] for r in out["restatements"]] == [second] and out["restatements"][0]["replaced"] == "Returns were 4% last week"
    assert out["cursor"] and R.read_restatements(since=out["cursor"], connection_id=conn)["restatements"] == []
    # the journal and the delivery record
    events = R.read_events(kind="claim.restated", connection_id=conn)["events"]
    assert events and events[0]["payload"]["claim_id"] == second
    delivered = [e for e in R.read_events(kind="ledger.delivered", connection_id=conn)["events"] if e["payload"]["subscription"] == sub["id"]]
    assert delivered and delivered[0]["payload"]["status"] == "ok" and delivered[0]["payload"]["http_status"] == 200
    assert delivered[0]["payload"]["departure"] and body["context"]["receipt"]["departure_id"] == delivered[0]["payload"]["departure"]
    assert body["context"]["receipt"]["guards"]["attention"] == "exempt" and body["context"]["receipt_line"]
    with pytest.raises(HTTPException):
        R.read_events(kind="not.a.kind")
    # the departure gate judges every delivery: the same entry again is "never the same finding twice" — held, and said
    third = C.book(restated, key=key, conn_id=conn)
    assert len(_webhooks) == 1
    held = [e for e in R.read_events(kind="ledger.delivered", connection_id=conn)["events"] if e["payload"]["subscription"] == sub["id"]][0]
    assert held["payload"]["status"] == "held" and "never the same finding twice" in held["payload"]["why"] and third
    from aughor.govern.departure import ATTENTION_POLICY
    from aughor.govern.departure_store import list_departures
    rows = [d for d in list_departures(limit=50, kind=S.DEPARTURE_KIND) if d.get("actor") == f"subscription:{sub['id']}"]
    assert {d["state"] for d in rows} == {"departed", "held"} and all(d["kind"] == S.DEPARTURE_KIND for d in rows)
    assert S.DEPARTURE_KIND in ATTENTION_POLICY
    # a subscription to another connection is not fired; a withdrawn one is not either
    R.post_subscription(R.SubscriptionIn(url="https://elsewhere.example.com/h", kinds=["claim.restated"], connection_id=_conn()), principal=PERSON)
    gone = R.delete_subscription(sub["id"], principal=PERSON)
    assert gone["active"] is False and gone["withdrawn_by"] == "user:ana"
    assert sub["id"] not in {s["id"] for s in R.read_subscriptions(active=True)["subscriptions"]}
    restated.statement = C.Statement(text="Restated again: 6%", metric="returns")
    C.book(restated, key=key, conn_id=conn)
    assert len(_webhooks) == 1
    assert S.notify("claim.restated", {"id": "x"}, conn_id=conn) == []


def test_the_export_is_json_lines_and_the_contract_door_serves_the_contract():
    conn = _conn()
    C.book(C.Claim(kind="said", tier="said", about=C.About(kind="connection", key=conn), statement=C.Statement(text="exported"),
                   author="system"), key=C.claim_key("said", conn, "e1"), conn_id=conn)
    lines = list(R.export_lines(["claim"], conn, 100))
    rows = [json.loads(line) for line in lines]
    assert rows and rows[0]["kind"] == "claim" and rows[0]["payload"]["statement"]["text"] == "exported" and rows[0]["conn_id"] == conn
    resp = R.export_ledger(connection_id=conn)
    assert resp.media_type == "application/x-ndjson" and "aughor-ledger.jsonl" in resp.headers["content-disposition"]
    assert R.read_contract()["version"] == "2027.1" and len(R.read_contract()["duties"]) == 7
    cat = R.read_event_catalogue()
    assert any(k["kind"] == "claim.restated" and k["subscribable"] for k in cat["kinds"]) and "outcome.booked" in cat["subscribable"]
