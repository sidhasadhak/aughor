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

WS4B_FLAGS = ["deep_analysis.premise_check", "deep_analysis.causal_drill", "closed_loop"]


@pytest.fixture(autouse=True)
def _no_override_leak():
    yield
    for name in WS4B_FLAGS:
        clear_flag(name)


def test_ws4b_flags_registered_with_meta():
    for name in WS4B_FLAGS:
        assert name in FLAG_ENV, name
        assert FLAG_META.get(name, {}).get("label"), f"{name} needs Settings-UI copy"


def test_auto_eligible_flag_env_semantics(monkeypatch):
    # 2026-07-13 capability graduation: `capabilities.auto` defaults ON, so an unset
    # auto-eligible guard is ELEVATED (its deterministic trigger gates per run). An
    # explicit env value always wins — the kill switch survives graduation.
    monkeypatch.delenv("AUGHOR_CAPABILITIES_AUTO", raising=False)
    monkeypatch.delenv("AUGHOR_PREMISE_CHECK", raising=False)
    assert flag_enabled("deep_analysis.premise_check") is True
    monkeypatch.setenv("AUGHOR_PREMISE_CHECK", "1")
    assert flag_enabled("deep_analysis.premise_check") is True
    monkeypatch.setenv("AUGHOR_PREMISE_CHECK", "garbage")
    assert flag_enabled("deep_analysis.premise_check") is False
    monkeypatch.setenv("AUGHOR_PREMISE_CHECK", "0")
    assert flag_enabled("deep_analysis.premise_check") is False


def test_plain_default_off_flag_env_semantics(monkeypatch):
    # A NON-auto-eligible default-off flag keeps the strict opt-in contract.
    # `semops.champion_validate` is the exemplar (its predecessors `ai_sql` and
    # `obs.prompt_capture` were both removed in the 2026-08-01 flag endgame).
    monkeypatch.delenv("AUGHOR_SEMOPS_CHAMPION_VALIDATE", raising=False)
    assert flag_enabled("semops.champion_validate") is False
    monkeypatch.setenv("AUGHOR_SEMOPS_CHAMPION_VALIDATE", "1")
    assert flag_enabled("semops.champion_validate") is True
    monkeypatch.setenv("AUGHOR_SEMOPS_CHAMPION_VALIDATE", "garbage")
    assert flag_enabled("semops.champion_validate") is False


def test_specialist_packs_is_default_on(monkeypatch):
    # Graduated 2026-07-31 (flag strategy batch 1, receipt 452a6fcebba4). What
    # matters at default-on is the OPERATOR ESCAPE HATCH: an explicit falsy env
    # value still kills steering outright.
    assert FLAG_DEFAULT.get("specialist_packs") is True
    monkeypatch.delenv("AUGHOR_SPECIALIST_PACKS", raising=False)
    assert flag_enabled("specialist_packs") is True
    for off in ("0", "false", "no", "off"):
        monkeypatch.setenv("AUGHOR_SPECIALIST_PACKS", off)
        assert flag_enabled("specialist_packs") is False, off
    # default-on semantics: any non-off value stays on
    monkeypatch.setenv("AUGHOR_SPECIALIST_PACKS", "garbage")
    assert flag_enabled("specialist_packs") is True


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
    monkeypatch.delenv("AUGHOR_CLOSED_LOOP", raising=False)
    assert flag_enabled("closed_loop") is False
    set_flag("closed_loop", True)
    assert flag_enabled("closed_loop") is True  # override beats unset env
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    set_flag("closed_loop", False)
    assert flag_enabled("closed_loop") is False  # override beats truthy env
    clear_flag("closed_loop")
    assert flag_enabled("closed_loop") is True  # env decides again


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
