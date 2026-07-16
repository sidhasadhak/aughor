"""R10 — purpose persistence, deterministic canvas auto-name, THUMBS→priors.

The Databricks analogs: request_purpose tags every call (ours rides the run row
+ the kernel job payload), generate_space_name derives a canvas name at create
(deterministic-first; the LLM suggest-name endpoint stays the richer client
path), and thumbs feedback closes into the learned table prior — the same
counter overview drills and R14 query popularity already feed.

Hermetic: history/drills stores ride the conftest temp overrides.
"""
from __future__ import annotations

from aughor.db.history import create_investigation, get_investigation, save_chat_turn


# ── purpose persistence ──────────────────────────────────────────────────────

def test_investigation_row_carries_purpose():
    inv_id = create_investigation("why is X down?", "connP", purpose="outlier_scan")
    row = get_investigation(inv_id)
    assert row["purpose"] == "outlier_scan"


def test_free_typed_runs_default_to_empty_purpose():
    inv_id = create_investigation("why is X down?", "connP")
    assert get_investigation(inv_id)["purpose"] == ""


def test_chat_turn_carries_purpose():
    turn_id = save_chat_turn(
        question="top brands?", connection_id="connP", headline="Brand A leads",
        sql="SELECT 1", tables_used=["sales"], purpose="curated_question")
    assert get_investigation(turn_id)["purpose"] == "curated_question"


# ── canvas auto-name (generate_space_name analog, deterministic) ─────────────

def test_canvas_autoname_from_table(client):
    r = client.post("/canvases", json={"connection_id": "fixture",
                                       "tables": ["main.flight_bookings"]})
    assert r.status_code == 201
    assert r.json()["name"] == "Flight Bookings Canvas"


def test_canvas_autoname_from_schema(client):
    r = client.post("/canvases", json={"connection_id": "fixture",
                                       "schema_name": "airlines"})
    assert r.status_code == 201
    assert r.json()["name"] == "Airlines Canvas"


def test_canvas_explicit_name_always_wins(client):
    r = client.post("/canvases", json={"name": "My Board", "connection_id": "fixture",
                                       "tables": ["sales"]})
    assert r.status_code == 201
    assert r.json()["name"] == "My Board"


# ── THUMBS→priors ────────────────────────────────────────────────────────────

def test_helpful_thumbs_bumps_table_priors(client):
    from aughor.overview.drills import load_priors
    turn_id = save_chat_turn(
        question="revenue by brand?", connection_id="connT", headline="…",
        sql="SELECT 1", tables_used=["main.sales", "orders"])

    before = load_priors("connT")["table"]
    r = client.post("/chat/feedback", json={"conn_id": "connT", "turn_id": turn_id,
                                            "verdict": "helpful"})
    assert r.status_code == 200
    after = load_priors("connT")["table"]
    assert after.get("sales", 0) == before.get("sales", 0) + 1     # bare table name
    assert after.get("orders", 0) == before.get("orders", 0) + 1


def test_unhelpful_thumbs_never_decrements(client):
    from aughor.overview.drills import load_priors
    turn_id = save_chat_turn(
        question="q", connection_id="connU", headline="…",
        sql="SELECT 1", tables_used=["sales"])
    client.post("/chat/feedback", json={"conn_id": "connU", "turn_id": turn_id,
                                        "verdict": "helpful"})
    base = load_priors("connU")["table"].get("sales", 0)
    r = client.post("/chat/feedback", json={"conn_id": "connU", "turn_id": turn_id,
                                            "verdict": "unhelpful"})
    assert r.status_code == 200
    assert load_priors("connU")["table"].get("sales", 0) == base   # monotone counter


def test_thumbs_on_unknown_turn_is_fail_open(client):
    r = client.post("/chat/feedback", json={"conn_id": "connT", "turn_id": "nope",
                                            "verdict": "helpful"})
    assert r.status_code == 200 and r.json() == {"ok": True}
