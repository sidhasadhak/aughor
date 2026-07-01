"""Agent context manifest — make the working context an explicit, inspectable object (P2).

Aughor already scopes the schema it shows the agent (schema-linking → FK/temporal
expansion → a 10-table cap). But that scope is invisible: the user can't see which
tables the agent looked at, how big the context is, or trim it. This module turns
the assembled schema string into a structured manifest (tables · token budget · join
hints) that the stream surfaces as a ``context_assembled`` event, and provides
:func:`rescope_schema` so the user can drop or add tables and see the token delta —
the AI FDE "resource ribbon + chat outline" idea, grounded in Aughor's own
schema helpers.

Token counts are ESTIMATES (chars/4) for a live budget bar — deliberately cheap and
dependency-free; the ledger's :mod:`aughor.kernel.metering` remains the source of
truth for actual spend. This mirrors the metering module's "honest, always-available
signal" stance rather than pretending to a precise pre-count.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from aughor.db.schema_render import parse_schema_tables
from aughor.tools.schema import compute_join_map, fk_neighbor_expand, get_schema_for_tables

# Rough tokens-per-char for English + SQL identifiers. Good enough for a budget bar;
# NOT billing. ~4 chars/token is the common GPT-family rule of thumb.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate for a context-budget display."""
    return (len(text or "") + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN


@dataclass
class ContextManifest:
    tables: list[str] = field(default_factory=list)
    table_count: int = 0
    estimated_tokens: int = 0
    joins: list[dict] = field(default_factory=list)   # [{from, to, kind}]

    def to_dict(self) -> dict:
        return asdict(self)


def build_context_manifest(schema: str) -> ContextManifest:
    """Structured view of an assembled schema string: which tables are in scope, the
    estimated token budget they cost, and the join edges between them."""
    table_cols = parse_schema_tables(schema or "")
    tables = list(table_cols.keys())
    joins: list[dict] = []
    try:
        jm = compute_join_map(table_cols)
        for j in jm.get("joins", []):
            # compute_join_map edges are {t1,c1,t2,c2,match}; render as from/to/kind.
            if isinstance(j, dict) and j.get("t1") and j.get("t2"):
                joins.append({
                    "from": f"{j['t1']}.{j.get('c1', '')}".rstrip("."),
                    "to": f"{j['t2']}.{j.get('c2', '')}".rstrip("."),
                    "kind": j.get("match") or "",
                })
    except Exception:
        from aughor.kernel.errors import tolerate
        tolerate(Exception("join-map best-effort"), "context manifest join hints", counter="context_manifest")
    return ContextManifest(
        tables=tables,
        table_count=len(tables),
        estimated_tokens=estimate_tokens(schema),
        joins=joins,
    )


def rescope_schema(full_schema: str, *, keep: list[str] | None = None,
                   exclude: list[str] | None = None, add: list[str] | None = None,
                   expand_fk: bool = True, cap: int = 10) -> tuple[str, ContextManifest]:
    """Re-derive the scoped schema after a user edit and report the new manifest.

    ``keep`` — an explicit table allowlist (overrides everything else when given).
    ``exclude`` / ``add`` — drop or add tables relative to the full schema's set.
    ``expand_fk`` — pull in FK-neighbour bridge tables so joins still resolve (capped).
    Returns (scoped_schema, manifest). Deterministic; no LLM, no warehouse round-trip."""
    all_tables = list(parse_schema_tables(full_schema or "").keys())
    if keep:
        selected = [t for t in keep if t in all_tables]
    else:
        excl = {e.strip().lower() for e in (exclude or [])}
        selected = [t for t in all_tables if t.strip().lower() not in excl]
        for a in (add or []):
            if a in all_tables and a not in selected:
                selected.append(a)
    if expand_fk and selected:
        selected = fk_neighbor_expand(full_schema, selected, cap=cap)
    scoped = get_schema_for_tables(full_schema, selected) if selected else ""
    return scoped, build_context_manifest(scoped)
