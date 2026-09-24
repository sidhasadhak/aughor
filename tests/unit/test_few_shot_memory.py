"""PENDING item 24 — the few-shot memory learns from every good answer and forgets bad ones.

The memory (`aughor/tools/prior_analyses.py`) is the self-improving loop that exists without training: past SQL
offered to the SQL writer as examples. Measured 2026-09-24 by reading: only deep runs wrote to it, never a quick answer
or a chat turn; a query a person rejected stayed an example forever; nothing checked the guards; every deep sub-query
was filed under the top-level question though the writer searches by hypothesis; deleting an investigation left its
SQL behind; and a dead vector store or embedder read exactly like "nothing similar was ever asked".

Against the REAL embedded vector store (conftest points it at a temp path); the one stand-in is the embedder — a
hashed bag of words over the text's first line (the question), deterministic and similarity-bearing.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
import uuid

import pytest

from aughor.feedback.verdicts import record_verdict
from aughor.tools import prior_analyses as pa


def _vector(text: str) -> list[float]:
    v = [0.0] * 768
    for word in re.findall(r"\w+", text.split("\n", 1)[0].lower()):
        v[int(hashlib.sha1(word.encode()).hexdigest(), 16) % 768] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


@pytest.fixture()
def memory(monkeypatch):
    monkeypatch.setattr("aughor.semantic.embedder.embed", lambda texts: [_vector(t) for t in texts])
    monkeypatch.setattr(pa, "_ENABLED", True)
    pa._LAST_SAID.clear()
    return f"conn-{uuid.uuid4().hex[:8]}"       # every test its own connection: the store is shared


def _answer(conn: str, question: str, sql: str, *, receipts=(), caveats=(), rows=((1,),)) -> str:
    from aughor.db.history import attach_envelope, save_chat_turn
    turn = save_chat_turn(question=question, connection_id=conn, headline="h", sql=sql, columns=["n"],
                          rows=[list(r) for r in rows])
    attach_envelope(turn, {"question": question, "headline": "h", "caveats": list(caveats),
                           "provenance": {"connection_id": conn, "guard_receipts": list(receipts)}})
    return turn


def _offered(conn: str, question: str) -> str:
    block, note = pa.search_sql_examples_checked(question, conn)
    assert note == "", note
    return block


# ── every good answer ─────────────────────────────────────────────────────────────────────

def test_a_quick_answer_is_remembered_and_offered_to_the_next_question(memory):
    sql = "SELECT COUNT(*) FROM orders WHERE ship_month = 5"
    assert pa.index_answer(_answer(memory, "how many orders shipped in May?", sql)) is True
    assert sql in _offered(memory, "how many orders shipped in May?")


def test_an_answer_the_reader_was_warned_about_is_not_remembered(memory):
    flagged = _answer(memory, "what is revenue by store?", "SELECT store, SUM(x) FROM a JOIN b USING (id) GROUP BY 1",
                      receipts=[{"guard": "fanout_detected", "action": "flagged", "detail": "fans out"}])
    caveated = _answer(memory, "what is the margin by brand?", "SELECT brand, AVG(m) FROM p GROUP BY 1",
                       caveats=["an average of ratios"])
    empty = _answer(memory, "which orders came from Mars?", "SELECT * FROM orders WHERE planet = 'Mars'", rows=())
    assert [pa.index_answer(t) for t in (flagged, caveated, empty)] == [False, False, False]
    assert _offered(memory, "what is revenue by store?") == ""


def test_a_follow_up_does_not_stand_alone_so_it_is_not_an_example(memory):
    assert pa.index_answer(_answer(memory, "now break that down by region", "SELECT region FROM t")) is False


def test_a_deep_run_files_each_query_under_its_hypothesis(memory):
    """The SQL writer searches a hypothesis's SQL by the hypothesis's text; the examples were filed under the run's
    question, so a sub-query was never found by what it answered."""
    from aughor.control_plane.contracts.execution import QueryResult
    north = QueryResult(hypothesis_id="h1", sql="SELECT SUM(amount) FROM orders WHERE region = 'north'",
                        columns=["s"], rows=[[1]], row_count=1)
    flagged = QueryResult(hypothesis_id="h2", sql="SELECT AVG(r) FROM a JOIN b USING (k)", columns=["a"],
                          rows=[[1]], row_count=1, caveats=["the join fans out"])
    pa.index_sql_examples("inv-deep", "why did revenue fall last quarter?", [north, flagged], memory,
                          hypotheses=[{"id": "h1", "description": "orders fell in the north region"},
                                      {"id": "h2", "description": "the average basket shrank"}])
    assert north.sql in _offered(memory, "orders fell in the north region")
    assert "Q: orders fell in the north region" in _offered(memory, "orders fell in the north region")
    assert _offered(memory, "the average basket shrank") == ""          # a guard flagged it


def test_a_direct_run_teaches_examples_but_is_not_a_cached_investigation(memory):
    from aughor.agent.bootstrap import _register_ingest_sinks
    from aughor.db.history import complete_investigation, create_investigation
    _register_ingest_sinks()
    run = create_investigation("how many stores are open?", memory)
    complete_investigation(run, report={"headline": "412 stores"}, hypotheses=[],
                           query_history=[{"sql": "SELECT COUNT(*) FROM stores WHERE open", "row_count": 1,
                                           "columns": ["n"]}],
                           question="how many stores are open?", connection_id=memory, cache=False)
    assert "SELECT COUNT(*) FROM stores WHERE open" in _offered(memory, "how many stores are open?")
    assert pa.find_similar_investigation("how many stores are open?", memory) is None


# ── and forgets bad ones ──────────────────────────────────────────────────────────────────

def test_a_rejected_answer_is_forgotten_and_never_comes_back(memory):
    question, sql = "how many customers churned?", "SELECT COUNT(*) FROM customers WHERE churned"
    turn = _answer(memory, question, sql)
    assert pa.index_answer(turn)
    record_verdict(memory, turn, "reject", note="churn is defined by 90 days of silence")
    assert _offered(memory, question) == ""
    from aughor.semantic.vector_store import scroll_payloads
    assert not [p for p in scroll_payloads(pa.SQL_EXAMPLES_COLLECTION) if p.get("inv_id") == turn], \
        "the verdict did not evict the point (the read-time tombstone only hid it)"
    # the same query answered again, and the answer re-filed: the tombstone holds on write
    assert pa.index_answer(_answer(memory, question, sql)) is False
    assert pa.index_answer(turn) is False
    assert _offered(memory, question) == ""


def test_a_rejected_run_of_many_queries_is_not_re_remembered(memory):
    """A run that issued several queries has no single query its verdict rests on, so no SQL is tombstoned — the
    ANSWER is: re-indexing it (a reindex, a re-ingest) writes nothing."""
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.db.history import complete_investigation, create_investigation
    run = create_investigation("why did margin fall?", memory)
    queries = [QueryResult(hypothesis_id="h", sql=f"SELECT {c} FROM margins", columns=["m"], rows=[[1]], row_count=1)
               for c in ("gross", "net")]
    complete_investigation(run, report={"headline": "costs rose"}, hypotheses=[], query_history=queries,
                           question="why did margin fall?", connection_id=memory, skip_index=True)
    record_verdict(memory, run, "reject", note="the cost column is in cents")
    pa.index_sql_examples(run, "why did margin fall?", queries, memory)
    from aughor.semantic.vector_store import scroll_payloads
    assert not [p for p in scroll_payloads(pa.SQL_EXAMPLES_COLLECTION) if p.get("inv_id") == run]


def test_the_tombstone_holds_on_read_when_eviction_did_not_happen(memory, monkeypatch):
    """Points written before this change, or whose eviction failed: the verdict — not the point's absence — is the
    authority, so a search refuses them too."""
    question, sql = "what was the refund rate?", "SELECT AVG(refunded) FROM orders"
    turn = _answer(memory, question, sql)
    assert pa.index_answer(turn)
    monkeypatch.setattr(pa, "forget_answer", lambda inv_id: 0)
    record_verdict(memory, turn, "correct", sql_source=sql, corrected_sql="SELECT AVG(refunded::INT) FROM orders")
    assert _offered(memory, question) == ""


def test_a_later_accept_lifts_the_tombstone(memory):
    question, sql = "how many returns in June?", "SELECT COUNT(*) FROM returns WHERE month = 6"
    turn = _answer(memory, question, sql)
    record_verdict(memory, turn, "reject", sql_source=sql)
    record_verdict(memory, turn, "accept", sql_source=sql)       # a person may change their mind
    assert pa.index_answer(turn) is True
    assert sql in _offered(memory, question)


def test_deleting_an_investigation_forgets_every_example_it_taught(memory):
    from aughor.agent.bootstrap import _qdrant_inv
    turn = _answer(memory, "how many suppliers ship late?", "SELECT COUNT(*) FROM suppliers WHERE late")
    assert pa.index_answer(turn)
    assert _qdrant_inv([turn])["qdrant_points"] >= 1
    assert _offered(memory, "how many suppliers ship late?") == ""


# ── an unreachable memory is said ─────────────────────────────────────────────────────────

def test_a_dead_embedder_is_said_not_read_as_nothing_similar(memory, monkeypatch):
    def down(texts):
        raise ConnectionError("connection refused")
    monkeypatch.setattr("aughor.semantic.embedder.embed", down)
    block, note = pa.search_sql_examples_checked("how many orders shipped in May?", memory)
    assert block == "" and note.startswith("past SQL was not searched: the embedding service did not answer")
    from aughor.agent.grounding import build_grounding_context
    ctx = build_grounding_context("how many orders shipped in May?", memory).to_dict()
    (examples,) = [b for b in ctx["blocks"] if b["key"] == "sql_examples"]
    assert examples["present"] is False and "embedding service did not answer" in examples["note"]


def test_no_vector_store_at_all_is_said_too(memory, monkeypatch):
    monkeypatch.setattr("aughor.semantic.vector_store.available", lambda: False)
    assert pa.search_sql_examples_checked("anything", memory)[1] == (
        "past SQL was not searched: no vector store is configured on this deployment")


def test_a_searched_memory_with_nothing_similar_says_nothing(memory):
    assert pa.search_sql_examples_checked("a question nobody has asked here", memory) == ("", "")


def test_a_dead_memory_is_counted_every_time_and_logged_once_a_minute(memory, monkeypatch):
    from aughor.stats import stats
    told: list[str] = []
    monkeypatch.setattr("aughor.kernel.errors.tolerate", lambda exc, reason, **kw: told.append(reason))
    monkeypatch.setattr("aughor.semantic.vector_store.available", lambda: False)
    counted = lambda: stats.snapshot()["counters"].get("tolerated.prior_analyses.search_failed", 0)  # noqa: E731
    before = counted()
    for _ in range(5):
        pa.search_sql_examples("anything", memory)
    assert len(told) == 1, told                       # logged and journalled once (tolerate counts that one)…
    assert counted() - before == 4                    # …and every other miss is still counted


# ── the quick path files what it answered ─────────────────────────────────────────────────

def test_a_filed_answer_is_remembered_off_the_stream_in_its_organisation(monkeypatch):
    from aughor.org.context import current_org_id, using_org
    from aughor.routers import investigations as inv
    seen: dict = {}
    done = threading.Event()

    def remember(inv_id):
        seen.update(inv_id=inv_id, org=current_org_id(), thread=threading.current_thread().name)
        done.set()
        return True
    monkeypatch.setattr(pa, "index_answer", remember)
    with using_org("org-item24"):
        inv._remember_answer("turn-24")
    assert done.wait(5)
    assert seen == {"inv_id": "turn-24", "org": "org-item24", "thread": "remember-answer"}
