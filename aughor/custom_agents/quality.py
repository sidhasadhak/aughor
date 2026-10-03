"""Measured agents — evaluate a user-agent against ITS OWN golden questions.

The differentiator over Gem/custom-GPT builders (study Part B Phase 3): an
agent's quality is measured, not vibes. Each golden = {question, reference_sql}
(ground truth authored by the agent's creator). An evaluation:

1. activates the agent (brief + document scope + connection binding — the same
   contextvar the live answer path uses),
2. generates SQL for each golden question with the CURRENT coder model through
   the product chat prompt,
3. executes both the generated and the reference SQL on the agent's connection,
4. compares result sets DETERMINISTICALLY (no LLM judges), and
5. stamps {passed, total, at, per_question} onto the agent (the pass chip) —
   and logs a span per evaluation when MLflow tracing is configured.

Failure posture: a generation/execution error fails THAT golden, never the run.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from aughor.custom_agents.context import activate_agent, release_agent
from aughor.custom_agents.models import UserAgent
from aughor.custom_agents.store import list_goldens, record_eval

logger = logging.getLogger(__name__)

MAX_GOLDENS_PER_EVAL = 20  # sync endpoint budget: one LLM call per golden
_COMPARE_ROWS = 50         # compare at most the first N rows (stable sort applied)


# ── Deterministic result comparison ───────────────────────────────────────────

#: Numeric cells compare after rounding to this many places. 2 = cents. A model
#: that writes ROUND(SUM(profit), 2) gives a MORE presentable answer, not a wrong
#: one; comparing at 6 places called it wrong (2026-08-14 Superstore audit: the
#: comparator, not the model, produced the miss). Two decimals is coarse enough
#: for money and rates and fine enough that a genuinely different aggregate —
#: a wrong join, a fan-out — is off by far more than 0.005.
_NUMERIC_PLACES = 2


def _num(f: float) -> str:
    """Canonical numeric spelling: cents for ordinary values; a FRACTION in (0, 1)
    keeps two more places (0.1173, not 0.12), because it is a rate that may be
    compared to its percent (11.73) — rounding it to cents first would destroy the
    very digits the ×100 needs."""
    places = _NUMERIC_PLACES + 2 if 0 < abs(f) < 1 else _NUMERIC_PLACES
    return f"{round(f, places):.{places}f}".rstrip("0").rstrip(".")


def _normalize(rows: list, limit: int = _COMPARE_ROWS) -> list[tuple]:
    """Order-insensitive, type-tolerant view of a result set: every cell to a
    canonical string (numbers via ``_num``), rows sorted."""
    def cell(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return str(v)
        if isinstance(v, (int, float)):
            return _num(float(v))
        # Temporal cells: DATE_TRUNC('year', d) yields 2015-01-01 00:00:00 where
        # EXTRACT(YEAR …) yields 2015 — the same period, two spellings (2026-08-14
        # audit false negative). A midnight-Jan-1 timestamp normalizes to its year;
        # a midnight-first-of-month to 'YYYY-MM'; any other date/datetime to its
        # ISO date, so '2017-06-12' and datetime(2017,6,12) compare equal.
        if isinstance(v, datetime):
            if v.month == 1 and v.day == 1 and (v.hour, v.minute, v.second) == (0, 0, 0):
                return str(v.year)
            if v.day == 1 and (v.hour, v.minute, v.second) == (0, 0, 0):
                return f"{v.year:04d}-{v.month:02d}"
            return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat()
        if isinstance(v, date):
            if v.month == 1 and v.day == 1:
                return str(v.year)
            if v.day == 1:
                return f"{v.year:04d}-{v.month:02d}"
            return v.isoformat()
        s = str(v).strip()
        # A numeric string ('5', '108418.45') normalizes like the number it is, so
        # a VARCHAR-typed aggregate and a DOUBLE one compare equal.
        f = _as_float(s)
        if f is not None:
            return _num(f)
        # An ISO date/datetime STRING is what the observation carries once rows have
        # crossed the SSE/JSON boundary (datetime → '2015-01-01T00:00:00'); the
        # reference is fetched live and carries the object. Both must land on the same
        # period spelling or a correct DATE_TRUNC answer scores wrong (grid 2026-08-15).
        parsed = _parse_iso(s)
        if parsed is not None:
            return cell(parsed)
        return s

    normed = sorted(tuple(cell(c) for c in row) for row in rows)
    return normed[:limit]


def _as_float(s: str):
    """The number a string spells, else None (not-a-number is a normal outcome
    here, not a failure — the cell then tries its other spellings)."""
    try:
        return float(s)
    except ValueError:
        return None


def _parse_iso(s: str):
    """A date/datetime from its ISO string, else None. Strict on shape so a plain
    word or an id ('2015', 'CA-2017-152156') is never taken as a date."""
    if len(s) < 10 or not (s[:4].isdigit() and s[4] == "-" and s[7] == "-"):
        return None
    try:
        if len(s) == 10:
            return date.fromisoformat(s)
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _variants(cell: str) -> set[str]:
    """Every spelling of a reference cell that counts as the same value: the cell,
    and for a FRACTION in (0, 1] both its percent ('0.1173' → '11.73') and its
    cents rounding ('0.1646' → '0.16' — ROUND(AVG(discount), 2) is presentation, and
    the fraction is kept at four places only so the percent path has its digits)."""
    out = {cell}
    f = _as_float(cell)
    if f is None:
        return out
    if 0 < f <= 1:
        out.add(_num(f * 100))
        out.add(f"{round(f, _NUMERIC_PLACES):.{_NUMERIC_PLACES}f}".rstrip("0").rstrip("."))
    return out


def results_match(ref_rows: list, gen_rows: list) -> bool:
    """The golden passes when the generated result carries the reference result:
    identical normalized sets, or the reference's values all present per-row in
    the generated rows (extra columns are fine — a richer correct answer must not
    fail the suite), or — narrowly — the generated rows carry the reference's
    LABEL column and a subset of its measures (the model answered "Tables" to
    "which sub-category loses the most?" and dropped the amount; that names the
    right entity and is not a wrong answer). Row count must agree in every case.
    """
    ref_n, gen_n = _normalize(ref_rows), _normalize(gen_rows)
    if ref_n == gen_n:
        return True
    if not ref_rows or not gen_rows or len(ref_rows) != len(gen_rows):
        return False
    # Column-superset tolerance: each reference row's cells ⊆ some generated row.
    # A reference FRACTION (0.1173) also matches its PERCENT (11.73) — the model wrote
    # the rate the way a person reads it (grid 2026-08-15: a correct return-rate
    # answer scored wrong on the ×100). Only cells in (0, 1] get the variant, so an
    # ordinary count or amount can never match a hundredfold neighbour.
    gen_sets = [set(r) for r in gen_n]
    used: set[int] = set()
    for ref_row in ref_n:
        need = set(ref_row)
        hit = next((i for i, g in enumerate(gen_sets)
                    if i not in used and all(_variants(c) & g for c in need)), None)
        if hit is None:
            break
        used.add(hit)
    else:
        return True
    # Column-subset tolerance, GUARDED: the generated row must be a strict subset
    # of the reference row that keeps the reference's first (label) cell — so a
    # bare number without its entity, or an unrelated column, still fails.
    ref_width = len(ref_n[0]) if ref_n else 0
    if ref_width < 2 or not all(len(g) < ref_width for g in gen_n):
        return False
    ref_sets = [(r[0], set(r)) for r in ref_n]
    used = set()
    for g in gen_n:
        gs = set(g)
        hit = next((i for i, (label, rs) in enumerate(ref_sets)
                    if i not in used and label in gs and gs <= rs), None)
        if hit is None:
            return False
        used.add(hit)
    return True


# ── Generation (the PRODUCTION quick path, stopped before it executes) ───────

def _frame_on_production_path(agent: UserAgent):
    """A generator that frames each golden question the way a user's question is framed.

    AO-1c. Until 2026-10-03 the suite ran its own prompt — `CHAT_PROMPT` with every
    section empty but the schema, the legacy `CHAT_SQL_SYSTEM`, the brief prepended — so
    the "goldens 5/5" chip certified a prompt no user drives: no documents, no packs, no
    schema scope, no governed metrics, no corrections, none of the guards that rewrite a
    statement before it runs. Now it is `answer_core` with ``frame_only``: the same
    prelude, the same model call, the same lint, preflight and literal guards, stopped at
    the statement. The schema argument is ignored on purpose — the production path reads
    the connection itself, through the agent's scope.
    """
    from aughor.db.registry import BUILTIN_ID

    def _gen(question: str, schema: str) -> str:   # noqa: ARG001 — the caller's contract
        from aughor.routers.investigations import answer_core
        result = answer_core(
            question, agent.connection_id or BUILTIN_ID, [],
            emit=lambda _name, _payload: None,
            skip_clarify=True,                      # an evaluation cannot answer a question
            purpose="agent_eval",
            schema_scope=agent.schema_scope or None,
            frame_only=True,
        )
        if result.outcome != "framed":
            # The production path stopped before a statement existed — a refusal, a clarify
            # it could not skip, a failure. Said as the golden's error, never as empty SQL.
            raise RuntimeError(
                f"production path ended '{result.outcome}' before framing SQL"
                + (f": {result.error}" if result.error else ""))
        return (result.sql or "").strip()

    return _gen


# ── The evaluation ────────────────────────────────────────────────────────────

def evaluate_agent(agent: UserAgent, db=None,
                   generate: Optional[Callable[[str, str], str]] = None) -> dict:
    """Run the agent's golden suite; stamp + return the result.

    ``db``/``generate`` are injectable for tests; by default the agent's bound
    connection (or the builtin) is opened and the coder model generates."""
    # AO-6: CERTIFIED goldens only — a candidate has no SQL a person vouched for, and a
    # suite that counted one would be measuring the model against the model.
    goldens = list_goldens(agent.id, status="certified")[:MAX_GOLDENS_PER_EVAL]
    before = dict(agent.last_eval) if isinstance(agent.last_eval, dict) else None
    started = time.monotonic()
    result: dict = {"passed": 0, "total": len(goldens), "per_question": [],
                    "at": datetime.now(timezone.utc).isoformat()}
    if not goldens:
        record_eval(agent.id, result)
        return result

    if db is None:
        from aughor.db.connection import open_connection_for
        from aughor.db.registry import BUILTIN_ID
        db = open_connection_for(agent.connection_id or BUILTIN_ID)
    gen = generate or _frame_on_production_path(agent)
    schema = ""
    try:
        schema = db.get_schema()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "schema introspection for agent eval is best-effort",
                 counter="agents.eval_schema")
    # The engine's dialect rules ride the schema block — parity with the live
    # quick path, which now carries the same `writer_rules` text. Without them
    # the suite measured a path no user drives: both live failure classes on
    # BigQuery (DATE_TRUNC argument order, DATE-typed literals) were rules the
    # dialect block already teaches, unseen by this generator.
    try:
        from aughor.db.dialects import writer_rules
        rules = writer_rules(db)
        if rules:
            schema = f"{schema}\n\n{rules}" if schema else rules
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "dialect rules for agent eval are best-effort",
                 counter="agents.eval_dialect_rules")

    token = activate_agent(agent)
    try:
        for g in goldens:
            entry = {"golden_id": g["id"], "question": g["question"], "passed": False,
                     "error": ""}
            try:
                ref = db.execute("__agent_eval_ref__", g["reference_sql"])
                if ref.error:
                    entry["error"] = f"reference failed: {ref.error}"
                    result["per_question"].append(entry)
                    continue
                sql = gen(g["question"], schema)
                if not sql:
                    entry["error"] = "no SQL generated"
                    result["per_question"].append(entry)
                    continue
                got = db.execute("__agent_eval_gen__", sql)
                if got.error:
                    entry["error"] = f"generated SQL failed: {got.error}"
                else:
                    entry["passed"] = results_match(ref.rows, got.rows)
                    if not entry["passed"]:
                        entry["error"] = "result mismatch vs reference"
            except Exception as exc:  # one golden's failure never aborts the suite
                entry["error"] = f"{type(exc).__name__}: {exc}"
            result["per_question"].append(entry)
            if entry["passed"]:
                result["passed"] += 1
    finally:
        release_agent(token)

    result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    # AO-6/AO-7d — what changed since the last stamp rides on the result: the goldens that
    # newly fail or newly pass, and the pass count before. That delta is the receipt.
    from aughor.custom_agents.learning import eval_diff
    result["diff"] = eval_diff(before, result)
    record_eval(agent.id, result)
    # MLflow — the evaluation as a TOOL span when a trace is active (advisory).
    try:
        from aughor.telemetry import mlflow_tool_span
        with mlflow_tool_span("agent.evaluate",
                              {"agent_id": agent.id, "passed": result["passed"],
                               "total": result["total"]}):
            pass
    except Exception as exc:
        logger.debug("agent-eval telemetry best-effort: %s", exc)
    return result
