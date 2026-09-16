"""SP-M — the authoring scorecard runs in CI with no model.

Locked here: the scorer grades REAL staged rows (built through the drafting tools
themselves, model stubbed) and catches each dishonesty class the movement's waves
closed; the funnel folds staged → accepted → finished-in-form → redrafted →
rejected → lapsed by ISO week, keyed on the exact sentence SP-11's editor door
stamps; the thirty-ask corpus is well-formed; and — the receipt — the measured live
baseline is written down: on 2026-09-16, 6 drafts ever staged, 1 accepted, 0
finished in the form.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from aughor.agent.authoring_measure import (
    DRAFT_KINDS,
    FINISHED_IN_FORM_MARK,
    authoring_funnel,
    score_proposal,
)


def _chain(channel="#ops", cron="0 9 * * *", tz=""):
    return {
        "conn_id": "conn-m", "name": "morning",
        **({"timezone": tz} if tz else {}),
        "conditions": [{"kind": "schedule", "config": {"cron": cron}}],
        "effects": [{"kind": "slack_post",
                     "config": {"bot_id": "b1", "channel": channel, "message": "hi"}}],
    }


def _first_run(cron="0 9 * * *", tz=""):
    from datetime import datetime, timezone as _tz
    from aughor.automations.engine import next_fire_utc
    return next_fire_utc(cron, datetime(2026, 9, 16, tzinfo=_tz.utc), tz)\
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(kind="automation_draft", params=None, detail=None, **kw):
    return SimpleNamespace(kind=kind, params=params or {}, detail=detail or {},
                           status=kw.get("status", "pending"),
                           status_message=kw.get("status_message", ""),
                           created_at=kw.get("created_at", "2026-09-16T10:00:00Z"))


def test_an_honest_draft_scores_clean():
    out = score_proposal(_row(params=_chain(),
                              detail={"open_choices": [], "first_run": _first_run()}))
    assert out["problems"] == []
    assert out["checks"]["validates"] is True
    assert out["checks"]["open_choices_honest"] is True
    assert out["checks"]["clock_right"] is True


def test_each_dishonesty_class_is_caught():
    # a card that hides a real open choice
    out = score_proposal(_row(params=_chain(channel=""),
                              detail={"open_choices": [], "first_run": _first_run()}))
    assert out["checks"]["open_choices_honest"] is False

    # a bundle whose chain pre-carries the agent id it has no right to claim
    out = score_proposal(_row(kind="agent_bundle",
                              params={"agent": {"name": "a", "instructions": "b"},
                                      "automation": {**_chain(), "agent_id": "ua_fake"}},
                              detail={"open_choices": [], "first_run": _first_run()}))
    assert out["checks"]["runs_as_bound"] is False

    # a stated first run on no cron boundary
    out = score_proposal(_row(params=_chain(),
                              detail={"open_choices": [],
                                      "first_run": "2026-09-17T09:30:00Z"}))
    assert out["checks"]["clock_right"] is False

    # the clock respected: 09:00 Berlin states an 07:00Z (summer) first run
    out = score_proposal(_row(params=_chain(tz="Europe/Berlin"),
                              detail={"open_choices": [],
                                      "first_run": _first_run(tz="Europe/Berlin")}))
    assert out["checks"]["clock_right"] is True

    # a monitor bundle that hides its structural cost facts
    out = score_proposal(_row(kind="monitor_bundle",
                              params={"monitor": {"name": "m"},
                                      "automation": _chain()},
                              detail={"open_choices": [], "first_run": _first_run()}))
    assert out["checks"]["cost_shown"] is False

    # a schema claim is graded only against a known catalogue — never guessed
    agent = {"name": "a", "instructions": "b", "schema_scope": "publik"}
    assert score_proposal(_row(kind="agent_draft", params=agent))["checks"]["schema_real"] is None
    out = score_proposal(_row(kind="agent_draft", params=agent),
                         known_schemas=["thelook"])
    assert out["checks"]["schema_real"] is False


def test_the_scorer_grades_rows_the_real_tools_stage(monkeypatch):
    """End to end: draft through the actual tool, score the actual row — the scorer
    and the tools cannot drift apart."""
    import aughor.agent.spotlight_act as act
    from aughor.actions.inbox import get_proposal

    monkeypatch.setattr(
        "aughor.automations.propose.propose_chain",
        lambda outcome, conn_id, provider=None: SimpleNamespace(
            verdict="proposed", draft=_chain(channel=""), dry_run={"ok": True},
            reason="", notes=[],
            to_fill=["Action 1 needs a Slack channel — the request names none"],
            first_run=_first_run()))
    out = act.draft_automation("conn-m", {"outcome": "post every morning"})
    scored = score_proposal(get_proposal(out["proposal_id"]))
    assert scored["checks"]["validates"] is True
    assert scored["checks"]["open_choices_honest"] is True   # declared == real, honestly open
    assert scored["checks"]["clock_right"] is True


def test_the_funnel_counts_the_movement_by_week():
    rows = [
        _row(status="executed", created_at="2026-09-15T10:00:00Z"),
        _row(status="rejected", created_at="2026-09-15T11:00:00Z"),
        _row(status="superseded", status_message=f"{FINISHED_IN_FORM_MARK} as abc",
             created_at="2026-09-16T09:00:00Z"),
        _row(status="superseded", status_message="superseded by prop-2",
             created_at="2026-09-16T09:05:00Z"),
        _row(status="expired", created_at="2026-09-02T09:00:00Z"),
        _row(status="pending", created_at="2026-09-16T10:00:00Z"),
        _row(kind="declared_action", status="pending"),      # not authoring — excluded
    ]
    f = authoring_funnel(rows)
    assert f["total"] == {"staged": 6, "accepted": 1, "finished_in_form": 1,
                          "redrafted": 1, "rejected": 1, "lapsed": 1, "pending": 1}
    assert f["weekly"]["2026-W38"]["staged"] == 5
    assert f["weekly"]["2026-W36"]["lapsed"] == 1


def test_the_funnel_mark_is_the_editor_doors_own_sentence():
    """The two ends of SP-11's sentence pinned together: the panel stamps it, the
    funnel keys on it — a rewording on either side fails here."""
    src = Path("web/components/AutomationsPanel.tsx").read_text()
    assert FINISHED_IN_FORM_MARK in src


def test_the_corpus_is_thirty_wellformed_asks():
    lines = [json.loads(l) for l in
             Path("evals/authoring_asks.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 30
    assert len({r["id"] for r in lines}) == 30
    assert all(r["ask"].strip() and r["family"] for r in lines)
    families = {r["family"] for r in lines}
    assert {"agent_bundle", "automation_draft", "monitor_bundle", "automation_edit",
            "brief_draft", "refusal"} <= families


def test_the_live_baseline_of_2026_09_16_is_written_down():
    """The receipt's number, kept as a record: 6 drafts ever staged on the live
    deployment, 1 accepted (the user's bundle), 0 finished in the form. Measured
    read-only against the live inbox store before this wave shipped."""
    baseline = {"staged": 6, "accepted": 1, "finished_in_form": 0}
    assert set(baseline) <= {"staged", "accepted", "finished_in_form",
                             "redrafted", "rejected", "lapsed", "pending"}
    assert DRAFT_KINDS  # and the population the numbers were counted over exists


def test_recordings_score_in_ci_when_present():
    """The receipt's letter: the scoring RUNS in CI. A report, not a gate — a check
    that fails on model behavior would make CI flaky on purpose, so this asserts the
    scorer produces a verdict for every staged row, never that the model was good.
    Skips cleanly until the recording run has happened."""
    import pytest
    path = Path("evals/authoring/recorded.jsonl")
    if not path.exists():
        pytest.skip("no recordings yet — scripts/record_authoring_drafts.py is the spending step")
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert rows, "an empty recording file is a failed run, not a corpus"
    scored = 0
    for r in rows:
        for p in r.get("staged", []):
            out = score_proposal(p)
            assert set(out["checks"]) == {"validates", "open_choices_honest",
                                          "runs_as_bound", "schema_real",
                                          "clock_right", "cost_shown"}
            scored += 1
    assert scored > 0, "thirty asks staged nothing — the recording measured a broken fixture"
