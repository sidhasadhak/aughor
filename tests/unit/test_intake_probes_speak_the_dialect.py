"""The intake's two month-key probes must run on the engine the connection actually is.

Measured 2026-09-18 from the live audit log. September: 4,409 executions, 222 failed (5.0%).
The single biggest class was a dialect error, and 71 of those 222 — 32% — came from these
two probes alone, every one on the theLook BigQuery connection:

    SELECT COUNT(DISTINCT substr(CAST(created_at AS VARCHAR), 1, 7)) …
    -> 400 Type not found: VARCHAR

Both docstrings called the probe "dialect-robust". It was not: `VARCHAR` is DuckDB/Postgres.
BigQuery wants `STRING` and MySQL wants `CHAR`.

WHY IT SURVIVED SO LONG — and why this matters more than the tokens it wasted: both probes
fail OPEN (`return None` on any error). `_populated_month_count` feeds the density guard and
`_monthly_counts` feeds `_flag_trailing_partial`. So on every BigQuery connection both guards
silently did not run, and the intake proceeded as though the window were dense and its final
month complete — the same shape as everything else found this day: a guard that does not fire.

THE FIX IS THE SEAM THAT ALREADY EXISTED. `aughor.db.dialects.native_sql` transpiles
DuckDB-written platform SQL into the dialect a `writes_native_sql` connection runs, and hands
DuckDB's own back untouched. Writing a second type-name map here would have covered the cast
and missed the `::` operator, `date_trunc` and the function names it also rewrites.

NOTE FOR ANYONE TIGHTENING THIS: parsing the OLD sql *as bigquery* with sqlglot SUCCEEDS —
sqlglot accepts `CAST(x AS VARCHAR)` and normalises it. A parse-based test would have passed
while BigQuery rejected the query. Only the live audit log caught this, which is why the
assertions below are on the TRANSPILE, not on a parse.
"""
import inspect

import pytest
import sqlglot

from aughor.agent import investigate as I
from aughor.db.dialects import native_sql


class _FakeDB:
    def __init__(self, dialect, native): self.dialect, self.writes_native_sql = dialect, native


class TestTheSeamTranslatesWhatTheProbesWrite:
    #: Exactly the two probe bodies, as the module writes them.
    DENSITY = ("SELECT COUNT(DISTINCT substr(CAST(created_at AS VARCHAR), 1, 7)) "
               "FROM ds.t WHERE created_at >= '2026-01-01' AND created_at <= '2026-06-30'")
    MONTHLY = ("SELECT substr(CAST(created_at AS VARCHAR), 1, 7) AS m, COUNT(*) AS n "
               "FROM ds.t WHERE created_at >= '2026-01-01' AND created_at <= '2026-06-30' "
               "GROUP BY 1 ORDER BY 1")

    @pytest.mark.parametrize("sql", [DENSITY, MONTHLY], ids=["density", "monthly"])
    def test_bigquery_never_receives_varchar(self, sql):
        out = native_sql(_FakeDB("bigquery", True), sql)
        assert "VARCHAR" not in out.upper(), f"BigQuery rejects this outright: {out}"
        assert "STRING" in out.upper()

    @pytest.mark.parametrize("sql", [DENSITY, MONTHLY], ids=["density", "monthly"])
    def test_mysql_never_receives_varchar(self, sql):
        out = native_sql(_FakeDB("mysql", True), sql)
        assert "VARCHAR" not in out.upper(), f"MySQL rejects a CAST to VARCHAR: {out}"
        assert "CHAR" in out.upper()

    @pytest.mark.parametrize("sql", [DENSITY, MONTHLY], ids=["density", "monthly"])
    def test_duckdb_is_handed_its_own_sql_untouched(self, sql):
        """The overwhelmingly common case must not pay a transpile round-trip."""
        assert native_sql(_FakeDB("duckdb", False), sql) == sql

    def test_the_translation_still_means_the_same_thing(self):
        """A rewrite that changed the month key would silently change every guard's verdict."""
        out = native_sql(_FakeDB("bigquery", True), self.MONTHLY)
        parsed = sqlglot.parse_one(out, dialect="bigquery").sql(dialect="bigquery").upper()
        assert "1, 7" in parsed, "the YYYY-MM prefix width changed"
        assert "COUNT(*)" in parsed and "GROUP BY" in parsed


class TestBothProbesUseIt:
    @pytest.mark.parametrize("fn", ["_populated_month_count", "_monthly_counts"])
    def test_the_probe_routes_through_the_seam(self, fn):
        src = inspect.getsource(getattr(I, fn))
        assert "native_sql(" in src, f"{fn} still sends DuckDB SQL to whatever engine it finds"

    @pytest.mark.parametrize("fn,counter", [
        ("_populated_month_count", "intake.density_probe_failed"),
        ("_monthly_counts", "intake.monthly_probe_failed"),
    ])
    def test_a_probe_failure_is_counted_not_silent(self, fn, counter):
        """Failing open is right — failing SILENTLY is how two guards went missing on every
        BigQuery run for months with nobody able to see it.

        Asserted on the SPECIFIC counter name, not on `"tolerate(" in src`: both probes
        already end in a `finally:` that tolerates a connection-CLOSE failure with its own
        counter, so the loose form passed whether or not the error path recorded anything.
        Caught by mutation — the same wrong-reason pass as `slides.code.text` in
        test_producer_reaches_surface.py, made twice in one day."""
        src = inspect.getsource(getattr(I, fn))
        assert f'counter="{counter}"' in src, (
            f"{fn} returns None on error without recording that a guard was skipped")

    @pytest.mark.parametrize("fn", ["_populated_month_count", "_monthly_counts"])
    def test_the_docstring_no_longer_claims_robustness_it_lacks(self, fn):
        doc = (getattr(I, fn).__doc__ or "")
        assert "dialect-robust" not in doc, (
            "the claim that made this invisible: it was asserted, never held")
