"""The runtime flag system (kernel/flags.py) — registration, defaults, override precedence.

WS4b moved the four direct-`os.environ` flags (premise check · causal drill · ask-clarify ·
closed loop) into FLAG_ENV so they gain the ledger override + Settings-UI toggle every other
flag has.

The default-ON contract — an unset variable resolves ON, an explicit falsy value still
disables, any other value stays on — is asserted against the SYNTHETIC exemplar from
`tests/conftest.py`, not a product flag. `ask.clarify` used to play that role and was
removed by Wave 2d of the flag endgame; the default-OFF exemplar had already been
re-pointed twice for the same reason (ai_sql -> obs.prompt_capture ->
semops.champion_validate). Since the endgame deletes every flag eventually, an exemplar
that is a product flag is guaranteed to be re-pointed again.
"""
from __future__ import annotations

import pytest

from aughor.kernel.flags import (
    FLAG_DEFAULT,
    FLAG_ENV,
    FLAG_META,
    clear_flag,
    flag_enabled,
    list_flags,
    set_flag,
)

# `deep_analysis.premise_check` left this list 2026-08-04 (Wave 3), and
# `deep_analysis.causal_drill` left 2026-08-06 (Wave 5 hardwired it). The registry's
# last two flags are the exemplars now — when they graduate, Wave 7 retires this
# machinery and these tests with it.
WS4B_FLAGS = ["explore.route_wide", "federation.planner"]


@pytest.fixture(autouse=True)
def _no_override_leak():
    yield
    for name in WS4B_FLAGS:
        clear_flag(name)


def test_ws4b_flags_registered_with_meta():
    for name in WS4B_FLAGS:
        assert name in FLAG_ENV, name
        assert FLAG_META.get(name, {}).get("label"), f"{name} needs Settings-UI copy"


def test_the_auto_tier_is_dissolved_and_stays_dissolved(monkeypatch):
    """Wave 3 rot guard. Auto-mode elevated an unset flag to enabled from a SECOND source
    of truth (a master env var) beside the one that actually decided (the runtime
    trigger). The tier is empty and the elevation branch is gone; this fails if either
    comes back, because a re-elevated flag would silently resolve on unrelated state."""
    from aughor.kernel.flags import AUTO_ELIGIBLE, FLAG_ENV, flag_state

    assert AUTO_ELIGIBLE == frozenset()
    assert "capabilities.auto" not in FLAG_ENV

    # …and with the tier empty, an unregistered-default flag is plainly off, never "auto".
    monkeypatch.delenv("AUGHOR_FEDERATION_PLANNER", raising=False)
    assert flag_enabled("federation.planner") is False
    assert flag_state("federation.planner") == "off"


def test_plain_default_off_flag_env_semantics(monkeypatch):
    # A NON-auto-eligible default-off flag keeps the strict opt-in contract.
    # `semops.champion_validate` is the exemplar (its predecessors `ai_sql` and
    # `obs.prompt_capture` were both removed in the 2026-08-01 flag endgame).
    monkeypatch.delenv("AUGHOR_FEDERATION_PLANNER", raising=False)
    assert flag_enabled("federation.planner") is False
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "1")
    assert flag_enabled("federation.planner") is True
    monkeypatch.setenv("AUGHOR_FEDERATION_PLANNER", "garbage")
    assert flag_enabled("federation.planner") is False


def test_specialist_packs_left_the_registry_for_good():
    """Hardwired by flag endgame Wave 2 (2026-08-06; graduated 2026-07-31 on
    receipt 452a6fcebba4). The escape hatch the old test pinned is now the DATA
    GATE itself: steering needs an active pack with a human-pinned deploy binding,
    so there is nothing an env var needs to kill. The registry must stay empty of
    it — a re-registration would be the drift the endgame exists to prevent."""
    assert "specialist_packs" not in FLAG_ENV
    assert FLAG_DEFAULT == {}     # Wave 2 complete: no graduated default-ONs remain


def test_default_on_flag_env_semantics(monkeypatch, synthetic_default_on):
    """The default-ON contract, asserted against a synthetic flag so it survives the
    endgame deleting whichever product flag last played this role."""
    from tests.conftest import SYNTHETIC_DEFAULT_ON_VAR as VAR

    assert FLAG_DEFAULT.get(synthetic_default_on) is True
    monkeypatch.delenv(VAR, raising=False)
    assert flag_enabled(synthetic_default_on) is True
    # explicit off-list value disables
    for off in ("0", "false", "no", "off"):
        monkeypatch.setenv(VAR, off)
        assert flag_enabled(synthetic_default_on) is False, off
    # default-on semantics: any NON-off value stays on
    monkeypatch.setenv(VAR, "garbage")
    assert flag_enabled(synthetic_default_on) is True


def test_runtime_override_wins_both_directions(monkeypatch):
    monkeypatch.delenv("AUGHOR_EXPLORE_ROUTE_WIDE", raising=False)
    assert flag_enabled("explore.route_wide") is False
    set_flag("explore.route_wide", True)
    assert flag_enabled("explore.route_wide") is True  # override beats unset env
    monkeypatch.setenv("AUGHOR_EXPLORE_ROUTE_WIDE", "1")
    set_flag("explore.route_wide", False)
    assert flag_enabled("explore.route_wide") is False  # override beats truthy env
    clear_flag("explore.route_wide")
    assert flag_enabled("explore.route_wide") is True  # env decides again


def test_list_flags_reflects_default_on(monkeypatch, synthetic_default_on):
    from tests.conftest import SYNTHETIC_DEFAULT_ON_VAR as VAR

    monkeypatch.delenv(VAR, raising=False)
    flags = list_flags()
    assert flags[synthetic_default_on]["value"] is True
    # With the variable unset, this flag is on because of FLAG_DEFAULT — so the source is
    # "default". It used to report "env" (the old catch-all tail), which pointed an operator
    # at a variable nobody had set; the distinction matters more with every graduation.
    assert flags[synthetic_default_on]["source"] == "default"
    assert flags[synthetic_default_on]["env_var"] == VAR
    # …and the disposition falls out of FLAG_DEFAULT membership, with no separate table.
    assert flags[synthetic_default_on]["disposition"] == "default_on"
    for name in WS4B_FLAGS:
        assert name in flags
