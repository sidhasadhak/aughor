"""SQL-guard coverage ratchet — one guard battery, every agent that fires model-written SQL.

**The rule this enforces:** a module that turns natural language into SQL and then EXECUTES that
SQL must route the execution through ``aughor/sql/executor.py``, so every agent — Deep Analysis,
the autonomous Explorer, quick/Insight, monitors, dashboards, the Query Builder — shares ONE
deterministic guard battery instead of hand-assembling its own.

**Why a ratchet and not a refactor.** The repo already has THREE unification attempts
(``sql/executor.execute_guarded``, the ``trust.verify`` plane, ``explorer/verify.verify_insight``),
each wired to a subset of callers. A fourth abstraction would not help; what is missing is a gate
that makes a door the ONLY door. The number-formatting layer is the proof: it stayed unified
because ``web/scripts/check-formatting.mjs`` fails CI when anyone re-implements it. The guards had
no equivalent, so every new path quietly re-assembled its own bundle — which is how the autonomous
Explorer, the agent that writes the Briefing, ended up the LEAST guarded path in the system and
shipped a €102,870,539,329 fan-out to a reader.

This test does two things:
  1. **Forces a decision on every new site.** The discovered set of generate-and-execute modules
     must equal the declared inventory below. A new one fails the test until it is classified.
  2. **Ratchets the unguarded count down.** It may shrink, never grow (same contract as
     SILENT_SWALLOW_BASELINE).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "aughor"

# A module "generates" SQL if it reaches for one of the LLM SQL writers…
_GENERATES = re.compile(
    r"SqlWriter|WRITE_SQL_PROMPT|FIX_SQL_PROMPT|sql_generate|SQLOutput|generate_sql|write_sql")
# …and "executes" if it calls the connector's 2-arg form, `conn.execute(query_id, sql)`.
# Internal SQLite/DuckDB stores use the 1-arg cursor form, so they never match.
_EXECUTES = re.compile(r"\b\w+\.execute\(\s*[^,)]+,")
# Compliance = the execution goes through the shared executor module.
_ROUTES = re.compile(r"from aughor\.sql\.executor import|aughor\.sql\.executor\b")
# The full battery vs. the pre-execute half only.
_FULL_BATTERY = re.compile(r"\bexecute_guarded\b")

# ── The declared inventory ────────────────────────────────────────────────────
# Compliant: execution routes through aughor/sql/executor.py.
COMPLIANT = {
    "agent/investigate.py",   # Deep Analysis — execute_guarded (the original, extracted verbatim)
    "agent/nodes.py",         # quick / Insight — preflight_harden only (see PARTIAL below)
    "agent/explore.py",       # chat explore tool — preflight_harden only (see PARTIAL below)
    "explorer/agent.py",      # autonomous Explorer (Scout) — execute_guarded, deterministic-only
    "sql/executor.py",        # the executor itself
}

# Exempt, with the reason stated. An exemption is a claim that must stay true.
EXEMPT = {
    "trust/__init__.py":
        "the guard's OWN uniqueness probe (`__trust_grain__`). The SQL is constructed by the "
        "guard from a parsed table+key, never model-written — and routing the guard through the "
        "guard would recurse.",
    "capability/builtins.py":
        "guarded by a DIFFERENT door: CapabilityPipeline runs `validate` (= trust.verify) before "
        "`execute`, so a BLOCK short-circuits ahead of this call. Reclassify if that ordering "
        "ever changes.",
}

# Not yet routed through the shared executor. THIS LIST MAY ONLY SHRINK.
# Ordered by how much a wrong number here costs a reader.
UNGUARDED = {
    "routers/exploration.py":
        "`__retry__` runs LLM-corrected SQL straight from `writer.fix(...)`; `__ground__` re-runs "
        "a stored insight's SQL.",
    "explorer/fix_persist.py":
        "`__fix_save__` executes a model-repaired query to validate it before persisting.",
    "routers/investigations.py":
        "`soma_probe` executes model-generated candidate readings for ambiguity assessment.",
    "user_agents/quality.py":
        "the agent-eval harness runs a model-generated query against a reference.",
}

UNGUARDED_BASELINE = len(UNGUARDED)   # 4 (was 5 — explorer/agent.py wired 2026-07-21)
#                                       lower this as each is wired, never raise it


def _generate_and_execute() -> set[str]:
    """Modules that turn NL into SQL and then run it — the population this rule governs."""
    found = set()
    for p in ROOT.rglob("*.py"):
        text = p.read_text()
        if _GENERATES.search(text) and _EXECUTES.search(text):
            found.add(str(p.relative_to(ROOT)))
    return found


def test_every_generate_and_execute_module_is_classified():
    """A NEW module that writes SQL with a model and runs it must be classified — compliant,
    exempt-with-a-reason, or an explicit entry on the unguarded list. Silence is not an option:
    an unclassified path is exactly how the Explorer drifted for months without anyone noticing."""
    declared = COMPLIANT | set(EXEMPT) | set(UNGUARDED)
    found = _generate_and_execute()

    undeclared = found - declared
    assert not undeclared, (
        f"New generate-and-execute module(s) not classified in {Path(__file__).name}: "
        f"{sorted(undeclared)}.\nRoute execution through aughor/sql/executor.py and add it to "
        f"COMPLIANT, or add it to EXEMPT with a reason / UNGUARDED and raise nothing."
    )
    stale = declared - found
    assert not stale, (
        f"Declared but no longer generate-and-execute: {sorted(stale)}. Remove the stale entry "
        f"(and lower UNGUARDED_BASELINE if it was on the unguarded list)."
    )


def test_unguarded_sql_execution_only_shrinks():
    """The ratchet. Wiring `explorer/agent.py` through `execute_guarded` is the single highest-value
    move on this list — it is the agent whose numbers reach the Briefing."""
    still_unguarded = sorted(m for m in UNGUARDED if not _ROUTES.search((ROOT / m).read_text()))
    assert len(still_unguarded) <= UNGUARDED_BASELINE, (
        f"{len(still_unguarded)} modules execute model-written SQL without the shared guard "
        f"battery (baseline {UNGUARDED_BASELINE}): {still_unguarded}"
    )
    if len(still_unguarded) < UNGUARDED_BASELINE:
        print(f"\n[ratchet] unguarded SQL execution now {len(still_unguarded)} — lower "
              f"UNGUARDED_BASELINE in {Path(__file__).name}")


def test_compliant_modules_really_import_the_shared_executor():
    """Guards the COMPLIANT list against rot — a module that stops routing through the executor
    must not keep claiming it does."""
    for m in sorted(COMPLIANT - {"sql/executor.py"}):
        assert _ROUTES.search((ROOT / m).read_text()), (
            f"{m} is listed COMPLIANT but no longer imports aughor.sql.executor"
        )


# ── Sub-ratchet: pre-execute hardening is only HALF the battery ───────────────
# `preflight_harden` is the deterministic de-fan + preflight-repair. `execute_guarded` adds the
# post-execute guard findings (value-disjoint join, unbound literal, id-arithmetic) and the
# self-correction retry. A path with only the former is partially covered.
PARTIAL = {
    "agent/nodes.py":   "quick / Insight — preflight_harden only, no post-execute battery",
    "agent/explore.py": "chat explore — preflight_harden only, no post-execute battery",
}
PARTIAL_BASELINE = len(PARTIAL)   # 2 — lower as each adopts execute_guarded


def test_partial_coverage_only_shrinks():
    still_partial = sorted(
        m for m in PARTIAL if not _FULL_BATTERY.search((ROOT / m).read_text())
    )
    assert len(still_partial) <= PARTIAL_BASELINE, (
        f"{len(still_partial)} paths harden pre-execute but skip the full battery "
        f"(baseline {PARTIAL_BASELINE}): {still_partial}"
    )
    if len(still_partial) < PARTIAL_BASELINE:
        print(f"\n[ratchet] partial-coverage paths now {len(still_partial)} — lower "
              f"PARTIAL_BASELINE in {Path(__file__).name}")
