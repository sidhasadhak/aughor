"""P6 rate/infra governor — the deployment-wide token ceiling (AUGHOR_MAX_TOKEN_BUDGET).

The runaway-fan-out enforcement itself already exists (the kernel heartbeat cancels a
kernel job over its charter budget and emits `budget.exceeded`). This covers the new
piece: a global hard ceiling that floors every agent's resolved budget so an operator
can bound worst-case cost without per-agent config.
"""
from __future__ import annotations

from aughor.kernel.agents import effective_governance

# The investigate/explore fan-out runs under the 'analyst' charter (500k tokens).
_ANALYST_DEFAULT = 500_000


def test_no_ceiling_keeps_charter_budget(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_TOKEN_BUDGET", raising=False)
    assert effective_governance("analyst").token_budget == _ANALYST_DEFAULT


def test_ceiling_floors_budget(monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_TOKEN_BUDGET", "50000")
    assert effective_governance("analyst").token_budget == 50_000


def test_ceiling_only_lowers_never_raises(monkeypatch):
    # a ceiling above the charter default must not inflate the budget
    monkeypatch.setenv("AUGHOR_MAX_TOKEN_BUDGET", "999999999")
    assert effective_governance("analyst").token_budget == _ANALYST_DEFAULT


def test_nonnumeric_ceiling_ignored(monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_TOKEN_BUDGET", "lots")
    assert effective_governance("analyst").token_budget == _ANALYST_DEFAULT


def test_ceiling_applies_when_agent_has_no_charter_budget(monkeypatch):
    # an agent whose charter has no budget still gets the deployment ceiling
    monkeypatch.setenv("AUGHOR_MAX_TOKEN_BUDGET", "12345")
    gov = effective_governance("some_unknown_agent")
    assert gov.token_budget == 12345
