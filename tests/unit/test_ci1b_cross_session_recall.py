"""CI-1b — the same question, asked in an earlier session, is recalled for comparison.

CI-0 measured 46 questions asked three or more times ("where are we losing money?" 52
times), each starting cold because conversation memory is per session. CI-1a gave the
session its memory; this is the cross-session half.

Two invariants the design turns on:
  * matching is DETERMINISTIC (normalised equality) — the measured repeats are verbatim,
    the quick path cannot afford an embedding round-trip, and a false match would hand
    the model another question's answer as this one's history;
  * the recalled block is for COMPARISON, never for restating — a prior headline
    repeated as current is the staleness class this repo keeps paying for.
"""
from __future__ import annotations

from aughor.db import history as H
from aughor.routers.investigations import (
    build_prior_answers_section,
    resolve_prior_answers,
)


def _row(question, headline, started_at, session_id, connection_id="c1",
         status="complete", report_json="{}"):
    return {"id": f"i-{started_at}", "question": question, "headline": headline,
            "report_json": report_json, "started_at": started_at,
            "session_id": session_id, "connection_id": connection_id, "status": status}


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params):
        return self

    def fetchall(self):
        return self._rows

    def close(self):
        pass


def _patch_rows(monkeypatch, rows):
    monkeypatch.setattr(H, "_conn", lambda: _FakeCursor(rows))
    monkeypatch.setattr(H, "ensure_once", lambda c, f: None)


# ── normalisation: the same question, spelled slightly differently ───────────────

def test_normalisation_matches_case_space_and_punctuation(monkeypatch):
    _patch_rows(monkeypatch, [
        _row("Where are we losing money?", "West region leads losses",
             "2026-08-11T09:00:00", "sess-old"),
    ])
    out = H.find_prior_answers("  where are we   losing money  ", "c1",
                               exclude_session="sess-now")
    assert len(out) == 1
    assert out[0]["headline"] == "West region leads losses"
    assert out[0]["asked_at"].startswith("2026-08-11")


def test_a_different_question_never_matches(monkeypatch):
    _patch_rows(monkeypatch, [
        _row("where are we losing money?", "West leads", "2026-08-11T09:00:00", "s1"),
    ])
    assert H.find_prior_answers("where are we MAKING money?", "c1") == [], \
        "near-miss matching belongs to the semantic seam, not here — a wrong match " \
        "would present another question's answer as this one's history"


# ── scoping: this session's turns are conversation history, not recall ───────────

def test_current_session_is_excluded(monkeypatch):
    _patch_rows(monkeypatch, [
        _row("total revenue?", "12M", "2026-08-12T10:00:00", "sess-now"),
        _row("total revenue?", "11M", "2026-08-05T10:00:00", "sess-old"),
    ])
    out = H.find_prior_answers("total revenue?", "c1", exclude_session="sess-now")
    assert [p["headline"] for p in out] == ["11M"], \
        "the current session's turns already ride in CONVERSATION HISTORY"


def test_one_answer_per_prior_session(monkeypatch):
    _patch_rows(monkeypatch, [
        _row("total revenue?", "12M newest", "2026-08-12T10:00:00", "sess-a"),
        _row("total revenue?", "12M earlier same session", "2026-08-12T09:00:00", "sess-a"),
        _row("total revenue?", "11M", "2026-08-05T10:00:00", "sess-b"),
    ])
    out = H.find_prior_answers("total revenue?", "c1", exclude_session="")
    assert [p["headline"] for p in out] == ["12M newest", "11M"], \
        "a session that asked it four times contributes its newest answer once"


def test_limit_is_respected(monkeypatch):
    _patch_rows(monkeypatch, [
        _row("q?", f"answer {i}", f"2026-08-{10 - i:02d}T10:00:00", f"s{i}")
        for i in range(5)
    ])
    assert len(H.find_prior_answers("q?", "c1", limit=2)) == 2


def test_missing_inputs_and_errors_are_empty(monkeypatch):
    assert H.find_prior_answers("", "c1") == []
    assert H.find_prior_answers("q?", "") == []

    def _boom():
        raise RuntimeError("store down")

    monkeypatch.setattr(H, "_conn", _boom)
    assert H.find_prior_answers("q?", "c1") == [], "fail-open: the turn answers without recall"


# ── the prompt block: comparison, never restatement ──────────────────────────────

