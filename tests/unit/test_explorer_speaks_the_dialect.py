"""The explorer's own probes must run on the engine the connection actually is.

Measured 2026-09-18 from the live audit log — the explorer's 42 September SQL failures, by
what its own SQL contained:

    22  CAST(x AS FLOAT)      -> 400 Type not found: FLOAT
    14  CAST(x AS VARCHAR)    -> 400 Type not found: VARCHAR
     4  date_trunc(…)::VARCHAR-> 400 CAST operators are not supported
     2  FILTER (WHERE …)      -> 400 Syntax error: Expected end of input but got "("

All four are DuckDB spellings sent verbatim to BigQuery. `_run`'s own docstring already drew
the line this fix keys on: SQL with a `schema` was written by a MODEL and is guarded, while
SQL without one is "built by the explorer itself from parsed schema metadata" — platform SQL,
written in DuckDB's dialect, which is precisely what `aughor.db.dialects.native_sql` exists to
translate. Model-written SQL is deliberately NOT transpiled: the model is told the target
dialect and writes in it, so reading that as DuckDB would corrupt it.

The FILTER one is the exception `native_sql` could not fix — sqlglot leaves `FILTER (WHERE …)`
in its BigQuery output and BigQuery has no such clause. It was a no-op anyway: every aggregate
but COUNT(*) already ignores NULLs, and the sibling subquery on the next line always expressed
the same intent as a plain WHERE. Removed rather than translated.
"""
import inspect

import pytest
import sqlglot

from aughor.db.dialects import native_sql
from aughor.explorer import agent as EA


class _FakeConn:
    def __init__(self, dialect="bigquery", native=True):
        self.dialect, self.writes_native_sql = dialect, native


#: The four shapes, verbatim from the audit log's failing rows.
SHAPES = {
    "distribution": ("SELECT COUNT(*) AS n, MIN(id) AS mn, MAX(id) AS mx, "
                     "AVG(CAST(id AS FLOAT)) AS mean_v, "
                     "AVG(CAST(id AS FLOAT)*CAST(id AS FLOAT)) - "
                     "AVG(CAST(id AS FLOAT))*AVG(CAST(id AS FLOAT)) AS variance FROM ds.t"),
    "period":       ("SELECT date_trunc('quarter', created_at)::VARCHAR AS p, COUNT(*) AS c "
                     "FROM ds.events WHERE created_at IS NOT NULL GROUP BY 1 ORDER BY 1"),
    "fk_hll":       ("SELECT approx_count_distinct(CAST(user_id AS VARCHAR)) AS fk_distinct, "
                     "(SELECT approx_count_distinct(CAST(id AS VARCHAR)) FROM ds.users "
                     "WHERE id IS NOT NULL) AS pk_distinct FROM ds.t"),
}

#: Spellings BigQuery rejects, each with the error it answered in the log.
REJECTED = {"AS FLOAT)": "Type not found: FLOAT",
            "AS VARCHAR)": "Type not found: VARCHAR",
            "::": "CAST operators are not supported",
            "FILTER (": "Syntax error"}


class TestEveryFailingShapeNowTranslates:
    @pytest.mark.parametrize("name", sorted(SHAPES), ids=sorted(SHAPES))
    def test_bigquery_gets_nothing_it_rejects(self, name):
        out = native_sql(_FakeConn(), SHAPES[name])
        left = [f"{tok} ({err})" for tok, err in REJECTED.items() if tok in out]
        assert not left, f"{name} still sends BigQuery: {left}\n  {out}"

    @pytest.mark.parametrize("name", sorted(SHAPES), ids=sorted(SHAPES))
    def test_the_result_is_valid_bigquery(self, name):
        out = native_sql(_FakeConn(), SHAPES[name])
        sqlglot.parse_one(out, dialect="bigquery")      # raises if it is not

    @pytest.mark.parametrize("name", sorted(SHAPES), ids=sorted(SHAPES))
    def test_duckdb_is_untouched(self, name):
        """The overwhelmingly common engine must not pay a transpile round-trip."""
        assert native_sql(_FakeConn("duckdb", False), SHAPES[name]) == SHAPES[name]

    def test_the_translation_preserves_the_measurement(self):
        """A rewrite that dropped the variance terms would silently change every profile."""
        out = native_sql(_FakeConn(), SHAPES["distribution"]).upper()
        assert out.count("AVG(") == 4 and "MIN(" in out and "MAX(" in out


class TestTheExplorerRoutesItsOwnSql:
    def test_the_platform_branch_translates(self):
        src = inspect.getsource(EA.SchemaExplorer._run)
        assert "native_sql(" in src, "_run still sends DuckDB SQL to whatever engine it finds"

    def test_model_written_sql_is_not_transpiled(self):
        """The model is told the dialect and writes in it; reading that as DuckDB corrupts it.
        The translation must sit on the `else` (no-schema) branch only."""
        src = inspect.getsource(EA.SchemaExplorer._run)
        before = src.split("native_sql(")[0]
        assert "else:" in before, "the translation is not confined to the platform-SQL branch"
        assert "_repair_contra_amount" in before, "the model branch moved — re-pin this test"

    def test_the_direct_period_probes_translate_too(self):
        """Two period probes call the connector directly, bypassing `_run` — they carried the
        `::VARCHAR` that BigQuery refused outright."""
        src = inspect.getsource(EA)
        direct = src.count('self._conn.execute("__explorer__", native_sql(')
        assert direct == 2, f"expected both direct probes wrapped, found {direct}"

    def test_no_filter_clause_survives_in_explorer_sql(self):
        """sqlglot does not rewrite `FILTER (WHERE …)` for BigQuery, so the seam cannot save
        it — it must not be written in the first place."""
        src = inspect.getsource(EA)
        offending = [ln.strip() for ln in src.splitlines()
                     if "FILTER (WHERE" in ln and not ln.strip().startswith("#")]
        assert not offending, f"FILTER reaches an engine that has no FILTER: {offending[:2]}"
