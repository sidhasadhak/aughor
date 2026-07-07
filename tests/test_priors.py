"""P1 close-the-loop: past-correction priors read back into the prompt.

Deterministic (no LLM) — isolates the verdict store to a temp DB and drives the
flag, proving the corrections block fires only when the loop is enabled AND a
relevant correction exists, and is byte-empty (zero-cost) otherwise.
"""
from __future__ import annotations


import pytest


@pytest.fixture
def isolated_verdicts(tmp_path, monkeypatch):
    from aughor.semantic import ambiguity_ledger
    from aughor.verify import verdicts
    monkeypatch.setattr(verdicts, "_DB_PATH", tmp_path / "verdicts.db")
    # record_verdict now bridges into the Ambiguity Ledger (a session-shared store); isolate it
    # per-test too so a verdict crystallized here can't leak into another test's connection.
    monkeypatch.setattr(ambiguity_ledger, "_DB_PATH", tmp_path / "ambiguity.db")
    # priors.py imports list_corrections at module load; it resolves through the
    # verdicts module object, so patching _DB_PATH is sufficient.
    return verdicts


def _seed_reject(verdicts, question_headline: str, corrected_sql: str = "", note: str = ""):
    return verdicts.record_verdict(
        connection_id="samples", investigation_id="inv1", verdict="reject",
        note=note, headline=question_headline, sql_source="SELECT bad FROM t",
        corrected_sql=corrected_sql,
    )


def test_flag_off_is_zero_cost(isolated_verdicts, monkeypatch):
    monkeypatch.delenv("AUGHOR_CLOSED_LOOP", raising=False)
    _seed_reject(isolated_verdicts, "revenue by product category")
    from aughor.verify.priors import build_corrections_section
    assert build_corrections_section("what is revenue by product category?", "samples") == ""


def test_fires_on_relevant_match(isolated_verdicts, monkeypatch):
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    _seed_reject(isolated_verdicts, "revenue by product category",
                 corrected_sql="SELECT category, SUM(line_total) FROM order_items GROUP BY 1",
                 note="use order_items.line_total, not orders.total_amount (fan-out)")
    from aughor.verify.priors import build_corrections_section
    block = build_corrections_section("what is revenue by product category?", "samples")
    assert "PAST CORRECTIONS" in block
    assert "order_items.line_total" in block          # the corrected structure is present
    assert "USE THIS CORRECTED STRUCTURE" in block


def test_empty_on_irrelevant_question(isolated_verdicts, monkeypatch):
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    _seed_reject(isolated_verdicts, "revenue by product category")
    from aughor.verify.priors import build_corrections_section
    # A question with no token overlap must inject nothing (conservative threshold).
    assert build_corrections_section("how many suppliers are in France?", "samples") == ""


def test_empty_when_no_verdicts(isolated_verdicts, monkeypatch):
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    from aughor.verify.priors import build_corrections_section
    assert build_corrections_section("anything at all", "samples") == ""


def test_only_reject_and_correct_are_read_back(isolated_verdicts, monkeypatch):
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    # an ACCEPT teaches nothing new — it must not surface as a correction
    isolated_verdicts.record_verdict(
        connection_id="samples", investigation_id="i", verdict="accept",
        headline="revenue by product category is healthy")
    from aughor.verify.priors import build_corrections_section
    assert build_corrections_section("revenue by product category?", "samples") == ""


# ── Ambiguity Ledger prior (I1) — the resolved-ambiguity block reads back too ──
def _seed_resolution(conn_id, subject, reading, source="probe"):
    from aughor.semantic.ambiguity_ledger import AmbiguityResolution, save_resolution
    return save_resolution(AmbiguityResolution(
        connection_id=conn_id, dim_kind="AmbiIntent", dim_facet="grain", subject=subject,
        resolved_reading=reading, resolution_source=source,
        resolved_sql="GROUP BY player", evidence="a live probe matched the asked grain"))


def test_ledger_resolution_reads_back_into_priors(monkeypatch):
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    _seed_resolution("led_conn1", "total runs scored by strikers", "career totals")
    from aughor.verify.priors import build_priors_section, retrieve_priors
    section = build_priors_section("what is the average total runs by strikers?", "led_conn1")
    assert "RESOLVED AMBIGUITIES" in section and "career totals" in section
    # the served resolution is tracked in the result (the burn-down numerator)
    res = retrieve_priors("total runs by strikers?", "led_conn1")
    assert res.fired and res.resolutions


def test_ledger_prior_off_when_flag_off(monkeypatch):
    monkeypatch.delenv("AUGHOR_CLOSED_LOOP", raising=False)
    _seed_resolution("led_conn2", "total runs by strikers", "career totals")
    from aughor.verify.priors import build_priors_section
    assert build_priors_section("total runs by strikers?", "led_conn2") == ""


def test_ledger_prior_empty_on_irrelevant_question(monkeypatch):
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    _seed_resolution("led_conn3", "total runs by strikers", "career totals")
    from aughor.verify.priors import build_priors_section
    assert build_priors_section("how many suppliers are in France?", "led_conn3") == ""


def test_verdict_surfaces_via_corrections_not_double_injected(isolated_verdicts, monkeypatch):
    # a reject/correct verdict lands in BOTH the ledger (bridge) and the verdicts store; the PROMPT
    # must surface it ONCE — via the emphatic corrections voice — with the redundant ledger line
    # deduped, while the ledger row survives for the burn-down metric + the Trust Receipt.
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    from aughor.semantic.ambiguity_ledger import list_resolutions, purge_connections
    purge_connections(["ded_conn"])
    isolated_verdicts.record_verdict(
        connection_id="ded_conn", investigation_id="i", verdict="reject",
        headline="revenue by product category", note="use order_items.line_total",
        corrected_sql="SELECT category, SUM(line_total) FROM order_items GROUP BY 1")
    assert list_resolutions("ded_conn") and list_resolutions("ded_conn")[0].resolution_source == "verdict"
    from aughor.verify.priors import retrieve_priors
    res = retrieve_priors("what is revenue by product category?", "ded_conn")
    assert "PAST CORRECTIONS" in res.section and res.corrections
    assert "RESOLVED AMBIGUITIES" not in res.section     # the redundant ledger line is deduped out


def test_probe_resolution_reaches_the_live_corrections_section(monkeypatch):
    # the LIVE answer path (chat + plan node) calls build_corrections_section — the Ambiguity-Ledger
    # read path MUST fire there, or the whole compounding feature never reaches a real prompt.
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    _seed_resolution("led_live", "total runs by strikers", "career totals")   # probe-source
    from aughor.verify.priors import build_corrections_section
    section = build_corrections_section("what is the total runs by strikers?", "led_live")
    assert "RESOLVED AMBIGUITIES" in section and "career totals" in section
