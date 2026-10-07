"""The Semantic Layer's metric catalogue reads the schema a connection is registered on.

The explorer keeps a connection's proposed metrics on its business profile, keyed by
(connection, schema). The Semantic Layer asked for no schema, so it read the bare key: theLook
(registered on `thelook`) listed 0 explorer metrics where its `thelook` profile holds 3, while
the Briefing measured them as Key Metrics (2026-10-07).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def seen(monkeypatch):
    from aughor.business_profile import store as profile_store
    from aughor.db import registry
    from aughor.semantic import metric_catalogue
    got: dict = {}
    profiles = {("c1", "thelook"): {"north_star_metrics": []}}
    metas = {"c1": {"schema_name": "thelook"}, "bare": {"schema_name": "main"}, "multi": {}}
    monkeypatch.setattr(registry, "get_meta", lambda cid: metas.get(cid, {}))
    monkeypatch.setattr(profile_store, "load_raw", lambda cid, schema=None: profiles.get((cid, schema)))

    def catalogue_for(conn_id, schema_name=None):
        got["schema"] = schema_name
        return []

    monkeypatch.setattr(metric_catalogue, "catalogue_for", catalogue_for)
    return got


def test_a_declared_schema_with_its_own_profile_is_read(seen):
    from aughor.routers.metrics import get_metric_catalogue
    out = get_metric_catalogue("c1")
    assert seen["schema"] == "thelook" and out["schema"] == "thelook"


def test_a_connection_whose_only_profile_is_bare_keeps_reading_it(seen):
    from aughor.routers.metrics import get_metric_catalogue
    get_metric_catalogue("bare")
    assert seen["schema"] is None


def test_a_multi_dataset_connection_is_unchanged_and_an_explicit_schema_wins(seen):
    from aughor.routers.metrics import get_metric_catalogue
    get_metric_catalogue("multi")
    assert seen["schema"] is None
    get_metric_catalogue("c1", schema="other")
    assert seen["schema"] == "other"
