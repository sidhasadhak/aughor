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


def semantic_filter(
    result: QueryResult,
    column: str,
    predicate: str,
    *,
    role: Role = DEFAULT_ROLE,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = DEFAULT_BATCH,
    override_cap: bool = False,
) -> SemanticOpResult:
    """Keep only the rows whose ``column`` text satisfies the natural-language ``predicate``."""
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
    keep_idx: list[int] = []
    llm_calls = 0
    provider = get_provider(role)

    for start in range(0, len(rows), max(1, batch)):
        chunk = rows[start:start + batch]
        listing = "\n".join(
            f"[{start + i}] {str(chunk[i][ci])[:_MAX_CELL]}" for i in range(len(chunk))
        )
        try:
            resp = provider.complete(
                system=_FILTER_SYS,
                user=f"Predicate: {predicate}\n\nRows (index: text):\n{listing}\n\nReturn a verdict for every index above.",
                response_model=_FilterBatch,
            )
            llm_calls += 1
            decided = {v.index: v.keep for v in resp.verdicts}
            # fail-open on a row the model didn't return: keep it (never silently drop data)
            keep_idx.extend(start + i for i in range(len(chunk)) if decided.get(start + i, True))
        except Exception as e:  # noqa: BLE001 — operator must never raise into the query path
            logger.warning("semantic_filter: batch [%d:%d] failed: %s", start, start + len(chunk), e)
            notes.append(f"batch [{start}:{start + len(chunk)}] failed ({str(e)[:80]}) — rows kept unchanged")
            keep_idx.extend(range(start, start + len(chunk)))

    kept = [rows[i] for i in keep_idx]
    new_result = result.model_copy(update={"rows": kept, "row_count": len(kept)})
    notes.insert(0, f"kept {len(kept)} of {len(rows)} rows matching: {predicate}")
    return SemanticOpResult(new_result, "filter", column, len(rows), len(kept), False, notes, llm_calls)


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


def semantic_extract(
    result: QueryResult,
    column: str,
    fields: list[tuple[str, str]],
    *,
    role: Role = DEFAULT_ROLE,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = DEFAULT_BATCH,
    override_cap: bool = False,
) -> SemanticOpResult:
    """Pull named ``fields`` (``[(name, description), ...]``) out of ``column``'s text into new columns."""
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

    out_rows: list[list] = []
    for gi, row in enumerate(rows):
        vals = extracted.get(gi, {})
        out_rows.append(list(row) + [str(vals.get(name, "")) for name in field_names])

    new_result = result.model_copy(update={"columns": list(result.columns) + new_cols, "rows": out_rows})
    notes.insert(0, f"extracted {', '.join(new_cols)} from {column} for {len(rows)} rows")
    return SemanticOpResult(new_result, "extract", column, len(rows), len(rows), False, notes, llm_calls)


def apply_step(
    result: QueryResult,
    operator: str,
    column: str,
    *,
    predicate: str = "",
    fields: list[tuple[str, str]] | None = None,
    role: Role = DEFAULT_ROLE,
    max_rows: int = DEFAULT_MAX_ROWS,
    batch: int = DEFAULT_BATCH,
    override_cap: bool = False,
) -> SemanticOpResult:
    """Dispatch one semantic operator by name — the shared entry point for callers (API + agent)."""
    if operator == "filter":
        return semantic_filter(result, column, predicate, role=role, max_rows=max_rows,
                               batch=batch, override_cap=override_cap)
    if operator == "extract":
        return semantic_extract(result, column, fields or [], role=role, max_rows=max_rows,
                                batch=batch, override_cap=override_cap)
    raise ValueError(f"unknown semantic operator {operator!r} (expected 'filter' or 'extract')")


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
