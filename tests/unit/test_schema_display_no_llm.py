"""Displaying a schema must not call a model.

`apply_schema_enrichment` runs on every `get_schema` — the request that merely
DISPLAYS table and column names — and it called `seed_missing_tables`, which makes
**one LLM call per unseeded table**.

Instrumented in production (#326), on one 21-column table:

    total                        55.9s
      annotator.enrichment       51.361s
        enrich.seed_missing_tables 51.053s   <- 91% of the request
      pg.information_schema       0.103s
      pg.row_counts               0.096s
      pg.head_samples             0.094s

All the actual Postgres introspection came to 0.29s. The database was never the
problem.

AND IT NEVER STOPPED
--------------------
There is a fast-path — seed once, then skip — but seeds are written to
`data/glossary_generated.yaml`, read-only on serverless, so it could never arm.
`mark_complete`'s own tolerate message states the consequence: "schema re-seeds next
time". Every time. Forever.

Three earlier attempts moved this number by nothing (#324 profiling, #325 the vector
index) because each was chosen by reasoning from LOCAL proportions into a production
environment that behaves differently. This one was chosen by measuring production.
"""
from __future__ import annotations

import inspect

from aughor.agent import schema_annotators
from aughor.tools import schema as schema_tools


def test_the_display_path_does_not_seed_the_glossary():
    """The claim. Seeding calls a model; a display must never wait on inference."""
    src = inspect.getsource(schema_tools.apply_schema_enrichment)
    assert "seed_missing_tables(" not in src, (
        "the schema display path seeds the glossary — that is one LLM call per table")


def test_the_background_path_does_seed():
    """Removing it from the hot path must not mean it never runs: without seeding, a
    new table never gets generated glossary terms at all."""
    src = inspect.getsource(schema_annotators._intelligence)
    assert "seed_missing_tables(" in src, "nothing seeds the glossary any more"


def test_the_seeding_cannot_break_the_intelligence_build():
    """A model that will not answer is exactly the production condition that started
    all of this. It must degrade the glossary, not the build carrying profiles."""
    src = inspect.getsource(schema_annotators._intelligence)
    idx = src.index("seed_missing_tables(")
    window = src[max(0, idx - 400):idx + 400]
    assert "try:" in window and "tolerate(" in window, (
        "glossary seeding is unguarded — a failing model would fail the whole build")


def test_no_model_call_survives_on_the_display_path():
    """A rot guard over the PRINCIPLE rather than one call. `get_provider` is how
    every model call in this codebase begins, so nothing reachable from the display
    path may reference it."""
    src = inspect.getsource(schema_tools.apply_schema_enrichment)
    assert "get_provider" not in src, (
        "something on the schema display path resolves an LLM provider")
