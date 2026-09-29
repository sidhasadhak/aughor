"""GM-4 — a guard that cannot run says so (ROADMAP §3.49).

A guard that could not read a statement returned what a clean statement returns: nothing. Measured on theLook
(BigQuery) 2026-09-29: on a backticked, project-qualified query — the spelling the model and the cards write
there — the join and filter guards ran no statement and reported clean, and GM-3's receipt said the statement had
passed them; a snapshot fingerprint quietly left out a table it could not count; the answer resolver called a
value "absent" from a column the warehouse refused to search.

What these pin: each guard's run says what it could not check (`GuardRun.unchecked`), the receipt says
`unchecked:<guard>` rather than `guarded:<guard>`, the reason rides the result as a caveat, and a repair is never
accepted on the word of a guard that could not re-check it.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.connection import DatabaseConnection, DuckDBConnection
from aughor.sql.guard_run import GuardRun
from aughor.sql.join_guard import filter_domain_check, join_domain_check

#: The spelling the model and theLook's cards write — a hyphenated project in backticks. The guards' neutral reading
#: could not parse it; they now read a statement in its own engine's dialect.
NATIVE = ("SELECT u.country, COUNT(*) FROM `bigquery-public-data.thelook_ecommerce.orders` o "
          "JOIN `bigquery-public-data.thelook_ecommerce.users` u ON o.status = u.country "
          "WHERE o.status = 'Complete' GROUP BY 1")
BARE = "SELECT u.country, COUNT(*) FROM orders o JOIN users u ON o.status = u.country GROUP BY 1"
#: A statement no dialect reads — what a guard can genuinely not parse.
UNREADABLE = "SELECT u.country FROM orders o JOIN users u ON o.status = u.country WHERE o.status = 'x' AND (("


class _Warehouse:
    """Runs the answer; answers each guard probe from ``probes`` (a substring of the probe's SQL → rows, or an
    error string), and refuses any probe it has no answer for — the engine refusing the guard's own statement.
    A fake has no door, so a probe arrives in DuckDB's spelling, as the guard wrote it."""
    dialect = "bigquery"
    writes_native_sql = True

    def __init__(self, probes: dict | None = None):
        self.probes = probes or {}
        self.ran: list[str] = []
        self.sent: list[tuple[str, str | None]] = []

    def execute(self, label, sql, *, sql_dialect=None):
        self.ran.append(label)
        self.sent.append((sql, sql_dialect))
        if not label.startswith("__"):
            return QueryResult(hypothesis_id=label, sql=sql, columns=["n"], rows=[["1"]], row_count=1)
        for needle, answer in self.probes.items():
            if needle in sql:
                if isinstance(answer, str):
                    break
                return QueryResult(hypothesis_id=label, sql=sql, columns=["a", "b"], rows=answer,
                                   row_count=len(answer))
        return QueryResult(hypothesis_id=label, sql=sql, columns=[], rows=[], row_count=0,
                           error="404 Not found: Dataset thelook_ecommerce was not found in location US")

    def get_schema(self):
        return ""

    # The real adapter, so a caller that reads `rows` gets what a connection gives it: [] for an error too.
    rows = DatabaseConnection.rows


@pytest.fixture
def shop(tmp_path: Path):
    path = tmp_path / "shop.duckdb"
    raw = duckdb.connect(str(path))
    raw.execute("CREATE TABLE orders (order_id INTEGER, status VARCHAR, num INTEGER)")
    raw.execute("INSERT INTO orders VALUES (1, 'Complete', 2), (2, 'Shipped', 1)")
    raw.execute("CREATE TABLE items (order_id INTEGER, price DOUBLE)")
    raw.execute("INSERT INTO items VALUES (1, 10.0), (1, 5.0), (2, 7.5)")
    raw.execute("CREATE TABLE users (id INTEGER, country VARCHAR)")
    raw.execute("INSERT INTO users VALUES (1, 'Brasil'), (2, 'China')")
    raw.close()
    conn = DuckDBConnection(path, connection_id="gm4")
    yield conn
    conn.close()


