"""Semantic operators over SQL result text.

After SQL has done the structured push-down (filter/agg/join in the warehouse), these operators
run LLM judgments over the *text* columns of the residue — the tickets / reviews / notes / incident
write-ups that SQL can't reason over. The split is deliberate: SQL does the structured 99%, the LLM
only ever touches the small text residue.

**Cost is bounded by push-down + an explicit per-operator row cap**, not by a cascade: an operator
*refuses* above ``max_rows`` (surfaced, never a silent truncation) so the caller is pushed to add a
SQL ``WHERE`` / ``LIMIT`` first; within the cap, rows are batched per LLM call to bound call count.

Operators are pure, synchronous functions over a :class:`QueryResult` and return a
:class:`SemanticOpResult` carrying the transformed ``QueryResult`` plus surfaced metadata (rows
in/out, truncation, per-op notes, llm_calls). Any LLM or parse failure degrades gracefully — filter
keeps the row, extract leaves the fields blank — and is recorded in ``notes``; an operator never
raises into the query path.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from aughor.agent.state import QueryResult
from aughor.llm.provider import Role, get_provider

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 200       # refuse above this unless override_cap — push the filter into SQL first
DEFAULT_BATCH = 25           # rows per LLM call
DEFAULT_ROLE: Role = "fast"  # the cheap narrator sub-tier — these are simple per-row text judgments
_MAX_CELL = 1200             # truncate a single text cell before sending to the LLM
_NULL = "NULL"


# ── Result envelope ───────────────────────────────────────────────────────────

@dataclass
class SemanticOpResult:
    """A semantic operator's output: the transformed result plus surfaced metadata."""
    result: QueryResult
    operator: str
    column: str
    input_rows: int
    output_rows: int
    truncated: bool                              # True when the row cap forced a refusal
    notes: list[str] = field(default_factory=list)
    llm_calls: int = 0


# ── Text-column detection ─────────────────────────────────────────────────────
# Rows arrive stringified with no dtypes (db.execute renders every value via str()), so text-ness
# is inferred from the values: a column is "text" if most of its sampled non-null values are not
# numbers, dates, or opaque ids, and read as free text (multi-word or reasonably long).

_NUMERIC_RE = re.compile(r"^-?[\d,]*\.?\d+%?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}|$)")
_ID_RE = re.compile(r"^[0-9a-fA-F][0-9a-fA-F\-]{7,}$")  # uuid-ish / long hex ids


def _looks_textual(v: str) -> bool:
    s = (v or "").strip()
    if not s or s == _NULL:
        return False
    if _NUMERIC_RE.match(s) or _DATE_RE.match(s):
        return False
    return (" " in s) or (len(s) >= 16 and not _ID_RE.match(s))


def detect_text_columns(result: QueryResult, *, sample: int = 50, min_fraction: float = 0.5) -> list[str]:
    """Column names whose sampled non-null values are mostly free text (operator candidates)."""
    out: list[str] = []
    for ci, col in enumerate(result.columns):
        vals = [
            str(row[ci]) for row in result.rows[:sample]
            if ci < len(row) and row[ci] not in (None, _NULL, "")
        ]
        if not vals:
            continue
        if sum(1 for v in vals if _looks_textual(v)) / len(vals) >= min_fraction:
            out.append(col)
    return out


# ── Shared helpers ────────────────────────────────────────────────────────────

def _col_index(result: QueryResult, column: str) -> int:
    try:
        return result.columns.index(column)
    except ValueError:
        return -1


def _cap_refusal(result: QueryResult, max_rows: int, override_cap: bool) -> str | None:
    """The surfaced refusal message when a result exceeds the cap, else None."""
    if not override_cap and result.row_count > max_rows:
        return (
            f"Refused: {result.row_count} rows exceeds the semantic-operator cap of {max_rows}. "
            f"Push the filtering into SQL (add WHERE/LIMIT) so only the text residue reaches the LLM, "
            f"or set override_cap to accept the cost."
        )
    return None


def _materialized_note(result: QueryResult) -> list[str]:
    """When override_cap let an over-500 result through, only the first MAX_ROWS rows are present."""
    if result.row_count > len(result.rows):
        return [f"only the first {len(result.rows)} of {result.row_count} rows were materialized by SQL"]
    return []


# ── Operator: semantic filter ─────────────────────────────────────────────────

class _RowVerdict(BaseModel):
    index: int
    keep: bool


class _FilterBatch(BaseModel):
    verdicts: list[_RowVerdict]


