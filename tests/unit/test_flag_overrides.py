"""Run-scoped flag overrides (Wave E4) — the third resolution layer and its traps.

`flag_enabled` resolved through the ledger then the environment, both process-global, so two
cells of one grid could not disagree inside a single process. E4 adds a contextvar consulted
ahead of both.

Three properties are worth more than the happy path here, and each has a matching test below:

* **Every reader agrees.** Adding a layer to `flag_enabled` while `flag_state` and
  `list_flags` keep their own copy of the precedence is the shape that has bitten this repo
  repeatedly (the ~5-site guard battery; R4's 15 hand-assembled error frames). A receipt that
  reported the operator's setting while the run used the override would attribute a
  measurement to the wrong configuration.
* **A typo is loud.** An override on an unregistered name would silently do nothing, and
  "the override did nothing" reads downstream as "the variant did not help".
* **Topology is decided at COMPILE time.** `agent/graph.py` reads three flags inside
  `_compile()`. Wrapping only the run leaves those at the process-global value while every
  other axis moves — a half-overridden cell that reports as fully overridden.
"""
from __future__ import annotations

import pytest

from aughor.kernel.concurrency import ContextThreadPoolExecutor
from aughor.kernel.flags import (
    UnknownFlagError,
    active_flag_overrides,
    clear_flag,
    flag_enabled,
    flag_overrides,
    flag_state,
    list_flags,
    set_flag,
)

FLAG = "deep_analysis.evidence_stubs"      # registered, defaults off, and E4's own sixth customer
# `ai_sql` deliberately: the nested-release assertion below expects OTHER's AMBIENT value
# to be off, and ai_sql is intentionally-off forever (per-row LLM cost) so this test never
# needs re-pointing when a flag graduates (its previous exemplar, ada.evidence_dedup,
# graduated default-ON in flag strategy batch A).
OTHER = "ai_sql"


@pytest.fixture(autouse=True)
def _no_override_leak():
    yield
    for name in (FLAG, OTHER):
        clear_flag(name)


def test_override_wins_inside_the_block_and_is_gone_after():
    assert flag_enabled(FLAG) is False
    with flag_overrides({FLAG: True}):
        assert flag_enabled(FLAG) is True
    assert flag_enabled(FLAG) is False


def test_override_beats_the_ledger_override():
    """The ledger layer is the operator's setting; the run's is a measurement decision."""
    set_flag(FLAG, False)
    assert flag_enabled(FLAG) is False
    with flag_overrides({FLAG: True}):
        assert flag_enabled(FLAG) is True
    assert flag_enabled(FLAG) is False


def test_nested_blocks_merge_so_one_axis_can_vary_inside_another():
    with flag_overrides({FLAG: True}):
        with flag_overrides({OTHER: True}):
            assert flag_enabled(FLAG) is True
            assert flag_enabled(OTHER) is True
            assert active_flag_overrides() == {FLAG: True, OTHER: True}
        assert flag_enabled(OTHER) is False      # inner block released
        assert flag_enabled(FLAG) is True        # outer block still in force


def test_unknown_flag_name_raises_rather_than_no_opping():
    with pytest.raises(UnknownFlagError) as exc:
        with flag_overrides({"deep_analysis.evidence_stub": True}):   # missing trailing 's'
            pass
    assert "deep_analysis.evidence_stub" in str(exc.value)


def test_unknown_name_is_rejected_before_any_flag_is_applied():
    """A partially-applied override would be worse than a rejected one."""
    with pytest.raises(UnknownFlagError):
        with flag_overrides({FLAG: True, "nope.not_a_flag": True}):
            pass
    assert flag_enabled(FLAG) is False


def test_every_reader_agrees_with_flag_enabled():
    """flag_enabled, flag_state and list_flags must not each keep their own precedence."""
    with flag_overrides({FLAG: True}):
        assert flag_enabled(FLAG) is True
        assert flag_state(FLAG) == "on"
        entry = list_flags()[FLAG]
        assert entry["value"] is True
        assert entry["source"] == "run"


def test_list_flags_marks_the_source_as_run_not_runtime():
    """A run override must not be mistaken for an operator toggle in a receipt."""
    set_flag(OTHER, True)
    with flag_overrides({FLAG: True}):
        flags = list_flags()
        assert flags[FLAG]["source"] == "run"
        assert flags[OTHER]["source"] == "runtime"


def test_override_reaches_worker_threads():
    """ContextThreadPoolExecutor copies the context in — the same mechanism the model pin,
    metering and the R5 parallel-safety refusal all ride on."""
    with flag_overrides({FLAG: True}):
        with ContextThreadPoolExecutor(max_workers=3) as pool:
            seen = list(pool.map(lambda _: flag_enabled(FLAG), range(3)))
    assert seen == [True, True, True]


def test_a_plain_thread_pool_does_not_inherit_the_override():
    """Pinning the boundary: the propagation is a property of ContextThreadPoolExecutor, not
    of contextvars generally. A fan-out that used a bare pool would measure the baseline
    while reporting the variant."""
    from concurrent.futures import ThreadPoolExecutor

    with flag_overrides({FLAG: True}):
        with ThreadPoolExecutor(max_workers=2) as pool:
            seen = list(pool.map(lambda _: flag_enabled(FLAG), range(2)))
    assert seen == [False, False]


def test_exception_inside_the_block_still_releases_the_override():
    with pytest.raises(ValueError):
        with flag_overrides({FLAG: True}):
            raise ValueError("boom")
    assert flag_enabled(FLAG) is False
    assert active_flag_overrides() == {}


def test_graph_topology_reads_the_override_only_at_compile_time():
    """The trap, as an executable fact.

    `_ada_parallel_lenses_enabled()` is called from inside `_compile()`. Evaluating it
    within the block sees the override; a graph compiled OUTSIDE the block has already
    baked in the process-global answer and no later block can change it. This is why
    `experiments.applied` must wrap `build_graph_generic`, not just the run.
    """
    from aughor.agent import graph as g

    assert g._ada_parallel_lenses_enabled() is False
    with flag_overrides({"deep_analysis.parallel_lenses": True}):
        assert g._ada_parallel_lenses_enabled() is True     # read INSIDE ⇒ override applies
    assert g._ada_parallel_lenses_enabled() is False

    # A value captured before the block is fixed — exactly what a pre-built graph holds.
    captured = g._ada_parallel_lenses_enabled()
    with flag_overrides({"deep_analysis.parallel_lenses": True}):
        assert captured is False

    clear_flag("deep_analysis.parallel_lenses")
