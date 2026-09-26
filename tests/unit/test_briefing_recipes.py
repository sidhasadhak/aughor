"""Arc BR-4 (ROADMAP §3.48) — each horizon a different job.

A DuckDB shop with regions: one region carries the range's move, one is too thin to call. The
recipe must rank the segment that moved, list the thin one without headlining it, link the
standing finding that names the mover, read the Day's still-settling days as EARLY, judge a
week against the four before it, and tell the narrator which job it is doing.
"""
from __future__ import annotations

import contextlib
from datetime import date, timedelta

import duckdb
import pytest

import aughor.knowledge.briefing as briefing_mod
import aughor.llm.provider as prov
from aughor.briefing import ranges, recipes
from aughor.knowledge.briefing import BriefingNarrative

SEP26 = date(2026, 9, 26)


def _cols(table: str, **spec) -> dict:
    return {f"{table}.{c}": {"table": table, "column": c, **p} for c, p in spec.items()}


PROFILE = {
    "tables": {"orders": {"primary_timestamp": "created_at"}},
    "columns": _cols("orders",
                     created_at={"dtype": "TIMESTAMP"},
                     amount={"dtype": "DOUBLE"},
                     region={"dtype": "VARCHAR", "is_low_cardinality": True, "distinct_count": 3},
                     customer_id={"dtype": "BIGINT", "is_fk": True, "distinct_count": 900},
                     sku={"dtype": "VARCHAR", "distinct_count": 4000}),
}


@pytest.fixture
def con():
    """40 orders a day in 'north' and 'south' worth 10 each; from 17 Aug 'north' doubles; 'isles'
    has one order every other day (too few to call)."""
    c = duckdb.connect()
    c.execute("""CREATE TABLE orders AS
        SELECT d::TIMESTAMP + INTERVAL 9 HOUR AS created_at, r AS region,
               CASE WHEN r = 'north' AND d >= DATE '2026-08-17' THEN 20.0 ELSE 10.0 END AS amount,
               'done' AS status, NULL::TIMESTAMP AS returned_at
        FROM range(DATE '2026-06-01', DATE '2026-09-26', INTERVAL 1 DAY) t(d),
             (SELECT unnest(['north', 'south']) AS r), range(40) k(i)
        UNION ALL
        SELECT d::TIMESTAMP + INTERVAL 9 HOUR, 'isles', 500.0, 'done', d::TIMESTAMP + INTERVAL 3 DAY
        FROM range(DATE '2026-06-01', DATE '2026-09-26', INTERVAL 2 DAY) t(d)""")
    yield c
    c.close()


def _run(con):
    def run(sql):
        try:
            cur = con.execute(sql)
            return [d[0] for d in cur.description], cur.fetchall(), None
        except Exception as exc:  # noqa: BLE001
            return [], [], str(exc)
    return run


@pytest.fixture
def revenue(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    from aughor.semantic.metrics import MetricDefinition, get_metric, save_metric
    save_metric(MetricDefinition(name="revenue", connection="c1", label="Revenue", sql="SUM(amount)",
                                 tables=["orders"], dimensions=["region", "customer_id", "sku", "created_at"],
                                 unit="USD", status="approved", approved_by="test",
                                 time_kind="flow", time_column="created_at",
                                 time_source="set automatically: test"))
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: PROFILE)
    return get_metric("revenue", connection_id="c1")


def test_a_breakdown_is_a_declared_low_cardinality_column_never_a_key_a_date_or_a_drill(revenue):
    assert recipes.breakdown_dimensions(revenue, PROFILE) == ["region"]


def test_the_segment_that_moved_leads_and_a_thin_one_is_listed_not_headlined(con, revenue):
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    got = recipes.what_moved([revenue], spec, _run(con), dialect="duckdb", profile_entry=PROFILE)
    lead = got["moves"][0]
    assert (lead["group"], lead["current"], lead["previous"]) == ("north", 8000.0, 4000.0)  # 10 days × 40 × 20|10
    assert lead["change"] == 4000.0 and lead["n"] == 400
    assert [c["group"] for c in got["thin"]] == ["isles"] and "isles" not in [c["group"] for c in got["moves"]]
    block = ranges.range_block(spec)
    line = recipes.move_line(lead, block, "USD")
    assert line.startswith("Revenue for region north moved from $4,000 to $8,000 (+$4,000)")


