"""ADA cross-section ratio-over-chasm fixes (the ROAS-by-channel mess).

Fix C — when a finding hands `run_analysis_phase` its grain-correct query (preplanned), the
phase REUSES it verbatim and does NOT call the LLM coder to re-derive (which re-fanned the
join to the 0.0–0.01 values). Fix B — when a ratio still fans out, its corrupted values are
SUPPRESSED, not presented + rationalised. Hermetic: real DuckDB + a provider that raises if
any LLM call happens."""
from __future__ import annotations

import duckdb
import pytest

import aughor.agent.investigate as I
from aughor.db.connection import DuckDBConnection
from aughor.agent.prompts_investigate import PhasePlan, PhaseQueryPlan


class _BoomProvider:
    """Any LLM call (coder plan OR fast interpret) raises — so a passing run PROVES the coder
    was never asked to plan (Fix C reused the preplanned query)."""
    def complete(self, **_kw):
        raise AssertionError("LLM must not be called when a grain-correct query is preplanned")


# email_crm: rev 600 / spend 100 = ROAS 6.0 ; display: rev 300 / spend 75 = ROAS 4.0
_GRAIN_CORRECT = (
    "WITH r AS (SELECT channel, SUM(total_amount) AS rev FROM orders GROUP BY channel), "
    "     s AS (SELECT channel, SUM(spend) AS spend FROM marketing_spend GROUP BY channel) "
    "SELECT r.channel, ROUND(r.rev / NULLIF(s.spend, 0), 2) AS roas "
    "FROM r JOIN s ON r.channel = s.channel ORDER BY roas DESC"
)


def _ro_conn(tmp_path):
    p = str(tmp_path / "w.duckdb")
    w = duckdb.connect(p)
    w.execute("CREATE TABLE orders(channel VARCHAR, total_amount DOUBLE)")
    w.execute("INSERT INTO orders VALUES ('email_crm',300),('email_crm',300),"
              "('display',100),('display',100),('display',100)")
    w.execute("CREATE TABLE marketing_spend(channel VARCHAR, spend DOUBLE)")
    w.execute("INSERT INTO marketing_spend VALUES ('email_crm',100),('display',75)")
    w.close()
    return DuckDBConnection(p)


def test_preplanned_reuses_grain_correct_query_and_skips_the_coder(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_provider", lambda role: _BoomProvider())
    conn = _ro_conn(tmp_path)
    plan = PhasePlan(queries=[PhaseQueryPlan(
        title="Marketing ROAS by Channel (established finding)", sql=_GRAIN_CORRECT,
        chart_type="bar_horizontal", rationale="reuse the drilled finding's grain-correct query")])

    run = I.run_analysis_phase(
        conn, phase_id="cross_section", title="Cross-Sectional Scan", emoji="🧭",
        plan_system="x", plan_user="x", interpret_system="x", interpret_user_fn=lambda t: "x",
        preplanned=plan)

    assert run.ok is True            # the coder would have raised if called → it wasn't (Fix C)
    _q, r = run.results[0]
    roas = {row[0]: float(row[1]) for row in r.rows}
    assert roas["email_crm"] == 6.0 and roas["display"] == 4.0   # real ROAS, not the fanned 0.0–0.01


def test_without_preplanned_the_coder_is_used(tmp_path, monkeypatch):
    # control: with no preplanned query the coder IS called (and here raises → the run fails),
    # confirming the skip in the test above is due to Fix C, not a dead code path.
    monkeypatch.setattr(I, "_provider", lambda role: _BoomProvider())
    conn = _ro_conn(tmp_path)
    run = I.run_analysis_phase(
        conn, phase_id="cross_section", title="X", emoji="🧭",
        plan_system="x", plan_user="x", interpret_system="x", interpret_user_fn=lambda t: "x")
    assert run.ok is False           # coder was called and raised → planning failed


def test_suppress_fanned_ratio_drops_chart_and_replaces_narrative():
    findings = [{
        "interpretation": "email_crm has the highest ROAS at 0.01 — reflects high budget, not poor performance",
        "chart_type": "bar_horizontal",
        "key_numbers": [{"label": "ROAS", "value": "0.01"}],
        "rows": [["email_crm", 0.01]],
    }]
    summary = I._suppress_fanned_ratio(findings, "Marketing ROAS by Channel", "a join multiplied the rows.")
    f = findings[0]
    assert f["chart_type"] == "none"                         # no chart of garbage
    assert f["key_numbers"] == []                            # bogus 0.01 cleared
    assert "could not be computed reliably" in f["interpretation"]   # rationalisation replaced
    assert "reflects high budget" not in f["interpretation"]
    assert "suppressed" in summary and "Marketing ROAS by Channel" in summary
