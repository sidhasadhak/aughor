"""Wave R5 — declared parallel-safety.

The property Aughor had was real but accidental: every fan-out happens to dispatch reads,
and the SQL gate proves reads safe. Nothing *declared* it, so nothing could notice when
something unsafe was fanned out — and the K-plane, the growing surface, is invisible to
the SQL gate because no SQL is involved. Two refunds or a twice-delivered webhook is not a
crash; it is a silent wrong outcome.

The design decision under test is WHERE the check lives. On the fan-out side it is a
helper the fifth fan-out forgets (the guard battery's five re-assembled sites; R4's
fifteen hand-built error frames). On the dangerous side it is structural: a concurrent
region declares itself, and the executor asks. So the tests care most about two things —
that the refusal fires from a fan-out the checker has never heard of, and that everything
outside a fan-out is byte-identical.
"""
from __future__ import annotations

import pytest

from aughor.kernel import parallel_safety as PS
from aughor.kernel.concurrency import ContextThreadPoolExecutor
from aughor.ontology.models import KineticAction


def _action(**kw) -> KineticAction:
    base = dict(id="refund_order", kind="side_effect", display_name="Refund")
    base.update(kw)
    return KineticAction(**base)


@pytest.fixture(autouse=True)
def _clear_region():
    """The flag is a contextvar and must not leak between tests."""
    PS._fanout.set("")
    yield
    PS._fanout.set("")


# ── the declared property ─────────────────────────────────────────────────────

def test_an_action_defaults_to_not_parallel_safe():
    """Fail-safe, for the same reason `risk` defaults to high: the failure mode is two
    refunds with no error anywhere."""
    assert _action().parallel_safe is False
    assert PS.is_parallel_safe(_action()) is False


def test_an_action_can_declare_itself_safe():
    assert PS.is_parallel_safe(_action(parallel_safe=True)) is True


def test_undeclared_and_declared_false_are_distinguishable():
    """'Nobody said' is a gap worth logging; 'declared unsafe' is a decision that was
    made. Both refuse, but only one is a bug."""
    assert PS.declared_parallel_safe(object()) is None
    assert PS.declared_parallel_safe(_action()) is False
    assert PS.declared_parallel_safe(_action(parallel_safe=True)) is True


def test_a_non_bool_declaration_is_not_a_declaration():
    """A truthy string must not read as a declaration — that is how a typo becomes an
    authorization."""
    class Sloppy:
        parallel_safe = "yes"

    assert PS.declared_parallel_safe(Sloppy()) is None
    assert PS.is_parallel_safe(Sloppy()) is False


# ── the checkpoint ────────────────────────────────────────────────────────────

def test_outside_a_fanout_nothing_is_refused():
    """Byte-identical for every existing serial path — this is what makes the wave safe
    to land with the K-plane already in production."""
    assert not PS.in_fanout()
    PS.assert_dispatchable(_action())          # must not raise


def test_inside_a_fanout_an_undeclared_action_is_refused():
    with PS.fanout("ada.phase_waves"):
        with pytest.raises(PS.ParallelSafetyError) as caught:
            PS.assert_dispatchable(_action(), name="kinetic.refund_order")
    msg = str(caught.value)
    assert "kinetic.refund_order" in msg
    assert "ada.phase_waves" in msg              # names the region it came from
    assert "serially" in msg                     # says what to do


def test_inside_a_fanout_a_declared_safe_action_proceeds():
    with PS.fanout("explore.subq_wave"):
        PS.assert_dispatchable(_action(parallel_safe=True))   # must not raise


def test_the_region_is_cleared_on_the_way_out():
    with PS.fanout("x"):
        assert PS.current_fanout() == "x"
    assert PS.current_fanout() == "" and not PS.in_fanout()


def test_the_region_is_cleared_even_when_the_body_raises():
    with pytest.raises(ValueError):
        with PS.fanout("x"):
            raise ValueError("boom")
    assert not PS.in_fanout()


def test_nested_regions_report_the_innermost():
    with PS.fanout("outer"):
        with PS.fanout("inner"):
            assert PS.current_fanout() == "inner"
        assert PS.current_fanout() == "outer"


def test_the_flag_propagates_into_worker_threads():
    """The whole design depends on this: ContextThreadPoolExecutor copies context into its
    workers, which is why the flag is a contextvar and not a thread-local. Without this
    the checkpoint would never fire where it matters — inside the workers."""
    seen: list[str] = []
    with PS.fanout("ada.phase_queries"):
        with ContextThreadPoolExecutor(max_workers=2) as pool:
            for f in [pool.submit(PS.current_fanout) for _ in range(4)]:
                seen.append(f.result())
    assert seen == ["ada.phase_queries"] * 4


