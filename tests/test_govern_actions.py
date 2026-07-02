"""P4 graduated approval + audit (aughor.govern.actions).

Uses the hermetic test ledger (conftest sets AUGHOR_SYSTEM_DB). Each test uses a
unique scope so allowlist entries don't leak between tests.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aughor import govern
from aughor.govern.actions import ActionRisk


def test_classify_known_and_failsafe():
    assert govern.classify("connection.delete") is ActionRisk.HIGH
    assert govern.classify("skill.save") is ActionRisk.LOW
    # An unregistered mutation must be HIGH by default (fail-safe gate).
    assert govern.classify("some.brand.new.mutation") is ActionRisk.HIGH


def test_guard_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("AUGHOR_ACTION_APPROVAL", raising=False)
    # Even a high-risk action passes silently when the gate is off.
    assert govern.guard("connection.delete", "scope-off") is None


def test_guard_blocks_unapproved_high_risk(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    with pytest.raises(HTTPException) as ei:
        govern.guard("connection.delete", "scope-block")
    assert ei.value.status_code == 428
    assert ei.value.detail["error"] == "approval_required"
    assert ei.value.detail["action"] == "connection.delete"


def test_guard_allows_low_risk(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    assert govern.guard("skill.save", "scope-low") is None  # low risk → auto, no raise


def test_allow_then_guard_passes(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    scope = "conn-allow-1"
    with pytest.raises(HTTPException):
        govern.guard("connection.delete", scope)          # blocked before approval
    govern.allow("connection.delete", scope)
    assert govern.is_allowed("connection.delete", scope)
    assert govern.guard("connection.delete", scope) is None  # now proceeds


def test_revoke_reinstates_the_gate(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    scope = "conn-revoke-1"
    govern.allow("connection.delete", scope)
    assert govern.guard("connection.delete", scope) is None
    assert govern.revoke("connection.delete", scope) is True
    with pytest.raises(HTTPException):
        govern.guard("connection.delete", scope)


def test_allowlist_is_scoped(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    govern.allow("connection.delete", "conn-A")
    assert govern.is_allowed("connection.delete", "conn-A")
    # a different scope is NOT allowlisted by approving conn-A
    assert not govern.is_allowed("connection.delete", "conn-B")


def test_audit_trail_records_every_decision(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    scope = "conn-audit-1"
    with pytest.raises(HTTPException):
        govern.guard("connection.delete", scope)   # -> blocked
    govern.allow("connection.delete", scope)         # -> allowlisted
    govern.guard("connection.delete", scope)         # -> approved
    trail = govern.recent_audit(limit=50)
    mine = [e for e in trail if e.get("scope") == scope]
    decisions = {e["decision"] for e in mine}
    assert {"blocked", "allowlisted", "approved"} <= decisions
    assert all(e["action"] == "connection.delete" and e["risk"] == "high" for e in mine)
