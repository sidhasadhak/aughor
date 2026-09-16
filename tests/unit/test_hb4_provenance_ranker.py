"""HB-4 — the envelope and the one ranker: deterministic on three axes, shown in the
receipt, and no model decides which context outranks which."""
from __future__ import annotations

from datetime import datetime, timezone

from aughor.hub.provenance import ContextPiece, Provenance
from aughor.hub.ranker import rank

_NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _piece(text, *, authority, source_kind="declaration", scope="connection",
           observed="2026-09-14T08:00:00Z", subject="", pid="", version=0, **prov):
    return ContextPiece(
        text=text, subject=subject, piece_id=pid or text[:12], version=version,
        provenance=Provenance(source_kind=source_kind, authority=authority,
                              scope_kind=scope, observed_at=observed, **prov))


# ── stamps: the roadmap's exact shapes ────────────────────────────────────────────

def test_measured_stamp_reads_like_the_roadmaps():
    p = Provenance(source_kind="measurement", authority="measured",
                   scope_kind="connection", observed_at="2018-09-11 19:48:28")
    assert p.stamp(_NOW) == "[measured 2018-09-11, this connection]"


def test_said_stamp_carries_author_place_age_and_tier():
    p = Provenance(source_kind="conversation", authority="said", author="Ana",
                   where="#ops", observed_at="2026-09-13T12:00:00Z",
                   verification="unverified")
    assert p.stamp(_NOW) == "[said by Ana in #ops, 3 days ago, unverified]"


# ── decay: observations rot, definitions and measurements do not ──────────────────

def test_a_conversation_piece_expires_past_the_window():
    stale = _piece("carrier X was on strike", authority="said",
                   source_kind="conversation", observed="2026-08-01T00:00:00Z")
    fresh = _piece("carrier X was on strike again", authority="said",
                   source_kind="conversation", observed="2026-09-14T00:00:00Z")
    out = rank([stale, fresh], now=_NOW)
    assert [p.text for p in out.kept] == ["carrier X was on strike again"]
    assert any("expired" in d.reason for d in out.dropped)


def test_an_old_approved_definition_never_expires_and_version_wins():
    old_v2 = _piece("Revenue = SUM(total_amount)", authority="approved",
                    source_kind="definition", observed="2025-01-01T00:00:00Z",
                    version=2, pid="v2")
    newer_v1 = _piece("Revenue = SUM(line_total)", authority="approved",
                      source_kind="definition", observed="2026-09-15T00:00:00Z",
                      version=1, pid="v1")
    out = rank([old_v2, newer_v1], now=_NOW)
    assert [p.piece_id for p in out.kept] == ["v2", "v1"]   # version, not age


def test_measurements_rank_by_the_datas_own_as_of():
    older = _piece("rate 9.35%", authority="measured", source_kind="measurement",
                   observed="2018-08-01T00:00:00Z", pid="old")
    fresher = _piece("rate 9.10%", authority="measured", source_kind="measurement",
                     observed="2018-09-11T00:00:00Z", pid="new")
    out = rank([older, fresher], now=_NOW)
    assert [p.piece_id for p in out.kept] == ["new", "old"]


# ── the axes: authority then scope ────────────────────────────────────────────────

def test_authority_orders_before_scope_and_scope_before_recency():
    inferred_on_object = _piece("guess", authority="inferred", scope="object", pid="g")
    said_industry = _piece("heard", authority="said", scope="industry", pid="h",
                           source_kind="conversation", observed="2026-09-15T00:00:00Z")
    measured_org = _piece("counted", authority="measured", scope="organisation", pid="m")
    out = rank([inferred_on_object, said_industry, measured_org], now=_NOW)
    assert [p.piece_id for p in out.kept] == ["m", "h", "g"]


def test_unknown_authority_ranks_below_everything():
    weird = _piece("??", authority="cosmic", pid="w")
    inferred = _piece("model guess", authority="inferred", pid="i")
    out = rank([weird, inferred], now=_NOW)
    assert [p.piece_id for p in out.kept] == ["i", "w"]


# ── conflicts: higher wins with a flag; same tier is surfaced, never guessed ──────

def test_a_higher_tier_wins_and_the_loser_is_a_flag_not_a_block():
    measured = _piece("dispatch window is 2 days (measured)", authority="measured",
                      subject="dispatch-window", pid="m")
    said = _piece("someone said the window is 3 days", authority="said",
                  source_kind="conversation", subject="dispatch-window", pid="s",
                  observed="2026-09-15T00:00:00Z")
    out = rank([measured, said], now=_NOW)
    assert [p.piece_id for p in out.kept] == ["m"]
    flag = next(d for d in out.dropped if d.piece_id == "s")
    assert "outranked" in flag.reason and "said loses to measured" in flag.reason
    assert not out.conflicts


def test_same_tier_disagreement_is_surfaced_not_decided():
    a = _piece("window is 2 days", authority="declared", subject="dispatch-window", pid="a")
    b = _piece("window is 3 days", authority="declared", subject="dispatch-window", pid="b")
    out = rank([a, b], now=_NOW)
    assert {p.piece_id for p in out.kept} == {"a", "b"}     # both survive
    assert out.conflicts and out.conflicts[0].tier == "declared"
    assert set(out.conflicts[0].piece_ids) == {"a", "b"}


# ── the budget says what it dropped ───────────────────────────────────────────────

def test_budget_overflow_is_recorded_not_silent():
    pieces = [_piece(f"piece {i} " + "x" * 60, authority="declared", pid=f"p{i}")
              for i in range(5)]
    out = rank(pieces, budget_chars=250, now=_NOW)
    assert out.kept and len(out.kept) < 5
    assert any("budget" in d.reason for d in out.dropped)
    receipt = out.receipt()
    assert receipt["kept"] and receipt["dropped"]


def test_rendered_blocks_carry_their_stamps():
    p = _piece("Dispatch broke on 9.35% of lines.", authority="measured",
               source_kind="measurement", observed="2018-09-11T00:00:00Z")
    out = rank([p], now=_NOW)
    assert out.rendered(_NOW).endswith("[measured 2018-09-11, this connection]")