# ── the join value-domain guard ─────────────────────────────────────────────────────────────────────────────────

def test_a_join_the_guard_cannot_parse_is_unchecked_not_clean():
    wh = _Warehouse()
    run = join_domain_check(wh, UNREADABLE)
    assert run.findings == [] and wh.ran == [], "the guard probed a statement it could not read"
    assert run.unchecked == ["the statement could not be parsed to find its join keys"]
    assert run.door == "unchecked:join-domain"
    assert run.caveats() == ["join value-domain guard: not checked — the statement could not be parsed to find "
                             "its join keys"]
    # A statement with no join has nothing for this guard to check, parsed or not.
    assert join_domain_check(wh, "SELECT `x` FROM `p-x.d.t` WHERE ((").unchecked == []


def test_a_join_whose_probes_the_warehouse_refuses_is_unchecked():
    run = join_domain_check(_Warehouse(), BARE)
    assert run.findings == []
    assert len(run.unchecked) == 1
    assert run.unchecked[0].startswith("orders.status ↔ users.country: the probe of orders.status failed: 404")


def test_a_join_probed_one_way_is_checked():
    """One refused direction does not make the pair unchecked when the other direction measured it."""
    wh = _Warehouse({'FROM (SELECT "country" FROM "users" LIMIT': [["5", "0"]]})
    run = join_domain_check(wh, BARE)
    assert run.unchecked == [] and run.door == "guarded:join-domain"
    assert [(w.table_a, w.col_a, w.overlap) for w in run.findings] == [("orders", "status", 0.0)]


def test_a_checked_join_fires_and_says_guarded(shop):
    run = join_domain_check(shop, "SELECT u.country, COUNT(*) FROM orders o JOIN users u ON o.status = u.country "
                                  "GROUP BY 1")
    assert run.door == "guarded:join-domain" and run.unchecked == []
    assert [(w.col_a, w.col_b, w.overlap) for w in run.findings] == [("status", "country", 0.0)]


# ── the filter value-domain guard ───────────────────────────────────────────────────────────────────────────────

def test_a_filter_the_guard_cannot_read_is_unchecked():
    assert filter_domain_check(_Warehouse(), UNREADABLE).unchecked == [
        "the statement could not be parsed to find its filter values"]
    run = filter_domain_check(_Warehouse(), "SELECT COUNT(*) FROM orders WHERE status = 'complete'")
    assert run.findings == [] and run.door == "unchecked:filter-domain"
    assert run.unchecked[0].startswith("the values of orders.status could not be read: 404")


def test_a_value_in_no_column_whose_sibling_search_fails_is_said():
    """The domain is complete, so the predicate matches no row; which other column holds the value could not be
    looked up. That used to be said by nothing at all."""
    wh = _Warehouse({'SELECT DISTINCT CAST("status"': [["Complete"], ["Shipped"]]})
    run = filter_domain_check(wh, "SELECT COUNT(*) FROM orders WHERE status = 'Zzyzx'")
    assert run.findings == []
    assert run.unchecked == ["'Zzyzx' is not a stored value of orders.status, and the table's other columns "
                             "could not be searched for it"]


# ── the grain guard ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_grain_guard_says_what_it_could_not_probe(shop):
    from aughor.sql.grain_guard import grain_check

    refused = lambda s: (False, None, "400 Unrecognized name: order_id")  # noqa: E731
    run = grain_check("SELECT SUM(o.num) FROM orders o JOIN items i ON o.order_id = i.order_id", refused, "duckdb")
    assert run.findings == [] and run.door == "unchecked:grain"
    assert run.unchecked == ["the key order_id of items could not be probed: 400 Unrecognized name: order_id"]
    assert grain_check("SELECT SUM(x) FROM a JOIN b ON (((", refused, "duckdb").unchecked == [
        "the statement could not be parsed in duckdb's dialect to find its join keys"]

    def probe(s):
        r = shop.execute("__grain_probe__", s, sql_dialect="duckdb")
        return (not r.error, r.rows, r.error or "")
    run = grain_check("SELECT SUM(o.num) FROM orders o JOIN items i ON o.order_id = i.order_id", probe, "duckdb")
    assert run.unchecked == [] and [f.fanned_table for f in run.findings] == ["items"]


