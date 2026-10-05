"""Phase 1 of the 2027 study, P1-2 — the writers into the Record (`aughor/record/writers.py`).

What these hold: every receipted answer that concluded something with a query behind it books an
OBSERVATION warranted by its receipt; one that concluded nothing, or ran no query, books none; a
deep analysis books its findings from the evidence ledger beside the observation — measured when
the finding has its own SQL, a hypothesis at tier `said` when it does not; a partial report books
no findings; the daily re-check RESTATES the observation when the numbers moved, warranted by a
receipt of the re-check, the first version kept; and the evidence ledger writes no confidence any
more, reads old rows that carry one, and rebuilds a file whose column still refuses NULL.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import duckdb
import pytest

import aughor.evidence.store as ev_store
from aughor.evidence.linker import extract_claims_from_ada_phases, extract_claims_from_report
from aughor.evidence.models import EvidenceClaim
from aughor.kernel.ledger import DEEP_REPORT_KIND, Ledger
from aughor.record import claims as C
from aughor.record import writers as W
from aughor.routers import investigations as inv


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(ev_store, "_DB_PATH", tmp_path / "ev.db")
    return ev_store


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


# ── from the Trust Receipt ─────────────────────────────────────────────────────────────────

def test_a_receipted_answer_books_an_observation_warranted_by_its_receipt():
    conn = _conn()
    out = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:inv1",
                                   question="How many orders a day last week?",
                                   sqls=["SELECT COUNT(*) FROM orders"], headline="1,744 orders a day",
                                   schema="", connection_id=conn)
    assert out["receipt_id"] and out["claim_id"]
    claim = C.latest(W.observation_key(conn, "inv1"))
    assert claim is not None and claim.id == out["claim_id"]
    assert claim.kind == "observation" and claim.tier == "measured" and claim.status == "Provisional"
    assert claim.statement.text == "1,744 orders a day"
    assert [(w.kind, w.ref) for w in claim.warrants] == [("run", out["receipt_id"])]
    assert claim.as_of and claim.recorded_at and claim.confidence is None
    assert claim.extra["investigation_id"] == "inv1" and claim.extra["receipt_kind"] == "chat_answer"
    assert claim.author_kind == "system"          # nobody asked as an agent
    rec = Ledger.default().receipt_by_id(claim.id)
    assert any(e["relation"] == "warrant:run" and e["ref"] == out["receipt_id"] for e in rec["lineage"])


def test_an_answer_that_concluded_nothing_or_ran_no_query_books_no_observation():
    conn = _conn()
    # headline == question: the receipt page shows something, the Record gets nothing
    out = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:a", question="how many?",
                                   sqls=["SELECT 1"], headline="how many?", schema="", connection_id=conn)
    assert out["receipt_id"] and out["claim_id"] is None
    assert C.latest(W.observation_key(conn, "a")) is None
    # a conclusion with no query behind it is not measured, so it is not an observation
    out = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:b", question="why?",
                                   sqls=[], headline="because of the weather", schema="", connection_id=conn)
    assert out["receipt_id"] and out["claim_id"] is None


def test_the_observation_names_its_falsifier_and_next_check_when_the_recheck_is_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_ANSWERS_RECHECK", "1")
    conn = _conn()
    out = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:c", question="q",
                                   sqls=["SELECT SUM(x) FROM t WHERE d >= DATE '2026-09-01'"],
                                   headline="12", schema="", connection_id=conn)
    claim = C.get(out["claim_id"])
    assert "re-run daily" in claim.falsifier and claim.next_check
    # a query that reads the clock cannot be re-checked, and the claim says so instead of promising
    out = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:d", question="q",
                                   sqls=["SELECT COUNT(*) FROM t WHERE d = current_date"],
                                   headline="7", schema="", connection_id=conn)
    claim = C.get(out["claim_id"])
    assert claim.falsifier.startswith("not re-checked") and claim.next_check == ""


def test_a_deep_analysis_books_its_findings_measured_or_as_hypotheses(evidence):
    conn, inv_id = _conn(), "deep-" + uuid.uuid4().hex[:6]
    evidence.append_claim(EvidenceClaim(investigation_id=inv_id, hypothesis_id="p1",
                                        claim_text="Returns rose 12% in the north region",
                                        sql_source="SELECT region, COUNT(*) FROM returns GROUP BY 1",
                                        metric_used="refund"))
    evidence.append_claim(EvidenceClaim(investigation_id=inv_id, hypothesis_id="p2",
                                        claim_text="Late dispatch is the likeliest driver"))
    out = inv.write_answer_receipt(kind=DEEP_REPORT_KIND, natural_key=f"deep:{conn}:{inv_id}",
                                   question="why did returns rise?",
                                   sqls=["SELECT region, COUNT(*) FROM returns GROUP BY 1"],
                                   headline="Returns rose on late dispatch in the north", schema="",
                                   connection_id=conn, payload_extra={"investigation_id": inv_id})
    assert out["claim_id"] and len(out["finding_claims"]) == 2
    booked = [C.get(cid) for cid in out["finding_claims"]]
    measured = next(c for c in booked if c.kind == "finding")
    said = next(c for c in booked if c.kind == "hypothesis")
    assert measured.tier == "measured" and measured.warrants[0].ref == out["receipt_id"]
    assert measured.statement.metric == "refund" and measured.extra["phase"] == "p1"
    assert said.tier == "said" and said.state == "open" and said.warrants == []
    assert "without a query" in said.extra["why_hypothesis"]
    assert all(c.confidence is None for c in booked)
    # the same report receipted again restates the same findings rather than doubling them
    again = inv.write_answer_receipt(kind=DEEP_REPORT_KIND, natural_key=f"deep:{conn}:{inv_id}", question="why?",
                                     sqls=["SELECT 1"], headline="Returns rose on late dispatch in the north",
                                     schema="", connection_id=conn, payload_extra={"investigation_id": inv_id})
    assert len(again["finding_claims"]) == 2
    assert all(C.get(cid).version == 2 for cid in again["finding_claims"])


def test_a_partial_report_books_no_findings(evidence):
    conn, inv_id = _conn(), "part-" + uuid.uuid4().hex[:6]
    evidence.append_claim(EvidenceClaim(investigation_id=inv_id, claim_text="half a finding", sql_source="SELECT 1"))
    out = inv.write_answer_receipt(kind=DEEP_REPORT_KIND, natural_key=f"deep:{conn}:{inv_id}", question="q",
                                   sqls=["SELECT 1"], headline="so far: nothing settled", schema="",
                                   connection_id=conn, payload_extra={"investigation_id": inv_id, "partial": True})
    assert out["claim_id"] and out["finding_claims"] == []


# ── from the daily re-check ───────────────────────────────────────────────────────────────

def _entry(**kw):
    e = {"checked_at": "2026-09-23T06:00:00Z", "status": "changed", "reason": "", "compared": 6,
         "missing_rows": 0, "new_rows": 1, "cause": "late_rows", "lag_days": 3, "changed": 1,
         "changes": [{"column": "orders", "label": {"day": "2026-09-20"}, "old": 1744.0, "new": 1902.0,
                      "rel": 0.0906, "day": "2026-09-20", "cause": "late_rows"}]}
    e.update(kw)
    return e


def test_a_changed_recheck_restates_the_observation_and_keeps_the_first_version():
    conn = _conn()
    first = W.book_answer_observation(kind="chat_answer", natural_key=f"chat:{conn}:r1", receipt_id="rcpt-first",
                                      connection_id=conn, question="orders a day?", headline="1,744 orders a day",
                                      sql="SELECT day, COUNT(*) FROM orders GROUP BY 1")
    answer = {"id": "r1", "connection_id": conn, "report": {"sql": "SELECT day, COUNT(*) FROM orders GROUP BY 1",
                                                             "headline": "1,744 orders a day"}}
    noted = W.restate_answer_observation(answer, _entry(), text="Restated: orders for 2026-09-20 is now 1,902")
    assert noted["superseded"] == first and noted["restated"] != first
    old, new = C.get(first), C.get(noted["restated"])
    assert old.superseded_by == new.id and old.statement.text == "1,744 orders a day"       # kept
    assert new.version == 2 and new.supersedes == first
    assert new.statement.text.startswith("Restated:") and new.statement.value == 1902.0
    assert new.statement.metric == "orders" and new.as_of == "2026-09-23"
    assert new.extra["cause"] == "late_rows" and new.extra["first_receipt"] == "rcpt-first"
    # the warrant is a receipt of the re-check run, which names the first receipt it re-checked
    rcpt = Ledger.default().artifact_by_id(new.warrants[0].ref)
    assert rcpt["kind"] == W.RECHECK_RECEIPT_KIND and rcpt["payload"]["changes"][0]["new"] == 1902.0
    assert any(e["relation"] == "rechecks" and e["ref"] == "rcpt-first"
               for e in Ledger.default().receipt_by_id(rcpt["id"])["lineage"])
    assert [v.statement.value for v in C.versions(new.key)] == [1902.0, None]


def test_an_answer_with_no_observation_restates_nothing_and_an_unchanged_one_is_left_alone():
    conn = _conn()
    assert W.restate_answer_observation({"id": "ghost", "connection_id": conn, "report": {}}, _entry()) is None
    W.book_answer_observation(kind="chat_answer", natural_key=f"chat:{conn}:u", receipt_id="rcpt-u",
                              connection_id=conn, question="q", headline="12", sql="SELECT 12")
    assert W.restate_answer_observation({"id": "u", "connection_id": conn, "report": {}},
                                        _entry(status="unchanged", changes=[])) is None
    assert C.latest(W.observation_key(conn, "u")).version == 1


def test_the_recheck_end_to_end_restates_the_record_and_the_entry_names_it(monkeypatch):
    """The real spine: a chat turn saved, its observation booked, the source gaining late rows, the
    daily re-check finding them — and the Record restated with the entry on the answer saying so."""
    from aughor.answer import recheck
    from aughor.db.history import get_chat_answer, save_chat_turn
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: 3)
    con = duckdb.connect()
    con.execute("""CREATE TABLE orders AS SELECT DATE '2026-09-15' + (i % 6)::INT
                   + INTERVAL 12 HOUR AS created_at FROM range(0, 6 * 1744) t(i)""")
    sql = ("SELECT CAST(created_at AS DATE) AS day, COUNT(*) AS orders FROM orders "
           "WHERE created_at >= TIMESTAMP '2026-09-15' GROUP BY 1 ORDER BY 1")

    def run_sql(q):
        cur = con.execute(q)
        return [d[0] for d in cur.description], [list(r) for r in cur.fetchall()], None

    cols, rows, _ = run_sql(sql)
    conn = _conn()
    inv_id = save_chat_turn(question="How many orders each day?", connection_id=conn, headline="1,744 orders a day",
                            sql=sql, session_id="web-1", columns=cols, rows=[[str(r[0]), r[1]] for r in rows])
    out = inv.write_answer_receipt(kind="chat_answer", natural_key=f"chat:{conn}:{inv_id}",
                                   question="How many orders each day?", sqls=[sql], headline="1,744 orders a day",
                                   schema="", connection_id=conn)
    assert out["claim_id"]
    con.execute("INSERT INTO orders SELECT TIMESTAMP '2026-09-20 23:00' FROM range(0, 158)")
    answer = get_chat_answer(inv_id) | {"completed_at": "2026-09-21T10:00:00+00:00"}
    entry = recheck.recheck_and_tell(answer, run_sql=run_sql, now=datetime(2026, 9, 23, 6, tzinfo=timezone.utc))
    assert entry["status"] == "changed" and entry["claim"]["superseded"] == out["claim_id"]
    restated = C.get(entry["claim"]["restated"])
    assert restated.statement.text == ("Restated: orders for 2026-09-20 is now 1,902 (we said 1,744). "
                                       "Cause: late rows. First said: 1,744 orders a day")
    assert restated.statement.value == 1902.0 and restated.extra["cause"] == "late_rows"
    # the filed entry carries the same pointer, so the answer's row and the Record agree
    filed = get_chat_answer(inv_id)["report"]["rechecks"][-1]
    assert filed["claim"]["restated"] == restated.id
    # an answer from before the Record says it had nothing to restate, instead of implying a claim
    older = save_chat_turn(question="q", connection_id=conn, headline="h", sql=sql, session_id="web-1",
                           columns=cols, rows=[[str(r[0]), r[1]] for r in rows])
    entry = recheck.recheck_and_tell(get_chat_answer(older) | {"completed_at": "2026-09-21T10:00:00+00:00"},
                                     run_sql=run_sql, now=datetime(2026, 9, 23, 6, tzinfo=timezone.utc))
    assert entry["status"] == "changed" and entry["claim"] == {
        "restated": "", "why": "this answer booked no observation to restate"}
    con.close()


# ── the evidence ledger writes no confidence ───────────────────────────────────────────────

def test_the_linker_writes_no_confidence_from_either_shape():
    from types import SimpleNamespace
    report = SimpleNamespace(key_findings=[SimpleNamespace(claim="Revenue fell 12%", confidence=0.93,
                                                           hypothesis_id="h1"),
                                           {"claim": "Churn held", "confidence": 0.4, "hypothesis_id": "h2"}])
    claims = extract_claims_from_report("inv", report, [{"hypothesis_id": "h1", "sql": "SELECT 1"}])
    assert [c.confidence for c in claims] == [None, None]
    assert claims[0].sql_source == "SELECT 1" and claims[0].metric_used == "revenue"
    phases = [{"phase_id": "p1", "findings": [
        {"title": "North", "interpretation": "Returns rose. More follows.", "sql": "SELECT 1", "is_significant": True},
        {"title": "South", "interpretation": "Flat.", "is_significant": False},
        {"title": "err", "interpretation": "x", "error": "boom"}]}]
    claims = extract_claims_from_ada_phases("inv", phases)
    assert [c.confidence for c in claims] == [None, None] and len(claims) == 2


def test_the_store_keeps_a_null_and_reads_an_old_number(evidence):
    evidence.append_claim(EvidenceClaim(investigation_id="i", claim_text="new row"))
    evidence.append_claim(EvidenceClaim(investigation_id="i", claim_text="old row", confidence=0.8,
                                        created_at="2026-01-01T00:00:00Z"))
    got = {c.claim_text: c.confidence for c in evidence.get_claims_for_investigation("i")}
    assert got == {"new row": None, "old row": 0.8}


def test_a_file_whose_column_still_refuses_null_is_rebuilt_with_its_rows(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE evidence_claims (
            id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL, hypothesis_id TEXT, claim_text TEXT NOT NULL,
            sql_source TEXT, metric_used TEXT, data_freshness TEXT, confidence REAL NOT NULL,
            created_at TEXT NOT NULL, owner_feedback TEXT, feedback_note TEXT,
            downstream_recommendations TEXT NOT NULL DEFAULT '[]', outcome_status TEXT);
        CREATE INDEX idx_ec_inv ON evidence_claims(investigation_id);
        INSERT INTO evidence_claims (id, investigation_id, claim_text, confidence, created_at)
        VALUES ('old1', 'i', 'from before', 0.5, '2026-01-01T00:00:00Z');
    """)
    con.commit()
    con.close()
    monkeypatch.setattr(ev_store, "_DB_PATH", path)
    ev_store.append_claim(EvidenceClaim(investigation_id="i", claim_text="from after"))      # NULL now storable
    got = {c.claim_text: c.confidence for c in ev_store.get_claims_for_investigation("i")}
    assert got == {"from before": 0.5, "from after": None}
    con = sqlite3.connect(str(path))
    cols = {r[1]: r[3] for r in con.execute("PRAGMA table_info(evidence_claims)")}
    assert cols["confidence"] == 0 and cols["claim_text"] == 1                             # nullable; the rest as shipped
    assert {r[1] for r in con.execute("PRAGMA index_list(evidence_claims)")} >= {"idx_ec_inv", "idx_ec_met"}
    con.close()
