"""Home's three doors: what is already on record for a question, what a person said, and their record.

Measured 2026-10-05 on the user's install: "Which 10 product categories brought in the most revenue
in the last 6 months…" ran 13 times in two days as deep runs, and nothing told the person it was
answered; the recall that exists (`find_prior_answers`) reads quick answers only and feeds the model.
A `said` claim could be booked only from a filed Slack reply.
"""
from __future__ import annotations

import pytest

Q = "Which 10 product categories brought in the most revenue in the last 6 months?"


def _answered(question: str, conn: str, headline: str) -> str:
    from aughor.db import history
    iid = history.create_investigation(question, conn)
    history.complete_investigation(iid, {"headline": headline}, [], [])
    return iid


def test_a_question_asked_before_says_how_often_and_the_newest_answer():
    from aughor.db.history import asked_before
    _answered(Q, "c-home", "Outerwear & Coats led, with $229,793.89")
    _answered(Q.upper() + "  ", "c-home", "Outerwear & Coats still led")
    _answered(Q, "c-other", "another connection's answer")
    _answered("A different question", "c-home", "unrelated")
    got = asked_before(Q.lower(), "c-home")
    assert got["count"] == 2
    assert got["latest"]["headline"] == "Outerwear & Coats still led"
    assert got["first_at"] <= got["last_at"]


def test_nothing_on_record_is_said_as_nothing():
    from aughor.db.history import asked_before
    assert asked_before("never asked here", "c-home") == {"count": 0, "first_at": "", "last_at": "", "latest": None}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from aughor.api import app
    return TestClient(app)


def test_the_prior_door_reads_without_running_anything(client):
    _answered(Q, "builtin", "Outerwear & Coats led")
    r = client.get("/ask/prior", params={"connection_id": "builtin", "question": Q})
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1


def test_a_person_answer_is_booked_as_theirs_and_restated_not_duplicated(client):
    body = {"connection_id": "builtin", "text": "A campaign", "about": "inv-aug",
            "asked": "August revenue rose 13.2%. Did the team do anything that explains it?", "by": "Amit"}
    first = client.post("/record/claims/said", json=body)
    assert first.status_code == 201, first.text
    assert first.json()["kind"] == "said" and first.json()["author"] == "person:Amit"
    again = client.post("/record/claims/said", json={**body, "text": "A price change"})
    assert again.status_code == 201
    assert again.json()["supersedes"] == first.json()["id"]
    you = client.get("/record/you", params={"by": "Amit"}).json()
    assert you["principal"] == "person:Amit" and you["by_kind"].get("said", 0) >= 1


def test_an_unnamed_answer_is_refused_and_an_unnamed_reader_has_no_record(client):
    r = client.post("/record/claims/said", json={"connection_id": "builtin", "text": "A campaign"})
    assert r.status_code == 422
    assert client.get("/record/you").json()["n"] == 0
