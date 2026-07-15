"""Per-connection overview drill priors (``aughor.overview.drills``) — capture + read-back.

Hermetic: conftest points AUGHOR_OVERVIEW_DRILLS_DB at a throwaway temp DB, so these
exercise the real SQLite store without touching data/. Each test uses a UNIQUE
connection id so they stay independent inside the shared session DB.
"""
from __future__ import annotations

from aughor.overview.drills import load_priors, record_drill


def test_record_and_load_accumulates_lens_and_table_counts():
    conn = "drills_A"
    record_drill(conn, lens="concentration", table="s.orders")
    record_drill(conn, lens="concentration", table="s.tickets")
    record_drill(conn, lens="outlier", table="s.orders")
    p = load_priors(conn)
    assert p["lens"] == {"concentration": 2, "outlier": 1}
    assert p["table"] == {"s.orders": 2, "s.tickets": 1}


def test_priors_are_per_connection():
    record_drill("drills_X", lens="coverage", table="x.t")
    record_drill("drills_Y", lens="coverage", table="y.t")
    assert load_priors("drills_X")["table"] == {"x.t": 1}
    assert load_priors("drills_Y")["table"] == {"y.t": 1}
    assert load_priors("drills_X")["lens"]["coverage"] == 1   # the two never merge


def test_load_priors_empty_for_unknown_connection():
    assert load_priors("drills_never_seen") == {"lens": {}, "table": {}}


def test_record_drill_ignores_blank_inputs():
    record_drill("", lens="x", table="y")            # no connection → no-op
    record_drill("drills_Z")                          # no lens/table → no-op
    assert load_priors("drills_Z") == {"lens": {}, "table": {}}
    assert load_priors("") == {"lens": {}, "table": {}}


def test_record_drill_with_only_one_coordinate():
    record_drill("drills_one", lens="scale")          # table blank → only the lens bumps
    p = load_priors("drills_one")
    assert p["lens"] == {"scale": 1}
    assert p["table"] == {}
