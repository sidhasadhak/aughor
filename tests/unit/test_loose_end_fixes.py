"""Two halves of a feature that existed while the feature did not.

Both fixes here are the same shape: something was stored, editable and typed all the
way to the web client, and then read by nobody. Grepping for the CONSUMER of a value
is what finds these — the producer side looks complete on its own.

  * `exclude_when` was extracted from glossary caveats beside `default_filters` (one
    function returns both), persisted, and exposed for editing — but only the filters
    half was ever rendered into a prompt. The exclusions reached no model.
  * `delete_ontology_override` restated the store's target kinds as a hand-copied
    tuple and left "action" out of it, so a kinetic action could be created over HTTP
    and never removed.
"""
from __future__ import annotations

from typing import get_args

from aughor.ontology.builder import render_ontology_annotations
from aughor.ontology.models import OntologyEntity, OntologyGraph
from aughor.ontology.overrides import TargetKind


def _graph_with(**entity_kwargs) -> OntologyGraph:
    entity = OntologyEntity(
        id="orders",
        display_name="Orders",
        source_tables=["analytics.orders"],
        identity_key="order_id",
        grain_verified=True,
        **entity_kwargs,
    )
    return OntologyGraph(
        connection_id="test_conn",
        schema_fingerprint="test_fingerprint",
        entities={"orders": entity},
    )


def test_exclude_when_reaches_the_prompt():
    """The fix. A business rule nobody renders is a business rule nobody applies."""
    block = render_ontology_annotations(
        _graph_with(exclude_when=["test orders are not counted as revenue"])
    )
    assert "test orders are not counted as revenue" in block
    assert "EXCLUDES" in block


def test_exclude_when_renders_beside_its_sibling():
    """Both halves of `_extract_default_filters` must survive into the same block —
    rendering one and dropping the other is the state this test exists to prevent."""
    block = render_ontology_annotations(
        _graph_with(
            default_filters=["status <> 'draft'"],
            exclude_when=["refunded rows are excluded from net revenue"],
        )
    )
    assert "status <> 'draft'" in block
    assert "refunded rows are excluded from net revenue" in block


def test_empty_exclude_when_adds_nothing():
    """The off-state: an entity with no exclusions renders byte-identically to before."""
    with_field = render_ontology_annotations(_graph_with(exclude_when=[]))
    assert "EXCLUDES" not in with_field


def test_exclude_when_is_capped_like_default_filters():
    """Token discipline, not decoration: this block is question-scoped and injected on
    every generation, so an entity with a long caveat list must not blow it open."""
    block = render_ontology_annotations(
        _graph_with(exclude_when=[f"exclusion number {i}" for i in range(5)])
    )
    assert block.count("EXCLUDES") == 2


def test_every_store_target_kind_is_deletable():
    """The route must not restate the store's vocabulary — it must read it.

    "action" was missing from the old hand-copied tuple, so `PUT /ontology/kinetic-actions/{id}`
    could write an override that no request could remove. Asserting against `TargetKind`
    itself means a future kind cannot reintroduce the gap.
    """
    from aughor.routers.ontology import delete_ontology_override

    source = delete_ontology_override.__code__.co_consts
    assert "action" in get_args(TargetKind), "the store itself must still support actions"
    # The route resolves its whitelist at call time from TargetKind; a literal tuple of
    # kinds sitting in the function's constants would mean someone re-hardcoded it.
    hardcoded = [c for c in source if isinstance(c, tuple) and "entity" in c]
    assert not hardcoded, (
        f"delete_ontology_override re-hardcodes the kind list {hardcoded}; read "
        "get_args(TargetKind) instead so the route cannot drift from the store."
    )
