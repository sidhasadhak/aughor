"""Build the resolver's SchemaFacts from a warehouse's layout (P1b).

Two entry points:
  • schema_facts_from_schema_context(ctx) — parses the LLM schema-context string (with real
    dtypes), the right call on the live path; dates come from the column TYPE, not its name.
  • schema_facts_from_table_cols(table_cols, col_types=...) — the lower-level builder.

Identity/FK detection is PREFIX-TOLERANT so real-world keys line up: `customer_unique_id`
(root 'customer_unique') still maps to the `customers` table (base 'customer'). Kept pure +
testable; the live wrapper just hands us the connection's schema context.
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.tools.schema import fk_root
from aughor.packs.resolver import SchemaFacts, TableFact, ColumnFact

# Name fallback only when a column has no known dtype.
_DATE_KW = ("date", "_at", "_on", "_ts", "_dt", "timestamp", "signup", "joined", "created", "approved")

_TABLE_RE = re.compile(r"^TABLE:\s+([\w.]+)")
_COL_RE = re.compile(r"^\s{2}(\S+)\s{2,}(\S+)")   # "  col  TYPE  [desc]"


def _base(table: str) -> str:
    b = table.split(".")[-1].lower()
    b = re.sub(r"^(dim|fact|tbl|stg)_", "", b)
    b = re.sub(r"_(dim|fact|tbl)$", "", b)
    return b.rstrip("s")


def _is_date_type(dtype: Optional[str]) -> bool:
    d = (dtype or "").upper()
    return any(k in d for k in ("DATE", "TIMESTAMP", "TIME"))


def _id_match(root: Optional[str], base: str) -> bool:
    """Does an FK-root identify rows of `base`? Tolerant of compound keys: exact, or one is a
    prefix of the other with enough shared length (customer_unique ↔ customer)."""
    if not root:
        return False
    if root == base:
        return True
    if root.startswith(base) and len(base) >= 4:
        return True
    if base.startswith(root) and len(root) >= 4:
        return True
    return False


def _match_target(root: str, base_to_table: dict) -> Optional[str]:
    """The table a foreign-key root points at (exact base first, then prefix-tolerant)."""
    if root in base_to_table:
        return base_to_table[root]
    cands = [(b, t) for b, t in base_to_table.items()
             if (b.startswith(root) or root.startswith(b)) and min(len(b), len(root)) >= 4]
    if not cands:
        return None
    cands.sort(key=lambda bt: len(bt[0]), reverse=True)   # longest base wins
    return cands[0][1]


def schema_facts_from_table_cols(
    table_cols: dict[str, list[str]],
    business_model: str = "",
    row_counts: Optional[dict[str, int]] = None,
    col_types: Optional[dict[str, dict[str, str]]] = None,
) -> SchemaFacts:
    """Derive SchemaFacts. `col_types` ({table:{col:dtype}}) makes date detection dtype-based
    (kills name false positives like lead_time_days BIGINT); without it, names are the fallback.
    Pure; never raises."""
    row_counts = row_counts or {}
    col_types = col_types or {}
    bases = {t: _base(t) for t in table_cols}
    base_to_table: dict[str, str] = {}
    for t, b in bases.items():
        base_to_table.setdefault(b, t)

    tables: list[TableFact] = []
    for t, cols in table_cols.items():
        b = bases[t]
        tt = col_types.get(t, {})
        col_facts: list[ColumnFact] = []
        refs: dict[str, str] = {}
        for c in (cols or []):
            root = fk_root(c)
            dtype = tt.get(c)
            is_date = _is_date_type(dtype) if dtype else any(k in c.lower() for k in _DATE_KW)
            is_id = _id_match(root, b)
            col_facts.append(ColumnFact(name=c, dtype=dtype or "", is_date=is_date, is_identity=is_id))
            if root and not is_id:
                tgt = _match_target(root, base_to_table)
                if tgt and tgt != t:
                    refs[c] = tgt
        tables.append(TableFact(name=t, columns=col_facts, references=refs,
                                row_count=int(row_counts.get(t, 0))))
    return SchemaFacts(tables=tables, business_model=business_model)


def schema_facts_from_schema_context(schema_context: str, business_model: str = "") -> SchemaFacts:
    """Parse the LLM schema-context string (real dtypes) → SchemaFacts. The right entry point
    on the live path."""
    typed: dict[str, list[tuple[str, str]]] = {}
    current: Optional[str] = None
    for line in (schema_context or "").splitlines():
        m = _TABLE_RE.match(line)
        if m:
            current = m.group(1)
            typed[current] = []
            continue
        if current is None or line.strip().startswith("--"):
            continue
        cm = _COL_RE.match(line)
        if cm:
            typed[current].append((cm.group(1), cm.group(2)))
    table_cols = {t: [c for c, _ in cols] for t, cols in typed.items()}
    col_types = {t: {c: dt for c, dt in cols} for t, cols in typed.items()}
    return schema_facts_from_table_cols(table_cols, business_model=business_model, col_types=col_types)
