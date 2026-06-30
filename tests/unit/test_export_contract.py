"""Output-contract parity: aughor.sql.closed_loop.rows_to_csv must match the Spider2 evaluator's
serialization (``pd.DataFrame(rows, columns=cols).to_csv(index=False)``) byte-for-byte.

This is the gap that silently zeroes a *correct* cloud query (a value-correct result that serializes
differently fails the result-table match). Locking it offline now de-risks the first cloud run,
where the failure would otherwise be invisible and expensive to diagnose.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from aughor.sql.closed_loop import rows_to_csv

pd = pytest.importorskip("pandas")   # the evaluator uses pandas; parity is defined against it


def _evaluator_csv(cols, rows, path):
    """Exactly what Spider's evaluate.py does to materialize a result table."""
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    return Path(path).read_text()


@pytest.mark.parametrize("cols,rows", [
    (["a", "b"], [[1, 2], [3, 4]]),                                   # plain ints
    (["x", "y"], [[1.5, 2.0], [3.25, 4.0]]),                          # floats (trailing-zero formatting)
    (["region", "total"], [["DE", 100.0], ["US", 250.5]]),           # strings + floats
    (["a", "b"], [[1, None], [None, 4]]),                            # None ⇒ NaN/float upcast (the classic landmine)
    (["s"], [["has,comma"], ['has"quote'], ["plain"]]),              # quoting/escaping
    (["n"], [[0], [-5], [12345678]]),                                # signed / large ints
    (["v"], [[None], [None]]),                                       # all-null column
])
def test_rows_to_csv_matches_evaluator(tmp_path, cols, rows):
    ours = tmp_path / "ours.csv"
    theirs = tmp_path / "theirs.csv"
    rows_to_csv(cols, rows, ours)
    expected = _evaluator_csv(cols, rows, theirs)
    assert ours.read_text() == expected, "rows_to_csv diverged from the evaluator's pandas to_csv"


def test_no_literal_null_string(tmp_path):
    """Regression guard for the original SnowflakeConnection bug: None must never serialize as the
    literal string 'NULL' (which would fail the match against the evaluator's empty cell)."""
    p = tmp_path / "n.csv"
    rows_to_csv(["a", "b"], [[None, "x"]], p)
    assert "NULL" not in p.read_text()


def test_column_order_preserved(tmp_path):
    p = tmp_path / "o.csv"
    rows_to_csv(["c", "a", "b"], [[3, 1, 2]], p)
    assert list(csv.reader(p.open()))[0] == ["c", "a", "b"]
