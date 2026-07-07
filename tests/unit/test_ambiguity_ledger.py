"""The Ambiguity Ledger (SOMA improvisation I1) — resolution that compounds per connection.

Hermetic via the conftest `AUGHOR_AMBIGUITY_LEDGER_DB` override (points at a throwaway temp dir —
the suite never touches live `data/`). Each test uses its own connection_id so they're independent
without teardown. What's pinned: idempotent burn-down (same dimension → one row), override-wins
authority (verdict > user > probe), conservative token-overlap retrieval, per-connection scoping,
and the burn-down metric.
"""
from __future__ import annotations

from aughor.semantic.ambiguity_ledger import (
    AmbiguityResolution,
    Reading,
    build_resolution_block,
    crystallize_user_choice,
    crystallize_verdict,
    ledger_stats,
    list_resolutions,
    purge_connections,
    record_hit,
    retrieve_resolutions,
    save_resolution,
)


def _res(conn, subject="total runs scored by strikers", reading="career totals",
         source="probe", facet="grain", kind="AmbiIntent", **kw):
    return AmbiguityResolution(
        connection_id=conn, dim_kind=kind, dim_facet=facet, subject=subject,
        resolved_reading=reading, resolution_source=source,
        readings=[Reading(label="per-match totals", sql_evidence="GROUP BY player, match"),
                  Reading(label="career totals", sql_evidence="GROUP BY player")],
        **kw)


def test_save_then_retrieve_by_token_overlap():
    save_resolution(_res("t_retrieve", evidence="live probe: per-career matches the grain"))
    m = retrieve_resolutions("what is the average total runs by strikers?", "t_retrieve")
    assert m and m[0][0].resolved_reading == "career totals"
    assert m[0][1] >= 0.34
    # an unrelated question injects nothing (conservative threshold)
    assert retrieve_resolutions("list all store addresses in california", "t_retrieve") == []


def test_retrieval_is_connection_scoped():
    save_resolution(_res("t_scope_a"))
    # same subject, different connection — must not leak across connections
    assert retrieve_resolutions("total runs by strikers", "t_scope_b") == []
    assert retrieve_resolutions("total runs by strikers", "t_scope_a")


def test_idempotent_natural_key_one_row_per_dimension():
    save_resolution(_res("t_idem"))
    save_resolution(_res("t_idem", reading="per-match totals"))  # same dimension, re-resolved
    rows = list_resolutions("t_idem")
    assert len(rows) == 1  # burn-down: same (conn, facet, subject) collapses to one row
    # a different facet on the same subject is a distinct dimension → its own row
    save_resolution(_res("t_idem", facet="window", kind="AmbiIntent"))
    assert len(list_resolutions("t_idem")) == 2


def test_override_wins_authority_ordering():
    save_resolution(_res("t_auth", reading="career totals", source="probe"))
    # equal authority (probe→probe) overwrites with the fresher reading
    save_resolution(_res("t_auth", reading="per-match", source="probe"))
    assert list_resolutions("t_auth")[0].resolved_reading == "per-match"
    # verdict (higher) overrides
    save_resolution(_res("t_auth", reading="career (confirmed)", source="verdict"))
    assert list_resolutions("t_auth")[0].resolution_source == "verdict"
    # a probe MUST NOT clobber a human verdict
    save_resolution(_res("t_auth", reading="nope", source="probe"))
    row = list_resolutions("t_auth")[0]
    assert row.resolution_source == "verdict" and row.resolved_reading == "career (confirmed)"


def test_user_beats_probe_but_loses_to_verdict():
    save_resolution(_res("t_rank", source="probe"))
    save_resolution(_res("t_rank", reading="user pick", source="user"))
    assert list_resolutions("t_rank")[0].resolution_source == "user"
    save_resolution(_res("t_rank", reading="downgrade attempt", source="probe"))
    assert list_resolutions("t_rank")[0].resolved_reading == "user pick"


def test_resolution_block_is_authoritative_and_cites_source():
    save_resolution(_res("t_block", resolved_sql="GROUP BY player",
                         evidence="per-career matches the asked grain"))
    block = build_resolution_block(retrieve_resolutions("total runs by strikers", "t_block"))
    assert "RESOLVED AMBIGUITIES" in block and "authoritative" in block
    assert "career totals" in block and "GROUP BY player" in block
    assert build_resolution_block([]) == ""


def test_record_hit_and_stats_track_burndown():
    save_resolution(_res("t_stats", source="probe"))
    save_resolution(_res("t_stats", subject="fatality rate for motorcycle collisions",
                         source="user", reading="deaths / collisions"))
    (res, _score) = retrieve_resolutions("total runs by strikers", "t_stats")[0]
    record_hit(res.id)
    record_hit(res.id)
    stats = ledger_stats("t_stats")
    assert stats["resolutions"] == 2
    assert stats["by_source"] == {"probe": 1, "user": 1}
    assert stats["served_total"] == 2


def test_purge_removes_only_named_connection():
    save_resolution(_res("t_purge_x"))
    save_resolution(_res("t_purge_y"))
    assert purge_connections(["t_purge_x"]) == 1
    assert list_resolutions("t_purge_x") == []
    assert list_resolutions("t_purge_y")  # untouched
    assert purge_connections([]) == 0