# ── a repair is confirmed only by a guard that could re-check it ────────────────────────────────────────────────

def test_cleared_means_found_nothing_and_left_nothing_newly_unchecked():
    before = GuardRun("join-domain", unchecked=["a.x ↔ b.y: the probe of a.x failed: 404 job 1"])
    assert GuardRun("join-domain").cleared(before)
    assert GuardRun("join-domain", unchecked=["a.x ↔ b.y: the probe of a.x failed: 404 job 2"]).cleared(before), \
        "the same part, refused again with different engine words, was read as newly unchecked"
    assert not GuardRun("join-domain", unchecked=["the statement could not be parsed to find its join keys"]
                        ).cleared(before)
    assert not GuardRun("join-domain", findings=["still disjoint"]).cleared(before)


class _Fixer:
    def __init__(self, fixed_sql):
        self.fixed_sql = fixed_sql

    def __call__(self, role):
        return self

    def complete(self, *, system, user, response_model):
        return response_model(fixed_sql=self.fixed_sql, explanation="rejoined")


_TEMPLATE = "{dialect}{sql}{error}{schema}{kb_patterns_section}{metrics_section}{error_diagnosis}"


@pytest.mark.parametrize("fix_probe, accepted", [("404", False), ([["5", "5"]], True)],
                         ids=["the fix's join cannot be re-checked", "control: the fix's join re-checks clean"])
def test_a_fix_the_join_guard_cannot_recheck_is_not_accepted(fix_probe, accepted):
    from aughor.sql.executor import execute_guarded

    wh = _Warehouse({'"users"': [["5", "0"]], '"customers"': fix_probe})
    fix = "SELECT c.name, COUNT(*) FROM orders o JOIN customers c ON o.user_id = c.id GROUP BY 1"
    r = execute_guarded(wh, BARE, query_id="answer", fix_prompt_template=_TEMPLATE, provider_factory=_Fixer(fix))
    assert (r.sql == fix) is accepted
    assert ("repaired:model" in r.doors) is accepted
    if not accepted:
        assert any("share only 0%" in c for c in r.caveats), "the unrepaired mismatch lost its caveat"


# ── the battery's receipt and its caveats ───────────────────────────────────────────────────────────────────────

def test_the_battery_says_unchecked_and_the_caveat_travels():
    from aughor.sql.executor import execute_guarded

    r = execute_guarded(_Warehouse(), UNREADABLE, query_id="answer")
    assert not r.error
    assert {"unchecked:join-domain", "unchecked:filter-domain"} <= set(r.doors)
    assert not {"guarded:join-domain", "guarded:filter-domain"} & set(r.doors)
    assert "join value-domain guard: not checked — the statement could not be parsed to find its join keys" \
        in r.caveats


def test_the_validate_route_never_passes_a_statement_a_guard_could_not_read(shop):
    from aughor.sql.validation import validate_sql

    v = validate_sql("gm4", NATIVE, db=_Warehouse())
    assert v["passed"] is False and v["issue_count"] == 0
    assert {u["guard"] for u in v["unchecked_guards"]} >= {"join-domain", "filter-domain"}
    clean = validate_sql("gm4", "SELECT status, COUNT(*) FROM orders GROUP BY 1", db=shop)
    assert clean["passed"] is True and clean["unchecked_guards"] == []


def test_the_trust_verdict_carries_what_it_could_not_check():
    from aughor.trust import Scope, verify

    checks = [c for c in verify(BARE, Scope(conn=_Warehouse(), dialect="bigquery")).checks if c.name == "join_domain"]
    assert [(c.ok, c.severity, c.detail) for c in checks] == [(False, "info", {"unchecked": True})]
    assert checks[0].reason.startswith("not checked — orders.status ↔ users.country")


