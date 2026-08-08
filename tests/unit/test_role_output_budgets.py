"""Per-role output ceilings (Wave 3 / Layer 4.2a).

`_max_output_tokens()` used to take no arguments and resolve the CODER's binding
unconditionally, so every call in the system generated under whatever ceiling the
coder's model implied — including the narrator, the one role that was measured
truncating (a ~25-finding briefing died at 4096), and `fast`, the cheap-by-declaration
tier that had no use for a capable binding's bump.

Numbers here are pinned as absolute values rather than derived from the module's own
tables, following `test_model_profile.py`: a test that recomputes the thing it is
checking passes when the table is wrong.
"""
from __future__ import annotations

import pytest

from aughor.llm import provider as P
from aughor.llm.faux import CAPABLE_MODEL
from aughor.llm.profile import profile_for, role_output_cap, tier_for


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    """The operator's env wins over every tier default — and this repo's own `.env`
    sets AUGHOR_MAX_OUTPUT_TOKENS=8192, which would make every assertion below vacuous
    by pinning the answer. Unset it so the TIERS are what is under test."""
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)


# ── the baseline stays byte-identical ────────────────────────────────────────

def test_every_role_keeps_the_old_constant_on_an_unknown_model():
    """BASELINE is the behaviour everything was measured against; 4.2a must not move
    it for any role."""
    for role in ("coder", "narrator", "fast"):
        assert role_output_cap(role, "somebody-elses-finetune") == 4096


# ── the capable tier is role-shaped ──────────────────────────────────────────

def test_the_narrator_gets_headroom_above_the_coder():
    """The measured failure was a narrator truncation, and prose carries none of the
    reasoning-token runaway risk that keeps structured ceilings low."""
    assert role_output_cap("narrator", CAPABLE_MODEL) == 12288
    assert role_output_cap("coder", CAPABLE_MODEL) == 8192
    assert role_output_cap("narrator", CAPABLE_MODEL) > role_output_cap("coder", CAPABLE_MODEL)


def test_fast_does_not_inherit_the_capable_bump():
    """`fast` is chosen BECAUSE the work is a throwaway; a bigger ceiling buys nothing
    there and rides the run's largest per-call multiplier."""
    assert role_output_cap("fast", CAPABLE_MODEL) == 4096
    assert role_output_cap("fast", CAPABLE_MODEL) < role_output_cap("coder", CAPABLE_MODEL)


def test_an_unknown_role_falls_back_to_the_tier_default():
    """A role added to ROLES without a cap must behave exactly as before rather than
    inheriting some other role's budget."""
    assert role_output_cap("auditor", CAPABLE_MODEL) == tier_for(CAPABLE_MODEL)["max_output_tokens"]


# ── the provider actually uses it ────────────────────────────────────────────

def test_the_provider_ceiling_follows_the_role(monkeypatch):
    """The plumbing is the point: before 4.2a this function took no arguments."""
    assert P._max_output_tokens("narrator", CAPABLE_MODEL) == 12288
    assert P._max_output_tokens("fast", CAPABLE_MODEL) == 4096


def test_the_ceiling_follows_the_model_actually_being_called():
    """A fallback link is sized by the binding that will really serve the request —
    not by the primary's, which is what re-resolving the role's binding would give."""
    assert P._max_output_tokens("narrator", "somebody-elses-finetune") == 4096
    assert P._max_output_tokens("narrator", CAPABLE_MODEL) == 12288


def test_the_env_override_still_wins_outright(monkeypatch):
    """The operator's explicit number outranks every tier decision, in both
    directions — the pre-4.2a contract, unchanged."""
    monkeypatch.setenv("AUGHOR_MAX_OUTPUT_TOKENS", "777")
    assert P._max_output_tokens("narrator", CAPABLE_MODEL) == 777
    assert profile_for("narrator", model=CAPABLE_MODEL).max_output_tokens == 777


def test_a_missing_model_still_resolves(monkeypatch):
    """Called with no model (the legacy signature's behaviour), it must resolve the
    role's own binding rather than raise."""
    assert P._max_output_tokens("narrator") >= 256


def test_the_profile_reports_the_roles_own_ceiling():
    """`profile_for(role).max_output_tokens` is what a reader of the profile trusts;
    it must describe the budget that role really runs under."""
    assert profile_for("narrator", model=CAPABLE_MODEL).max_output_tokens == 12288
    assert profile_for("fast", model=CAPABLE_MODEL).max_output_tokens == 4096


def test_a_faux_binding_is_role_sized_end_to_end(faux_llm):
    """Through the real provider stack: the request the backend receives carries the
    NARRATOR's ceiling, not the coder's."""
    from pydantic import BaseModel

    class _Out(BaseModel):
        answer: str

    faux_llm.set_responses(['{"answer": "ok"}'])
    P.get_provider("narrator").complete("s", "u", _Out)
    (call,) = faux_llm.calls()
    # faux-narrator is a BASELINE model, so every role is 4096 there — the assertion
    # that matters is that a ceiling was sent at all and is the role's own.
    assert call.kwargs["max_tokens"] == role_output_cap("narrator", call.model)
