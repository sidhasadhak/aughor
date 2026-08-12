"""Displaying a schema must not rebuild the semantic index.

`apply_schema_enrichment` runs on every `get_schema` — the request that merely
DISPLAYS table and column names — and it called `build_schema_index`, which embeds
the whole schema. Where the embedder is unreachable that call retries with backoff,
so the display waits on work that cannot succeed.

Measured in production, one table of 21 columns, after the profiling phase had
already been moved off this path (#324):

    schema/rich          81.1s
    forced re-introspect 96.0s
    schema/rich again    79.9s

against **0.94s locally**, where the embedder answers. The logs name it directly:
`APIConnectionError: Connection error` and `Retrying request to /embeddings`.

Nothing is lost by removing it. `retriever._retrieve` already builds the index on
first use when the collection is empty ("Auto-build index on first use"), and the
freshness this call existed for — after a glossary change — now happens in the HEAVY
phase, in the background, where the file itself says such work belongs: "the schema
hot-path never depends on the vector store unless explicitly turned on".
"""
from __future__ import annotations

import inspect

from aughor.agent import schema_annotators
from aughor.tools import schema as schema_tools


def test_the_display_path_does_not_build_the_index():
    """The claim. `apply_schema_enrichment` is reached by every get_schema."""
    src = inspect.getsource(schema_tools.apply_schema_enrichment)
    assert "build_schema_index(" not in src, (
        "the schema display path rebuilds the semantic index — that is the 80s")


def test_the_background_path_still_refreshes_it():
    """Removing it from the hot path must not mean it never runs: a glossary change
    has to reach the index somewhere, or retrieval silently serves stale terms."""
    src = inspect.getsource(schema_annotators._intelligence)
    assert "build_schema_index(" in src, (
        "nothing refreshes the semantic index any more")


def test_the_refresh_cannot_break_the_intelligence_build():
    """An unreachable embedder is exactly the production condition. It must degrade
    the index, not the build that carries profiles and the ontology."""
    src = inspect.getsource(schema_annotators._intelligence)
    idx = src.index("build_schema_index(")
    window = src[max(0, idx - 400):idx + 400]
    assert "try:" in window and "tolerate(" in window, (
        "the index refresh is not guarded — an unreachable embedder would fail the "
        "whole intelligence build")


def test_retrieval_still_builds_on_first_use():
    """The safety net that makes removal safe rather than merely faster."""
    from aughor.semantic import retriever

    src = inspect.getsource(retriever._retrieve)
    assert "build_schema_index()" in src and "collection_count" in src, (
        "retrieval no longer self-builds, so dropping the display-path build would "
        "leave the index empty")