def test_the_receipt_says_unchecked_in_plain_words():
    from aughor.db.doors import describe

    assert describe(["unchecked:join-domain"]) == [
        "NOT checked by the join value-domain guard: it could not run on this statement"]


# ── the snapshot pin, answer resolution, the ambiguity probe ────────────────────────────────────────────────────

class _Counts:
    """Counts the tables it knows; refuses the rest. No raw path, so every probe goes through the door."""
    def __init__(self, counts):
        self.counts = counts

    def raw_execute(self, sql):
        raise AttributeError("no raw path")

    def execute(self, label, sql, *, sql_dialect=None):
        for table, n in self.counts.items():
            if f'"{table}"' in sql:
                return QueryResult(hypothesis_id=label, sql=sql, columns=["n"], rows=[[str(n)]], row_count=1)
        return QueryResult(hypothesis_id=label, sql=sql, columns=[], rows=[], row_count=0, error="404 Not found")


def test_a_fingerprint_that_cannot_cover_every_table_is_no_version():
    from aughor.db.snapshot import data_version

    assert data_version(_Counts({"orders": 3}), ["orders"]).startswith("fp:")
    assert data_version(_Counts({"orders": 3}), ["orders", "gone"]) is None, \
        "a table the probe could not count was left out and the rest passed for the version"


def test_revalidation_says_a_pinned_version_could_not_be_read():
    from aughor.explorer.grounding import numeric_cells_block
    from aughor.explorer.revalidate import revalidate_finding

    class _Moved(_Counts):
        def execute(self, label, sql, *, sql_dialect=None):
            if label == "__revalidate__":
                return QueryResult(hypothesis_id=label, sql=sql, columns=["n"], rows=[["42"]], row_count=1)
            return super().execute(label, sql, sql_dialect=sql_dialect)

    out = revalidate_finding({"sql": "SELECT COUNT(*) FROM orders", "finding": "there are 41 orders",
                              "result_cells": numeric_cells_block([["41"]]), "data_version": "fp:abc"}, _Moved({}))
    assert out["cells_changed"] and out["data_moved"] is None
    assert "could not be read, so whether the data moved is unknown" in out["interpretation"]


def test_a_column_the_warehouse_refused_is_not_a_confirmed_absence():
    from aughor.semantic.answer_resolution import _db_find_value

    schema = "TABLE: orders\n  status_label STRING\n"
    assert _db_find_value(_Warehouse(), schema, "Complete") is None          # every probe refused → cannot tell

    class _Empty(_Warehouse):
        def execute(self, label, sql, *, sql_dialect=None):
            return QueryResult(hypothesis_id=label, sql=sql, columns=["v"], rows=[], row_count=0)
    assert _db_find_value(_Empty(), schema, "Complete") == "absent"            # control: looked, and it is not there


def test_a_reading_that_could_not_run_leaves_ambiguity_undecided():
    from aughor.agent.ambiguity_probe import CandidateReading, assess_structural_ambiguity

    readings = [CandidateReading("by units", "SELECT 1"), CandidateReading("by revenue", "SELECT 2")]
    v = assess_structural_ambiguity("top products", readings,
                                    lambda s: (True, [[1]], "") if s.endswith("1") else (False, [], "400"))
    assert not v.ambiguous and v.unchecked == 1 and v.n_groups == 1
    agree = assess_structural_ambiguity("top products", readings, lambda s: (True, [[1]], ""))
    assert not agree.ambiguous and agree.unchecked == 0


# ── the guards read the engine's own spelling, and check what the statement defines ──────────────────────────────

_THELOOK = '"bigquery-public-data"."thelook_ecommerce"'


