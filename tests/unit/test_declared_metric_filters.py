"""A declared metric is its formula AND the rows it is over.

Measured 2026-09-29 on five Agent-mode runs against theLook, whose revenue is declared
``SUM(sale_price)`` over ``status <> 'Cancelled'``: the formula reached every statement and the
filter reached none. July 2026 was published as 426,292.28 where the declared definition
measures 365,320.51, and ten category figures ran 14.8–19.3% over. The enforcement check read
"used the governed formula" on statements over the wrong rows, because it compares formula text.

What these pin:

- the guard puts the declared filter on the scope that computes the metric — and on the
  statements those runs actually wrote, verbatim;
- it REFUSES where the scope has dealt with the filter's column on purpose (a breakdown by it, a
  filter on it, a conditional aggregate over it), because adding the filter there answers a
  different question;
- the rules are only for metrics a person APPROVED and the question TARGETS;
- the executor applies them to a statement a model wrote and to no other — ``metric_rules=None``
  is byte-identical to before the guard existed;
- the figure actually changes: the wiring test computes the number, so a guard that is imported
  and never called fails it.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
import sqlglot
from sqlglot import exp

from aughor.db.connection import DuckDBConnection
from aughor.kernel.registries.execution_hooks import collect_guard_receipts
from aughor.semantic import enforcement as E
from aughor.sql.executor import execute_guarded
from aughor.sql.metric_filter_guard import enforce_metric_filters

REVENUE = {"metric": "revenue", "formula": "SUM(sale_price)", "tables": ["order_items"],
           "filters": ["status <> 'Cancelled'"]}
UNITS = {"metric": "units_sold", "formula": "COUNT(id)", "tables": ["inventory_items"],
         "filters": ["sold_at IS NOT NULL"]}


def _guard(sql: str, rules=(REVENUE, UNITS), dialect: str = "bigquery"):
    return enforce_metric_filters(sql, list(rules), dialect=dialect)


def _own(select, kind):
    return [n for n in select.find_all(kind) if n.find_ancestor(exp.Select) is select]


def _scope_filtering_status(sql: str):
    """The one SELECT whose own WHERE names ``status``."""
    tree = sqlglot.parse_one(sql, read="bigquery")
    hits = [s for s in tree.find_all(exp.Select) if s.args.get("where") is not None
            and any(c.name == "status" and c.find_ancestor(exp.Select) is s
                    for c in s.args["where"].find_all(exp.Column))]
    assert len(hits) == 1, sql
    return hits[0]


# ── The statements the measured runs wrote ───────────────────────────────────────────

Q1_MONTHLY = ("SELECT TIMESTAMP_TRUNC(created_at, MONTH) AS period, SUM(sale_price) AS total_revenue, "
              "COUNT(id) AS units_sold FROM order_items WHERE created_at >= TIMESTAMP '2025-07-01' "
              "AND created_at < TIMESTAMP '2026-08-01' GROUP BY 1 ORDER BY 1 ASC NULLS LAST")
Q1_CTE = ("WITH monthly_stats AS (SELECT DATE_TRUNC(DATE(created_at), MONTH) AS period, "
          "SUM(sale_price) AS revenue FROM order_items WHERE created_at >= '2025-06-01' GROUP BY 1) "
          "SELECT curr.period, curr.revenue FROM monthly_stats curr WHERE curr.period = '2026-07-01'")
Q2_CATEGORIES = ("SELECT p.category, SUM(oi.sale_price) AS total_revenue, "
                 "SUM(oi.sale_price) / COUNT(DISTINCT oi.order_id) AS average_order_value "
                 "FROM order_items AS oi JOIN products AS p ON oi.product_id = p.id "
                 "WHERE oi.created_at >= '2026-03-02' AND oi.created_at <= '2026-08-31' "
                 "GROUP BY 1 ORDER BY total_revenue DESC LIMIT 10")


@pytest.mark.parametrize("sql, expected", [
    (Q1_MONTHLY, "order_items.status <> 'Cancelled'"),
    (Q1_CTE, "order_items.status <> 'Cancelled'"),
    (Q2_CATEGORIES, "oi.status <> 'Cancelled'"),          # the table's own alias
])
def test_the_measured_statements_get_the_declared_filter(sql, expected):
    out, applied = _guard(sql)
    assert applied == [{"metric": "revenue", "table": "order_items", "filter": "status <> 'Cancelled'"}]
    assert out.count(expected) == 1
    assert "sold_at" not in out                           # units_sold is declared on another table


#: The period comparison the baseline planned for Q2, verbatim: the rows are handed on
#: through a CTE before anything is summed. The first version of the guard missed it, and
#: the report would have carried a period total over every row beside a category table
#: over the declared ones.
Q2_PERIODS = """WITH period_data AS (
    SELECT
        CASE
            WHEN created_at >= TIMESTAMP '2026-03-02' AND created_at < TIMESTAMP '2026-09-01' THEN 'observation'
            WHEN created_at >= TIMESTAMP '2025-08-31' AND created_at < TIMESTAMP '2026-03-02' THEN 'comparison'
        END AS period_label,
        sale_price,
        order_id
    FROM order_items
    WHERE created_at >= TIMESTAMP '2025-08-31' AND created_at < TIMESTAMP '2026-09-01'
),
aggregated AS (
    SELECT period_label, SUM(sale_price) AS revenue,
           SUM(sale_price) / NULLIF(COUNT(DISTINCT order_id), 0) AS aov
    FROM period_data WHERE period_label IS NOT NULL GROUP BY 1
)
SELECT a.revenue AS obs_revenue, b.revenue AS comp_revenue
FROM aggregated a CROSS JOIN aggregated b
WHERE a.period_label = 'observation' AND b.period_label = 'comparison'"""


@pytest.mark.parametrize("sql", [
    Q2_PERIODS,
    "WITH x AS (SELECT sale_price FROM order_items) SELECT SUM(sale_price) FROM x",
    "SELECT SUM(t.sale_price) FROM (SELECT * FROM order_items WHERE created_at >= '2026-07-01') AS t",
])
def test_rows_handed_on_once_are_followed_to_where_they_are_read(sql):
    out, applied = _guard(sql)
    assert applied == [{"metric": "revenue", "table": "order_items", "filter": "status <> 'Cancelled'"}]
    assert out.count("order_items.status <> 'Cancelled'") == 1
    # on the scope that READS the table — the one that aggregates reads only what is left
    scope = _scope_filtering_status(out)
    assert [t.name for t in _own(scope, exp.Table)] == ["order_items"]
    assert not _own(scope, exp.AggFunc)


def test_the_filter_lands_in_the_scope_that_computes_the_metric():
    """Inside the CTE that aggregates — not on the outer SELECT that only reads its rows."""
    scope = _scope_filtering_status(_guard(Q1_CTE)[0])
    assert [t.name for t in _own(scope, exp.Table)] == ["order_items"]
    assert _own(scope, exp.Sum)


# ── The refusals ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("why, sql", [
    ("the question filtered the column itself",
     "SELECT SUM(sale_price) FROM order_items WHERE status = 'Complete'"),
    ("a breakdown BY the column — the filter would delete a row the question asked for",
     "SELECT status, SUM(sale_price) AS revenue FROM order_items GROUP BY status"),
    ("a conditional aggregate over the column",
     "SELECT SUM(IF(status = 'Cancelled', sale_price, 0)) AS lost, SUM(sale_price) AS r FROM order_items"),
    ("the formula is over ANOTHER table's column",
     "SELECT SUM(p.retail_price) FROM order_items oi JOIN products p ON oi.product_id = p.id"),
    # Each of the next three hands `sale_price` on as a bare column, so only the grain
    # check can refuse it (mutation-tested: the first draft of these cases was refused by
    # the projection check instead, and deleting the grain check left every test green).
    ("the CTE it reads has grouped — a row there is no longer an order line",
     "WITH x AS (SELECT sale_price FROM order_items GROUP BY sale_price) SELECT SUM(sale_price) FROM x"),
    ("the CTE it reads has de-duplicated",
     "WITH x AS (SELECT DISTINCT sale_price FROM order_items) SELECT SUM(sale_price) FROM x"),
    ("the derived table it reads aggregates beside the column",
     "SELECT SUM(t.sale_price) FROM (SELECT sale_price, MAX(id) AS top FROM order_items "
     "GROUP BY 1) AS t"),
    ("the name `sale_price` is handed on, but it is ANOTHER column wearing it",
     "WITH x AS (SELECT sale_price AS amount, shipping AS sale_price FROM order_items) "
     "SELECT SUM(sale_price) FROM x"),
    ("the CTE hands the column on under another name, so the formula is not the declared one",
     "WITH x AS (SELECT sale_price AS price FROM order_items) SELECT SUM(price) FROM x"),
    ("the CTE does not hand the formula's column on at all",
     "WITH x AS (SELECT order_id FROM order_items) SELECT SUM(sale_price) FROM x, products"),
    ("a self-join with an unqualified column cannot say which side it means",
     "SELECT SUM(sale_price) FROM order_items a JOIN order_items b ON a.order_id = b.order_id"),
    ("the declared table is read, the declared formula is not computed",
     "SELECT COUNT(*) FROM order_items WHERE created_at >= '2026-07-01'"),
])
def test_it_leaves_the_statement_alone(why, sql):
    out, applied = _guard(sql)
    assert applied == [] and out == sql, why


def test_an_unusable_rule_or_statement_changes_nothing():
    sql = "SELECT SUM(sale_price) FROM order_items"
    assert _guard("SELEC nonsense ((") == ("SELEC nonsense ((", [])
    assert _guard(sql, rules=()) == (sql, [])
    # a "formula" that is a whole statement has no shape to look for
    whole = {"metric": "csat", "formula": "SELECT AVG(csat) FROM t;", "tables": ["order_items"],
             "filters": ["a = 1"]}
    assert _guard(sql, rules=(whole,)) == (sql, [])
    for missing in ("tables", "filters"):
        assert _guard(sql, rules=({**REVENUE, missing: []},)) == (sql, [])


def test_a_filter_is_added_once_however_often_the_formula_appears():
    out, applied = _guard(Q2_CATEGORIES)                  # SUM(oi.sale_price) appears twice
    assert len(applied) == 1 and out.count("status <> 'Cancelled'") == 1


# ── Naming the column is not dealing with it (2026-10-02) ────────────────────────────

#: Verbatim: the Q1 analyst's fourth statement, written after the guard had filtered its revenue
#: three times. Left alone because it NAMED `status`, it put every cancelled line into July's
#: revenue — 418,928.40 published, 359,224.30 declared.
Q1_NOT_NULL = ("SELECT\n    SUM(sale_price) AS total_revenue,\n    COUNT(id) AS units_sold\n"
               "FROM order_items\nWHERE created_at >= '2026-07-01' AND created_at < '2026-08-01'\n"
               "AND status IS NOT NULL")


@pytest.mark.parametrize("why, sql", [
    ("keeps every status, the cancelled one with them", Q1_NOT_NULL),
    ("excludes another status and keeps the cancelled one",
     "SELECT SUM(sale_price) FROM order_items WHERE status <> 'Returned'"),
    ("a NOT IN that leaves the cancelled one in",
     "SELECT SUM(sale_price) FROM order_items WHERE status NOT IN ('Returned')"),
    ("a value spelled another way is not the declared one — it keeps 'Cancelled'",
     "SELECT SUM(sale_price) FROM order_items WHERE status <> 'cancelled'"),
    ("a list that reads another column keeps whatever that column holds",
     "SELECT SUM(oi.sale_price) FROM order_items oi JOIN orders o ON oi.order_id = o.order_id "
     "WHERE oi.status IN (o.status)"),
])
def test_a_condition_that_keeps_the_excluded_rows_still_gets_the_filter(why, sql):
    out, applied = _guard(sql)
    assert applied == [{"metric": "revenue", "table": "order_items", "filter": "status <> 'Cancelled'"}], why
    assert out.count("status <> 'Cancelled'") == 1, why


@pytest.mark.parametrize("why, sql", [
    ("names the excluded value — it measures the cancelled rows",
     "SELECT SUM(sale_price) FROM order_items WHERE status = 'Cancelled'"),
    ("is the declared filter, written by the analyst",
     "SELECT SUM(sale_price) FROM order_items WHERE status != 'Cancelled'"),
    ("excludes it among others",
     "SELECT SUM(sale_price) FROM order_items WHERE status NOT IN ('Cancelled', 'Returned')"),
    ("keeps only the statuses it lists",
     "SELECT SUM(sale_price) FROM order_items WHERE status IN ('Complete', 'Shipped')"),
    ("keeps only the status it names, under a function",
     "SELECT SUM(sale_price) FROM order_items WHERE LOWER(status) = 'complete'"),
])
def test_a_condition_that_chose_its_rows_is_left_alone(why, sql):
    out, applied = _guard(sql)
    assert applied == [] and out == sql, why


def test_a_filter_that_names_no_value_is_dealt_with_by_any_condition_on_its_column():
    """`sold_at IS NOT NULL` is about the column itself: a window on `sold_at` has dealt with it."""
    windowed = ("SELECT COUNT(id) FROM inventory_items "
                "WHERE sold_at >= '2026-07-01' AND sold_at < '2026-08-01'")
    assert _guard(windowed, rules=(UNITS,)) == (windowed, [])
    out, applied = _guard("SELECT COUNT(id) FROM inventory_items WHERE created_at >= '2026-07-01'",
                          rules=(UNITS,))
    assert applied == [{"metric": "units_sold", "table": "inventory_items", "filter": "sold_at IS NOT NULL"}]
    assert out.count("NOT inventory_items.sold_at IS NULL") == 1     # sqlglot's spelling of IS NOT NULL


# ── Which metrics make rules ─────────────────────────────────────────────────────────

def _metric(**kw):
    base = dict(name="revenue", label="Revenue", sql="SUM(sale_price)", tables=["order_items"],
                filters=["status <> 'Cancelled'"], status="approved")
    return SimpleNamespace(**{**base, **kw})


def test_rules_are_for_approved_metrics_the_question_targets():
    q = "What was total revenue and how many units were sold in July 2026?"
    units = _metric(name="units_sold", label="Units Sold", sql="COUNT(id)",
                    tables=["inventory_items"], filters=["sold_at IS NOT NULL"])
    rules = E.declared_filter_rules(q, [_metric(), units])
    assert [r["metric"] for r in rules] == ["revenue", "units_sold"]
    assert rules[0] == REVENUE


@pytest.mark.parametrize("why, metric, question", [
    ("a draft's filter is a proposal", _metric(status="draft"), "total revenue in July"),
    ("the question does not target it", _metric(), "how many orders shipped late?"),
    ("it declares no filter", _metric(filters=[]), "total revenue in July"),
    ("it declares no table", _metric(tables=[]), "total revenue in July"),
])
def test_no_rule_without_all_three_conditions(why, metric, question):
    assert E.declared_filter_rules(question, [metric]) == [], why


# ── A metric stored as a statement ───────────────────────────────────────────────────
#
# The first version of this guard was built against `data/metrics.json` — the LEGACY file,
# where revenue is the expression `SUM(sale_price)`. The catalogue the platform serves is
# `data/metrics.instance.json`, where it is a statement. Live, the guard found no shape in
# the statement and rewrote nothing; three re-runs passed `guarded:declared-filter` and
# published the unfiltered figure again. These are the live definitions, verbatim.

LIVE_REVENUE = "SELECT (SUM(sale_price)) AS revenue FROM order_items WHERE status <> 'Cancelled'"
LIVE_NET = ("SELECT (SUM(sale_price)) AS net_merchandise_revenue FROM order_items "
            "WHERE status NOT IN ('Cancelled', 'Returned')")
LIVE_AOV = ("SELECT SAFE_DIVIDE(SUM(sale_price), COUNT(DISTINCT order_id)) AS average_order_value_aov\n"
            "FROM order_items")


def test_a_statement_is_read_for_its_measure_its_table_and_its_where():
    from aughor.sql.metric_filter_guard import measure_of, same_condition
    assert measure_of(LIVE_REVENUE, "bigquery") == {
        "formula": "SUM(sale_price)", "tables": ["order_items"], "filters": ["status <> 'Cancelled'"]}
    (net,) = measure_of(LIVE_NET, "bigquery")["filters"]      # the parser's own spelling of NOT IN
    assert same_condition(net, "status NOT IN ('Cancelled', 'Returned')", "bigquery")
    assert not same_condition(net, "status <> 'Cancelled'", "bigquery")
    assert measure_of(LIVE_AOV, "bigquery")["filters"] == []
    assert measure_of("SELECT SUM(a) FROM t WHERE x = 1 AND (y > 2 AND z IS NULL)", "bigquery")[
        "filters"] == ["x = 1", "y > 2", "z IS NULL"]
    assert measure_of("COUNT(id)", "bigquery") == {"formula": "COUNT(id)", "tables": [], "filters": []}


@pytest.mark.parametrize("why, text", [
    ("it joins — the rows are no longer one table's",
     "SELECT SUM(oi.sale_price - ii.cost) FROM order_items oi JOIN inventory_items ii ON oi.inventory_item_id = ii.id"),
    ("it groups", "SELECT SUM(sale_price) FROM order_items GROUP BY status"),
    ("it has two projections", "SELECT SUM(sale_price), COUNT(*) FROM order_items"),
    ("it is built on a CTE", "WITH c AS (SELECT * FROM orders) SELECT COUNT(*) FROM c"),
    ("it reads a subquery", "SELECT SUM(x) FROM (SELECT 1 AS x) AS t"),
    ("it measures nothing", "SELECT sale_price FROM order_items"),
    ("it is not SQL", "SELEC nonsense (("),
    ("it is empty", ""),
])
def test_what_is_not_one_measure_over_one_table_makes_no_rule(why, text):
    from aughor.sql.metric_filter_guard import measure_of
    assert measure_of(text, "bigquery") is None, why


def test_the_live_revenue_definition_makes_the_rule_that_rewrites_the_live_statement():
    """End to end on the two texts that met on 2026-09-29: the stored definition, and the
    statement the analyst wrote in the re-run."""
    revenue = _metric(sql=LIVE_REVENUE)
    rules = E.declared_filter_rules("What was total revenue and how many units were sold in July 2026?",
                                    [revenue], "bigquery")
    assert rules == [REVENUE]                     # the filter said once, though declared twice
    written = ("SELECT SUM(sale_price) AS total_revenue, COUNT(*) AS units_sold FROM order_items "
               "WHERE created_at >= '2026-07-01' AND created_at < '2026-08-01'")
    out, applied = enforce_metric_filters(written, rules, dialect="bigquery")
    assert len(applied) == 1 and out.endswith("AND order_items.status <> 'Cancelled'")


def test_two_metrics_with_one_formula_the_question_decides():
    revenue = _metric(sql=LIVE_REVENUE)
    net = _metric(name="net_merchandise_revenue", label="Net Merchandise Revenue", sql=LIVE_NET,
                  filters=["status NOT IN ('Cancelled', 'Returned')"])
    ask = lambda q: [(r["metric"], r["filters"]) for r in                     # noqa: E731
                     E.declared_filter_rules(q, [revenue, net], "bigquery")]
    assert ask("total revenue in July") == [("revenue", ["status <> 'Cancelled'"])]
    # "net merchandise revenue" contains "revenue": both are targeted, one is meant
    assert ask("what was net merchandise revenue in July?") == [
        ("net_merchandise_revenue", ["status NOT IN ('Cancelled', 'Returned')"])]


def test_a_tie_between_rivals_makes_no_rule():
    a = _metric(name="revenue", label="Revenue", sql=LIVE_REVENUE)
    b = _metric(name="revenue", label="Revenue", sql=LIVE_NET,
                filters=["status NOT IN ('Cancelled', 'Returned')"])
    assert E.declared_filter_rules("total revenue in July", [a, b], "bigquery") == []
    # the same metric declared twice the same way is no rivalry, and is said once
    assert E.declared_filter_rules("total revenue in July", [a, _metric(sql="SUM(sale_price)")],
                                   "bigquery") == [REVENUE]


def test_the_bound_question_is_released(monkeypatch):
    seen = []
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics",
                        lambda connection_id=None: seen.append(connection_id) or [_metric()])
    assert E.rules_for_statement("c1") is None            # nothing bound, nothing to enforce
    with E.answering("total revenue in July"):
        assert E.rules_for_statement("c1") == [REVENUE]
        assert E.rules_for_statement("") is None          # no connection: never the global catalogue
    assert E.rules_for_statement("c1") is None
    assert E.rules_for_statement("c1", "total revenue in July") == [REVENUE]
    assert seen == ["c1", "c1"]


# ── The executor: the figure changes, and only when rules are passed ────────────────

@pytest.fixture
def shop(tmp_path: Path):
    path = tmp_path / "shop.duckdb"
    raw = duckdb.connect(str(path))
    raw.execute("CREATE TABLE order_items (id INTEGER, order_id INTEGER, status VARCHAR, sale_price DOUBLE)")
    raw.execute("INSERT INTO order_items VALUES (1, 1, 'Complete', 100.0), (2, 1, 'Shipped', 50.0), "
                "(3, 2, 'Cancelled', 30.0), (4, 3, 'Returned', 20.0)")
    raw.close()
    conn = DuckDBConnection(path, connection_id="declared")
    yield conn
    conn.close()


STATEMENT = "SELECT SUM(sale_price) AS revenue, COUNT(id) AS lines FROM order_items"


def test_without_rules_the_statement_runs_exactly_as_written(shop):
    with collect_guard_receipts() as receipts:
        r = execute_guarded(shop, STATEMENT, query_id="answer")
    assert not r.error and r.sql == STATEMENT
    assert [float(r.rows[0][0]), int(r.rows[0][1])] == [200.0, 4]
    assert not any("declared-filter" in d for d in r.doors)
    assert not [x for x in receipts if x["guard"] == "declared_filter"]


def test_with_rules_the_figure_is_the_declared_one_and_says_so(shop):
    with collect_guard_receipts() as receipts:
        r = execute_guarded(shop, STATEMENT, query_id="answer", metric_rules=[REVENUE])
    assert not r.error
    # 200 with the cancelled line, 170 without: the number is what proves the guard ran.
    assert [float(r.rows[0][0]), int(r.rows[0][1])] == [170.0, 3]
    assert "guarded:declared-filter" in r.doors and "repaired:declared-filter" in r.doors
    said = [x for x in receipts if x["guard"] == "declared_filter"]
    assert len(said) == 1 and said[0]["action"] == "rewrote_sql"
    assert "status <> 'Cancelled'" in said[0]["detail"] and "order_items" in said[0]["detail"]
    assert said[0]["before"] == STATEMENT and "Cancelled" in said[0]["after"]
    assert not r.caveats                                  # a figure ON the definition carries no warning
    assert r.sql == said[0]["after"]                      # the result names the statement that ran


def test_the_evidence_shows_the_statement_that_ran(shop, monkeypatch):
    """The finding printed the model's statement beside the rewritten statement's rows, and
    the report then listed "does not distinguish between order statuses" as a data gap
    (live, 2026-09-29). The rows and the SQL a reader is shown are one statement's."""
    from aughor.agent import analyst as A
    from aughor.agent import converse_tools as T
    monkeypatch.setattr(T, "_connection", lambda cid: shop)
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics",
                        lambda connection_id=None: [_metric()])
    out = T.run_sql("declared", {"sql": STATEMENT}, user_question="total revenue in July")
    assert "status <> 'Cancelled'" in out["sql"] and float(out["rows"][0][0]) == 170.0

    turn = SimpleNamespace(evidence_rows=0, phase_tools_run=[], state={"question": "total revenue"},
                           merged=[])
    turn.merge = lambda update, tool="": turn.merged.append(update)
    A._record_evidence(turn, {"sql": STATEMENT}, out)
    (finding,) = turn.merged[0]["investigation_phases"][0]["findings"]
    assert finding["sql"] == out["sql"]

    # untouched: nothing is repeated back, and the finding shows what the model framed
    plain = T.run_sql("declared", {"sql": STATEMENT}, user_question="how many lines are there?")
    assert "sql" not in plain and float(plain["rows"][0][0]) == 200.0


