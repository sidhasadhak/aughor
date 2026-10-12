"""A removed dataset takes its trusted queries (`semantic.trusted_queries.purge_scope`).

Measured 2026-10-12 on the live install: the Workspace's `luxexperience` dataset was removed the day before, and eleven
of the Workspace's trusted queries still read `luxexperience.orders`, `.returns`, `.order_items` — and the Briefer kept
running one, failing on a schema that was gone. The store is a connection's, so a dataset's removal never saw them.
The user's rule (2026-10-11): a removal takes everything but the SQL audit log and the model-call log.
"""
from __future__ import annotations

import json

import pytest

from aughor.semantic import trusted_queries as tq


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_TRUSTED_QUERIES_PATH", str(tmp_path / "trusted_queries.json"))
    rows = [
        {"id": "lux-orders", "connection_id": "workspace", "question": "orders", "sql": "SELECT COUNT(*) FROM luxexperience.orders"},
        {"id": "lux-join", "connection_id": "workspace", "question": "returns by reason",
         "sql": "SELECT r.reason FROM luxexperience.returns r JOIN uber_ncr.rides x ON 1=1"},
        {"id": "lux-listed", "connection_id": "workspace", "question": "listed", "sql": "SELECT 1", "tables": ["luxexperience.orders"]},
        {"id": "uber", "connection_id": "workspace", "question": "rides", "sql": "SELECT COUNT(*) FROM uber_ncr.rides"},
        {"id": "plain", "connection_id": "workspace", "question": "default", "sql": "SELECT COUNT(*) FROM orders"},
        {"id": "luxish", "connection_id": "workspace", "question": "a look-alike", "sql": "SELECT COUNT(*) FROM luxexperience_v2.orders"},
        {"id": "other-conn", "connection_id": "dcc63d83", "question": "theirs", "sql": "SELECT COUNT(*) FROM luxexperience.orders"},
        {"id": "bq", "connection_id": "bigq", "question": "a project", "sql": "SELECT 1 FROM proj.luxexperience.orders"},
    ]
    (tmp_path / "trusted_queries.json").write_text(json.dumps(rows))
    return tmp_path / "trusted_queries.json"


def _ids(path) -> list[str]:
    return sorted(d["id"] for d in json.loads(path.read_text()))


def test_a_removed_dataset_takes_the_trusted_queries_that_read_it_and_keeps_the_rest(store):
    assert tq.purge_scope("workspace", "luxexperience") == 3
    assert _ids(store) == ["bq", "luxish", "other-conn", "plain", "uber"]
    assert tq.purge_scope("workspace", "luxexperience") == 0                  # once
    assert tq.purge_scope("bigq", "luxexperience") == 1                       # project.dataset.table
    assert tq.purge_scope("", "luxexperience") == 0 and tq.purge_scope("workspace", "") == 0


def test_it_runs_on_every_dataset_removal(store):
    from aughor.kernel.registries import purge_hooks
    assert "trusted_queries" in purge_hooks.registered_hook_names()["schema"]
    assert purge_hooks.run_schema_purge_hooks("workspace", "luxexperience")["trusted_queries"] == 3
