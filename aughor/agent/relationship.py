"""Questions about how two things relate — and the rule that the two things must be two.

A relationship question ("is there a correlation between shipping delay and customer
location", "do late deliveries lower review scores") is not a ranking question, and the
investigation used to answer it with one: rank the metric across each dimension
separately and let a narrator read the spread. Two marginal rankings are true whatever
the relationship is, so they cannot describe it.

`aughor.agent.investigate._run_association_scan` already fixed that for one shape — two
CATEGORIES, crossed into a contingency grid with a chi-square verdict. This module owns
the rest of the type matrix, because the shape of the right query is decided by the TYPES
of the two sides, not by a planner:

  numeric   × numeric     → CORR(a, b) over the full table
  numeric   × categorical → per-group mean / spread / count → one-way ANOVA
  categorical × categorical → the existing joint-distribution scan

It also owns the precondition all three share: **the two sides must be different things.**
A live run asked "is there a correlation between shipping delay and customer location?"
against a table carrying `Late_delivery_risk`. Intake resolved the metric to
`AVG(Late_delivery_risk)` and, reading "shipping delay" a second time, resolved the
contrasted condition to `Late_delivery_risk = 1`. The planner then did exactly as
instructed and grouped the metric by its own definition:

    SELECT CASE WHEN Late_delivery_risk = 1 THEN 'Late' ELSE 'On-time' END AS segment,
           AVG(Late_delivery_risk) AS metric_total, COUNT(*) AS n
    FROM ... GROUP BY 1

100% and 0%, by construction, leading the report. Every SQL-shape guard passed it: there
is no fan-out, no id arithmetic, no ratio of sums, and `self_ratio_tautology` looks for a
ratio whose two SIDES match, not for a segment that matches the metric. The check that
catches it is a column-set intersection, and it costs one parse.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import sqlglot
from sqlglot import exp

#: Declared types we read as already-numeric. Matched as substrings against the type
#: string a schema reports, so DECIMAL(10,2) and DOUBLE PRECISION are covered.
_NUMERIC_TYPE_TOKENS = (
    "int", "float", "double", "real", "decimal", "numeric", "number", "bignumeric",
)

#: Share of non-null values that must survive a cast before a text column is treated as a
#: number. Deliberately the same 0.95 `aughor.sql.numeric_text` requires before it re-types
#: a decorated column — one threshold for "this text is really a number", two detectors.
_CASTABLE_THRESHOLD = 0.95


def sql_columns(expression: str, dialect: str = "duckdb") -> set[str]:
    """The bare column names an expression references, lower-cased.

    Names only, never qualifiers: the two sides of the check below are written by
    different prompts against the same table, so one may say `t.late_delivery_risk` and
    the other `Late_delivery_risk` for the identical column. Comparing qualified strings
    would make the guard blind exactly when the two sides came from different places,
    which is the only case it exists for.

    Returns an empty set for anything unparseable — a guard that cannot read its input
    must not claim a verdict about it.
    """
    text = (expression or "").strip()
    if not text:
        return set()
    try:
        tree = sqlglot.parse_one(text, read=dialect)
    except Exception:
        return set()
    if tree is None:
        return set()
    return {c.name.lower() for c in tree.find_all(exp.Column) if c.name}


def self_referential_segment(metric_sql: str, segment_sql: str,
                             dialect: str = "duckdb") -> Optional[str]:
    """Why this driver segment cannot explain this metric — or None when it can.

    A DRIVER question contrasts a metric Y across a condition X. When X is built from the
    same column Y is computed from, the contrast is a restatement of the metric's own
    definition: every X-true row scores 1 and every X-false row scores 0, so the query
    returns 100%/0% whatever the data says. The result is not wrong SQL — it executes,
    it is arithmetically correct, and it is worthless.

    Returns the reason as a sentence (it is carried into `intake_notes`, where a reader
    can see why the contrast was dropped), never a bare boolean.
    """
    metric_cols = sql_columns(metric_sql, dialect)
    segment_cols = sql_columns(segment_sql, dialect)
    shared = sorted(metric_cols & segment_cols)
    if not shared:
        return None
    names = ", ".join(shared)
    return (
        f"the contrasted condition is built from {names}, which the metric is also "
        f"computed from — grouping the metric by its own definition returns 100% and 0% "
        f"whatever the data holds, so it cannot show what drives the metric"
    )


# ── Typing the two sides ──────────────────────────────────────────────────────

def _is_numeric_type(declared: Optional[str]) -> bool:
    t = (declared or "").strip().lower()
    return any(tok in t for tok in _NUMERIC_TYPE_TOKENS) if t else False


def _quote(column: str) -> str:
    """A column reference safe to interpolate. Names in these schemas carry spaces and
    parentheses (`Days for shipping (real)`), so quoting is not optional; an embedded
    double quote is doubled rather than dropped."""
    return '"' + str(column).replace('"', '""') + '"'


def bare_column(side: str, known_columns=None, dialect: str = "duckdb") -> Optional[str]:
    """The column name when this side of a relationship IS one column, else None.

    A side arrives as either a name (`Customer State`) or the arithmetic that measures a
    concept the schema stores in pieces (`"Days for shipping (real)" - "Days for shipment
    (scheduled)"` for "shipping delay"). The two need opposite handling — a name must be
    quoted before it can survive a space or a parenthesis, an expression must be passed
    through untouched — and quoting an expression yields one absurd identifier that the
    binder rejects, naming the whole expression as the missing column.

    `known_columns` is consulted FIRST because parsing alone cannot separate the two on
    exactly the names this matters for: `Customer State` parses as two tokens, not a
    column, and `Days for shipping (real)` parses as something with a function call in it.
    Both are real column names in the table being queried, and the schema already knows
    that — so the schema decides, and the parser only handles what it has not been told
    about.
    """
    text = (side or "").strip()
    if not text:
        return None
    lookup = {str(c).split(".")[-1].strip().lower() for c in (known_columns or ())}
    unquoted = text[1:-1].replace('""', '"') if len(text) > 1 and text[0] == text[-1] == '"' else text
    if unquoted.strip().lower() in lookup:
        return unquoted.strip()
    try:
        tree = sqlglot.parse_one(text, read=dialect)
    except Exception:
        return None
    return tree.name if isinstance(tree, exp.Column) and tree.name else None


def side_expression(side: str, known_columns=None, dialect: str = "duckdb") -> str:
    """This side as SQL: a bare name quoted, an expression left exactly as written."""
    name = bare_column(side, known_columns, dialect)
    return _quote(name) if name else (side or "").strip()


def numeric_expression(
    column: str,
    declared_type: Optional[str],
    table: str,
    run: Optional[Callable[[str], Optional[list]]] = None,
    known_columns=None,
    dialect: str = "duckdb",
) -> Optional[str]:
    """The SQL that reads this side as a number, or None when it does not hold one.

    A bare column of an already-numeric declared type is returned quoted and unchanged —
    the one case that needs no round-trip. Everything else is PROBED against the real data
    with one `COUNT(TRY_CAST(...))`, because neither a declared type nor a piece of
    arithmetic is evidence about contents:

    * In the DataCo supply-chain export `Latitude` and `Longitude` land as VARCHAR holding
      `'18.2514534'`, while the same file loaded into BigQuery types them as floats. A
      type-only test makes the identical analysis reachable on one warehouse and invisible
      on another — a property of the loader, not of the question.
    * A computed side has no declared type at all, so there is nothing to consult.

    `run(sql)` returns rows (a list of sequences) or None. Without it — or when the probe
    fails, which is what a dialect lacking TRY_CAST does — the side is reported as
    non-numeric. Failing to the narrower answer keeps a broken probe and a true negative
    from looking alike: the analysis is skipped and said to be skipped, never run against
    an all-NULL cast that would report a confident zero.
    """
    if not column:
        return None
    expr = side_expression(column, known_columns, dialect)
    if not expr:
        return None
    if bare_column(column, known_columns, dialect) and _is_numeric_type(declared_type):
        return expr
    if run is None or not table:
        return None
    probe = (
        f"SELECT COUNT(*) AS n_total, COUNT(TRY_CAST({expr} AS DOUBLE)) AS n_cast "
        f"FROM {table} WHERE {expr} IS NOT NULL"
    )
    try:
        rows = run(probe)
    except Exception:
        return None
    if not rows or not rows[0]:
        return None
    try:
        n_total = float(rows[0][0])
        n_cast = float(rows[0][1])
    except (TypeError, ValueError, IndexError):
        return None
    if n_total <= 0 or (n_cast / n_total) < _CASTABLE_THRESHOLD:
        return None
    # An already-numeric expression casts to itself; the wrapper is what makes a text
    # column readable and is harmless on a number.
    return f"TRY_CAST({expr} AS DOUBLE)"


# ── The plan ──────────────────────────────────────────────────────────────────

#: Group cap on the numeric-by-category query. High enough that an ordinary dimension
#: (563 customer cities) is measured whole, low enough that a mis-typed id column cannot
#: drag a full-cardinality result back. A truncated scan says so rather than testing a
#: subset and reporting it as the whole.
_GROUP_CAP = 1000


@dataclass
class RelationshipPlan:
    """One query and everything needed to read its result."""
    kind: str                    # "numeric_pair" | "numeric_by_category" | "category_pair"
    sql: str
    left_label: str
    right_label: str
    #: Set when the plan could not be built; the caller reports this instead of a scan.
    skipped: str = ""
    columns: list = field(default_factory=list)


def plan_relationship(
    *,
    table: str,
    left_column: str,
    right_column: str,
    left_label: str,
    right_label: str,
    col_types: Optional[dict] = None,
    run: Optional[Callable[[str], Optional[list]]] = None,
    col_concepts: Optional[dict] = None,
) -> RelationshipPlan:
    """Build the query whose SHAPE answers "how do these two relate", typed by the pair.

    `col_types` maps a bare column name to its declared type; anything absent is probed
    (see `numeric_expression`) rather than assumed categorical, so a column the schema
    parse missed is not silently demoted.

    `col_concepts` maps a bare column name to a CONFIDENT concept (AT-4: two agreeing
    witness layers; a hint never arrives here). It is consulted for one purpose — refusing
    arithmetic on a column whose concept forbids it. `Customer Zipcode` casts to a number,
    correlates against anything, and returns a coefficient with a p-value; every part of
    that answer is well-formed and none of it means anything, because zip 90210 is not
    larger than zip 90209. Reading the pair as a numeric-by-category comparison instead
    answers the question the user actually asked.
    """
    types = {str(k).split(".")[-1].lower(): v for k, v in (col_types or {}).items()}
    known = set(types)
    concepts = {str(k).split(".")[-1].lower(): v for k, v in (col_concepts or {}).items()}

    def _declared(col: str) -> Optional[str]:
        name = bare_column(col, known)
        return types.get(name.lower()) if name else None

    def _forbidden(col: str) -> bool:
        """True when this side's concept says arithmetic on it is meaningless."""
        name = bare_column(col, known)
        if not name:
            return False
        concept = concepts.get(name.lower())
        if not concept:
            return False
        from aughor.ontology.operations import forbids_numeric_relationship
        return forbids_numeric_relationship(str(concept))

    def _numeric(col: str) -> Optional[str]:
        if _forbidden(col):
            return None
        return numeric_expression(col, _declared(col), table, run, known)

    l_lab = left_label or left_column
    r_lab = right_label or right_column

    if not table or not left_column or not right_column:
        return RelationshipPlan(kind="", sql="", left_label=l_lab, right_label=r_lab,
                                skipped="the relationship needs a table and two columns")
    # Compare RESOLVED sides, not parsed ones. `sql_columns("Customer State")` and
    # `sql_columns("Customer City")` both answer {"customer"} — a bare name with a space is
    # not a parseable column — so a parse-only comparison declares two different dimensions
    # identical and refuses to scan them.
    def _identity(side: str) -> set:
        name = bare_column(side, known)
        return {name.lower()} if name else sql_columns(side)

    left_id, right_id = _identity(left_column), _identity(right_column)
    if left_id and left_id == right_id:
        return RelationshipPlan(kind="", sql="", left_label=l_lab, right_label=r_lab,
                                skipped="both sides read the same columns, so there is "
                                        "no relationship to measure")

    left_num = _numeric(left_column)
    right_num = _numeric(right_column)

    if left_num and right_num:
        sql = (
            f"SELECT CORR({left_num}, {right_num}) AS correlation,\n"
            f"       COUNT(*) AS n_records\n"
            f"FROM {table}\n"
            f"WHERE {left_num} IS NOT NULL AND {right_num} IS NOT NULL"
        )
        return RelationshipPlan(kind="numeric_pair", sql=sql, left_label=l_lab,
                                right_label=r_lab, columns=["correlation", "n_records"])

    if left_num or right_num:
        measure_sql = left_num or right_num
        measure_label = l_lab if left_num else r_lab
        dim_col = right_column if left_num else left_column
        dim_label = r_lab if left_num else l_lab
        dim = side_expression(dim_col, known)
        sql = (
            f"SELECT {dim} AS {_alias(dim_label)},\n"
            f"       AVG({measure_sql}) AS mean_value,\n"
            f"       STDDEV_SAMP({measure_sql}) AS sd_value,\n"
            f"       COUNT(*) AS n_records\n"
            f"FROM {table}\n"
            f"WHERE {measure_sql} IS NOT NULL AND {dim} IS NOT NULL\n"
            f"GROUP BY 1\n"
            f"ORDER BY n_records DESC\n"
            f"LIMIT {_GROUP_CAP}"
        )
        return RelationshipPlan(
            kind="numeric_by_category", sql=sql,
            left_label=measure_label, right_label=dim_label,
            columns=[_alias(dim_label), "mean_value", "sd_value", "n_records"])

    left_q = side_expression(left_column, known)
    right_q = side_expression(right_column, known)
    sql = (
        f"SELECT {left_q}, {right_q}, COUNT(*) AS n_records\n"
        f"FROM {table}\nGROUP BY 1, 2\nORDER BY 1, 2"
    )
    return RelationshipPlan(kind="category_pair", sql=sql, left_label=l_lab,
                            right_label=r_lab,
                            columns=[left_q, right_q, "n_records"])