_FILTER_SYS = (
    "You filter rows from a SQL result set by a natural-language predicate evaluated over ONE text "
    "column. For each row you are given its index and the text. Return a verdict for EVERY index: "
    "keep=true if the text satisfies the predicate, keep=false otherwise. Judge only the text shown; "
    "do not invent facts. When the text is genuinely ambiguous, keep the row."
)


# ── Champion-model cost/quality cascade (Palimpzest/LOTUS-style) ──────────────────
# The semops run on the cheap ``fast`` tier. When validation is on, a small spread sample of a
# filter's verdicts is re-judged by the strong "champion" tier; if they disagree beyond a bar,
# the cheap tier is untrusted on this batch and the WHOLE batch is re-run on the champion —
# buying accuracy where the cheap model is wrong, at the cost of one extra sample call per op.
# (This is the deterministic, label-free "champion" quality estimator; a full LOTUS calibrated-
# threshold cascade with statistical guarantees is the future extension.)
CHAMPION_ROLE: Role = "coder"        # the strong tier, vs DEFAULT_ROLE = "fast"
_CHAMPION_ESCALATE = 0.20            # sample disagreement above this → re-run the batch on the champion


def _filter_verdicts(
    rows: list, ci: int, predicate: str, provider, batch: int, indices: list[int],
) -> tuple[set[int], int, list[str]]:
    """Which of ``indices`` the ``provider`` keeps for ``predicate``: (kept_set, llm_calls, notes).

    Fail-open: a row the model omits, or a whole failed batch, is kept (never silently dropped)."""
    kept: set[int] = set()
    llm_calls = 0
    notes: list[str] = []
    for start in range(0, len(indices), max(1, batch)):
        chunk_idx = indices[start:start + batch]
        listing = "\n".join(f"[{gi}] {str(rows[gi][ci])[:_MAX_CELL]}" for gi in chunk_idx)
        try:
            resp = provider.complete(
                system=_FILTER_SYS,
                user=f"Predicate: {predicate}\n\nRows (index: text):\n{listing}\n\nReturn a verdict for every index above.",
                response_model=_FilterBatch,
            )
            llm_calls += 1
            decided = {v.index: v.keep for v in resp.verdicts}
            kept.update(gi for gi in chunk_idx if decided.get(gi, True))
        except Exception as e:  # noqa: BLE001 — operator must never raise into the query path
            logger.warning("semantic_filter: batch failed: %s", e)
            notes.append(f"batch failed ({str(e)[:80]}) — rows kept unchanged")
            kept.update(chunk_idx)
    return kept, llm_calls, notes


