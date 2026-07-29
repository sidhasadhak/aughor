"""Wave S4 — the weekly digest over Aughor's own exhaust.

The carrying test is :func:`test_abstentions_are_reported_as_not_countable`. The scoping
doc listed abstentions as a section; the pre-check found only 3 of 795 receipts carry an
abstention-shaped phrase and **no structured field exists**. Counting them would mean
matching headline prose, producing an authoritative-looking number that is really a regex
opinion — the wolf-crying N1 caught in the divergence detector and N3 caught in its own
first cut.

Second: :func:`test_a_failed_section_is_reported_not_dropped`. A missing section reads as
"nothing to report", which is a different claim from "we could not compute this".
"""
from __future__ import annotations

import pytest

from aughor.knowledge.digest import (
    DEFAULT_WINDOW_DAYS,
    Digest,
    Section,
    build_digest,
)


# ── sections say where they came from ───────────────────────────────────────────────

def test_every_section_cites_its_source():
    """A figure a reader cannot trace is a figure they cannot act on — the same rule Q4's
    caveats follow. A digest is read fast and trusted by default."""
    d = build_digest("workspace")
    for s in d.sections:
        assert s.source, f"section {s.key} does not say where its number came from"


def test_the_expected_sections_are_present():
    keys = {s.key for s in build_digest("workspace").sections}
    assert {"volume", "usage", "health", "feedback", "curation", "abstentions"} <= keys


def test_a_measurable_section_renders_its_number():
    s = Section(key="volume", title="Questions answered", value=42, detail="across 3 days",
                source="ledger")
    assert s.line() == "Questions answered: 42 — across 3 days"


# ── the section the pre-check refused to fabricate ──────────────────────────────────

def test_abstentions_are_reported_as_not_countable():
    """3 of 795 receipts carry an abstention-shaped phrase and there is NO structured
    field. A plausible '3' would be worse than an honest 'not yet measurable'."""
    d = build_digest("workspace")
    abst = next(s for s in d.sections if s.key == "abstentions")
    assert abst.measurable is False
    assert abst.value is None
    assert "no structured field" in abst.detail


def test_the_unmeasurable_section_says_what_would_fix_it():
    """'Not measurable' with no remedy is a shrug; with one it is a work item."""
    abst = next(s for s in build_digest("workspace").sections if s.key == "abstentions")
    assert "would make this countable" in abst.detail


def test_unmeasurable_sections_are_named_never_omitted():
    """A section quietly dropped reads as 'nothing to report', which is a different claim
    from 'we cannot measure this yet'."""
    text = build_digest("workspace").narrative()
    assert "Not yet measurable:" in text
    assert "Abstentions" in text


def test_an_unmeasurable_section_renders_without_a_number():
    s = Section(key="x", title="Thing", measurable=False, detail="no field records it")
    assert s.line() == "Thing: not yet measurable — no field records it"


# ── robustness: one failure never sinks the digest ──────────────────────────────────

def test_a_failed_section_is_reported_not_dropped(monkeypatch):
    import aughor.knowledge.digest as D

    def _boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(D, "_usage", _boom)
    d = build_digest("workspace")
    usage = next(s for s in d.sections if s.key == "usage")
    assert usage.measurable is False
    assert "could not be computed" in usage.detail
    # …and the rest still rendered.
    assert any(s.key == "volume" and s.measurable for s in d.sections)


def test_the_digest_survives_every_section_failing(monkeypatch):
    import aughor.knowledge.digest as D

    def _boom(*a, **k):
        raise RuntimeError("everything is down")

    for fn in ("_volume", "_usage", "_health", "_feedback", "_curation"):
        monkeypatch.setattr(D, fn, _boom)
    d = build_digest("workspace")
    assert len(d.sections) == 6 and len(d.unmeasurable) == 6
    assert d.narrative()


# ── the narrative is assembled, never generated ─────────────────────────────────────

def test_the_narrative_takes_no_model_call():
    """A digest whose prose a model wrote is a digest that can be confidently wrong about
    the platform's own behaviour — and it reports on the platform to the people who would
    have to notice."""
    import inspect

    import aughor.knowledge.digest as D

    src = inspect.getsource(D)
    for llm in ("complete(", "chat(", "llm", "generate("):
        assert llm not in src.replace("llm_call", ""), f"digest must not call {llm}"


def test_the_narrative_names_the_window_and_connection():
    text = build_digest("workspace", window_days=14).narrative()
    assert "last 14 days" in text and "workspace" in text


def test_the_digest_serializes():
    out = build_digest("workspace").to_dict()
    assert out["narrative"] and out["sections"]
    assert all("source" in s for s in out["sections"])


def test_the_default_window_is_weekly():
    assert DEFAULT_WINDOW_DAYS == 7
    assert build_digest("workspace").window_days == 7


@pytest.mark.parametrize("days", [1, 7, 30])
def test_any_window_works(days):
    assert build_digest("workspace", window_days=days).window_days == days


def test_a_nonsense_window_is_clamped_not_crashed():
    assert build_digest("workspace", window_days=0).window_days == 0
    assert build_digest("workspace", window_days=-5)


def test_an_empty_digest_still_renders():
    d = Digest(connection_id="c1")
    assert "Workspace digest" in d.narrative()