def test_section_instructs_comparison_and_carries_dates():
    section = build_prior_answers_section([
        {"question": "where are we losing money?", "headline": "West region leads",
         "asked_at": "2026-08-11T09:00:00", "session_id": "s1"},
    ])
    assert "PREVIOUSLY ASKED" in section
    assert "2026-08-11" in section and "West region leads" in section
    low = section.lower()
    assert "today" in low and "unchanged or what moved" in low
    assert "never restate" in low, "the anti-staleness instruction is the point of the block"


def test_section_never_carries_prior_sql():
    section = build_prior_answers_section([
        {"question": "q", "headline": "H", "asked_at": "2026-08-01T00:00:00",
         "session_id": "s"},
    ])
    assert "SELECT" not in section.upper(), \
        "re-running an old query is a decision from today's schema, not a copy"


def test_empty_priors_render_nothing():
    assert build_prior_answers_section([]) == ""
    assert build_prior_answers_section(None) == ""


# ── the recalled VALUE: what makes the comparison possible ───────────────────────

def test_prior_result_carries_the_answer_not_just_the_title(monkeypatch):
    """Found by a LIVE check, not by reasoning: the most-repeated real question's two
    prior headlines were both captions ("Returns table row count"), so a block carrying
    only titles asked for a comparison with nothing to compare."""
    import json as _json
    _patch_rows(monkeypatch, [
        _row("how many rows are in the returns table?", "Returns table row count",
             "2026-07-31T10:00:00", "s-old",
             report_json=_json.dumps({"columns": ["n"], "rows": [["50048"]]})),
    ])
    out = H.find_prior_answers("How many rows are in the returns table?", "c1")
    assert out[0]["prior_result"] == "50048"
    section = build_prior_answers_section(out)
    assert "answered: 50048" in section


def test_prior_result_renders_a_small_grid_compactly():
    assert H._compact_result(
        {"columns": ["region", "gmv"],
         "rows": [["West", "725457"], ["East", "678781"], ["South", "391721"],
                  ["North", "1"]]}
    ) == "West=725457; East=678781; South=391721"


def test_prior_result_is_bounded_and_never_raises():
    assert H._compact_result({}) == ""
    assert H._compact_result({"columns": ["a"], "rows": []}) == ""
    long_grid = {"columns": ["a", "b"], "rows": [["x" * 200, "y" * 200]]}
    assert len(H._compact_result(long_grid)) <= 160
    assert H._compact_result({"columns": ["a"], "rows": "not-a-list"}) == ""


def test_resolve_is_fail_open(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr("aughor.db.history.find_prior_answers", _boom)
    assert resolve_prior_answers("q", "c1", "s1") == []


# ── what is comparable, and what only looks like it ──────────────────────────
# Live: a quick answer opened "Compared to the previous report from August 20, 2026, the
# picture has expanded significantly. While the previous report only listed three routes
# … the current data reflects a much broader set of 84 routes." Nothing had changed. The
# earlier turn was the run that reported "Data unavailable" and named three routes as
# EXAMPLES; this block offered it as a baseline and asked for a comparison, so it got one.

def test_a_run_that_reported_no_data_is_not_offered_as_a_baseline():
    from aughor.agent.investigate import NO_DATA_HEADLINE_PREFIX

    section = build_prior_answers_section([
        {"asked_at": "2026-08-20", "headline": f"{NO_DATA_HEADLINE_PREFIX}flight count could not be analyzed"},
    ])

    assert section == "", "a failed run was offered as something to compare against"


def test_a_real_prior_answer_is_still_offered():
    section = build_prior_answers_section([
        {"asked_at": "2026-08-20", "headline": "Revenue held October's level",
         "prior_result": "$1.2M"},
    ])
    assert "2026-08-20" in section and "$1.2M" in section


def test_the_failed_run_is_dropped_without_taking_the_good_ones_with_it():
    from aughor.agent.investigate import NO_DATA_HEADLINE_PREFIX

    section = build_prior_answers_section([
        {"asked_at": "2026-08-19", "headline": f"{NO_DATA_HEADLINE_PREFIX}traffic could not be analyzed"},
        {"asked_at": "2026-08-20", "headline": "Traffic rose 12%", "prior_result": "12%"},
    ])

    assert "Traffic rose 12%" in section
    assert "could not be analyzed" not in section


def test_the_instruction_forbids_reading_a_longer_list_as_growth():
    """The other half of the live failure: one answer named three examples, the next
    listed twenty, and the difference was reported as the data expanding."""
    section = build_prior_answers_section([
        {"asked_at": "2026-08-20", "headline": "Revenue held", "prior_result": "$1.2M"},
    ])

    assert "LIKE WITH LIKE" in section
    assert "difference in what was" in section