def test_the_native_spelling_is_read_and_the_project_kept():
    """theLook's own spelling parses in BigQuery's dialect, and the probe reads the table the statement named —
    project included; cut to `thelook_ecommerce.users` it resolves against the connection's project and is a 404."""
    wh = _Warehouse({f'FROM (SELECT "country" FROM {_THELOOK}."users" LIMIT': [["5", "0"]],
                     f'FROM (SELECT "status" FROM {_THELOOK}."orders" LIMIT': [["5", "0"]]})
    run = join_domain_check(wh, NATIVE)
    assert run.unchecked == [] and run.door == "guarded:join-domain"
    assert [(w.label_a, w.label_b, w.overlap) for w in run.findings] == [
        ("bigquery-public-data.thelook_ecommerce.orders.status",
         "bigquery-public-data.thelook_ecommerce.users.country", 0.0)]
    frun = filter_domain_check(_Warehouse({f'CAST("status" AS VARCHAR) AS v FROM {_THELOOK}."orders"':
                                           [["Complete"], ["Shipped"]]}), NATIVE)
    assert frun.unchecked == [] and frun.findings == []          # 'Complete' is a stored value there


def test_a_native_fragment_is_never_declared_duckdb():
    """A derived side is the author's own SQL: its probe is written in the statement's dialect and declares
    nothing. Declared DuckDB, BigQuery's DATE_TRUNC(x, MONTH) would be read as DuckDB's and its arguments swapped."""
    wh = _Warehouse()
    join_domain_check(wh, "WITH m AS (SELECT DATE_TRUNC(DATE(created_at), MONTH) AS mo FROM "
                          "`bigquery-public-data.thelook_ecommerce.orders`) SELECT o.status FROM "
                          "`bigquery-public-data.thelook_ecommerce.orders` o "
                          "JOIN m ON DATE_TRUNC(DATE(o.created_at), MONTH) = m.mo")
    derived = [(sql, declared) for sql, declared in wh.sent if "_aughor_side_a" in sql]
    assert len(derived) == 2 and all(declared is None for _, declared in derived)
    assert all("DATE_TRUNC(DATE(created_at), MONTH)" in sql for sql, _ in derived), "the CTE was not carried as written"


def test_a_join_to_a_cte_or_on_an_expression_is_probed(shop):
    fabricated = join_domain_check(shop, "WITH s AS (SELECT order_id, status FROM orders) "
                                         "SELECT u.country FROM s JOIN users u ON s.status = u.country")
    assert fabricated.unchecked == []
    assert [(w.label_a, w.label_b, w.overlap) for w in fabricated.findings] == [("s.status", "users.country", 0.0)]
    real = join_domain_check(shop, "WITH s AS (SELECT order_id FROM orders) "
                                   "SELECT SUM(i.price) FROM s JOIN items i ON s.order_id = i.order_id")
    assert real.unchecked == [] and real.findings == [] and real.door == "guarded:join-domain"
    shifted = join_domain_check(shop, "SELECT SUM(i.price) FROM orders o JOIN items i ON o.order_id + 100 = i.order_id")
    assert [(w.label_a, w.overlap) for w in shifted.findings] == [("o.order_id + 100", 0.0)]
    assert join_domain_check(shop, "SELECT SUM(i.price) FROM orders o JOIN items i "
                                   "ON o.order_id + 0 = i.order_id").findings == []           # control


def test_a_lagged_self_join_is_not_a_mismatch(shop):
    """Period-over-period joins a CTE to itself on a shifted key; it overlaps only partly by design. theLook's own
    year-over-year statement read as a 14% 'different entities' mismatch before self-joins of a CTE were skipped."""
    from aughor.sql.join_guard import _join_sides, _parse

    lagged = ("WITH m AS (SELECT order_id AS k, SUM(num) AS n FROM orders GROUP BY 1) "
              "SELECT cur.k, cur.n - prev.n FROM m cur LEFT JOIN m prev ON prev.k = cur.k - 1")
    assert _join_sides(_parse(lagged, "duckdb"), "duckdb") == ([], []), "a self-join of one CTE was probed"
    run = join_domain_check(shop, lagged)
    assert run.findings == [] and run.unchecked == []


