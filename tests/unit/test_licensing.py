"""Commercial capability gating — see aughor/licensing/.
Lands dark: default tier = enterprise (everything on)."""
import pytest
from fastapi import HTTPException

from aughor.licensing.capabilities import (
    Capability, Tier, TIER_CAPABILITIES, capabilities_for,
)
from aughor.licensing import resolver as R
from aughor.licensing.deps import require_capability


# ── tier map ──────────────────────────────────────────────────────────────────

def test_tiers_are_additive():
    free = TIER_CAPABILITIES[Tier.FREE]
    pro = TIER_CAPABILITIES[Tier.PRO]
    ent = TIER_CAPABILITIES[Tier.ENTERPRISE]
    assert free < pro < ent            # strict subsets
    assert Capability.NL2SQL_CHAT in free
    assert Capability.MONITORS in pro and Capability.MONITORS not in free
    assert Capability.SEMANTIC_COMPILER in ent and Capability.SEMANTIC_COMPILER not in pro


def test_capabilities_for_unknown_falls_back_enterprise():
    assert capabilities_for("nonsense") == TIER_CAPABILITIES[Tier.ENTERPRISE]


# ── resolve_tier ──────────────────────────────────────────────────────────────

def test_default_tier_is_enterprise(monkeypatch):
    monkeypatch.delenv("AUGHOR_TIER", raising=False)
    assert R.resolve_tier() == Tier.ENTERPRISE
    # everything-on: a fresh install behaves as before this layer existed
    assert R.has_capability(Capability.SEMANTIC_COMPILER)


def test_env_tier_override(monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "free")
    assert R.resolve_tier() == Tier.FREE
    assert R.has_capability(Capability.NL2SQL_CHAT) is True
    assert R.has_capability(Capability.MONITORS) is False


def test_bad_env_tier_falls_back(monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "platinum")
    assert R.resolve_tier() == Tier.ENTERPRISE


def test_per_connection_tier_wins(monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "enterprise")
    monkeypatch.setattr(R, "get_connection_settings", lambda cid: {"tier": "pro"}, raising=False)
    # patch the lazily-imported symbol used inside resolve_tier
    import aughor.db.registry as reg
    monkeypatch.setattr(reg, "get_connection_settings", lambda cid: {"tier": "pro"})
    assert R.resolve_tier("c1") == Tier.PRO
    assert R.has_capability(Capability.MONITORS, conn_id="c1") is True
    assert R.has_capability(Capability.SEMANTIC_COMPILER, conn_id="c1") is False


# ── require_capability dependency ─────────────────────────────────────────────

def test_dependency_passes_at_enterprise(monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "enterprise")
    dep = require_capability(Capability.MONITORS)
    assert dep(connection_id=None) is None     # no raise


def test_dependency_402s_when_locked(monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "free")
    dep = require_capability(Capability.MONITORS)
    with pytest.raises(HTTPException) as ei:
        dep(connection_id=None)
    assert ei.value.status_code == 402
    assert ei.value.detail["capability"] == "monitors"
    assert ei.value.detail["current_tier"] == "free"
