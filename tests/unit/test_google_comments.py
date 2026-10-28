"""Comments on a Google file, read onto a decision (the decision-framework study §3.2; the user's call of 2026-10-27;
`aughor/record/google_comments.py`, `POST /record/decisions/{id}/google-file`).

What these hold, with Google's answer faked at the call seam: a Sheets, Slides, Docs or Drive link names a file and
nothing else does; while the install has no Google OAuth client, or the person no grant that may read comments, the
decision says which where the file would be named and a read is refused with the same sentence; the ONE named file is read — never another — and each comment becomes a said claim in its
author's name with the cell or quoted text it points at, added to the decision as later evidence; reading again adds
nothing new, and an edited comment restates its claim; Google's refusal is said.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from aughor.integrations.call import CallResult
from aughor.record import byproducts as B
from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.record import google_comments as G

FILE = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abc"
LINK = f"https://docs.google.com/spreadsheets/d/{FILE}/edit#gid=0"


def _comments(content_first: str = "Paid social is 14% of September orders — pausing it is too risky."):
    return [
        {"id": "c1", "author": {"displayName": "Ana", "emailAddress": "ana@corp.example"}, "content": content_first,
         "createdTime": "2026-08-20T10:00:00Z", "modifiedTime": "2026-08-20T10:00:00Z", "resolved": False,
         "quotedFileContent": {"value": "Paid social · September"}},
        {"id": "c2", "author": {"displayName": "Ben"}, "content": "Agree with pausing; YOOX held without it.",
         "createdTime": "2026-08-21T09:00:00Z", "anchor": "{\"r\":\"head\",\"a\":[{\"cell\":\"C7\"}]}"},
    ]


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple] = []
    state = {"items": _comments(), "status": "executed"}

    def fake(grant, op, params, *, actor="", approved=False):
        seen.append((grant, op, dict(params)))
        if state["status"] != "executed":
            return CallResult(state["status"], "insufficient permissions for this file")
        return CallResult("executed", "", {"items": state["items"], "count": len(state["items"]), "next_page_token": ""})
    import aughor.integrations.call as call_mod
    monkeypatch.setattr(call_mod, "call_operation", fake)
    return seen, state


def _decision() -> D.Decision:
    did = B.declare_decision(question="Pause paid social on Mytheresa?", chosen="pause it",
                             connection_id="conn-" + uuid.uuid4().hex[:6], decided_by="user:amit")
    return D.get_decision(did)


def test_a_link_names_a_google_file_and_nothing_else_does():
    for link in (LINK, f"https://docs.google.com/presentation/d/{FILE}/edit", f"https://docs.google.com/document/d/{FILE}/",
                 f"https://drive.google.com/file/d/{FILE}/view", f"https://drive.google.com/open?id={FILE}"):
        assert G.file_id_of(link) == FILE, link
    assert G.file_id_of("https://example.com/spreadsheets/notes") == ""


def test_the_comments_card_asks_for_the_scope_the_read_needs():
    from aughor.integrations.operations import get_operation
    from aughor.integrations.providers import PROVIDERS
    card = PROVIDERS["google"].product("comments")
    assert card is not None and get_operation(G.OPERATION).scopes == (card.scopes,)


def test_the_named_file_is_read_onto_the_decision_as_later_evidence_and_never_another(calls):
    seen, _state = calls
    d = _decision()
    out = G.read_onto(d.id, LINK, user_id="", grant="g-1")
    assert seen == [("g-1", G.OPERATION, {"file_id": FILE})]                       # one read, the named file only
    assert out["read"] == 2 and out["new"] == 2 and out["already_held"] == 0
    now = D.latest_decision(d.source)
    ev = now.extra["evidence"]
    assert [e["ref"] for e in ev] == [f"gdrive:{FILE}:c1", f"gdrive:{FILE}:c2"] and all(e["added_later"] for e in ev)
    assert now.relied_on == d.relied_on and now.extra["google_files"] == [FILE]
    ana = C.get(ev[0]["claim"])
    assert ana.kind == "said" and ana.author == "person:ana@corp.example" and ana.extra["locator"] == "on “Paid social · September”"
    assert ana.warrants[0].kind == "conversation" and len(ana.warrants[0].content_hash) == 64
    assert C.get(ev[1]["claim"]).author == "person:Ben" and C.get(ev[1]["claim"]).extra["locator"].startswith("at ")


def test_reading_again_adds_nothing_new_and_an_edited_comment_restates_its_claim(calls):
    _seen, state = calls
    d = _decision()
    G.read_onto(d.id, LINK, user_id="", grant="g-1")
    first = C.latest(C.claim_key("said", "gdrive", FILE, "c1"))
    state["items"] = _comments("Paid social is 14% of September orders — but pause it for two weeks only.")
    again = G.read_onto(d.id, LINK, user_id="", grant="g-1")
    assert again["new"] == 0 and again["already_held"] == 2
    now = C.latest(C.claim_key("said", "gdrive", FILE, "c1"))
    assert now.id != first.id and "two weeks only" in now.statement.text
    assert len(D.latest_decision(d.source).extra["evidence"]) == 2


NO_CLIENT = "Not set up yet: this install has no Google OAuth client. Add it in Operations → Integrations → Google → Set up."
NO_GRANT = "Connect the Google Drive comments card first, in Operations → Integrations → Google."


def test_what_is_missing_is_said_the_client_first_then_the_grant(monkeypatch):
    import aughor.integrations.store as store
    from aughor.integrations.models import ProviderApp
    apps: dict = {}
    monkeypatch.setattr(store, "get_app", lambda provider_id: apps.get(provider_id))
    monkeypatch.setattr(G, "grant_for", lambda user_id: None)
    assert G.client_set_up() is False and G.missing("user:amit") == NO_CLIENT
    apps["google"] = ProviderApp(id="google", client_id="")                 # a row with no client is no client
    assert G.client_set_up() is False and G.missing("user:amit") == NO_CLIENT
    apps["google"] = ProviderApp(id="google", client_id="1-a.apps.googleusercontent.com")
    assert G.client_set_up() is True and G.missing("user:amit") == NO_GRANT
    monkeypatch.setattr(G, "grant_for", lambda user_id: "g-1")
    assert G.missing("user:amit") == ""


def test_no_client_no_grant_no_file_and_googles_refusal_are_each_said(calls, monkeypatch):
    _seen, state = calls
    d = _decision()
    monkeypatch.setattr(G, "grant_for", lambda user_id: None)
    monkeypatch.setattr(G, "client_set_up", lambda: False)
    with pytest.raises(G.CommentsRefused) as e:
        G.read_onto(d.id, LINK, user_id="user:amit")
    assert e.value.status == 409 and str(e.value) == NO_CLIENT
    monkeypatch.setattr(G, "client_set_up", lambda: True)
    with pytest.raises(G.CommentsRefused) as e:
        G.read_onto(d.id, LINK, user_id="user:amit")
    assert e.value.status == 409 and str(e.value) == NO_GRANT
    with pytest.raises(G.CommentsRefused, match="names no Google file"):
        G.read_onto(d.id, "https://example.com/x", user_id="", grant="g-1")
    state["status"] = "failed"
    with pytest.raises(G.CommentsRefused, match="insufficient permissions") as e:
        G.read_onto(d.id, LINK, user_id="", grant="g-1")
    assert e.value.status == 502


def test_the_decision_says_what_is_missing_and_the_route_refuses_with_it_then_reads(calls, monkeypatch):
    from aughor.routers import record as R
    d = _decision()
    monkeypatch.setattr(R, "_who", lambda principal: "user:amit")
    monkeypatch.setattr(R, "_visible", lambda conn_id: True)
    monkeypatch.setattr(G, "client_set_up", lambda: False)
    monkeypatch.setattr(G, "grant_for", lambda user_id: None)
    assert R.get_record_decision(d.id)["google"] == {"files": [], "missing": NO_CLIENT}
    with pytest.raises(HTTPException) as e:
        R.read_google_file_onto_decision(d.id, R.GoogleFileRequest(link=LINK), principal=None)
    assert e.value.status_code == 409 and e.value.detail == NO_CLIENT
    monkeypatch.setattr(G, "client_set_up", lambda: True)
    monkeypatch.setattr(G, "grant_for", lambda user_id: "g-1")
    out = R.read_google_file_onto_decision(d.id, R.GoogleFileRequest(link=LINK), principal=None)
    assert out["new"] == 2 and out["by"] == "user:amit"
    assert R.get_record_decision(out["decision"])["google"] == {"files": [FILE], "missing": ""}