def semantic_filter(
    result: QueryResult,
    column: str,
    predicate: str,
    *,
    role: Role = DEFAULT_ROLE,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = DEFAULT_BATCH,
    override_cap: bool = False,
    validate_sample: int = 0,
    champion_role: Role = CHAMPION_ROLE,
) -> SemanticOpResult:
    """Keep only the rows whose ``column`` text satisfies the natural-language ``predicate``.

    With ``validate_sample > 0`` a spread sample of the cheap tier's verdicts is checked against
    the ``champion_role`` tier and the whole batch is escalated on disagreement (see the note above)."""
    if result.error:
        return SemanticOpResult(result, "filter", column, 0, 0, False, [f"upstream SQL error: {result.error}"])

    ci = _col_index(result, column)
    if ci < 0:
        return SemanticOpResult(
            result, "filter", column, result.row_count, result.row_count, False,
            [f"column {column!r} is not in the result ({', '.join(result.columns) or 'no columns'}); no-op"],
        )

    refusal = _cap_refusal(result, max_rows, override_cap)
    if refusal:
        return SemanticOpResult(result, "filter", column, result.row_count, result.row_count, True, [refusal])

    rows = result.rows
    notes = _materialized_note(result)
    all_idx = list(range(len(rows)))
    kept, llm_calls, fnotes = _filter_verdicts(rows, ci, predicate, get_provider(role), batch, all_idx)
    notes.extend(fnotes)

    if validate_sample > 0 and rows and role != champion_role:
        k = min(validate_sample, len(rows))
        step = max(1, len(rows) // k)
        sample_idx = all_idx[::step][:k]            # evenly spread, deterministic
        champ = get_provider(champion_role)
        champ_kept, champ_calls, _ = _filter_verdicts(rows, ci, predicate, champ, batch, sample_idx)
        llm_calls += champ_calls
        disagree = sum(1 for gi in sample_idx if (gi in kept) != (gi in champ_kept))
        rate = disagree / len(sample_idx)
        if rate > _CHAMPION_ESCALATE:
            kept, esc_calls, esc_notes = _filter_verdicts(rows, ci, predicate, champ, batch, all_idx)
            llm_calls += esc_calls
            notes.extend(esc_notes)
            notes.append(
                f"champion cascade: {rate:.0%} sample disagreement > {_CHAMPION_ESCALATE:.0%} — "
                f"escalated all {len(rows)} rows to {champion_role}"
            )
        else:
            notes.append(
                f"champion cascade: validated {len(sample_idx)} rows, {rate:.0%} disagreement — "
                f"cheap tier ({role}) trusted"
            )

    keep_idx = sorted(kept)
    kept_rows = [rows[i] for i in keep_idx]
    new_result = result.model_copy(update={"rows": kept_rows, "row_count": len(kept_rows)})
    notes.insert(0, f"kept {len(kept_rows)} of {len(rows)} rows matching: {predicate}")
    return SemanticOpResult(new_result, "filter", column, len(rows), len(kept_rows), False, notes, llm_calls)


# ── Operator: semantic extract ────────────────────────────────────────────────

class _ExtractedRow(BaseModel):
    index: int
    values: dict[str, str] = {}


class _ExtractBatch(BaseModel):
    rows: list[_ExtractedRow]


_EXTRACT_SYS = (
    "You extract structured fields from ONE free-text column of a SQL result set. For each row you "
    "are given its index and the text, plus a list of fields to extract. Return, for every index, a "
    "values object mapping each field name to the extracted string. Use \"\" (empty string) when a "
    "field is not present in the text. Extract only what the text states; never invent values."
)


# ── Guarded extraction: deterministic value validation + gleaning re-extract ──────
# Pulling a structured value out of free text is where data agents are most fragile: benchmarks show
# frontier models fall back to regex and *never check the result*, so text-heavy extractions collapse
# (DataAgentBench's patent-date tasks score 0% across every model). Aughor's answer is its usual one —
# a deterministic guard over the LLM's output. When ``validate=True`` each extracted value is checked
# against a type inferred from the field's name/description; cells that fail are RE-EXTRACTED with
# targeted feedback in a bounded "gleaning" loop (à la DocETL). Values are only ever re-asked and kept,
# never dropped or blanked, so the operator's never-silently-lose-data contract still holds.

_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "year":   ("year",),
    "date":   ("date", "when ", "timestamp", "datetime", "day "),
    "email":  ("email", "e-mail"),
    "number": ("number", "count", "quantity", "amount", "price", "cost", "total",
               "rate", "percent", "percentage", "age ", "duration", "dollars",
               " usd", "revenue", "salary", "how many"),
}

_TYPE_HINT: dict[str, str] = {
    "year":   "a 4-digit year like 2024",
    "date":   "a date like 2024-01-31",
    "email":  "an email like name@example.com",
    "number": "a plain number like 1234.5 (no words)",
}

_DATE_SHAPE = re.compile(
    r"^(\d{4}[-/]\d{1,2}[-/]\d{1,2}"                                                    # 2024-01-31
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"                                                   # 31/01/2024
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"  # Jan 31, 2024
    r"|\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4})$", # 31 Jan 2024
    re.I,
)
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _infer_expected_type(name: str, description: str) -> str | None:
    """Infer a value-validation type from a field's name + description, or None if untyped."""
    hay = f" {name} {description} ".lower()
    for typ, kws in _TYPE_KEYWORDS.items():
        if any(kw in hay for kw in kws):
            return typ
    return None


def _validate_value(value: str, typ: str) -> str | None:
    """Return None if ``value`` is a valid ``typ``, else a short reason it's rejected.

    An empty string is always valid — extraction legitimately returns "" for an absent field, and we
    never want validation to pressure the model into inventing a value.
    """
    v = (value or "").strip()
    if not v:
        return None
    if typ == "year":
        return None if (v.isdigit() and len(v) == 4 and 1000 <= int(v) <= 2999) else "expected a 4-digit year"
    if typ == "date":
        return None if _DATE_SHAPE.match(v) else "expected a date (e.g. 2024-01-31)"
    if typ == "email":
        return None if _EMAIL_SHAPE.match(v) else "expected an email address"
    if typ == "number":
        cleaned = v.replace(",", "").replace("$", "").replace("%", "").replace("€", "").replace("£", "").strip()
        try:
            float(cleaned)
        except ValueError:
            return "expected a number"
        return None
    return None