def test_a_filter_on_a_ctes_column_is_read_through_the_statement(shop):
    run = filter_domain_check(shop, "WITH s AS (SELECT status FROM orders) SELECT COUNT(*) FROM s "
                                    "WHERE s.status = 'complete'")
    assert run.unchecked == [] and run.door == "guarded:filter-domain"
    assert [(w.table, w.col, w.bad_value, w.suggestion) for w in run.findings] == [("s", "status", "complete", "Complete")]


def test_every_filtered_column_is_probed():
    wh = _Warehouse({"AS v FROM": [["x"]]})
    cols = [f"c{i}" for i in range(8)]
    filter_domain_check(wh, "SELECT 1 FROM t WHERE " + " AND ".join(f"{c} = 'x'" for c in cols))
    assert wh.ran.count("__filter_domain_probe__") == 8, "a filtered column past a cap went unprobed"


def test_a_sibling_search_cut_short_is_not_a_confirmed_absence():
    """The table has more text columns than the search reads: 'Zzyzx' in none of the first sixteen is not
    'in no other column'."""
    class _Wide(_Warehouse):
        def execute(self, label, sql, *, sql_dialect=None):
            if label == "__filter_sibling_cols__":
                return QueryResult(hypothesis_id=label, sql=sql, row_count=0, rows=[],
                                   columns=["status"] + [f"c{i}" for i in range(20)])
            if label == "__filter_sibling_probe__":
                return QueryResult(hypothesis_id=label, sql=sql, columns=["one"], rows=[], row_count=0)
            return super().execute(label, sql, sql_dialect=sql_dialect)

    run = filter_domain_check(_Wide({'SELECT DISTINCT CAST("status"': [["Complete"], ["Shipped"]]}),
                              "SELECT COUNT(*) FROM orders WHERE status = 'Zzyzx'")
    assert run.findings == [], "a search cut short at sixteen columns was read as 'in no other column'"
    assert run.unchecked == ["'Zzyzx' is not a stored value of orders.status; only 16 of the table's other text "
                             "columns were searched for it"]


def test_a_refused_existence_probe_binds_nothing():
    """A high-cardinality column's existence probe the warehouse refused read as 'absent', and the literal —
    which may be right — was bound to its nearest neighbour."""
    from aughor.sql.join_guard import _highcard_bind_warnings

    class _Refuses:
        _connection_id = ""

        def execute(self, label, sql, sql_dialect=None):
            if label == "__filter_highcard_exists__":
                return QueryResult(hypothesis_id=label, sql=sql, columns=[], rows=[], row_count=0, error="400 refused")
            return QueryResult(hypothesis_id=label, sql=sql, columns=["v"], rows=[["Mytheresa"]], row_count=1)

    unchecked: list[str] = []
    assert _highcard_bind_warnings(_Refuses(), "sales", "brand", {("Mytheresea", "=")}, unchecked) == []
    assert unchecked == ["whether 'Mytheresea' is a value of sales.brand could not be read: 400 refused"]


def test_a_reconciliation_is_said_in_the_engines_spelling():
    from aughor.sql.join_guard import _in_engine_spelling

    duck = "regexp_replace(CAST(\"a\" AS VARCHAR), '[^0-9]', '', 'g')"
    said = _in_engine_spelling(duck, "bigquery")
    assert "STRING" in said and "VARCHAR" not in said and ", 'g')" not in said
    assert _in_engine_spelling(duck, "duckdb") == duck


def test_the_authored_dialect_is_the_engines_only_when_it_runs_sql_as_written():
    from aughor.db.dialects import authored_dialect
    from unittest.mock import MagicMock

    class _Native:
        dialect, writes_native_sql = "bigquery", True

    class _Translating:
        dialect, writes_native_sql = "postgres", False
    assert (authored_dialect(_Native()), authored_dialect(_Translating())) == ("bigquery", "duckdb")
    assert authored_dialect(MagicMock()) == "duckdb", "a stand-in's attributes were taken for a dialect"


# ── a monitor whose query cannot run says so, once ──────────────────────────────────────────────────────────────

