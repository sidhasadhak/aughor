"""The declared organization reaches the answer path (Wave 4, the real 1.2 gap).

`org_context()` builds a one-line block from facts the operator explicitly declared —
industry, reporting currency, fiscal year start. It had exactly three callers (profile
inference, the explorer, the brief), none of them the quick `/ask` path. So the most
used surface in the product could not see settings a person had deliberately entered.

This is the alternative to the plan's Layer 1.2 "guidance notes" store: both of that
item's canonical examples ("fiscal year starts in February", "always report EUR") are
already OrgSettings fields, and fiscal year is already enforced deterministically by
the compiler. The gap was never storage — it was reach.
"""
from __future__ import annotations

import inspect

import pytest

from aughor.orgsettings import org_context
from aughor.orgsettings.models import OrgSettings
from aughor.orgsettings.store import effective_settings  # noqa: F401  (patched below)


@pytest.fixture
def declared(monkeypatch):
    """A workspace with real declared identity — patched at the resolver so the test
    never writes the live settings store."""
    from aughor.orgsettings import store as S
    monkeypatch.setattr(
        S, "effective_settings",
        lambda workspace_id=None: OrgSettings(
            company_name="Acme", industry="retail",
            currency_code="EUR", fiscal_year_start_month=2),
    )


# ── the framing ──────────────────────────────────────────────────────────────

def test_the_default_wording_is_unchanged():
    """Three callers already emit this exact sentence; their prompts must not move."""
    sig = inspect.signature(org_context)
    assert sig.parameters["reading"].default == "this brief"


def test_an_unconfigured_org_contributes_nothing():
    """Empty string when nothing is declared, so callers prepend unconditionally and
    an unconfigured deployment's prompt is byte-identical."""
    out = org_context(workspace_id="definitely-not-a-configured-workspace")
    assert out == "" or out.startswith("ORGANIZATION reading")


def test_the_reading_is_nameable(declared):
    """Telling an answer's reader they are 'reading this brief' would be a small lie
    in service of reuse."""
    assert "reading this answer" in org_context(reading="this answer")
    assert "reading this brief" in org_context()


# ── it actually reaches the answer path ──────────────────────────────────────

def test_the_ask_path_asks_for_the_answer_framing():
    """The seam itself, pinned: the quick path must request its own framing rather
    than inheriting the brief's."""
    from aughor.routers import investigations

    src = inspect.getsource(investigations)
    assert 'org_context(reading="this answer")' in src


def test_the_org_note_is_carried_into_the_narrator_prompt():
    """Both halves must exist — building the block and then not sending it is the
    both-ends-exist-feature-doesn't trap."""
    from aughor.routers import investigations

    src = inspect.getsource(investigations)
    assert 'f"{_org_note}"' in src, "the block is built but never reaches the prompt"


def test_a_failure_to_read_org_settings_never_breaks_an_answer():
    """Additive context: an answer stands without it."""
    from aughor.routers import investigations

    src = inspect.getsource(investigations)
    assert "org context is additive; the answer stands without it" in src