def semantic_extract(
    result: QueryResult,
    column: str,
    fields: list[tuple[str, str]],
    *,
    role: Role = DEFAULT_ROLE,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = DEFAULT_BATCH,
    override_cap: bool = False,
    validate: bool = False,
    max_rounds: int = 1,
) -> SemanticOpResult:
    """Pull named ``fields`` (``[(name, description), ...]``) out of ``column``'s text into new columns.

    With ``validate=True`` each extracted value is checked against a type inferred from the field's
    name/description, and off-type cells are re-extracted with targeted feedback for up to
    ``max_rounds`` rounds (guarded extraction — see the module note above).
    """
    field_names = [n for n, _ in fields]

    if result.error:
        return SemanticOpResult(result, "extract", column, 0, 0, False, [f"upstream SQL error: {result.error}"])
    if not field_names:
        return SemanticOpResult(result, "extract", column, result.row_count, result.row_count, False,
                                ["no fields requested; no-op"])

    ci = _col_index(result, column)
    if ci < 0:
        return SemanticOpResult(
            result, "extract", column, result.row_count, result.row_count, False,
            [f"column {column!r} is not in the result ({', '.join(result.columns) or 'no columns'}); no-op"],
        )

    refusal = _cap_refusal(result, max_rows, override_cap)
    if refusal:
        return SemanticOpResult(result, "extract", column, result.row_count, result.row_count, True, [refusal])

    rows = result.rows
    notes = _materialized_note(result)
    # uniquify new column names against the existing ones (col, col_2, ...)
    new_cols = _uniquify(result.columns, field_names)
    extracted: dict[int, dict[str, str]] = {}
    llm_calls = 0
    provider = get_provider(role)
    fields_spec = "; ".join(f"{n}: {d}" if d else n for n, d in fields)

    for start in range(0, len(rows), max(1, batch)):
        chunk = rows[start:start + batch]
        listing = "\n".join(
            f"[{start + i}] {str(chunk[i][ci])[:_MAX_CELL]}" for i in range(len(chunk))
        )
        try:
            resp = provider.complete(
                system=_EXTRACT_SYS,
                user=(
                    f"Fields to extract: {fields_spec}\n\nRows (index: text):\n{listing}\n\n"
                    f"Return values for every index above; use \"\" for absent fields."
                ),
                response_model=_ExtractBatch,
            )
            llm_calls += 1
            for r in resp.rows:
                extracted[r.index] = r.values
        except Exception as e:  # noqa: BLE001 — operator must never raise into the query path
            logger.warning("semantic_extract: batch [%d:%d] failed: %s", start, start + len(chunk), e)
            notes.append(f"batch [{start}:{start + len(chunk)}] failed ({str(e)[:80]}) — fields left blank")

    # ── Guarded validation + gleaning re-extract ──────────────────────────────
    reextract_calls = 0
    still_invalid = 0
    typed = {n: t for (n, d) in fields if (t := _infer_expected_type(n, d))}
    if validate and typed:
        for _round in range(max(0, max_rounds)):
            failing: dict[int, dict[str, str]] = {}
            for gi in range(len(rows)):
                vals = extracted.get(gi, {})
                bad = {n: reason for n, t in typed.items()
                       if (reason := _validate_value(str(vals.get(n, "")), t))}
                if bad:
                    failing[gi] = bad
            if not failing:
                break
            fail_idx = sorted(failing)
            listing = "\n".join(f"[{gi}] {str(rows[gi][ci])[:_MAX_CELL]}" for gi in fail_idx)
            guidance = "; ".join(f"{n} → {_TYPE_HINT[typed[n]]}" for n in typed)
            try:
                resp = provider.complete(
                    system=_EXTRACT_SYS,
                    user=(
                        f"Fields to extract: {fields_spec}\n\n"
                        f"Some earlier values had the WRONG format. Re-extract carefully. "
                        f"Type requirements: {guidance}. Use \"\" only if the field is truly absent.\n\n"
                        f"Rows (index: text):\n{listing}\n\n"
                        f"Return corrected values for every index above."
                    ),
                    response_model=_ExtractBatch,
                )
                reextract_calls += 1
                for r in resp.rows:
                    if r.index in failing:
                        cur = dict(extracted.get(r.index, {}))
                        for n in failing[r.index]:  # overwrite only the fields that failed
                            if n in r.values:
                                cur[n] = r.values[n]
                        extracted[r.index] = cur
            except Exception as e:  # noqa: BLE001 — operator must never raise into the query path
                logger.warning("semantic_extract: re-extract round failed: %s", e)
                notes.append(f"guarded re-extract failed ({str(e)[:80]}) — kept prior values")
                break
        for gi in range(len(rows)):
            vals = extracted.get(gi, {})
            still_invalid += sum(1 for n, t in typed.items() if _validate_value(str(vals.get(n, "")), t))
        llm_calls += reextract_calls

    out_rows: list[list] = []
    for gi, row in enumerate(rows):
        vals = extracted.get(gi, {})
        out_rows.append(list(row) + [str(vals.get(name, "")) for name in field_names])

    new_result = result.model_copy(update={"columns": list(result.columns) + new_cols, "rows": out_rows})
    notes.insert(0, f"extracted {', '.join(new_cols)} from {column} for {len(rows)} rows")
    if validate and typed:
        notes.append(
            f"guarded extraction: validated {len(typed)} typed field(s) over {len(rows)} rows"
            + (f", re-extracted in {reextract_calls} round(s)" if reextract_calls else "")
            + (f", {still_invalid} value(s) still off-type (surfaced, kept)" if still_invalid else "")
        )
    return SemanticOpResult(new_result, "extract", column, len(rows), len(rows), False, notes, llm_calls)


