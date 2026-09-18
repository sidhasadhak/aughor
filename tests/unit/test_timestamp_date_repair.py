"""A strict-typing engine's TIMESTAMP-vs-DATE refusal is repaired without a round-trip.

Measured 2026-09-18 from the live audit log. Of September's 222 SQL failures, 42 were this
one shape — every one on the theLook BigQuery connection, every one the operator `>=`:

    WHERE orders.created_at >= DATE '2025-02-01' AND orders.created_at < DATE '2025-03-01'
    -> 400 No matching signature for operator >= for argument types: TIMESTAMP, DATE

And every literal in those 42 queries was the EXPLICIT `DATE 'x'` form — 228 of them, never
a bare string. That is the whole reason guidance had not worked: the BigQuery rule block has
warned about this for as long as it has existed, but it describes a BARE '2026-08-01'
literal, while the model writes `DATE '2026-08-01'`, which reads as already-typed and
deliberate. The rule is now explicit that writing DATE in front is what MAKES it a DATE.

Guidance alone had its chance 42 times, so the repair is deterministic: a second fast-path
in `SqlWriter.fix`, before any LLM call, under the same dry-run gate as the candidate-binding
substitution beside it.

MEANING-PRESERVING for the operators that occur: a DATE promoted to TIMESTAMP is midnight of
that day, which is exactly what an engine that DOES coerce (DuckDB, Postgres) computes — so
`ts >= DATE 'x'` and `ts < DATE 'y'` keep their boundaries precisely.
"""
import inspect

import pytest

from aughor.db.dialects import rules_for_dialect
from aughor.sql import writer as W

ERR = ("400 No matching signature for operator >= for argument types: TIMESTAMP, DATE\n"
       "  Signature: T1 >= T1\n    Unable to find common supertype")

#: The live failing query, verbatim in shape.
SQL = ("SELECT COUNT(*) AS n FROM `p.d.orders` AS orders "
       "WHERE (orders.created_at >= DATE '2025-02-01' AND orders.created_at < DATE '2025-03-01')")


class TestTheRewrite:
    def test_it_promotes_every_date_literal(self):
        out = W._repair_timestamp_date_literal(ERR, SQL)
        assert out is not None
        assert "TIMESTAMP '2025-02-01'" in out and "TIMESTAMP '2025-03-01'" in out
        assert "DATE '" not in out

    def test_it_keeps_the_boundaries_exactly(self):
        """Promotion must not move a range edge — midnight is what a coercing engine uses."""
        out = W._repair_timestamp_date_literal(ERR, SQL)
        assert ">= TIMESTAMP '2025-02-01'" in out
        assert "< TIMESTAMP '2025-03-01'" in out

    def test_it_leaves_the_DATE_function_alone(self):
        """`DATE(col)` is a cast, not a literal — rewriting it would change the column side."""
        sql = "SELECT DATE(created_at) AS d FROM t WHERE created_at >= DATE '2025-01-01'"
        out = W._repair_timestamp_date_literal(ERR, sql)
        assert "DATE(created_at)" in out, "the DATE() function was rewritten"
        assert "TIMESTAMP '2025-01-01'" in out

    def test_no_space_form_is_handled(self):
        out = W._repair_timestamp_date_literal(ERR, "SELECT * FROM t WHERE c >= DATE'2025-01-01'")
        assert "TIMESTAMP '2025-01-01'" in out

    @pytest.mark.parametrize("err", [
        "Binder Error: Referenced column \"x\" not found in FROM clause!",
        "400 Type not found: VARCHAR at [1:49]",
        "",
    ])
    def test_an_unrelated_error_is_not_touched(self, err):
        """It must key on the SIGNATURE, or it would rewrite date literals on every failure."""
        assert W._repair_timestamp_date_literal(err, SQL) is None

    def test_it_declines_sql_with_nothing_to_promote(self):
        assert W._repair_timestamp_date_literal(ERR, "SELECT 1 FROM t WHERE a >= b") is None

    def test_the_reversed_argument_order_also_matches(self):
        """The engine may word it DATE, TIMESTAMP depending on which side is which."""
        err = "No matching signature for operator <= for argument types: DATE, TIMESTAMP"
        assert W._repair_timestamp_date_literal(err, SQL) is not None


class TestItRunsBeforeTheModel:
    def test_the_fast_path_is_wired_ahead_of_the_llm_loop(self):
        src = inspect.getsource(W.SqlWriter.fix)
        i = src.find("_repair_timestamp_date_literal")
        j = src.find("for attempt in range(1, max_retries + 1)")
        assert i > 0, "the repair is not wired into fix() at all"
        assert i < j, "the repair runs AFTER the LLM loop — it saves no round-trip there"

    def test_it_is_dry_run_gated_like_its_sibling(self):
        """A rewrite that does not bind must be discarded, not executed."""
        src = inspect.getsource(W.SqlWriter.fix)
        seg = src[src.find("_repair_timestamp_date_literal"):]
        assert "dry_run(" in seg.split("return FixResult")[0], "adopted without a dry-run gate"

    def test_it_reports_a_typed_class(self):
        src = inspect.getsource(W.SqlWriter.fix)
        seg = src[src.find("_repair_timestamp_date_literal"):]
        assert 'error_class="type_mismatch"' in seg.split("for attempt")[0]


