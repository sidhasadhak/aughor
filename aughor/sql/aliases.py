"""Deterministic unique-output-column aliasing (R7 — a sqlx-lesson compile pass).

A result is only addressable by column NAME if its column names are distinct. LLM-
written NL2SQL routinely breaks that: ``SELECT a.id, b.id FROM a JOIN b`` yields two
columns both called ``id``; a reused ``AS total`` yields two ``total``s. The engine
returns them positionally, but every name-keyed consumer downstream — chart column
selection, the result renderer, column-based guards — sees only one and silently
drops the rest.

This pass renames the SECOND-and-later occurrence of a duplicated output name with a
numeric suffix (``id`` → ``id``, ``id_1``), leaving the first untouched, so the
result stays name-addressable. Pure AST via sqlglot, deterministic, fail-open:
anything it can't do safely returns None and the original SQL executes unchanged.
"""
from __future__ import annotations

from typing import Optional


def uniquify_output_columns(sql: str, dialect: str = "duckdb") -> Optional[str]:
    """Rewrite ``sql`` so the top-level SELECT's output columns are uniquely named.

    Returns the rewritten SQL, or ``None`` when nothing needs changing or it can't be
    done safely — a parse failure, a non-SELECT top (set operations take their names
    from the first branch and are riskier to touch), a ``SELECT *`` (the expanded
    names aren't knowable without the schema), or no duplicates. Never raises."""
    try:
        import sqlglot
        from sqlglot import expressions as exp
    except Exception:
        return None
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        return None
    # Only a plain top-level SELECT has user-visible, safely-rewritable output names.
    if not isinstance(tree, exp.Select):
        return None

    projections = list(tree.selects)
    # A star projection (SELECT *, t.*) hides its real output names — can't uniquify
    # safely. (COUNT(*) etc. are fine — they carry a normal output name, not a star.)
    for proj in projections:
        if isinstance(proj, exp.Star) or (
            isinstance(proj, exp.Column) and isinstance(proj.this, exp.Star)
        ):
            return None

    # Reserve EVERY existing output name first, so a rename can't collide with a name
    # that appears later (e.g. `id, id, id_1` must send the 2nd `id` to `id_2`).
    reserved = {p.alias_or_name.lower() for p in projections if p.alias_or_name}
    occur: dict[str, int] = {}
    new_projections = []
    changed = False
    for proj in projections:
        name = proj.alias_or_name
        if not name:
            new_projections.append(proj)   # an unnamed expression carries no addressable name
            continue
        key = name.lower()
        occur[key] = occur.get(key, 0) + 1
        if occur[key] == 1:
            new_projections.append(proj)   # first occurrence keeps its name
            continue
        i = occur[key] - 1
        new_name = f"{name}_{i}"
        while new_name.lower() in reserved:
            i += 1
            new_name = f"{name}_{i}"
        reserved.add(new_name.lower())
        if isinstance(proj, exp.Alias):
            proj.set("alias", exp.to_identifier(new_name))
            new_projections.append(proj)
        else:
            new_projections.append(proj.as_(new_name))
        changed = True

    if not changed:
        return None
    tree.set("expressions", new_projections)
    try:
        return tree.sql(dialect=dialect)
    except Exception:
        return None
