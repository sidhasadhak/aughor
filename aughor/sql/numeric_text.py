"""Numbers stored as text — detection primitives.

A number wearing formatting — ``₹1,099``, ``$1,234.56``, ``64%``, ``24,269`` — is
VARCHAR to every reader, and a bare ``TRY_CAST`` of it yields NULL for EVERY row.
That is not a cosmetic problem. Downstream, a metric planner sees only the declared
type, writes ``SUM(TRY_CAST(price AS DOUBLE))`` over a column that is 100% populated,
gets NULL, and reports *"no price data is recorded"* — a data-quality verdict on data
that is entirely present. Measured on a 1,465-row retail export: 0/1465 values cast
bare; 1465/1465 cast once the decoration is stripped.

Two consumers share these primitives, which is why they live here rather than in
either one:

* ``aughor.connectors.file.local_upload`` — re-types such columns at INGEST, so the
  problem never reaches the planner for an uploaded file.
* ``aughor.explorer.verify`` — DIAGNOSES the residue at runtime for sources we do not
  ingest (a warehouse connection we only read), so an all-NULL metric is reported as
  *"populated text that needs cleaning"* rather than as missing data.
"""
from __future__ import annotations

# Currency symbols we recognise as decoration. Deliberately a fixed set: any broader
# rule (e.g. "a leading non-digit") would swallow identifiers like 'ID123'.
CURRENCY_CHARS = "$€£¥₹₽₩₪₦₨฿₫₴₺¢"

# The shape a value must match to be read as a decorated number. Anchored and strict,
# because this gate — NOT the strip below — is what makes the transform safe.
#
# The digit body admits three groupings:
#   • plain            1099
#   • Western commas   1,099 · 1,234,567     (groups of 3)
#   • Indian commas    1,39,900 · 2,50,000   (lakh/crore: 2-digit groups, 3-digit tail)
# Every comma form REQUIRES a final 3-digit group, which is exactly what separates a
# thousands separator from a European decimal comma: '1,5' and '1.234,56' fail to
# match and are left alone, rather than being silently multiplied by 10 or 100.
COSTUME_SHAPE = (
    r"^[+-]?[" + CURRENCY_CHARS + r"]?\s*[+-]?"       # sign and/or currency prefix
    r"(\d{1,3}(,\d{2,3})*,\d{3}|\d+)"                 # digit body (see groupings above)
    r"(\.\d+)?"                                       # decimal tail
    r"\s*[%" + CURRENCY_CHARS + r"]?$"                # percent / trailing currency
)

# Evidence that a column is actually DECORATED rather than plainly numeric. Without
# this the probe would also fire on a VARCHAR column of bare digits — which is the
# ordinary type-suggestion path's job, at its own threshold. Keeping the two disjoint
# means this path only ever changes columns nothing else was going to type.
COSTUME_MARK = r"[%," + CURRENCY_CHARS + r"]"

# Share of non-empty values that must match the shape before we re-type the column.
COSTUME_THRESHOLD = 0.95

# Cast targets this detector may choose for itself.
COSTUME_TYPES = {"BIGINT", "DOUBLE"}

# Numeric types a CALLER may additionally request for a decorated column. Wider than
# the set above because a person picking a type in the import UI reasonably says
# INTEGER for a whole-rupee price or DECIMAL for a rate — and any of these means "I
# want a number here", which is only reachable by stripping the decoration first. Both
# sets are interpolated into SQL on every reload, so both stay allow-lists.
COSTUME_CAST_TYPES = COSTUME_TYPES | {"INTEGER", "DECIMAL"}


def sql_str(s: str) -> str:
    """Escape a Python string for embedding as a single-quoted SQL literal."""
    return s.replace("'", "''")


