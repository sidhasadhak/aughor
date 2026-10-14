"""P3 of the canvas-output study (2026-10-14): the phase planners say the job, code enforces the SQL.

Three things the prose used to hope for are now checks or facts: a filter the spec never declared is
detected on the planned query, re-planned once and caveated if it stays (live, 1f925796: the
decomposition kept `status NOT IN ('Cancelled','Returned')` over a metric declared on `<> 'Cancelled'`
and measured August at 335,733 against the baseline's 385,389); a result that hit its own LIMIT says it
is a slice, to the narrator and on the card (55e58a3b read a worst-first 15-row slice as "no category
above 3.8%"); and a capable binding reads one paragraph of SQL rules instead of four long blocks, the
retail dimension-priority list is gone from every tier, and no prompt asks for bold the code strips."""
from __future__ import annotations

from types import SimpleNamespace as NS

import aughor.agent.investigate as I
from aughor.agent import prompts_investigate as P

DECLARED = ["status <> 'Cancelled'"]
CLEAN = "SELECT category, SUM(sale_price) AS rev FROM order_items WHERE created_at >= '2026-08-01' AND created_at < '2026-09-01' AND status <> 'Cancelled' GROUP BY 1"
EXTRA = "SELECT category, SUM(sale_price) AS rev FROM order_items WHERE created_at >= '2026-08-01' AND created_at < '2026-09-01' AND status NOT IN ('Cancelled', 'Returned') GROUP BY 1"


def _q(title, sql):
    return NS(title=title, sql=sql, chart_type="auto", rationale="", semantic=None)


def test_a_filter_the_spec_declares_is_not_extra_and_one_it_does_not_is():
    assert I._extra_filters([_q("clean", CLEAN)], DECLARED, "bigquery") == []
    out = I._extra_filters([_q("decomp", EXTRA)], DECLARED, "bigquery")
    assert out == [("decomp", "status not in Cancelled, Returned")]
    assert I._extra_filters([_q("dates only", CLEAN.replace(" AND status <> 'Cancelled'", ""))], [], "bigquery") == []


def _run_phase(monkeypatch, plans, declared):
    """Drive the runner with a stub coder that answers the plan, then the re-plan, in order."""
    seen: list[str] = []

    class _Coder:
        def __init__(self):
            self.i = 0

        def complete(self, *, system, user, response_model=None, **kw):
            seen.append(user)
            if response_model is P.PhaseInterpretation:
                return None
            plan = plans[min(self.i, len(plans) - 1)]
            self.i += 1
            return NS(queries=[_q("decomp", plan)])
    coder = _Coder()
    monkeypatch.setattr(I, "_provider", lambda role="coder": coder)
    monkeypatch.setattr(I, "_phase_grounding", lambda *a, **k: "")
    monkeypatch.setattr(I, "_parallel_execute_safe", lambda conn, pid, queries, cap=4, schema=None: [
        (q, NS(sql=q.sql, columns=["category", "rev"], rows=[["Jeans", 1.0]], row_count=1, error=None, caveats=[], stats={}, truncated=False))
        for q in queries])
    monkeypatch.setattr(I, "_has_usable_data", lambda results: False)
    conn = NS(dialect="bigquery", writes_native_sql=True, get_schema=lambda: "", _connection_id="c1")
    run = I.run_analysis_phase(conn, phase_id="decomposition", title="t", emoji="", plan_system="Write SQL.",
                               plan_user="q", interpret_system="x", interpret_user_fn=lambda t: "x",
                               sql_context="SQL DIALECT: BigQuery\nTODAY: 2026-10-14 (UTC).", declared_filters=declared)
    return run, seen


def test_an_extra_filter_is_sent_back_once_and_the_repair_runs_clean(monkeypatch):
    run, seen = _run_phase(monkeypatch, [EXTRA, CLEAN], DECLARED)
    assert len(seen) == 2 and "CORRECTION REQUIRED — EXTRA FILTER" in seen[1]
    assert "keeps status not in Cancelled, Returned" in seen[1] and "status <> 'Cancelled'" in seen[1]
    assert run.ok and run.fanout_caveat is None
    assert run.results[0][0].sql == CLEAN


def test_a_filter_the_repair_keeps_becomes_the_findings_caveat(monkeypatch):
    run, seen = _run_phase(monkeypatch, [EXTRA, EXTRA], DECLARED)
    assert len(seen) == 2 and run.ok
    assert run.fanout_caveat.startswith("extra filter: this query keeps rows by status not in Cancelled, Returned")
    assert "narrower population" in run.fanout_caveat


def test_a_caller_that_declares_no_filters_turns_the_guard_off(monkeypatch):
    run, seen = _run_phase(monkeypatch, [EXTRA], None)
    assert len(seen) == 1 and run.fanout_caveat is None


def test_a_result_that_hit_its_limit_says_it_is_a_slice_to_the_narrator_and_on_the_card():
    capped = NS(sql="SELECT category, obs - comp AS abs_change FROM t ORDER BY abs_change ASC LIMIT 15",
                columns=["category", "abs_change"], rows=[[f"c{i}", -float(i)] for i in range(15)], row_count=15, error=None, stats={}, truncated=False)
    whole = NS(sql="SELECT category, obs - comp AS abs_change FROM t ORDER BY abs_change ASC",
               columns=["category", "abs_change"], rows=[[f"c{i}", -float(i)] for i in range(15)], row_count=15, error=None, stats={}, truncated=False)
    assert "A capped scan: these 15 rows are a slice" in I._capped_scan_note(capped)
    assert I._capped_scan_note(whole) == ""
    text = I._results_text_with_verdicts([capped, whole], max_rows=20)
    assert text.count("A capped scan") == 1 and "largest movers in the other direction" in text
    findings = I._assemble_phase_findings([(_q("by category", capped.sql), capped)], [], "dim")
    assert "A capped scan" in findings[0]["stat_note"]
    findings = I._assemble_phase_findings([(_q("by category", whole.sql), whole)], [], "dim")
    assert "capped scan" not in (findings[0].get("stat_note") or "")


