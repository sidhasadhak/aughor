"""Wave E4 — the run-scoped experiment plane (`aughor/evals/experiments.py`).

Hermetic: the instructor client is stubbed and the two recording sinks are neutered, so no
network, no LLM and no writes under `data/`.

What is actually worth pinning here is not that an override can be set — it is that the
harness cannot lie about having set one. Three failure modes, in descending order of how
badly they would corrupt a result:

1. **Measuring with the failover chain live.** The chain finishes a failed run on a
   different model; the report attributes the number to the binding that started it.
2. **A pin leaking out of a cell that raised** — the next cell inherits it, so the baseline
   silently becomes a second copy of the variant and the delta collapses to zero.
3. **Reporting the requested config instead of the resolved one.** An override that no-ops
   reads exactly like a variant that did not help, and that reading flatters the harness.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from aughor.evals import experiments as X
from aughor.evals.experiments import Cell, MeasurementIntegrityError
from aughor.kernel.flags import clear_flag, flag_enabled
from aughor.llm import provider as P

# Two registered flags, only ever cleared between tests — nothing here depends on what
# they DO. Both are EXPERIMENT-dispositioned so they outlive the endgame's hardwiring
# waves; the two predecessors were re-pointed for exactly that reason (evidence_stubs
# deleted 2026-08-01, evidence_dedup hardwired by Wave 2d).
FLAG = "explore.route_wide"
OTHER = "federation.planner"


@pytest.fixture(autouse=True)
def _measurable(monkeypatch):
    """Default every test into a measurable environment; the guard has its own tests."""
    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", "1")
    yield
    for name in (FLAG, OTHER):
        clear_flag(name)


# ── the integrity precondition ────────────────────────────────────────────────

def test_refuses_to_measure_while_the_fallback_chain_is_live(monkeypatch):
    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    with pytest.raises(MeasurementIntegrityError) as exc:
        X.assert_measurable()
    assert "AUGHOR_FALLBACK_DISABLED" in str(exc.value)


def test_applied_refuses_before_spending_a_single_request(monkeypatch):
    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    with pytest.raises(MeasurementIntegrityError):
        with X.applied(Cell(label="variant", flags={FLAG: True})):
            pytest.fail("the block must not run")


def test_dry_run_may_opt_out_of_the_precondition(monkeypatch):
    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    with X.applied(Cell(label="dry"), require_measurable=False) as resolved:
        assert resolved["effective"]["fallback_disabled"] is False


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("", False),
])
def test_fallback_disabled_reads_the_env_the_same_way_the_provider_does(monkeypatch, raw, expected):
    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", raw)
    assert X.fallback_disabled() is expected


# ── the cell applies, and reports what it actually got ────────────────────────

def test_applied_puts_the_flags_in_force_and_reports_them_resolved():
    with X.applied(Cell(label="stubs-on", flags={FLAG: True})) as resolved:
        assert flag_enabled(FLAG) is True
        assert resolved["label"] == "stubs-on"
        assert resolved["requested"]["flags"] == {FLAG: True}
        assert resolved["effective"]["flags"] == {FLAG: True}
        assert resolved["discrepancies"] == []
    assert flag_enabled(FLAG) is False


def test_effective_flags_list_only_the_axis_that_moved():
    """Two hundred unrelated flags would bury the one the experiment varied."""
    with X.applied(Cell(label="v", flags={FLAG: True})) as resolved:
        assert set(resolved["effective"]["flags"]) == {FLAG}


def test_baseline_cell_still_records_what_the_baseline_resolved_to():
    with X.applied(Cell(label="baseline")) as resolved:
        assert resolved["effective"]["flag_overrides"] == {}
        assert "backend" in resolved["effective"]
        assert resolved["effective"]["fallback_disabled"] is True


def test_a_discrepancy_is_reported_rather_than_silently_measured(monkeypatch):
    """If the read-back ever disagrees with the request, the run must say so.

    Simulated by making `flag_enabled` lie, because the real plane has no way to
    disagree — which is the point: the check costs nothing and catches the day it does.
    """
    monkeypatch.setattr(X, "flag_enabled", lambda name: False)
    with X.applied(Cell(label="v", flags={FLAG: True})) as resolved:
        assert resolved["discrepancies"] == [
            {"flag": FLAG, "requested": True, "effective": False}]


# ── pins must not leak between cells ──────────────────────────────────────────

def test_model_pin_is_released_when_the_cell_body_raises():
    assert P.current_run_model() is None
    with pytest.raises(RuntimeError):
        with X.applied(Cell(label="v", model="some/model")):
            assert P.current_run_model() == "some/model"
            raise RuntimeError("cell blew up")
    assert P.current_run_model() is None


def test_temperature_pin_is_released_when_the_cell_body_raises():
    assert P.current_run_temperature() is None
    with pytest.raises(RuntimeError):
        with X.applied(Cell(label="v", temperature=0.0)):
            assert P.current_run_temperature() == 0.0
            raise RuntimeError("cell blew up")
    assert P.current_run_temperature() is None


def test_sequential_cells_do_not_inherit_each_others_pins():
    seen = []
    for cell in [Cell(label="a", model="m-a", temperature=0.0),
                 Cell(label="b")]:
        with X.applied(cell):
            seen.append((P.current_run_model(), P.current_run_temperature()))
    assert seen == [("m-a", 0.0), (None, None)]


def test_temperature_zero_is_a_real_pin_not_a_falsy_skip():
    """0.0 is the value a measured run most wants; `if cell.temperature:` would drop it."""
    with X.applied(Cell(label="v", temperature=0.0)):
        assert P.current_run_temperature() == 0.0


# ── the temperature resolver ──────────────────────────────────────────────────

def test_pin_wins_over_the_call_sites_role_default():
    assert P._effective_temperature(0.1, "openrouter") == 0.1
    token = P.set_run_temperature(0.0)
    try:
        assert P._effective_temperature(0.1, "openrouter") == 0.0
    finally:
        P.reset_run_temperature(token)


def test_temperature_is_clamped_to_each_backends_accepted_range():
    """Anthropic rejects >1.0; the OpenAI-compatible family accepts up to 2.0. An unclamped
    grid axis would die on one backend and quietly succeed on the other."""
    token = P.set_run_temperature(1.8)
    try:
        assert P._effective_temperature(0.1, "anthropic") == 1.0
        assert P._effective_temperature(0.1, "openrouter") == 1.8
    finally:
        P.reset_run_temperature(token)

    token = P.set_run_temperature(-0.5)
    try:
        assert P._effective_temperature(0.1, "openrouter") == 0.0
    finally:
        P.reset_run_temperature(token)


# ── the kwargs the provider actually sends ────────────────────────────────────

class _Out(BaseModel):
    ok: bool = True


class _Endpoint:
    """Records the kwargs of the call instructor would have made."""

    def __init__(self):
        self.seen: dict = {}

    def create_with_completion(self, **kw):
        self.seen = kw
        return _Out(), SimpleNamespace(usage=None)


def _client(anthropic: bool):
    ep = _Endpoint()
    if anthropic:
        return SimpleNamespace(messages=ep), ep
    return SimpleNamespace(chat=SimpleNamespace(completions=ep)), ep


@pytest.fixture(autouse=True)
def _no_recording(monkeypatch):
    """Neuter the two sinks so the call stays hermetic and touches nothing under data/."""
    monkeypatch.setattr(P, "_record_llm_call", lambda **kw: None)
    from aughor.kernel import metering
    monkeypatch.setattr(metering, "record_llm", lambda *a, **k: None)


def _complete(backend: str, temperature: float = 0.1):
    client, ep = _client(anthropic=(backend == "anthropic"))
    P.LLMProvider._complete_on(client, backend, "m", "sys", "user", _Out, temperature)
    return ep.seen


def test_openai_compatible_backend_sends_the_pinned_temperature():
    token = P.set_run_temperature(0.0)
    try:
        assert _complete("openrouter", 0.1)["temperature"] == 0.0
    finally:
        P.reset_run_temperature(token)


def test_anthropic_omits_temperature_unless_a_run_pins_one():
    """This branch has never carried temperature and there is no Anthropic key here to
    verify the addition against — so ordinary traffic must stay byte-identical, and only a
    measured run opts in."""
    assert "temperature" not in _complete("anthropic", 0.1)

    token = P.set_run_temperature(0.0)
    try:
        assert _complete("anthropic", 0.1)["temperature"] == 0.0
    finally:
        P.reset_run_temperature(token)


def test_unpinned_openai_compatible_call_is_unchanged():
    assert _complete("openrouter", 0.1)["temperature"] == 0.1


# ── grid construction ─────────────────────────────────────────────────────────

def test_grid_holds_model_and_temperature_constant_across_cells():
    """Varying two axes at once produces a delta nobody can attribute."""
    cells = X.grid({"baseline": {}, "stubs": {FLAG: True}},
                   model="m", temperature=0.0)
    assert [c.label for c in cells] == ["baseline", "stubs"]
    assert {c.model for c in cells} == {"m"}
    assert {c.temperature for c in cells} == {0.0}
    assert cells[1].flags == {FLAG: True}


def test_cell_to_dict_round_trips_the_axes():
    c = Cell(label="v", model="m", temperature=0.2, flags={FLAG: True})
    assert c.to_dict() == {"label": "v", "model": "m", "temperature": 0.2,
                           "flags": {FLAG: True}}
