"""Semantic Compiler — deterministic SQL synthesis for the 4 safe intents.

Every reference must ground against the ontology or synthesize_sql returns None (the
caller falls back to LLM SQL). See aughor/semantic/compiler.py.
"""
from types import SimpleNamespace as NS

from aughor.semantic.compiler import QueryIntent, synthesize_sql


def _p(name, st):
    return NS(name=name, semantic_type=st)


def _entity(eid, tables, props, *, created_at_col=None, active_filter=None, object_sets=None):
    return NS(id=eid, source_tables=tables, created_at_col=created_at_col,
              active_filter=active_filter, object_sets=object_sets or {},
              properties={p.name: p for p in props})


def _onto(*entities, conn="c1", schema="main"):
    ents = {e.id: e for e in entities}

    def entity_for_table(t):
        for e in entities:
            if t in e.source_tables:
                return e
        return None
    return NS(entities=ents, entity_for_table=entity_for_table,
              connection_id=conn, schema_name=schema)


def _metric(name, sql, tables, verified=True):
    return NS(name=name, sql=sql, tables=tables, verified=verified)


ORDERS = _entity("Order", ["orders"],
                 [_p("order_id", "key"), _p("amount", "measure"), _p("region", "dimension"),
                  _p("status", "dimension"), _p("order_date", "timestamp")],
                 created_at_col="order_date",
                 active_filter="status <> 'canceled'",
                 object_sets={"delivered": NS(filter_sql="status = 'delivered'", verified=True),
                              "unverified_set": NS(filter_sql="x = 1", verified=False)})
ONTO = _onto(ORDERS)


def _l(sql):
    return (sql or "").lower()


# ── scalar ──────────────────────────────────────────────────────────────────

def test_scalar_named_metric():
    sql = synthesize_sql(QueryIntent(intent_type="scalar", table="orders", metric="revenue"),
                         ONTO, metrics=[_metric("revenue", "SUM(amount)", ["orders"])])
    assert sql and "sum(amount)" in _l(sql) and "from orders" in _l(sql)
    # active_filter is applied
    assert "canceled" in _l(sql)


def test_scalar_measure_agg():
    sql = synthesize_sql(QueryIntent(intent_type="scalar", table="orders", measure="amount", agg="avg"),
                         ONTO, metrics=[])
    assert sql and "avg(amount)" in _l(sql)


def test_scalar_count_star():
    sql = synthesize_sql(QueryIntent(intent_type="scalar", table="orders", agg="count"), ONTO, metrics=[])
    assert sql and "count(*)" in _l(sql)


def test_count_distinct_on_key():
    sql = synthesize_sql(QueryIntent(intent_type="scalar", table="orders",
                                     measure="order_id", agg="count_distinct"), ONTO, metrics=[])
    assert sql and "count(distinct order_id)" in _l(sql)


# ── timeseries ────────────────────────────────────────────────────────────────

def test_timeseries_resolves_time_col_and_grain():
    sql = synthesize_sql(QueryIntent(intent_type="timeseries", table="orders",
                                     measure="amount", agg="sum", time_grain="month"), ONTO, metrics=[])
    assert sql and "date_trunc('month', order_date)" in _l(sql)
    assert "group by" in _l(sql) and "order by" in _l(sql)
    # NULL guard present (sqlglot may render IS NOT NULL as NOT … IS NULL)
    assert "order_date is null" in _l(sql) and "not" in _l(sql)


def test_timeseries_bad_grain_gated():
    assert synthesize_sql(QueryIntent(intent_type="timeseries", table="orders",
                                      measure="amount", time_grain="fortnight"), ONTO, metrics=[]) is None


# ── breakdown / ranking ───────────────────────────────────────────────────────

def test_breakdown_by_dimension():
    sql = synthesize_sql(QueryIntent(intent_type="breakdown", table="orders",
                                     measure="amount", agg="sum", dimension="region"), ONTO, metrics=[])
    assert sql and "group by 1" in _l(sql) and "order by 2 desc" in _l(sql)
    assert "region" in _l(sql)


def test_ranking_applies_limit_and_dir():
    sql = synthesize_sql(QueryIntent(intent_type="ranking", table="orders", measure="amount",
                                     dimension="region", order_desc=False, limit=5), ONTO, metrics=[])
    assert sql and "order by 2 asc" in _l(sql) and "limit 5" in _l(sql)


def test_ranking_default_limit():
    sql = synthesize_sql(QueryIntent(intent_type="ranking", table="orders", measure="amount",
                                     dimension="region"), ONTO, metrics=[])
    assert "limit 10" in _l(sql)


# ── object set + window filters ───────────────────────────────────────────────

def test_object_set_filter_applied():
    sql = synthesize_sql(QueryIntent(intent_type="scalar", table="orders", measure="amount",
                                     object_set="delivered"), ONTO, metrics=[])
    assert "delivered" in _l(sql)


def test_unverified_object_set_gated():
    assert synthesize_sql(QueryIntent(intent_type="scalar", table="orders", measure="amount",
                                      object_set="unverified_set"), ONTO, metrics=[]) is None


def test_window_filter_applied():
    sql = synthesize_sql(QueryIntent(intent_type="scalar", table="orders", measure="amount",
                                     window=("2025-01-01", "2025-12-31")), ONTO, metrics=[])
    assert "2025-01-01" in sql and "2025-12-31" in sql


# ── gating (fall back to LLM) ─────────────────────────────────────────────────

def test_unknown_metric_gated():
    assert synthesize_sql(QueryIntent(intent_type="scalar", table="orders", metric="nope"),
                          ONTO, metrics=[_metric("revenue", "SUM(amount)", ["orders"])]) is None


def test_unverified_metric_gated():
    assert synthesize_sql(QueryIntent(intent_type="scalar", table="orders", metric="revenue"),
                          ONTO, metrics=[_metric("revenue", "SUM(amount)", ["orders"], verified=False)]) is None


def test_multitable_metric_gated():
    assert synthesize_sql(QueryIntent(intent_type="scalar", table="orders", metric="rev"),
                          ONTO, metrics=[_metric("rev", "SUM(o.a)", ["orders", "items"])]) is None


def test_sum_over_nonmeasure_gated():
    # 'region' is a dimension, not a measure → don't SUM it
    assert synthesize_sql(QueryIntent(intent_type="scalar", table="orders", measure="region", agg="sum"),
                          ONTO, metrics=[]) is None


def test_missing_dimension_gated():
    assert synthesize_sql(QueryIntent(intent_type="breakdown", table="orders", measure="amount",
                                      dimension="ghost"), ONTO, metrics=[]) is None


def test_unknown_table_gated():
    assert synthesize_sql(QueryIntent(intent_type="scalar", table="ghosts", measure="amount"),
                          ONTO, metrics=[]) is None


def test_bad_intent_type_gated():
    assert synthesize_sql(QueryIntent(intent_type="pivot", table="orders", measure="amount"),
                          ONTO, metrics=[]) is None


def test_timeseries_no_time_col_gated():
    bare = _onto(_entity("Bare", ["bare"], [_p("v", "measure")]))
    assert synthesize_sql(QueryIntent(intent_type="timeseries", table="bare", measure="v"),
                          bare, metrics=[]) is None