#: The spellings a NULL cell arrives in. Result rows reach this layer stringified, so a
#: SQL NULL is the four characters "NULL" — not None — and `float()` raises on it. Read as
#: "no value": the single-observation group whose STDDEV_SAMP is undefined was being
#: dropped whole (mean, n and all) by the exception that produced, which is a silent
#: exclusion of real data disguised as defensive parsing.
_NULL_STRINGS = {"", "null", "none", "nan", "na"}


def _num(value) -> Optional[float]:
    """A cell as a float, or None when it holds no number. Never raises."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in _NULL_STRINGS:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _alias(label: str) -> str:
    """A SQL-safe alias from a human label. Mirrors `investigate._safe_alias`, kept here so
    this module stays importable without the agent layer."""
    import re
    alias = re.sub(r"[^a-zA-Z0-9_]+", "_", (label or "value").strip().lower()).strip("_")
    return alias or "value"


# ── The verdict ───────────────────────────────────────────────────────────────

@dataclass
class RelationshipReading:
    """A verdict over one executed relationship query."""
    interpretation: str          # reader-facing
    technical: str               # the statistics, for the evidence log
    significant: bool
    #: Share of one side's variation the other accounts for — r² for a correlation, eta²
    #: for group means. On a scale both kinds share, so candidate pairings for the SAME
    #: concept can be ranked against each other instead of judged one at a time.
    effect: float = 0.0


def read_relationship(plan: RelationshipPlan, columns: list, rows: list,
                      truncated: bool = False) -> Optional[RelationshipReading]:
    """The executed result as a verdict, computed — never narrated.

    Returns None when the result cannot support a reading. A narrator is not asked to
    phrase "r = 0.0005": handing a null result to a model to write up is how "no
    relationship" becomes a sentence about whichever group happens to be largest — the
    failure `_association_finding` already names for the categorical case, and the reason
    this one is deterministic too.

    `truncated` is the connection's own flag, and it must be passed: the driver caps a
    result at `MAX_ROWS` (500) BELOW this module's `_GROUP_CAP`, so the SQL limit never
    fires and a 563-value dimension is silently tested on 500 groups. The prose that comes
    back is self-consistent — "across 500 groups and 177,421 records" — which is exactly
    what makes an unsaid truncation read as the whole population.
    """
    if not rows or not columns:
        return None
    lower = [str(c).lower() for c in columns]

    if plan.kind == "numeric_pair":
        from aughor.tools.stats import assess_correlation
        try:
            r_idx = lower.index("correlation")
            n_idx = lower.index("n_records")
        except ValueError:
            return None
        r_val, n_val = _num(rows[0][r_idx]), _num(rows[0][n_idx])
        if n_val is None:
            return None
        n = int(n_val)
        if r_val is None:
            # An undefined correlation is an ANSWER, not a failure to compute one, and it
            # has to survive as text: returning None here would drop the finding and leave
            # the report to fall back to rankings without saying why.
            return RelationshipReading(
                interpretation=(
                    f"The correlation between {plan.left_label} and {plan.right_label} is "
                    f"undefined — one of the two does not vary across the {n:,} records "
                    f"compared, so there is nothing for the other to move with."),
                technical="CORR returned NULL (a constant or all-NULL side)",
                significant=False)
        verdict = assess_correlation(r_val, n, plan.left_label, plan.right_label)
        if verdict is None:
            return None
        return RelationshipReading(verdict.interpretation, verdict.technical, True,
                                   effect=verdict.r * verdict.r)

    if plan.kind == "numeric_by_category":
        from aughor.tools.stats import assess_group_means
        try:
            m_idx = lower.index("mean_value")
            sd_idx = lower.index("sd_value")
            n_idx = lower.index("n_records")
        except ValueError:
            return None
        label_idx = next((i for i in range(len(columns))
                          if i not in (m_idx, sd_idx, n_idx)), None)
        groups, dropped = [], 0
        for row in rows:
            mean, n = _num(row[m_idx]) if m_idx < len(row) else None, \
                _num(row[n_idx]) if n_idx < len(row) else None
            if mean is None or n is None or n <= 0:
                dropped += 1
                continue
            # A group of one has no within-group spread to contribute; its SD is undefined,
            # not missing. Reading that as unparseable used to discard the group entirely.
            sd = _num(row[sd_idx]) if sd_idx < len(row) else None
            label = str(row[label_idx]) if label_idx is not None and label_idx < len(row) else "group"
            groups.append((label, mean, sd if sd is not None else 0.0, int(n)))
        verdict = assess_group_means(groups, plan.left_label, plan.right_label)
        if verdict is None:
            return None
        interp = verdict.interpretation
        if dropped:
            interp += (f" {dropped} group(s) were excluded for carrying no usable average.")
        if truncated or len(rows) >= _GROUP_CAP:
            interp += (f" This reads the {len(groups):,} largest groups of a dimension that has "
                       f"more values than that, so the comparison is not exhaustive.")
        return RelationshipReading(interp, verdict.technical, True,
                                   effect=verdict.eta_squared)

    return None
