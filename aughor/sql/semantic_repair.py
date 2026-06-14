"""Deterministic semantic column repair — the invention-starvation fix.

`repair_identifiers` fixes a *casing/separator* slip (`customer_id`→`customerID`). But the
Phase-8 generator also invents *semantic* renames the schema doesn't have — a real-sounding
column that means the same thing as a real one under a different name. On the Bakehouse
workspace these recur and starve a domain: it burns its whole budget inventing

    location_country / location_region / region   (real: country / state / continent)
    total_amount                                   (real: totalPrice)

The grounding gate (`unresolved_identifiers`) correctly SKIPS every one — so errors stay 0 —
but the domain produces 0 findings. The schema block lists the real columns and `dead_refs`
lists the bad ones, yet the model's prior overrides both.

This rewrites such an invented column to the schema's real one BEFORE the grounding gate, so
the question runs instead of being skipped. It is conservative by construction — the single
most important property, because a WRONG map silently answers a different question:

  * it only touches a column that does NOT resolve (so a real column is never rewritten);
  * it maps via a CONCEPT (geo level, money grain), and only when EXACTLY ONE real column in
    the query's in-scope tables carries that concept — two candidates (e.g. `state` AND
    `province`, or `totalPrice` AND `revenue`) → ambiguous → left for the gate to skip;
  * it never invents a concept: a column with no concept (`segment`, `customer_type`) is a
    genuine hallucination and is left alone;
  * it runs only when every base table is known, so an incomplete schema can't mislead it;
  * any parse problem returns the original SQL unchanged.

Downstream defence-in-depth still applies: the intent-preservation / metric-drift / grain
guards and the `dry_run` backstop all run AFTER this, so a bad rewrite that slips through is
caught before a finding is stored.
"""
from __future__ import annotations


def _norm(name: str) -> str:
    """Separator/case-insensitive key: 'customer_id' and 'customerID' → 'customerid'."""
    return (name or "").replace("_", "").replace("-", "").replace(" ", "").lower()


def _concept(name: str) -> str | None:
    """Canonical semantic concept of a column name, or None when it has no concept or an
    ambiguous one. Two columns with the same concept mean the same thing (a `location_country`
    and a `country`; a `total_amount` and a `totalPrice`) — that equivalence, plus a unique
    target, is what makes a rewrite safe.

    MONEY is checked first and is GRAIN-AWARE: `total_amount`/`totalPrice`→money_total,
    `unitPrice`→money_unit, `line_total`→money_line, so a total is never mapped onto a unit
    price. A bare money word (`price`/`value`/`cost` with no grain) is deliberately concept-less
    (too ambiguous to map). GEO returns a level only when exactly one geo word is present."""
    n = _norm(name)
    if not n:
        return None

    # ── money (grain-aware) ────────────────────────────────────────────────
    _MONEY = ("amount", "price", "total", "revenue", "cost", "spend", "sales",
              "gross", "paid", "charge", "subtotal", "grandtotal")
    if any(w in n for w in _MONEY):
        if "line" in n or "item" in n:
            return "money_line"
        if "unit" in n or "perunit" in n or "each" in n:
            return "money_unit"
        if ("total" in n or "grand" in n or "gross" in n or "revenue" in n
                or "amount" in n or "sales" in n or "paid" in n or "subtotal" in n):
            return "money_total"
        return None    # bare 'price'/'value'/'cost' — too ambiguous to map

    # ── geography (exactly one level) ──────────────────────────────────────
    geos: list[str] = []
    if "continent" in n:
        geos.append("geo_continent")
    if "country" in n or "nation" in n:
        geos.append("geo_country")
    if "province" in n or "state" in n or "region" in n:
        geos.append("geo_region")
    if "city" in n or "town" in n or "municipal" in n:
        geos.append("geo_city")
    if "district" in n or "county" in n or "borough" in n:
        geos.append("geo_district")
    if "postal" in n or "zip" in n:
        geos.append("geo_postal")
    return geos[0] if len(geos) == 1 else None


def repair_semantic_columns(
    sql: str, table_cols: dict[str, list[str]], dialect: str = "duckdb"
) -> str:
    """Rewrite an UNRESOLVED column to the schema's real one when they share a concept and the
    target is unique among the query's in-scope tables. Returns `sql` unchanged when nothing is
    repaired, the schema is incomplete for the query, or on any parse failure."""
    if not sql or not table_cols:
        return sql
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql
    if tree is None:
        return sql

    by_qualified: dict[str, list[str]] = {}
    by_bare: dict[str, list[list[str]]] = {}
    for tname, cols in table_cols.items():
        by_qualified[tname.lower()] = cols or []
        by_bare.setdefault(tname.split(".")[-1].lower(), []).append(cols or [])

    ctes = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    real_cols: set[str] = set()        # exact names of in-scope real columns
    for t in tree.find_all(exp.Table):
        bare = (t.name or "").lower()
        if not bare or bare in ctes:
            continue
        qual = ".".join(p for p in (t.catalog, t.db, t.name) if p).lower()
        is_qualified = bool(t.args.get("db") or t.args.get("catalog"))
        if qual in by_qualified:
            cols = by_qualified[qual]
        elif (not is_qualified) and bare in by_bare:
            cols = [c for group in by_bare[bare] for c in group]
        else:
            return sql                 # unknown table → incomplete schema, do not guess
        real_cols.update(cols)

    # exotic sources can supply columns outside table_cols → don't touch
    if any(tree.find_all(exp.Unnest)) or any(tree.find_all(exp.Values)) or any(tree.find_all(exp.Lateral)):
        return sql
    if not real_cols:
        return sql

    real_norms = {_norm(c) for c in real_cols}
    defined: set[str] = {_norm(n) for n in ctes}
    for a in tree.find_all(exp.Alias):
        if a.alias:
            defined.add(_norm(a.alias))
    for ta in tree.find_all(exp.TableAlias):
        if ta.name:
            defined.add(_norm(ta.name))
        for c in ta.columns:
            if getattr(c, "name", ""):
                defined.add(_norm(c.name))

    # concept → the set of real columns that carry it (unique target = safe to map)
    concept_to_real: dict[str, set[str]] = {}
    for c in real_cols:
        k = _concept(c)
        if k:
            concept_to_real.setdefault(k, set()).add(c)

    changed = False
    for col in tree.find_all(exp.Column):
        name = col.name
        if not name or "*" in name:
            continue
        n = _norm(name)
        if n in real_norms or n in defined:        # already valid / a query-defined name
            continue
        k = _concept(name)
        if not k:
            continue
        targets = concept_to_real.get(k)
        if targets and len(targets) == 1:
            real = next(iter(targets))
            if _norm(real) != n:
                col.set("this", exp.to_identifier(real))
                changed = True

    return tree.sql(dialect=dialect) if changed else sql
