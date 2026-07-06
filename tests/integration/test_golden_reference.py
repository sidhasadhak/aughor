"""WS3 · the golden-set reference replay as a CI gate.

Nothing in CI measured NL2SQL accuracy infrastructure before this: the 53-pair
golden set, the execution scorer (`evals.sql_accuracy.score_single`) and the
bundled ecommerce fixture could drift apart silently (a renamed column, a scorer
regression, a broken record) and the next LIVE eval would mismeasure. This gate
replays every record's reference_sql through the real scorer against a
freshly-seeded fixture — hermetic (temp DuckDB + the isolated registry), no LLM,
seconds. A red here means the measurement substrate itself broke, not the model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
DATASET = REPO / "evals" / "golden_sql_expanded.jsonl"


def _records() -> list[dict]:
    return [json.loads(line) for line in DATASET.open() if line.strip()]


@pytest.fixture(scope="module")
def golden_db(tmp_path_factory):
    """A fresh ecommerce fixture DB registered in the (test-isolated) registry."""
    import duckdb

    from aughor.db import registry
    from aughor.db.connection import open_connection_for
    from aughor.samples.setup import _seed_ecommerce

    path = tmp_path_factory.mktemp("golden") / "samples.duckdb"
    conn = duckdb.connect(str(path))
    try:
        _seed_ecommerce(conn)
    finally:
        conn.close()
    conn_id = registry.add_connection("golden-ci", "duckdb", str(path))
    db = open_connection_for(conn_id)
    yield db
    db.close()


@pytest.mark.parametrize("record", _records(), ids=lambda r: r["id"])
def test_reference_sql_replays_perfectly(record, golden_db):
    from evals.run_golden import run_eval

    result = run_eval(record, golden_db, mode="reference")
    scores = result["scores"]
    assert not scores.get("error"), f"{record['id']}: {scores.get('error')}"
    assert scores.get("overall", 0.0) >= 0.99, (
        f"{record['id']} reference replay scored {scores.get('overall')} — the golden "
        f"record, fixture schema, or scorer has drifted."
    )