def costume_clean_sql(col: str, cast_to: str = "DOUBLE") -> str:
    """SQL that strips a decorated number down to a plain one and casts it.

    The strip is deliberately blunt — remove every character that cannot belong to a
    number — so it is applied ONLY to values that match :data:`COSTUME_SHAPE`. The gate
    carries the correctness; this carries the work.

    That per-row guard is load-bearing, not decoration. Detection accepts a column at
    95%, so up to one value in twenty may not match the shape, and a blunt strip mangles
    exactly those: an accounting negative '(₹1,234)' loses its parentheses and returns
    as +1234 — a sign flip, inside a column now advertised as clean numeric. A
    non-conforming value becomes NULL instead, which is a visible gap rather than a
    plausible wrong number.
    """
    esc = col.replace('"', '""')
    if cast_to not in COSTUME_CAST_TYPES:             # never interpolate an unvetted type
        cast_to = "DOUBLE"
    txt = f'trim(CAST("{esc}" AS VARCHAR))'
    return (
        f"CASE WHEN regexp_matches({txt}, '{sql_str(COSTUME_SHAPE)}') THEN "
        f"TRY_CAST(NULLIF(regexp_replace({txt}, '[^0-9.+-]', '', 'g'), '') AS {cast_to}) END"
    )


def costume_probe_sql(col: str) -> str:
    """A SELECT list of seven aggregates characterising one column's decoration.

    Returned as a fragment rather than a whole query so callers can run it through
    whatever execution path they already hold — a raw DuckDB handle at ingest, the
    Connector's guarded ``execute`` at verification time. Feed the resulting row to
    :func:`interpret_costume`.
    """
    esc = col.replace('"', '""')
    cleaned = costume_clean_sql(col, "DOUBLE")
    return f"""count(*) FILTER (WHERE "{esc}" IS NOT NULL
                    AND trim(CAST("{esc}" AS VARCHAR)) <> '')                AS nn,
        count(*) FILTER (WHERE regexp_matches(trim(CAST("{esc}" AS VARCHAR)),
                                              '{sql_str(COSTUME_SHAPE)}'))   AS shaped,
        count(*) FILTER (WHERE regexp_matches(CAST("{esc}" AS VARCHAR),
                                              '{sql_str(COSTUME_MARK)}'))    AS marked,
        count(*) FILTER (WHERE {cleaned} IS NOT NULL
                         AND {cleaned} <> floor({cleaned}))                  AS fractional,
        count(*) FILTER (WHERE regexp_matches(CAST("{esc}" AS VARCHAR), '%')) AS pct,
        max(regexp_extract(CAST("{esc}" AS VARCHAR),
                           '[{sql_str(CURRENCY_CHARS)}]'))                   AS sym,
        max(CAST("{esc}" AS VARCHAR)) FILTER (
            WHERE regexp_matches(CAST("{esc}" AS VARCHAR),
                                 '{sql_str(COSTUME_MARK)}'))                 AS example"""


def _as_int(v) -> int:
    """Coerce a probe count that may have been stringified by a QueryResult."""
    try:
        if v is None or v == "NULL":
            return 0
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def interpret_costume(row) -> dict | None:
    """Turn a :func:`costume_probe_sql` row into ``{"cast_to", "unit", "sample"}``.

    Returns None when the column is not a decorated number. ``unit`` is the decoration
    itself ('₹', '%') so a report can say "₹3.4M" instead of an unlabelled 3400000 —
    the symbol is a UNIT, and dropping it is how a currency column becomes a bare
    number nobody can caption.
    """
    if not row or len(row) < 7:
        return None
    nn, shaped, marked, fractional, pct = (_as_int(v) for v in row[:5])
    sym, example = row[5], row[6]
    sym = "" if sym in (None, "NULL") else str(sym)
    example = None if example in (None, "NULL") else str(example)
    if nn == 0 or not marked:
        return None                                   # empty, or nothing decorated to strip
    if shaped < COSTUME_THRESHOLD * nn:
        return None                                   # not uniformly number-shaped — leave it
    # A percent or a currency amount stays DOUBLE even when this file happens to hold
    # whole numbers; only an undecorated grouped integer ('24,269') earns BIGINT.
    unit = sym or ("%" if pct else "")
    return {
        "cast_to": "DOUBLE" if (fractional or unit) else "BIGINT",
        "unit": unit,
        "sample": example,
    }


def costume_kind(unit: str) -> str:
    """A human label for the decoration: 'currency', 'percent', or 'grouped_number'."""
    if unit == "%":
        return "percent"
    return "currency" if unit else "grouped_number"


def detect_costume(con, src: str, col: str) -> dict | None:
    """Probe one column on a live DuckDB handle. See :func:`interpret_costume`."""
    try:
        return interpret_costume(
            con.execute(f"SELECT {costume_probe_sql(col)} FROM {src}").fetchone()
        )
    except Exception:
        return None