def test_crystallize_user_choice_is_a_user_source_prior():
    """I4: a reading the user chose in a clarify becomes a user-source resolution that reads back,
    and it OUTRANKS a probe on the same subject (a human decision wins)."""
    res = crystallize_user_choice("uc_conn", "top products", "by revenue")
    assert res and res.resolution_source == "user" and res.dim_kind == "AmbiIntent"
    m = retrieve_resolutions("what are the top products?", "uc_conn")
    assert m and m[0][0].resolved_reading == "by revenue"
    # a term-clarify choice records as an AmbiValue (a value/status filter)
    r2 = crystallize_user_choice("uc_conn", "urgent orders", "status = 'high_priority'",
                                 clarify_source="ambiguous_term")
    assert r2.dim_kind == "AmbiValue" and r2.dim_facet == "literal"
    # empty input is a no-op (no row written)
    assert crystallize_user_choice("uc_conn", "", "anything") is None


def test_user_choice_outranks_a_probe_on_same_dimension():
    save_resolution(AmbiguityResolution(
        connection_id="uc_rank", dim_kind="AmbiIntent", dim_facet="grain",
        subject="top products", resolved_reading="by units", resolution_source="probe"))
    crystallize_user_choice("uc_rank", "top products", "by revenue")  # user > probe, same key
    assert list_resolutions("uc_rank")[0].resolved_reading == "by revenue"
    assert list_resolutions("uc_rank")[0].resolution_source == "user"
    assert len(list_resolutions("uc_rank")) == 1  # same natural key → burn-down, one row


def test_crystallize_verdict_is_highest_authority():
    """A reviewer verdict overrides a user choice on the same question (verdict > user > probe)."""
    crystallize_user_choice("vd_conn", "average total runs by strikers", "per-match totals")
    crystallize_verdict("vd_conn", "average total runs by strikers",
                        note="use per-career totals", corrected_sql="GROUP BY player")
    rows = list_resolutions("vd_conn")
    assert len(rows) == 1  # same dimension → burn-down, verdict replaces the user reading
    assert rows[0].resolution_source == "verdict"
    assert rows[0].resolved_reading == "use per-career totals"
    assert rows[0].resolved_sql == "GROUP BY player"
    # a later user choice can NOT downgrade the reviewer's verdict
    crystallize_user_choice("vd_conn", "average total runs by strikers", "per-match again")
    assert list_resolutions("vd_conn")[0].resolution_source == "verdict"
    assert crystallize_verdict("vd_conn", "") is None  # empty subject → no-op


def test_record_verdict_bridges_to_the_ledger(monkeypatch):
    """The live hook: a reject/correct verdict on a headlined finding crystallizes a
    verdict-source resolution; accept / no-headline / flag-off write nothing."""
    from aughor.verify import verdicts
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    purge_connections(["vb_conn"])
    verdicts.record_verdict("vb_conn", "inv1", "correct", note="use per-career totals",
                            headline="average total runs by strikers", corrected_sql="GROUP BY player")
    rows = list_resolutions("vb_conn")
    assert len(rows) == 1 and rows[0].resolution_source == "verdict"
    assert rows[0].resolved_sql == "GROUP BY player"
    # an accept teaches no correction → no ledger write
    verdicts.record_verdict("vb_conn", "inv2", "accept", headline="something fine")
    assert len(list_resolutions("vb_conn")) == 1
    # flag off → no write even for a correction
    monkeypatch.delenv("AUGHOR_CLOSED_LOOP", raising=False)
    purge_connections(["vb_off"])
    verdicts.record_verdict("vb_off", "inv3", "reject", headline="a bad reading")
    assert list_resolutions("vb_off") == []


def test_compounding_loop_b1_settlement_then_read_back():
    """The whole point of I1: a B1-settled disagreement crystallizes, and a later similar
    question on the SAME connection reads it back as an authoritative prior — end to end, no LLM."""
    from evals.spider2 import crystallize_resolution
    from evals.spider2_probes import Dimension, RepairOutcome

    grain_dim = Dimension("AmbiIntent", "grain", "result grain (GROUP BY)",
                          ("player", "player, match"), ("group by player",))
    outcome = RepairOutcome(sql="SELECT player, SUM(runs) FROM b GROUP BY player",
                            changed=True, accepted=True, reason="grain probe matched per-career",
                            source="alternate:det:grain", resolved_dims=[grain_dim])
    # write: B1 settled it on connection "Baseball"
    assert crystallize_resolution("Baseball", "average total runs scored by strikers",
                                  outcome, outcome.sql)
    # read: a later similar question retrieves the prior + renders the authoritative block
    m = retrieve_resolutions("what is the total runs scored by each striker?", "Baseball")
    assert m, "a similar question on the same connection should hit the crystallized resolution"
    block = build_resolution_block(m)
    assert "RESOLVED AMBIGUITIES" in block and "GROUP BY player" in block
    # and it did NOT leak to a different connection
    assert retrieve_resolutions("total runs scored by strikers", "OtherDB") == []