# ── Operator: semantic top-k ──────────────────────────────────────────────────

class _RowScore(BaseModel):
    index: int
    score: float  # 0..1, higher = stronger match to the criterion


class _ScoreBatch(BaseModel):
    scores: list[_RowScore]


_TOPK_SYS = (
    "You rank rows of a SQL result set by how well ONE text column matches a natural-language "
    "criterion. For each row you are given its index and the text. Return a score in [0,1] for EVERY "
    "index: 1 = strongest match to the criterion, 0 = no match. Judge only the text shown; do not "
    "invent facts."
)

_NEUTRAL_SCORE = 0.5  # fail-open: an unscored row is neither buried nor falsely promoted


def semantic_top_k(
    result: QueryResult,
    column: str,
    criterion: str,
    k: int,
    *,
    role: Role = DEFAULT_ROLE,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = DEFAULT_BATCH,
    override_cap: bool = False,
) -> SemanticOpResult:
    """Rank rows by how well ``column``'s text matches ``criterion``; keep the top ``k`` (reordered)."""
    if result.error:
        return SemanticOpResult(result, "top_k", column, 0, 0, False, [f"upstream SQL error: {result.error}"])

    ci = _col_index(result, column)
    if ci < 0:
        return SemanticOpResult(
            result, "top_k", column, result.row_count, result.row_count, False,
            [f"column {column!r} is not in the result ({', '.join(result.columns) or 'no columns'}); no-op"],
        )
    if k < 1:
        return SemanticOpResult(result, "top_k", column, result.row_count, result.row_count, False,
                                [f"k must be >= 1 (got {k}); no-op"])

    refusal = _cap_refusal(result, max_rows, override_cap)
    if refusal:
        return SemanticOpResult(result, "top_k", column, result.row_count, result.row_count, True, [refusal])

    rows = result.rows
    notes = _materialized_note(result)
    scores: dict[int, float] = {}
    llm_calls = 0
    provider = get_provider(role)

    for start in range(0, len(rows), max(1, batch)):
        chunk = rows[start:start + batch]
        listing = "\n".join(
            f"[{start + i}] {str(chunk[i][ci])[:_MAX_CELL]}" for i in range(len(chunk))
        )
        try:
            resp = provider.complete(
                system=_TOPK_SYS,
                user=f"Criterion: {criterion}\n\nRows (index: text):\n{listing}\n\nScore every index above in [0,1].",
                response_model=_ScoreBatch,
            )
            llm_calls += 1
            for s in resp.scores:
                scores[s.index] = s.score
        except Exception as e:  # noqa: BLE001 — operator must never raise into the query path
            logger.warning("semantic_top_k: batch [%d:%d] failed: %s", start, start + len(chunk), e)
            notes.append(f"batch [{start}:{start + len(chunk)}] failed ({str(e)[:80]}) — rows scored neutral")

    keep = min(k, len(rows))
    # stable sort by score desc; ties and unscored rows (neutral) keep original order
    order = sorted(range(len(rows)), key=lambda i: scores.get(i, _NEUTRAL_SCORE), reverse=True)[:keep]
    new_rows = [rows[i] for i in order]
    new_result = result.model_copy(update={"rows": new_rows, "row_count": len(new_rows)})
    notes.insert(0, f"ranked {len(rows)} rows by '{criterion}', kept top {len(new_rows)}")
    return SemanticOpResult(new_result, "top_k", column, len(rows), len(new_rows), False, notes, llm_calls)


