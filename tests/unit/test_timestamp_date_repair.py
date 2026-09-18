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
