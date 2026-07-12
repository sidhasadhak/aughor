"""Capabilities Auto-mode (Wave 1 · E3).

The master ``capabilities.auto`` switch elevates each SELF-GATING guard to enabled (its deterministic
trigger then decides per run) — one switch instead of flipping each. What's pinned: byte-identical when the
master is off, elevation of auto-eligible guards when on, cost-dangerous flags staying manual, operator
On/Off always winning, no recursion on the master itself, and the flags API exposing the classification.
"""
from __future__ import annotations

import pytest

from aughor.kernel import flags
from aughor.kernel.flags import AUTO_ELIGIBLE, clear_flag, flag_enabled, flag_state, list_flags, set_flag

MASTER = "capabilities.auto"
GUARD = "ada.premise_check"                 # an auto-eligible self-gating capability
COSTLY = "semops.champion_validate"         # registered but NOT auto-eligible (cost-dangerous)


def _env(name):
    return flags.FLAG_ENV[name]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # No ambient env or leftover ledger override for the flags under test.
    for n in (MASTER, GUARD, COSTLY):
        monkeypatch.delenv(_env(n), raising=False)
        clear_flag(n)
    yield
    for n in (MASTER, GUARD, COSTLY):
        clear_flag(n)


def test_byte_identical_when_master_off():
    assert flag_enabled(GUARD) is False        # unset auto-eligible guard, master off → off, as before
    assert flag_state(GUARD) == "off"


def test_master_on_elevates_auto_eligible_guard(monkeypatch):
    monkeypatch.setenv(_env(MASTER), "1")
    assert flag_enabled(GUARD) is True          # enabled → its trigger now decides per run
    assert flag_state(GUARD) == "auto"          # …and reads "auto", not "on"


def test_master_on_does_not_elevate_cost_dangerous(monkeypatch):
    assert COSTLY not in AUTO_ELIGIBLE
    monkeypatch.setenv(_env(MASTER), "1")
    assert flag_enabled(COSTLY) is False        # cost-dangerous flags stay manual
    assert flag_state(COSTLY) == "off"


def test_explicit_off_overrides_auto_mode(monkeypatch):
    monkeypatch.setenv(_env(MASTER), "1")
    monkeypatch.setenv(_env(GUARD), "0")        # operator opts this one OUT
    assert flag_enabled(GUARD) is False
    assert flag_state(GUARD) == "off"


def test_explicit_on_without_auto_mode(monkeypatch):
    monkeypatch.setenv(_env(GUARD), "1")        # force-enable one guard, master off
    assert flag_enabled(GUARD) is True
    assert flag_state(GUARD) == "on"            # explicit → "on", not "auto"


def test_runtime_override_off_beats_auto_mode(monkeypatch):
    monkeypatch.setenv(_env(MASTER), "1")
    set_flag(GUARD, False)                       # a Settings-UI toggle off wins over Auto-mode
    assert flag_enabled(GUARD) is False
    assert flag_state(GUARD) == "off"


def test_master_switch_not_auto_eligible_no_recursion(monkeypatch):
    assert MASTER not in AUTO_ELIGIBLE
    monkeypatch.setenv(_env(MASTER), "1")
    assert flag_enabled(MASTER) is True          # resolves normally, no infinite loop
    assert flag_state(MASTER) == "on"


def test_list_flags_exposes_capability_metadata(monkeypatch):
    monkeypatch.setenv(_env(MASTER), "1")
    fl = list_flags()
    g = fl[GUARD]
    assert g["auto_eligible"] is True and g["state"] == "auto" and g.get("trigger")
    assert fl[COSTLY]["auto_eligible"] is False and "trigger" not in fl[COSTLY]