# ── Operator: semantic aggregate ──────────────────────────────────────────────

class _Aggregation(BaseModel):
    answer: str


_AGG_SYS = (
    "You synthesize ONE answer from the text values of a single column across many rows of a SQL "
    "result set, following the user's instruction. Base the answer ONLY on the provided text — do not "
    "invent facts or numbers. Be concise and specific."
)


def semantic_aggregate(
    result: QueryResult,
    column: str,
    instruction: str,
    *,
    role: Role = DEFAULT_ROLE,
    max_rows: int = DEFAULT_MAX_ROWS,
    override_cap: bool = False,
    out_column: str = "answer",
) -> SemanticOpResult:
    """Synthesize the text values of ``column`` across all rows into ONE answer (a 1-row result)."""
    if result.error:
        return SemanticOpResult(result, "aggregate", column, 0, 0, False, [f"upstream SQL error: {result.error}"])

    ci = _col_index(result, column)
    if ci < 0:
        return SemanticOpResult(
            result, "aggregate", column, result.row_count, result.row_count, False,
            [f"column {column!r} is not in the result ({', '.join(result.columns) or 'no columns'}); no-op"],
        )

    refusal = _cap_refusal(result, max_rows, override_cap)
    if refusal:
        return SemanticOpResult(result, "aggregate", column, result.row_count, result.row_count, True, [refusal])

    rows = result.rows
    notes = _materialized_note(result)
    listing = "\n".join(f"[{i}] {str(rows[i][ci])[:_MAX_CELL]}" for i in range(len(rows)))
    try:
        resp = get_provider(role).complete(
            system=_AGG_SYS,
            user=f"Instruction: {instruction}\n\nText values (one per row):\n{listing}\n\nReturn one synthesized answer.",
            response_model=_Aggregation,
        )
    except Exception as e:  # noqa: BLE001 — operator must never raise into the query path
        logger.warning("semantic_aggregate: synthesis failed: %s", e)
        notes.insert(0, f"aggregation failed ({str(e)[:80]}) — raw result kept unchanged")
        return SemanticOpResult(result, "aggregate", column, len(rows), len(rows), False, notes, 0)

    answer_result = result.model_copy(update={"columns": [out_column], "rows": [[resp.answer]], "row_count": 1})
    notes.insert(0, f"aggregated {len(rows)} rows of {column} into one answer")
    return SemanticOpResult(answer_result, "aggregate", column, len(rows), 1, False, notes, 1)


def apply_step(
    result: QueryResult,
    operator: str,
    column: str,
    *,
    predicate: str = "",
    fields: list[tuple[str, str]] | None = None,
    criterion: str = "",
    k: int = 10,
    instruction: str = "",
    out_column: str = "answer",
    role: Role = DEFAULT_ROLE,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = DEFAULT_BATCH,
    override_cap: bool = False,
    validate: bool = False,
    max_rounds: int = 1,
    validate_sample: int = 0,
) -> SemanticOpResult:
    """Dispatch one semantic operator by name — the shared entry point for callers (API + agent)."""
    if operator == "filter":
        return semantic_filter(result, column, predicate, role=role, max_rows=max_rows,
                               batch=batch, override_cap=override_cap, validate_sample=validate_sample)
    if operator == "extract":
        return semantic_extract(result, column, fields or [], role=role, max_rows=max_rows,
                                batch=batch, override_cap=override_cap,
                                validate=validate, max_rounds=max_rounds)
    if operator == "top_k":
        return semantic_top_k(result, column, criterion, k, role=role, max_rows=max_rows,
                              batch=batch, override_cap=override_cap)
    if operator == "aggregate":
        return semantic_aggregate(result, column, instruction, role=role, max_rows=max_rows,
                                  override_cap=override_cap, out_column=out_column)
    raise ValueError(
        f"unknown semantic operator {operator!r} (expected 'filter', 'extract', 'top_k', or 'aggregate')"
    )


def _uniquify(existing: list[str], new: list[str]) -> list[str]:
    """Return new column names disambiguated against existing ones and each other."""
    seen = set(existing)
    out: list[str] = []
    for name in new:
        candidate, n = name, 2
        while candidate in seen:
            candidate, n = f"{name}_{n}", n + 1
        seen.add(candidate)
        out.append(candidate)
    return out
