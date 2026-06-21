"""Phase-2: typed SQL-Engineer → Verifier → Narrator hand-off contracts + the
agent.handoff provenance journaled by run_analysis_phase."""
import json

from aughor.agent.handoff import (
    EngineeredQuery,
    NarratorHandoff,
    SqlEngineerHandoff,
    VerifierHandoff,
    emit_handoff,
    journal_phase_handoffs,
)
from aughor.kernel.agents import specialist
from aughor.kernel.ledger import Ledger


class _Q:
    def __init__(self, title): self.title = title


class _R:
    def __init__(self, sql, row_count, error=None):
        self.sql, self.row_count, self.error = sql, row_count, error


class _Interp:
    def __init__(self, findings): self.findings = findings


def _payload(ev):
    p = ev["payload"]
    return json.loads(p) if isinstance(p, str) else p


def _handoffs_for(phase):
    return [e for e in Ledger.default().events(kind="agent.handoff", limit=200)
            if _payload(e).get("phase") == phase]


def test_contracts_summarize():
    se = SqlEngineerHandoff("baseline", [EngineeredQuery("a", "SELECT 1", 5),
                                         EngineeredQuery("b", "SELECT x", 0, error="boom")])
    assert se.ok_count == 1
    assert se.summary() == {"queries": 2, "ok": 1, "rows": 5}
    assert VerifierHandoff("baseline", 2, ["fan-out caveat"], passed=True).summary()["caveats"] == ["fan-out caveat"]
    assert NarratorHandoff("baseline", 3).summary() == {"findings": 3}


def test_specialists_registered():
    assert specialist("sql_engineer")["name"] == "SQL Engineer"
    assert specialist("verifier")["name"] == "Verifier"
    assert specialist("narrator")["name"] == "Narrator"
    assert specialist("???")["name"] == "???"   # unknown echoed, never raises


def test_emit_handoff_journals():
    emit_handoff("sql_engineer", "verifier", "ph-emit-test", {"queries": 1})
    mine = _handoffs_for("ph-emit-test")
    assert mine and _payload(mine[0])["from"] == "sql_engineer" and _payload(mine[0])["to"] == "verifier"


def test_journal_phase_handoffs_emits_the_chain():
    results = [(_Q("revenue by month"), _R("SELECT ...", 12)),
               (_Q("orders"), _R("SELECT ...", 0, error="bad"))]
    journal_phase_handoffs("ph-cycle-test", plan=object(), results=results,
                           fanout_caveat="fan-out detected", interpretation=_Interp([1, 2, 3]))
    evs = _handoffs_for("ph-cycle-test")
    chain = {(_payload(e)["from"], _payload(e)["to"]) for e in evs}
    assert {("sql_engineer", "verifier"), ("verifier", "narrator"), ("narrator", "analyst")} <= chain
    se = _payload(next(e for e in evs if _payload(e)["from"] == "sql_engineer"))
    assert se["queries"] == 2 and se["ok"] == 1
    ve = _payload(next(e for e in evs if _payload(e)["from"] == "verifier"))
    assert ve["caveats"] == ["fan-out detected"]
    na = _payload(next(e for e in evs if _payload(e)["from"] == "narrator"))
    assert na["findings"] == 3


def test_journal_is_fail_open_on_bad_input():
    # malformed results must never raise into the investigation
    journal_phase_handoffs("ph-x", plan=None, results="not-pairs",
                           fanout_caveat=None, interpretation=None)
