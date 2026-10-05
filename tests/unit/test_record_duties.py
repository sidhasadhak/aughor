"""The week by duty (`aughor/record/duties.py`, the 2027 study §V screen 8) — a fold over the ledger.

What this holds: a claim is counted under the duty that books its kind and is warranted only above
`said`; a run's typed verdict is Inquire's and every verdict but `answered` is a failure by its
type; an execution is Operate's, warranted when its verification passed; nothing booked before
``since`` is counted; and a duty that carries no metered cost says so instead of reading zero.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from aughor.actions import authority as A
from aughor.record import claims as C
from aughor.record import duties as DU
from aughor.record import inquiry as I
from aughor.routers import record as R


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _claim(conn: str, kind: str, tier: str, n: int, **kw) -> str:
    claim = C.Claim(kind=kind, tier=tier, about=C.About(kind="connection", key=conn),
                    statement=C.Statement(text=f"{kind} {n}"), as_of="2026-10-01", author="user:ana",
                    author_kind="person", **kw)
    return C.book(claim, key=C.claim_key(kind, conn, str(n)), conn_id=conn)


def test_each_duty_counts_what_it_books_and_says_what_is_not_metered():
    conn = _conn()
    _claim(conn, "observation", "said", 1)
    _claim(conn, "definition", "declared", 2)
    I.book_run_verdict("r1", kind="answered", why="ok", connection_id=conn)
    I.book_run_verdict("r2", kind="no_data", why="the table is empty", connection_id=conn)
    I.book_run_verdict("r3", kind="contradicted", why="a promotion overlapped", connection_id=conn)
    # the entry reads the declaration's id, kind, reversibility and undo — nothing else of it
    action = SimpleNamespace(id="refund", kind="side_effect", reversibility="irreversible", undo=None)
    A.book_action(action=action, params={"order_id": "1"}, scope=conn, actor="user:ana", status="ok", outcome={},
                  verification={"status": "passed"})
    A.book_action(action=action, params={"order_id": "2"}, scope=conn, actor="user:ana", status="ok", outcome={},
                  verification={"status": "failed", "why": "not visible"})

    out = DU.week_by_duty(since="2000-01-01", conn_id=conn)
    by = {d["duty"]: d for d in out["duties"]}
    assert [d["duty"] for d in out["duties"]] == ["Observe", "Inquire", "Challenge", "Forecast", "Steward", "Operate", "Deliver"]
    assert (by["Observe"]["entries"], by["Observe"]["warranted"]) == (1, 0)        # said: counted, not warranted
    assert (by["Steward"]["entries"], by["Steward"]["warranted"]) == (1, 1)        # declared by a person
    assert by["Inquire"]["runs"] == 3 and by["Inquire"]["failures"] == {"no_data": 1, "contradicted": 1}
    assert by["Inquire"]["cost"]["tokens"] is None and "no run this period carries a receipt" in by["Inquire"]["cost"]["note"]
    assert (by["Operate"]["entries"], by["Operate"]["warranted"]) == (2, 1)
    assert by["Operate"]["failures"] == {"verification_failed": 1}
    assert by["Observe"]["runs"] is None and "not metered" in by["Observe"]["cost"]["note"]
    assert out["failures_by_type"]["no_data"] == 1 and out["failures_by_type"]["verification_failed"] == 1
    # nothing booked before `since` is counted, and the door serves the same fold
    later = R.record_duties(connection_id=conn, since="2999-01-01")
    assert all(d["entries"] == 0 and not d["failed"] for d in later["duties"] if d["duty"] != "Deliver")
    assert next(d for d in later["duties"] if d["duty"] == "Inquire")["runs"] == 0