def test_the_planners_read_one_paragraph_on_a_capable_binding_and_the_long_block_on_a_baseline_one():
    for phase in ("baseline", "decompose", "dimensional", "behavioral"):
        short, long = P.plan_sql_rules(phase, True), P.plan_sql_rules(phase, False)
        assert short is P._SQL_RULES_ASK and len(short) < 450
        assert "NO EXTRA FILTERS" in long and "DuckDB" not in long, phase
    for name in ("BASELINE_PLAN_PROMPT", "DECOMPOSE_PLAN_PROMPT", "DIMENSIONAL_PLAN_PROMPT", "BEHAVIORAL_PLAN_PROMPT"):
        t = getattr(P, name)
        assert "{sql_rules}" in t and "DuckDB" not in t, name
    assert "DIMENSION PRIORITY" not in P.DIMENSIONAL_PLAN_PROMPT
    assert "The dimensions above are listed in the order to analyse them" in P.DIMENSIONAL_PLAN_PROMPT


def test_the_shared_grounding_rides_only_a_baseline_planner(monkeypatch):
    import aughor.llm.profile as PR
    monkeypatch.setattr(PR, "profile_for", lambda role: NS(capable=True))
    assert I._sql_grounding() == "" and I._sql_rules_for("decompose") is P._SQL_RULES_ASK
    monkeypatch.setattr(PR, "profile_for", lambda role: NS(capable=False))
    assert I._sql_grounding() == I._ADA_SQL_GROUNDING and "NO EXTRA FILTERS" in I._sql_rules_for("decompose")


def test_no_prompt_asks_for_the_bold_the_code_strips():
    for name in ("DECOMPOSE_INTERPRET_PROMPT", "DIMENSIONAL_INTERPRET_PROMPT", "CROSS_SECTION_INTERPRET_PROMPT",
                 "CROSS_SECTION_RATIO_INTERPRET_PROMPT", "ARGUMENT_STYLE_ADDENDUM"):
        text = getattr(P, name)
        assert "**" not in text, name
        for ask in ("bold the", "bold it", "bolded", "bold inline", "bold lever"):
            assert ask not in text, (name, ask)


# ── what the live proof (d4039693, 2026-10-14) added ───────────────────────────────────────

COND = ("SELECT DATE_TRUNC(DATE(created_at), MONTH) AS m, SUM(IF(status NOT IN ('Cancelled','Returned'), sale_price, 0)) AS revenue "
        "FROM order_items WHERE created_at >= '2025-08-01' GROUP BY 1")


def test_a_filter_hidden_in_a_conditional_aggregate_is_read_too():
    """Refused a WHERE filter, the baseline planner kept the rows out through an IF instead, and
    measured August at 335,733 against the decomposition's 385,389."""
    assert I._extra_filters([_q("baseline", COND)], DECLARED, "bigquery") == [("baseline", "status not in Cancelled, Returned")]
    own = "SELECT SUM(CASE WHEN status <> 'Cancelled' THEN sale_price END) AS revenue FROM order_items"
    assert I._extra_filters([_q("own", own)], DECLARED, "bigquery") == []


def test_the_measures_own_conditions_are_declared_so_a_rate_is_never_asked_to_drop_them():
    intake = {"metric_filters": [], "metric_sql": "SUM(CASE WHEN status = 'Returned' THEN 1 END) / COUNT(*)",
              "other_measures": [{"label": "cancelled", "sql": "SUM(IF(status = 'Cancelled', 1, 0))"}]}
    declared = I._declared_conditions(intake)
    assert "status = 'Returned'" in declared and "status = 'Cancelled'" in declared
    rate = "SELECT SUM(CASE WHEN status = 'Returned' THEN 1 END) / COUNT(*) AS r FROM order_items WHERE created_at >= '2026-08-01'"
    assert I._extra_filters([_q("rate", rate)], declared, "bigquery") == []


def test_every_phase_stamps_the_slice_note_on_its_cards():
    """The decomposition builds its findings without `_assemble_phase_findings`; the stamp lives at
    `_phase_result`, the seam every phase passes."""
    capped = {"finding_id": "decomp_1", "title": "top movers", "sql": "SELECT p, d FROM t ORDER BY ABS(d) DESC LIMIT 20",
              "columns": ["p", "d"], "rows": [[i, i] for i in range(20)], "row_count": 20, "error": None,
              "interpretation": "", "key_numbers": [], "chart_type": "auto", "stat_note": "z = 1.2", "is_significant": False}
    whole = {**capped, "finding_id": "decomp_0", "sql": "SELECT p, d FROM t", "stat_note": None}
    phase = I._phase_result("decomposition", "Metric Decomposition", "", "complete", "s", [capped, whole])
    notes = {f["finding_id"]: f.get("stat_note") or "" for f in phase["findings"]}
    assert notes["decomp_1"].startswith("z = 1.2 A capped scan: these 20 rows are a slice")
    assert "capped" not in notes["decomp_0"]
    again = I._phase_result("decomposition", "Metric Decomposition", "", "complete", "s", phase["findings"])
    assert again["findings"][0]["stat_note"].count("capped scan") == 1          # idempotent