def test_a_worker_refuses_an_undeclared_action():
    """The end the design exists for: the refusal happens on the worker thread, where the
    dispatch would actually have happened."""
    def _dispatch():
        try:
            PS.assert_dispatchable(_action(), name="kinetic.refund_order")
            return "dispatched"
        except PS.ParallelSafetyError:
            return "refused"

    with PS.fanout("explore.subq_wave"):
        with ContextThreadPoolExecutor(max_workers=2) as pool:
            results = [f.result() for f in [pool.submit(_dispatch) for _ in range(3)]]
    assert results == ["refused"] * 3


def test_fanout_region_never_breaks_the_work_it_wraps(monkeypatch):
    """A safety-LABELLING helper that can raise would take down real work in order to
    protect it. Any failure degrades to 'unlabelled', which is the pre-R5 state — not a
    worse one."""
    class _Hostile:
        def set(self, *a):
            raise RuntimeError("boom")

        def get(self):
            return ""

    monkeypatch.setattr(PS, "_fanout", _Hostile())
    ran = []
    with PS.fanout_region("x"):
        ran.append(True)
    assert ran == [True]


# ── the executor: the ONE call site ───────────────────────────────────────────

def test_the_executor_refuses_rather_than_dispatching(monkeypatch):
    """The refusal must land BEFORE step 4 — the only step that can cause a side effect."""
    from aughor.kinetic.executor import execute_kinetic_action

    dispatched = []
    with PS.fanout("ada.phase_waves"):
        out = execute_kinetic_action(_action(risk="read_only"), {},
                                     dispatch=lambda *a, **k: dispatched.append(1))
    assert out.status == "parallel_refused" and out.ok is False
    assert dispatched == [], "the side effect must never have run"
    assert "refund_order" in out.message


def test_the_executor_is_untouched_outside_a_fanout():
    from aughor.kinetic.executor import execute_kinetic_action

    dispatched = []
    out = execute_kinetic_action(_action(risk="read_only"), {},
                                 dispatch=lambda *a, **k: (dispatched.append(1), {"ok": True})[1])
    assert out.status == "executed" and dispatched == [1]


def test_a_declared_safe_action_runs_inside_a_fanout():
    from aughor.kinetic.executor import execute_kinetic_action

    dispatched = []
    with PS.fanout("explore.subq_wave"):
        out = execute_kinetic_action(_action(risk="read_only", parallel_safe=True), {},
                                     dispatch=lambda *a, **k: (dispatched.append(1), {"ok": True})[1])
    assert out.status == "executed" and dispatched == [1]


# ── the read side ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql,safe", [
    ("SELECT a FROM t", True),
    ("SELECT a FROM t UNION SELECT b FROM u", True),          # set ops are reads
    ("WITH x AS (SELECT 1) SELECT * FROM x", True),
    ("DELETE FROM t", False),
    ("UPDATE t SET a = 1", False),
    ("DROP TABLE t", False),
    ("not sql at all (((", False),                            # unparseable ⇒ not safe
])
def test_sql_parallel_safety_follows_the_read_only_gate(sql, safe):
    """One opinion, not two: this reuses the platform's own read-only check. A divergence
    between 'the gate allows it' and 'we call it parallel-safe' would be worse than having
    no check at all. Lives in tools.executor, not the kernel — the kernel must not import
    the tools layer, and the platform→agent boundary test enforces that."""
    from aughor.tools.executor import sql_is_parallel_safe

    assert sql_is_parallel_safe(sql) is safe


def test_check_sql_fanout_reports_the_offenders():
    from aughor.tools.executor import check_sql_fanout

    bad = check_sql_fanout(["SELECT 1", "DELETE FROM t", "SELECT 2"], where="test")
    assert bad == ["DELETE FROM t"]
    assert check_sql_fanout(["SELECT 1", "SELECT 2"], where="test") == []


# ── every fan-out declares itself ─────────────────────────────────────────────

def test_no_fanout_is_left_undeclared():
    """The ratchet. A new ContextThreadPoolExecutor that does not declare its region is
    invisible to the checkpoint — and invisible is exactly the failure mode this wave
    exists to remove."""
    import pathlib
    import re

    undeclared: list[str] = []
    for path in pathlib.Path("aughor").rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if "with ContextThreadPoolExecutor" in line and "_fanout_region" not in line:
                undeclared.append(f"{path}:{i}")
    assert not undeclared, (
        "fan-out site(s) without a declared region — wrap with "
        f"`_fanout_region(\"<label>\"), `: {undeclared}")
    # …and the ones that exist really are wired.
    declared = sum(1 for p in pathlib.Path("aughor").rglob("*.py")
                   for line in p.read_text().splitlines()
                   if re.search(r'with _fanout_region\("[^"]+"\), ContextThreadPoolExecutor', line))
    assert declared >= 6, f"expected every known fan-out declared, found {declared}"
