"""``aughor/connectors/catalog.json`` is GENERATED from the registry and committed, so
a tool can read the connector plane without importing this package — which also means it
can drift. The first test fails the moment the registry moves without a regeneration;
the others pin the properties consumers rely on (coverage, secrets) to the registry
rather than to the file, so a generator bug cannot certify itself.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "aughor" / "connectors" / "catalog.json"

_spec = importlib.util.spec_from_file_location(
    "_gen_catalog", REPO / "scripts" / "gen_connector_catalog.py"
)
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)


def test_catalog_matches_the_registry():
    committed = json.loads(CATALOG.read_text())
    assert committed == _gen.build(), (
        "catalog.json drifted from the registry — regenerate: "
        "uv run python scripts/gen_connector_catalog.py"
    )


def test_catalog_covers_every_registered_type():
    from aughor.connectors.registry import DRIVERS, FORM_FIELDS, REGISTRY

    types = {t["type"] for t in _gen.build()["types"]}
    for source, expected in (
        ("FORM_FIELDS", set(FORM_FIELDS)),
        ("DRIVERS", set(DRIVERS)),
        ("REGISTRY", set(REGISTRY.supported_types())),
    ):
        missing = expected - types
        assert not missing, f"catalog omits types the registry's {source} knows: {missing}"


def test_secret_fields_agree_with_the_registry():
    from aughor.connectors.registry import secret_field_keys

    for entry in _gen.build()["types"]:
        flagged = {f["key"] for f in entry["fields"] if f.get("secret")}
        assert set(entry["secret_fields"]) == flagged, entry["type"]
        # secret_field_keys() is the storage-side view (dsn excluded — it lives in its
        # own encrypted column); the catalog's consumer view must be a superset, because
        # a consumer must treat a secret dsn as a secret regardless of where it lands.
        assert secret_field_keys(entry["type"]) <= flagged, entry["type"]