class TestTheGuidanceNamesTheFormTheModelWrites:
    def test_the_rule_covers_the_explicit_literal(self):
        """The old rule described a BARE literal only, which is why 42 queries sailed past it
        writing `DATE '2025-02-01'` and believing themselves correct."""
        line = next(l for l in rules_for_dialect("bigquery").splitlines()
                    if "TIMESTAMP vs DATE" in l)
        assert "DATE '2026-08-01'" in line, "the rule still only warns about a bare literal"
        assert "bare" in line, "the bare-literal case must not be lost in the rewrite"

    def test_it_says_what_to_write_instead(self):
        line = next(l for l in rules_for_dialect("bigquery").splitlines()
                    if "TIMESTAMP vs DATE" in l)
        assert "TIMESTAMP '2026-08-01'" in line and "DATE(ts_col)" in line


# ── The transpile candidate ───────────────────────────────────────────────────
# Promoting the DATE literals alone repaired 34 of the 42 measured failures. The other 8
# carried a SECOND DuckDB spelling in the same query — 5 x `DATE_TRUNC('x', col)`, 3 x
# `::cast` — and the dry-run gate correctly discarded a rewrite that still did not bind. A
# model that writes one DuckDB form usually writes another.

class _Conn:
    """A native-execution connection: `native_sql` transpiles for it."""
    dialect, writes_native_sql = "bigquery", True


DUCK_TWO_ERRORS = ("SELECT DATE_TRUNC('week', created_at) AS w, COUNT(order_id) AS n "
                   "FROM orders WHERE created_at >= DATE '2026-06-07' "
                   "AND created_at < DATE '2026-09-01' GROUP BY 1")


class TestTheTranspileCandidate:
    def test_it_fixes_BOTH_spellings_at_once(self):
        out = W._repair_by_transpile(_Conn(), ERR, DUCK_TWO_ERRORS)
        assert out is not None
        assert "TIMESTAMP_TRUNC(created_at, WEEK)" in out, "the DuckDB DATE_TRUNC survived"
        assert "TIMESTAMP '2026-06-07'" in out, "the DATE literal survived"
        assert "DATE '" not in out and "AS DATE)" not in out

    def test_the_order_is_transpile_then_promote(self):
        """Load-bearing, and the reverse of the obvious one. Verified against live BigQuery
        on the run that exposed this:

            transpile only         TIMESTAMP >= DATE      (the literal survives)
            promote only           valid date part name   (DATE_TRUNC survives)
            promote -> transpile   TIMESTAMP >= DATETIME  (sqlglot maps DuckDB's naive
                                                           TIMESTAMP to BigQuery's DATETIME)
            transpile -> promote   binds

        So a promoted literal must NOT be fed through the transpiler."""
        import sqlglot
        wrong = sqlglot.transpile(W._repair_timestamp_date_literal(ERR, DUCK_TWO_ERRORS),
                                  read="duckdb", write="bigquery")[0]
        assert "DATETIME" in wrong.upper(), (
            "the DATETIME trap is gone — re-verify the order before relaxing this")
        right = W._repair_by_transpile(_Conn(), ERR, DUCK_TWO_ERRORS)
        assert "DATETIME" not in right.upper()

    @pytest.mark.parametrize("err", [
        'Binder Error: Referenced column "x" not found in FROM clause!',
        "400 Unrecognized name: thelook at [1:20]",
        "Table \"orders\" must be qualified with a dataset",
    ])
    def test_a_name_error_never_triggers_a_transpile(self, err):
        """Re-reading SQL as DuckDB is safe when the engine rejected its SHAPE and unsafe
        when it merely could not find a name — that SQL may be good target-dialect SQL a
        round trip would mangle."""
        assert W._repair_by_transpile(_Conn(), err, DUCK_TWO_ERRORS) is None

    def test_a_duckdb_connection_gets_nothing(self):
        """`native_sql` is a no-op there, so the candidate must decline rather than loop."""
        class Duck: dialect, writes_native_sql = "duckdb", False
        assert W._repair_by_transpile(Duck(), ERR, DUCK_TWO_ERRORS) is None

    def test_unparseable_sql_declines_quietly(self):
        """BigQuery's backtick-quoted `project-id.dataset.table` cannot be read as DuckDB —
        `native_sql` hands such SQL back unchanged and this must return None, not the input."""
        bt = chr(96)
        sql = ("SELECT DATE_TRUNC('week', created_at) FROM " + bt +
               "bigquery-public-data.thelook.orders" + bt + " WHERE created_at >= DATE '2026-01-01'")
        assert W._repair_by_transpile(_Conn(), ERR, sql) is None


class TestCandidateOrdering:
    def test_the_narrow_repair_is_tried_first(self):
        """When promotion alone suffices — 34 of 42 — it is the smaller change, so it must
        be attempted before re-spelling the whole query."""
        src = inspect.getsource(W.SqlWriter.fix)
        assert src.index("_repair_timestamp_date_literal") < src.index("_repair_by_transpile")

    def test_the_transpile_still_precedes_the_llm(self):
        src = inspect.getsource(W.SqlWriter.fix)
        assert src.index("_repair_by_transpile") < src.index("for attempt in range(1, max_retries + 1)")

    def test_it_is_dry_run_gated(self):
        src = inspect.getsource(W.SqlWriter.fix)
        seg = src[src.index("_repair_by_transpile"):]
        assert "dry_run(" in seg.split("return FixResult")[0]
        assert 'error_class="dialect"' in seg.split("for attempt")[0]
