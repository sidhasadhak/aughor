"""DE-5f (ROADMAP §3.51) — the rows related to a value, through the joins the data bears out.

A cell in `orders.buyer` has related rows in `customers` where `id` holds the same value — IF the two columns
are joined by something better than a shared name: the engine's declared foreign key (DE-3c), the value
overlap the join guard measured (`sql/join_guard.py`), or the ontology's relationship, which carries both and
the measured cardinality. This module gathers those edges for one column, says each one's evidence in the
catalog's own words, and composes the one statement that opens the rows — with the value BOUND, never spelled
into the SQL.

A join the data rejected is listed with its evidence and not opened; a name match nobody probed is listed and
not opened either. The rows are never opened on a guess — which is the difference between this door and a
foreign-key click (the study's §3.5: dbx opens the row a declared key points to; a declared key the data does
not bear out opens into missing rows).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

#: The verdicts, and which of them open rows.
OPENABLE = frozenset({"verified", "declared"})
_FLIP = {"1:N": "N:1", "N:1": "1:N"}


@dataclass
class RelatedJoin:
    table: str
    column: str
    other_table: str
    other_column: str
    #: How the edge was found: `declared` (the engine's own key), `exact` or `inferred` (the name inference).
    match: str
    #: The measured containment of the two columns' values; None when nobody probed it.
    overlap: Optional[float]
    #: `verified` (the values bear it out), `declared` (the engine says so, not probed), `disputed` (declared,
    #: and the values disagree), `rejected` (a name match the values disprove), `unprobed` (a name match alone).
    verdict: str
    #: The ontology's measured cardinality from this column's side, when it has one.
    cardinality: Optional[str]
    #: `ontology` or `join_map` — where the edge was read.
    source: str
    openable: bool
    sentence: str

    def as_dict(self) -> dict:
        return asdict(self)


def _base(table: str) -> str:
    return (table or "").split(".")[-1].strip('"`[]').lower()


def _threshold() -> float:
    from aughor.sql.join_guard import _THRESHOLD
    return float(_THRESHOLD)


def verdict_for(match: str, overlap: Optional[float], *, rejected: bool) -> str:
    if rejected:
        return "disputed" if match == "declared" else "rejected"
    if overlap is None or overlap < 0:
        return "declared" if match == "declared" else "unprobed"
    return "verified"


def sentence_for(match: str, overlap: Optional[float], verdict: str, cardinality: Optional[str]) -> str:
    """The evidence in the catalog's words (`render_verified_joins`), so a person reads the same claim here
    that the model reads in the prompt."""
    if verdict == "disputed":
        s = f"DECLARED foreign key, but only {overlap:.0%} value overlap — the declaration and the data disagree"
    elif verdict == "rejected":
        s = f"{overlap:.0%} value overlap — the columns share a name and not their values"
    elif verdict == "declared":
        s = "declared foreign key — not probed"
    elif verdict == "unprobed":
        s = "name match — not probed, so not opened on the name alone"
    else:
        s = f"{overlap:.0%} value overlap" + ("; declared foreign key" if match == "declared" else "")
    if cardinality:
        s += f"; {cardinality}"
    return s


def _edge(table: str, column: str, other_table: str, other_column: str, match: str, overlap: Optional[float],
          *, rejected: bool, cardinality: Optional[str], source: str) -> RelatedJoin:
    verdict = verdict_for(match, overlap, rejected=rejected)
    return RelatedJoin(table=table, column=column, other_table=other_table, other_column=other_column, match=match,
                       overlap=overlap, verdict=verdict, cardinality=cardinality, source=source,
                       openable=verdict in OPENABLE,
                       sentence=sentence_for(match, overlap, verdict, cardinality))


def related_joins(db, conn_id: str, table: str, column: str, *, schema_text: str,
                  ontology: Any = None) -> tuple[list[RelatedJoin], dict]:
    """Every join edge touching ``table.column``, in either direction, with its evidence — the ontology's
    relationships first (they carry overlap and cardinality), then the verified join map for the pairs the
    ontology does not hold (a table that resolved to no object type). Returns the edges and the notes a
    caller says beside them (`ontology`: built or not; `join_map`: why it could not be read, when it could not)."""
    notes: dict = {"ontology": "built" if ontology is not None else "not built"}
    out: list[RelatedJoin] = []
    seen: set[tuple[str, str]] = set()
    tkey, ckey = _base(table), (column or "").lower()
    threshold = _threshold()

    def _take(ft: str, fc: str, tt: str, tc: str) -> bool:
        if _base(ft) != tkey or (fc or "").lower() != ckey:
            return False
        k = (_base(tt), (tc or "").lower())
        if k in seen:
            return False
        seen.add(k)
        return True

    for rel in (getattr(ontology, "relationships", None) or {}).values():
        conf = getattr(rel, "join_confidence", "inferred")
        match = "declared" if conf == "declared" else ("exact" if conf in ("exact", "verified") else "inferred")
        ov = getattr(rel, "value_overlap", None)
        rejected = ov is not None and ov < threshold
        card = getattr(rel, "measured_cardinality", None) or None
        if _take(rel.from_table, rel.from_col, rel.to_table, rel.to_col):
            out.append(_edge(table, column, rel.to_table, rel.to_col, match, ov, rejected=rejected,
                             cardinality=card, source="ontology"))
        if _take(rel.to_table, rel.to_col, rel.from_table, rel.from_col):
            out.append(_edge(table, column, rel.from_table, rel.from_col, match, ov, rejected=rejected,
                             cardinality=_FLIP.get(card, card) if card else None, source="ontology"))

    try:
        from aughor.db.schema_render import parse_schema_tables
        from aughor.sql.join_guard import verified_join_edges
        from aughor.tools.schema import join_map_for
        table_cols = parse_schema_tables(schema_text or "")
        joins = (join_map_for(db, table_cols, cache_key=conn_id) or {}).get("joins") or []
        verified, rejected_edges = verified_join_edges(db, joins, cache_key=conn_id)
    except Exception as exc:
        notes["join_map"] = f"not read: {exc}"
        verified, rejected_edges = [], []
    for vj, is_rejected in [*((v, False) for v in verified), *((r, True) for r in rejected_edges)]:
        ov = vj.overlap if vj.overlap is not None and vj.overlap >= 0 else None
        for ft, fc, tt, tc in ((vj.t1, vj.c1, vj.t2, vj.c2), (vj.t2, vj.c2, vj.t1, vj.c1)):
            if _take(ft, fc, tt, tc):
                out.append(_edge(table, column, tt, tc, vj.match, ov, rejected=is_rejected,
                                 cardinality=None, source="join_map"))
    return out, notes


def find_edge(joins: list[RelatedJoin], other_table: str, other_column: str) -> Optional[RelatedJoin]:
    for j in joins:
        if _base(j.other_table) == _base(other_table) and j.other_column.lower() == (other_column or "").lower():
            return j
    return None


def related_sql(db, other_table: str, other_column: str, schema: Optional[str] = None) -> str:
    """The statement that opens the related rows: every column of the other table where the joined column
    holds the bound value ``:v``. Identifiers are quoted for the engine; the value never enters the text."""
    from aughor.db.quoting import ident_quote
    q = ident_quote(db)
    table = other_table if ("." in other_table or not schema or schema in ("main", "public")) else f"{schema}.{other_table}"
    qt = ".".join(f"{q}{part.strip(q)}{q}" for part in table.split("."))
    return f"SELECT * FROM {qt} WHERE {q}{other_column}{q} = :v"


def related_label(other_table: str, table: str, column: str, value: Any) -> str:
    shown = str(value)
    if len(shown) > 24:
        shown = shown[:23] + "…"
    return f"{_base(other_table)} rows related to {_base(table)}.{column} = {shown}"
