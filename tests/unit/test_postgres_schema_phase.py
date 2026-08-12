"""Displaying a Postgres schema must not profile every column.

`PostgresConnection.get_schema` ran the HEAVY annotator phase — the one that builds
value profiles for every column. Measured against production, one table of 21
columns and 9,994 rows:

    schema/rich, cached                3.5s
    forced re-introspection           80.5s   <- the heavy phase
    schema/rich, cached again          3.5s

That is the request the Briefing needs merely to DISPLAY table and column names, and
the cache holding the 3.5s answer is per-process — so a deployment that cold-starts
43 times in half an hour pays the 80s repeatedly. To the user the schema simply never
appears.

WHY IT WAS LIKE THAT, which is the part worth keeping
------------------------------------------------------
`PostgresConnection` had no `build_intelligence`, and `DatabaseConnection` declares
no default — so the birth rite's `db.build_intelligence()` raised AttributeError for
every Postgres connection and its intelligence step failed. The heavy phase had been
moved into `get_schema` because that was the only place that ran at all.

Two faults, one cause: profiling never ran where it was meant to, and always ran
where it must not. Fixing the phase alone would have silently dropped profiling
entirely, so both halves are asserted here.
"""
from __future__ import annotations

import pytest

from aughor.db.connection import DatabaseConnection, DuckDBConnection, PostgresConnection


def test_postgres_has_the_background_path_at_all():
    """The missing method. Without it the birth rite's intelligence step raises
    AttributeError and no Postgres connection is ever profiled."""
    assert hasattr(PostgresConnection, "build_intelligence"), (
        "birth rite calls db.build_intelligence(); without it the step fails outright")


def test_the_split_matches_every_other_connector():
    """DuckDB and SQLite both keep profiling out of the display path. Postgres was
    the outlier, and being the outlier is what made it 80s."""
    import inspect

    fast = inspect.getsource(PostgresConnection.get_schema)
    heavy = inspect.getsource(PostgresConnection.build_intelligence)

    assert 'phase="fast"' in fast, "get_schema is the hot path and must stay fast"
    assert 'phase="heavy"' not in fast, (
        "get_schema runs the value-profiling phase again — that was the 80s")
    assert 'phase="heavy"' in heavy, "the heavy phase has to run SOMEWHERE"


@pytest.mark.parametrize("cls", [DuckDBConnection, PostgresConnection])
def test_every_connector_separates_display_from_profiling(cls):
    """A rot guard over the contract rather than one class: `build_intelligence`'s
    own docstring says 'never on the hot path', so no `get_schema` may run heavy."""
    import inspect

    assert 'phase="heavy"' not in inspect.getsource(cls.get_schema), (
        f"{cls.__name__}.get_schema profiles on the hot path")
    assert hasattr(cls, "build_intelligence"), f"{cls.__name__} has no background path"


def test_the_base_class_still_declares_no_default():
    """Pins WHY this was missable. A base-class default would have made the gap
    impossible; there isn't one, so each connector must supply its own and a missing
    one fails only at call time, in a background step whose error is tolerated."""
    assert "build_intelligence" not in DatabaseConnection.__dict__, (
        "if a default is ever added, this test should be replaced by one asserting it")