def test_a_statement_that_dealt_with_the_column_is_checked_and_left(shop):
    by_status = "SELECT status, SUM(sale_price) AS revenue FROM order_items GROUP BY status ORDER BY 1"
    r = execute_guarded(shop, by_status, query_id="answer", metric_rules=[REVENUE])
    assert [row[0] for row in r.rows] == ["Cancelled", "Complete", "Returned", "Shipped"]
    assert "guarded:declared-filter" in r.doors and "repaired:declared-filter" not in r.doors


def test_a_rewrite_that_does_not_dry_run_is_not_adopted_and_the_result_says_so(shop, monkeypatch):
    monkeypatch.setattr(shop, "dry_run", lambda sql: (False, "refused"))
    with collect_guard_receipts() as receipts:
        r = execute_guarded(shop, STATEMENT, query_id="answer", metric_rules=[REVENUE])
    assert float(r.rows[0][0]) == 200.0                   # ran as written…
    assert any(c.startswith("declared-filter guard:") and "not the declared one" in c
               for c in r.caveats)                        # …and is said to be off the definition
    assert [x["action"] for x in receipts if x["guard"] == "declared_filter"] == ["flagged"]


# ── Shown wherever the formula is shown ──────────────────────────────────────────────

def test_the_prompt_block_prints_the_filter_with_the_formula():
    from aughor.semantic.canonical import render_contracts_block
    c = SimpleNamespace(key="revenue", sql="SUM(sale_price)", unit="$", injectable=True,
                        caveats="", filters=["status <> 'Cancelled'"])
    bare = SimpleNamespace(key="aov", sql="AVG(total)", unit="", injectable=True, caveats="",
                           filters=[])
    block = render_contracts_block([c, bare]).splitlines()
    assert block[1] == "  - revenue [$] = SUM(sale_price)"
    assert block[2] == "      always filter: status <> 'Cancelled'"
    assert block[3] == "  - aov = AVG(total)" and len(block) == 4


