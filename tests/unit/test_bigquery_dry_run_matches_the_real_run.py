"""A dry run must be configured like the run it is standing in for.

`execute()` and the typed read both set `default_dataset`, so `FROM order_items`
resolves on a connection whose dataset is known. `dry_run()` built its OWN
`QueryJobConfig` and left it out — so the identical SQL came back "Table must be
qualified with a dataset".

That mattered because `validate.audit_value_sql` opens with `conn.dry_run(sql)` and
blanks the metric when it does not bind. On theLook every north-star formula was
rejected by a validator configured differently from the executor that would have run it
happily: 0 of 6 metrics kept their SQL, while the DuckDB connections kept 6/6, 7/8 and
5/7. Six metrics with no formula is why no approved metric defines revenue there, which
is what holds every Slack send at the departure gate.

Measured live on 2026-09-19 against connection 8233e4fd, before the fix:
`SELECT COUNT(*) FROM order_items` executes and returns 180342, and the same statement
fails to dry-run. One statement, two answers, and the audit only ever saw the second.
"""
import ast
import inspect
from pathlib import Path

import pytest

import aughor.connectors.warehouse.bigquery as bq


def _job_config_calls() -> list[ast.Call]:
    """Every `QueryJobConfig(...)` construction in the module, DISCOVERED from source.

    Listing the call sites by hand beside the expectation would be a guard that cannot
    fail: a fourth site added tomorrow is exactly the regression, and a hand-written
    population would not contain it.
    """
    tree = ast.parse(Path(inspect.getfile(bq)).read_text())
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", getattr(n.func, "id", "")) == "QueryJobConfig"]


def test_exactly_one_place_decides_how_a_query_is_configured():
    """Three sites built their own config and one of them forgot the dataset. The fix is
    not "add it to the third" — it is that there is one place to forget it in."""
    calls = _job_config_calls()
    assert len(calls) == 1, (
        f"{len(calls)} QueryJobConfig sites — every query on this connection must be "
        "configured by `_job_config`, or a validator can disagree with the runner again"
    )


def test_the_one_config_sets_the_default_dataset():
    """The keyword whose absence was the whole defect."""
    kwargs = {k.arg for k in _job_config_calls()[0].keywords if k.arg}
    assert "default_dataset" in kwargs


def test_every_method_that_runs_a_query_uses_the_shared_config():
    """The population is DISCOVERED: any method that reaches `self._client.query(` is a
    place a query is configured, and each must route through the shared builder. Naming
    the methods here instead would miss the next one added — which is the regression."""
    tree = ast.parse(Path(inspect.getfile(bq)).read_text())
    offenders = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        body = ast.dump(fn)
        runs_query = "attr='query'" in body and "attr='_client'" in body
        if runs_query and "attr='_job_config'" not in body:
            offenders.append(fn.name)
    assert not offenders, (
        f"{offenders} run a query without the shared job config — this is exactly how "
        "dry_run came to disagree with the executor"
    )


def test_the_dry_run_carries_the_dataset_the_run_would_use():
    """The behaviour, not just the shape: same `default_dataset` on both paths."""
    pytest.importorskip("google.cloud.bigquery")
    conn = bq.BigQueryConnection.__new__(bq.BigQueryConnection)   # no client, no network
    conn._project, conn._dataset = "proj", "thelook"

    run = conn._job_config()
    dry = conn._job_config(dry_run=True, use_query_cache=False)
    assert dry.default_dataset == run.default_dataset
    assert str(dry.default_dataset).endswith("proj.thelook")
    assert dry.dry_run is True, "the override must still reach the config"


def test_a_connection_with_no_dataset_still_configures_cleanly():
    """`default_dataset=None` is the honest answer when nothing is bound — it must not
    become the string 'proj.' and send BigQuery looking for a dataset with no name."""
    pytest.importorskip("google.cloud.bigquery")
    conn = bq.BigQueryConnection.__new__(bq.BigQueryConnection)
    conn._project, conn._dataset = "proj", ""
    assert conn._job_config().default_dataset is None