class _Warehouse2Rows:
    """A monitor's connection: the real adapters over an `execute` that refuses while `refusing` is set."""
    dialect = "duckdb"

    def __init__(self):
        self.refusing = True

    def execute(self, label, sql):
        if self.refusing:
            return QueryResult(hypothesis_id=label, sql=sql, columns=[], rows=[], row_count=0,
                               error="404 Not found: Table orders")
        return QueryResult(hypothesis_id=label, sql=sql, columns=["v"], rows=[["5"]], row_count=1)

    def get_schema(self):
        return ""

    rows = DatabaseConnection.rows
    scalar = DatabaseConnection.scalar


def _watch(**over):
    from aughor.monitors.models import Monitor
    base = dict(id="gm4-watch", conn_id="gm4-conn", name="Units watch", alert_on="threshold_cross",
                custom_sql="SELECT COUNT(*) FROM orders", warning_threshold=10.0, threshold_direction="below")
    base.update(over)
    return Monitor(**base)


def test_a_refused_monitor_query_is_a_failed_run_not_a_quiet_one():
    from aughor.monitors.runner import check_monitor, run_monitor

    run = check_monitor(_watch(), _Warehouse2Rows(), suppress=False)
    assert run.alert is None and run.failed.startswith("404 Not found")
    assert run_monitor(_watch(), _Warehouse2Rows(), suppress=False) is None     # the alert-only API, unchanged


def test_the_effect_records_the_failure_and_alerts_once_then_once_on_recovery(monkeypatch):
    from aughor.automations.adopt import monitor_as_automation
    from aughor.automations.engine import _dispatch_monitor
    from aughor.automations.models import Effect
    from aughor.monitors.runner import QUERY_FAILING, QUERY_RUNS_AGAIN
    from aughor.monitors.store import get_alerts, upsert_monitor

    watch = _watch()
    upsert_monitor(watch)
    wh = _Warehouse2Rows()
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: wh)
    wh.close = lambda: None

    def tick():
        return _dispatch_monitor(Effect(kind="monitor", config={"monitor_id": watch.id}),
                                 monitor_as_automation(watch))

    first, second = tick(), tick()
    assert (first.status, second.status) == ("failed", "failed")
    assert "could not run" in first.message
    assert [a.alert_on for a in get_alerts(monitor_id=watch.id)] == [QUERY_FAILING], "alerted per failing tick"
    wh.refusing = False
    third = tick()
    assert third.status == "executed"
    kinds = [a.alert_on for a in get_alerts(monitor_id=watch.id)]
    assert kinds.count(QUERY_RUNS_AGAIN) == 1 and kinds.count(QUERY_FAILING) == 1
    assert "threshold_cross" in kinds, "the run that recovered did not also check its metric (5 is below 10)"


def test_a_condition_on_a_monitor_that_cannot_run_cannot_be_read(monkeypatch):
    from aughor.automations.engine import ProbeUnavailable, default_probe
    from aughor.automations.models import Condition
    from aughor.monitors.store import upsert_monitor

    upsert_monitor(_watch(id="gm4-cond"))
    wh = _Warehouse2Rows()
    wh.close = lambda: None
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: wh)
    with pytest.raises(ProbeUnavailable, match="could not run"):
        default_probe(Condition(kind="metric", config={"monitor_id": "gm4-cond"}), None)


def test_an_alert_about_running_is_never_a_reading():
    """After a failure and a recovery, a change monitor compares with the last VALUE it read, not with the
    alerts about whether it could run."""
    from aughor.monitors.models import MonitorAlert
    from aughor.monitors.runner import QUERY_FAILING, QUERY_RUNS_AGAIN, _last_alert_value
    from aughor.monitors.store import append_alert

    for kind, value in (("any_change", 7.0), (QUERY_FAILING, None), (QUERY_RUNS_AGAIN, None)):
        append_alert(MonitorAlert(monitor_id="gm4-reading", triggered_at="2026-09-29T10:00:00Z",
                                  alert_on=kind, current_value=value, message=kind))
    assert _last_alert_value("gm4-reading") == 7.0
