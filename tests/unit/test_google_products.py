"""Google's products, each its own card (2026-10-07).

The user wanted Gmail, Sheets, Slides, Drive and Calendar as separate cards, each opening
Google's consent for that product alone. Google is one app and one grant per person, so a
card asks for its own scope with `include_granted_scopes` and the grant grows a product at a
time — one record, one id, which an automation naming it keeps.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from aughor.integrations import broker, store
from aughor.integrations.operations import extract, get_operation

GMAIL = "https://www.googleapis.com/auth/gmail.readonly"
SHEETS = "https://www.googleapis.com/auth/spreadsheets.readonly"


@pytest.fixture(autouse=True)
def _virgin_stores():
    for s in (store._APPS, store._CONNS, store._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])
    yield
    for s in (store._APPS, store._CONNS, store._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])


def _consent(client, monkeypatch, product: str, granted: str, n: int) -> dict:
    """Press a product card's Connect, then come back from Google having granted ``granted``."""
    url = client.post(f"/integrations/google/connect?product={product}").json()["authorize_url"]
    query = parse_qs(urlparse(url).query)
    monkeypatch.setattr(broker, "_post", lambda *a, **k: {
        "access_token": f"at-{n}", "refresh_token": f"rt-{n}", "expires_in": 3600,
        "scope": granted, "token_type": "Bearer", "_status": 200})
    assert client.get(f"/oauth/callback?state={query['state'][0]}&code=c{n}").status_code == 200
    return query


def _products(client) -> dict:
    google = next(p for p in client.get("/integrations/catalog").json()["providers"] if p["id"] == "google")
    return {p["id"]: p for p in google["products"]}


def test_each_card_asks_only_for_its_product_and_grows_one_grant(client, monkeypatch):
    client.put("/integrations/google/app", json={"client_id": "cid-1", "client_secret": "cs-1"})
    assert not any(p["connected"] for p in _products(client).values())

    asked = _consent(client, monkeypatch, "gmail", f"openid email {GMAIL}", 1)
    assert set(asked["scope"][0].split()) == {"openid", "email", GMAIL}
    assert asked["include_granted_scopes"] == ["true"]
    first = client.get("/integrations/connections").json()["connections"]

    # Google answers the second consent with every scope the grant now covers.
    asked = _consent(client, monkeypatch, "sheets", f"openid email {GMAIL} {SHEETS}", 2)
    assert set(asked["scope"][0].split()) == {"openid", "email", SHEETS}
    after = client.get("/integrations/connections").json()["connections"]
    assert [c["id"] for c in after] == [c["id"] for c in first], "one grant, grown — not a second"

    products = _products(client)
    assert products["gmail"]["connected"] and products["sheets"]["connected"]
    assert not products["slides"]["connected"]
    assert products["sheets"]["tools"] == ["Sheets · read a range"]
    assert client.post("/integrations/google/connect?product=photos").status_code == 404


def test_a_slides_text_is_gathered_slide_by_slide():
    """A slide's words sit under its page elements' text runs; a tool that published the
    nesting would hand a later step a tree to walk instead of the slide's text."""
    deck = {"title": "Q3 review", "slides": [
        {"objectId": "p1", "pageElements": [
            {"shape": {"text": {"textElements": [{"paragraphMarker": {}},
                                                 {"textRun": {"content": "Revenue up 12%\n"}},
                                                 {"textRun": {"content": "Churn flat\n"}}]}}},
            {"image": {"contentUrl": "https://example.com/chart.png"}}]},
        {"objectId": "p2", "pageElements": []}]}
    assert extract(get_operation("slides.presentations.get"), deck) == {
        "items": [{"objectId": "p1", "text": "Revenue up 12%\nChurn flat"},
                  {"objectId": "p2", "text": ""}],
        "count": 2, "title": "Q3 review"}