def test_why_links_the_standing_finding_that_names_the_mover_and_ignores_tiny_names():
    moves = [{"group": "north", "dimension": "region"}, {"group": "M", "dimension": "size"}]
    data = {"Sales": [{"id": "f1", "finding": "The North region carries the highest basket."},
                      {"id": "f2", "finding": "M is the most common size."}]}
    links = recipes.why_links(moves, data)
    assert [(w["segment"], w["id"]) for w in links] == [("north", "f1")]


def test_the_day_reads_the_days_still_settling_as_early(con, revenue):
    """…and leaves a cohort out: a return rate a few days old says nothing yet."""
    from aughor.semantic.metrics import MetricDefinition
    returns = MetricDefinition(name="rr", connection="c1", label="Return rate", tables=["orders"],
                               sql="SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / COUNT(*)",
                               status="approved", time_kind="cohort", time_column="created_at",
                               outcome_column="returned_at", settles_after_days=5)
    spec, _ = ranges.resolve_range("yesterday", today=SEP26, lag_days=13)
    assert spec.start == date(2026, 9, 13)
    early = recipes.early_read([revenue, returns], spec, _run(con), dialect="duckdb")
    assert [f["name"] for f in early["figures"]] == ["Revenue"]
    assert (early["start"], early["end"]) == ("2026-09-14", "2026-09-25")
    days = 12
    # north 40×20 + south 40×10 a day, plus isles 500 every other day in the span
    isles = sum(500.0 for d in range(days) if ((date(2026, 9, 14) + timedelta(days=d)) - date(2026, 6, 1)).days % 2 == 0)
    assert early["figures"][0]["value"] == days * (800.0 + 400.0) + isles


def test_a_week_is_judged_against_the_four_before_it(con, revenue):
    spec, _ = ranges.resolve_range("last_week", today=SEP26, lag_days=13)
    norm = recipes.weekly_norm(revenue, spec, _run(con), dialect="duckdb")
    assert norm is not None and norm > 0


class FakeNarrator:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.calls.append((system, user))
        return BriefingNarrative(narrative="North doubled.", headline_theme="North", citations=[])


def test_the_day_is_built_by_its_recipe_and_the_narrator_is_told_so(con, revenue, monkeypatch, tmp_path):
    fake = FakeNarrator()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fake)
    from aughor.util.json_store import KeyedJsonStore
    store = KeyedJsonStore(tmp_path / "briefing_cache.json")
    monkeypatch.setattr(briefing_mod, "_store", lambda: store)

    @contextlib.contextmanager
    def runner():
        yield _run(con), "duckdb"

    spec, _ = ranges.resolve_range("yesterday", today=SEP26, lag_days=13)
    brief = ranges.build_range_briefing("c1", spec, scope_key="c1", domain_data={}, profile=None,
                                        runner=runner)
    block = brief["period"]
    assert block["recipe"] == "day" and "early_read" in block["sections"]
    assert block["early"]["figures"] and block["moves"]
    system, user = fake.calls[-1]
    assert "This is the DAY briefing, written for acting today." in system
    assert "Revenue for region north" in user


def test_a_figure_from_a_table_that_has_not_settled_is_provisional_whatever_its_age():
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metric_time import Window
    w = Window("current", date(2026, 8, 17), date(2026, 8, 27))
    flow = {"time_kind": "flow"}
    assert mt.figure_status(flow, w, as_of=SEP26, lag_days=15) == "final"
    assert mt.figure_status(flow, w, as_of=SEP26, lag_days=15, unsettled=True) == "provisional"


def test_a_move_on_a_thin_comparison_is_too_few_to_call(con, revenue):
    """theLook's Day, 2026-09-26: Shorts 7 → 31 led the narrative on a comparison of 7 rows."""
    # the comparison window keeps five 'north' orders; the range keeps its 400
    con.execute("DELETE FROM orders WHERE region = 'north' AND created_at >= TIMESTAMP '2026-08-03' "
                "AND created_at < TIMESTAMP '2026-08-13'")
    con.execute("INSERT INTO orders SELECT TIMESTAMP '2026-08-05 09:00', 'north', 10.0, 'done', NULL "
                "FROM range(5)")
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    got = recipes.what_moved([revenue], spec, _run(con), dialect="duckdb", profile_entry=PROFILE)
    assert [c["group"] for c in got["thin"]][:1] == ["north"]
    assert "north" not in [c["group"] for c in got["moves"]]
    assert got["thin"][0]["n"] == 5