def test_the_analyst_spec_and_the_report_definition_carry_it():
    from aughor.agent.analyst import _spec_section
    from aughor.agent.investigate import _metric_definition_receipt
    intake = {"metric_label": "revenue", "metric_sql": "SUM(sale_price)",
              "metric_table": "order_items", "metric_filters": ["status <> 'Cancelled'"]}
    assert ("  metric filter (declared, part of the definition): status <> 'Cancelled'"
            in _spec_section(intake).splitlines())
    assert "over rows where `status <> 'Cancelled'` (its declared filter)" in \
        _metric_definition_receipt(intake)
    plain = {k: v for k, v in intake.items() if k != "metric_filters"}
    assert "declared" not in _spec_section(plain) + _metric_definition_receipt(plain)


@pytest.mark.parametrize("spec_table, carried", [
    ("order_items", ["status <> 'Cancelled'"]),
    ("thelook.order_items", ["status <> 'Cancelled'"]),
    ("orders", []),          # the metric is not declared there; its filter names no column of it
])
def test_the_pin_carries_the_filter_only_onto_the_declared_table(monkeypatch, spec_table, carried):
    from aughor.agent import investigate as I
    governed = SimpleNamespace(name="revenue", label="Revenue", sql="SUM(sale_price)",
                               tables=["order_items"], filters=["status <> 'Cancelled'"],
                               verified=True, rank=0, unit="$", source="catalog")
    monkeypatch.setattr("aughor.semantic.canonical.resolve_planning_metrics",
                        lambda *a, **k: [governed])
    monkeypatch.setattr(I, "_match_canonical_metric", lambda *a, **k: governed)
    intake = SimpleNamespace(metric_label="revenue", metric_sql="sum( sale_price )",
                             metric_table=spec_table, metric_is_ratio=False, metric_filters=[])
    note = I._pin_canonical_metric(intake, "c1", "", None)
    assert intake.metric_filters == carried
    assert ("declared over rows where status <> 'Cancelled'" in (note or "")) == bool(carried)
