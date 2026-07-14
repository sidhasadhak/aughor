"""Hermetic unit tests for overview routing detection + eligibility.

No DB, no LLM: ``_is_overview_question`` is pure regex + the pure measure/entity/grain
helpers, and ``_overview_eligible`` reads a fake request plus the ``ask.overview`` flag
(resolved against the hermetic temp ledger from conftest). We drive the flag with the
``AUGHOR_ASK_OVERVIEW`` env var, including the explicit kill switch.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.routers.investigations import _is_overview_question, _overview_eligible


# ── _is_overview_question ─────────────────────────────────────────────────────

_OVERVIEW_TRUE = [
    "show me interesting facts about this schema",
    "tell me about this data",
    "what's notable in this dataset",
    "summarize this schema",
    "give me an overview of the data",
    "what can I ask about here",
]

_OVERVIEW_FALSE = [
    "show monthly sales for Mytheresa",   # named metric + entity + grain
    "what is total revenue by platform",  # named metric + dimension
    "why did returns spike",              # an investigation, no overview phrasing
    "tell me about revenue",              # overview phrasing BUT names a measure
    "tell me about customer churn",       # overview phrasing BUT names an entity/measure
    "top 10 customers",                   # a direct ranking ask
]


@pytest.mark.parametrize("q", _OVERVIEW_TRUE)
def test_is_overview_question_true(q):
    assert _is_overview_question(q) is True


@pytest.mark.parametrize("q", _OVERVIEW_FALSE)
def test_is_overview_question_false(q):
    assert _is_overview_question(q) is False


def test_is_overview_question_handles_empty_and_none():
    assert _is_overview_question("") is False
    assert _is_overview_question(None) is False


# ── _overview_eligible ────────────────────────────────────────────────────────

def _req(question="tell me about this data", *, depth="auto", deep=False,
         insight_id=None, history=None, skip_clarify=False, canvas_id=None):
    """A minimal AskRequest-shaped stand-in — only the fields _overview_eligible reads."""
    return SimpleNamespace(
        question=question, depth=depth, deep=deep, insight_id=insight_id,
        history=history or [], skip_clarify=skip_clarify, canvas_id=canvas_id,
    )


def test_eligible_for_fresh_auto_overview_when_flag_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_ASK_OVERVIEW", "1")
    assert _overview_eligible(_req()) is True


@pytest.mark.parametrize("kwargs", [
    {"depth": "quick"},                       # explicit depth override
    {"depth": "deep"},                        # explicit depth override
    {"deep": True},                           # legacy deep escalation
    {"insight_id": "ins_123"},                # dossier drill
    {"history": [{"question": "prev"}]},       # a follow-up, not a fresh look
    {"skip_clarify": True},                   # already answering a clarification
    {"question": "what is total revenue by platform"},  # a specific ask, not an overview
])
def test_not_eligible_when_disqualified_even_with_flag_on(monkeypatch, kwargs):
    monkeypatch.setenv("AUGHOR_ASK_OVERVIEW", "1")
    assert _overview_eligible(_req(**kwargs)) is False


def test_kill_switch_env_zero_disables_even_for_overview_question(monkeypatch):
    # ask.overview is AUTO_ELIGIBLE + capabilities.auto is default-on, so an explicit
    # AUGHOR_ASK_OVERVIEW=0 is required to prove the operator kill switch is honored.
    monkeypatch.setenv("AUGHOR_ASK_OVERVIEW", "0")
    assert _overview_eligible(_req()) is False


def test_auto_elevated_when_env_unset(monkeypatch):
    # With the env var unset, the auto-eligible flag rides capabilities.auto (default-on),
    # so a fresh overview ask is still eligible without any explicit opt-in.
    monkeypatch.delenv("AUGHOR_ASK_OVERVIEW", raising=False)
    assert _overview_eligible(_req()) is True
