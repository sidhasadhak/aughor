"""Wave L4 — deterministic receipts for claims of EXACTNESS.

Most flags are graduated by sampling: run a suite twice, compare pass rates, and refuse the
delta if it does not clear a noise floor. The automation engine's claims are a different kind
and deserve a different kind of evidence: pass/fail on real rows with no sampling, no floor,
and no LLM budget — which is why the promotion gate's own carve-out (a threshold run with no
baseline, therefore no A/B, therefore no floor required) fits them exactly.

**History: the legacy path WAS the oracle.** Until flag endgame Wave 4 (2026-08-06) the
monitor scenarios computed ``expected`` by calling the actual legacy tick body
(``run_monitor_job``) and ``observed`` by driving the same monitor through
:func:`aughor.automations.engine.run_automation` — that comparison is the L4 receipt
(`65364174a172`, 9/9 stable ×3: alerts byte-for-byte, anti-flap and no-double-fire held)
that let ``automations.adopt_legacy`` turn ON and the legacy schedulers be DELETED. With
the legacy loop gone there is nothing left to compare against, so the legacy-vs-engine
scenarios went with it; what remains here are the engine-path claims those comparisons
covered — a breach alerts, a healthy metric stays quiet, the anti-flap debounce suppresses
a repeat — now against DECLARED expectations on the same real-DuckDB fixtures. The unit
tests (`tests/unit/test_automations_adopt.py`) still lock only the WIRING; these scenarios
are the only real-rows coverage of the monitor effect, which is why they outlive the
comparison that created them.

**Isolation.** Each scenario runs on a throwaway DuckDB warehouse registered as a real
connection under a ``_eqv-`` name and purged in a ``finally`` — monitors, alerts, automations,
runs and probe baselines all cascade on that connection id, so a scenario cannot leave state
behind for the next one to read (which would silently turn an equivalence test into a
history-dependent one). Live data is never the test subject.

**A scenario that cannot answer must FAIL, not skip.** The runner scores a case as passed when
no evaluator fired and no error was raised, so an evaluator that skips is an evaluator that
passes — the exact shape by which a measurement plane reports success for work it never did.
:class:`DeterministicEquivalenceEvaluator` therefore declares no ``requires`` (it can never be
skipped for missing inputs) and fails explicitly when the observation carries no comparison.
"""
from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from aughor.evals.evaluator import EvalCase, EvalObservation, EvalScore
from aughor.trust import BLOCK, Check

#: Suite name — looked up by name so creating the suite is idempotent across runs.
SUITE_NAME = "automations — deterministic equivalence (L4)"

# The suite once carried a FLAGS tuple naming what it was evidence for; every flag it
# backed is now hardwired (`automations.engine` and `automations.source_probes`
# 2026-08-02, `automations.adopt_legacy` turned ON and deleted 2026-08-06 with the
# legacy schedulers). The scenarios remain as standing receipts, not as a graduation.


@dataclass
class Comparison:
    """One scenario's verdict material: an oracle value and the value under the flag.

    ``expected`` is never a hand-written literal for the monitor scenarios — it is what the
    legacy loop actually produced on this run. ``oracle`` records which, so a reader can tell a
    measured expectation from a declared one without reading the scenario body.
    """

    scenario: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    oracle: str                       # "declared (A5)" | "declared (A3)"
    note: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def equivalent(self) -> bool:
        return self.expected == self.observed

    def to_meta(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "expected": self.expected,
            "observed": self.observed,
            "oracle": self.oracle,
            "note": self.note,
            "detail": self.detail,
        }


Scenario = Callable[[], Comparison]
SCENARIOS: dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def _register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return _register


# ── the throwaway warehouse ──────────────────────────────────────────────────────

@dataclass
class Warehouse:
    """A throwaway warehouse: its connection id, and a way to change the data under it."""

    conn_id: str
    path: Path

    def mutate(self, *statements: str) -> None:
        """Apply DML directly to the DuckDB file.

        Deliberately NOT through ``open_connection_for``: the app's handle refuses anything but
        SELECT ("Only SELECT statements are permitted"), which is correct — a warehouse
        connection is a read path. Routing fixture writes through it silently did nothing here
        until the discarded ``QueryResult.error`` was read, and four probe scenarios "passed
        the first tick and went quiet" for a reason that had nothing to do with the probe.

        The pooled handle is evicted first: the app holds the file open ``read_only=True``, and
        DuckDB refuses a second in-process connection to the same file under a different
        configuration. The next tick re-acquires through the pool as usual.
        """
        import duckdb

        if self.conn_id:
            from aughor.db.pool import evict_conn
            evict_conn(self.conn_id)

        con = duckdb.connect(str(self.path))
        try:
            for stmt in statements:
                con.execute(stmt)
        finally:
            con.close()


@contextmanager
def throwaway_warehouse(statements: Sequence[str], *, label: str) -> Iterator[Warehouse]:
    """A real DuckDB file registered as a real connection, seeded with ``statements``.

    Purged on exit through the SAME catalog-delete cascades the app uses when a connection is
    deleted, so the cleanup path is itself exercised rather than hand-rolled.
    """
    from aughor.automations.store import purge_connection as purge_automations
    from aughor.db.registry import add_connection, delete_connection
    from aughor.monitors.store import purge_connection as purge_monitors

    tmpdir = tempfile.mkdtemp(prefix="aughor-eqv-")
    warehouse = Warehouse(conn_id="", path=Path(tmpdir) / "warehouse.duckdb")
    warehouse.mutate(*statements)

    conn_id = add_connection(f"_eqv-{label}", "duckdb", str(warehouse.path))
    warehouse.conn_id = conn_id
    try:
        yield warehouse
    finally:
        for cleanup in (lambda: purge_monitors(conn_id),
                        lambda: purge_automations(conn_id),
                        lambda: delete_connection(conn_id),
                        lambda: shutil.rmtree(tmpdir, ignore_errors=True)):
            try:
                cleanup()
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "equivalence fixture cleanup is best-effort; the comparison is "
                              "already computed and the connection id is unique per scenario",
                         counter="evals.equivalence.cleanup")


# ── monitor fixtures ─────────────────────────────────────────────────────────────

#: SUM(revenue) = 1200 — below the 2000 critical threshold, so `threshold_cross` fires critical.
_SALES_BREACH = (
    "CREATE TABLE sales (id INTEGER, revenue DOUBLE)",
    "INSERT INTO sales VALUES (1, 500.0), (2, 700.0)",
)
#: SUM(revenue) = 9000 — above both thresholds, so the monitor stays quiet.
_SALES_HEALTHY = (
    "CREATE TABLE sales (id INTEGER, revenue DOUBLE)",
    "INSERT INTO sales VALUES (1, 4000.0), (2, 5000.0)",
)


def _revenue_monitor(conn_id: str, monitor_id: str):
    """The same monitor on both sides, differing only in id — the message embeds the NAME, so a
    byte-level message comparison stays meaningful across two throwaway connections."""
    from aughor.monitors.models import Monitor

    return Monitor(
        id=monitor_id, conn_id=conn_id, name="Revenue floor",
        custom_sql="SELECT SUM(revenue) FROM sales",
        alert_on="threshold_cross", threshold_direction="below",
        warning_threshold=5000.0, critical_threshold=2000.0,
        check_cron="* * * * *", grace_period_hours=4.0,
    )


def _alert_shape(alert) -> dict[str, Any]:
    """The parts of an alert A5 claims equivalence over. Id and timestamp are deliberately
    excluded — they are unique per alert by construction, so including them would make the
    comparison fail for reasons that carry no information."""
    return {
        "severity": alert.severity,
        "message": alert.message,
        "current_value": alert.current_value,
        "previous_value": alert.previous_value,
        "threshold": alert.threshold,
        "alert_on": alert.alert_on,
        "monitor_name": alert.monitor_name,
    }


def _alerts_for(conn_id: str) -> list:
    from aughor.monitors.store import get_alerts
    return list(get_alerts(conn_id=conn_id))


import contextlib


@contextlib.contextmanager
def _no_kernel_loop():
    """Force the no-loop condition (not assume it — inside the full test suite an
    earlier test may have captured a loop, the exact trap batch A's receipt hit)."""
    from aughor.kernel import jobs as jobs_mod
    saved = getattr(jobs_mod, "_main_loop", None)
    jobs_mod._main_loop = None
    try:
        yield
    finally:
        jobs_mod._main_loop = saved


def _run_engine(monitor) -> tuple[Any, list]:
    """One engine tick over the monitor read as a virtual automation. Returns
    ``(run, alerts)``. ``persist=False`` keeps the automation-run history out of it — the
    schedule condition then reports "first run" every tick, so the only thing that can suppress
    the second alert is the monitor's own anti-flap debounce, which is what the claim is about.
    The kernel-loop pin makes the effect run inline (submit declines), synchronous and
    readable the moment the call returns."""
    from aughor.automations.adopt import monitor_as_automation
    from aughor.automations.engine import run_automation
    from aughor.monitors.store import upsert_monitor

    upsert_monitor(monitor)
    with _no_kernel_loop():
        run = run_automation(monitor_as_automation(monitor), persist=False)
    return run, _alerts_for(monitor.conn_id)


# ── scenarios: the monitor effect on the engine path ─────────────────────────────

@scenario("monitor_alert_via_engine")
def _monitor_alert_via_engine() -> Comparison:
    """A breaching metric produces exactly one alert with the right verdict.

    ``expected`` is declared, not measured — the legacy loop that used to measure it was
    deleted (Wave 4); the declared values are the ones the L4 comparison receipt recorded
    byte-for-byte. SUM(revenue)=1200 sits below the 2000 critical floor, so the alert is
    critical and carries that reading."""
    with throwaway_warehouse(_SALES_BREACH, label="engine") as wh:
        run, alerts = _run_engine(_revenue_monitor(wh.conn_id, "eqv-engine"))

    return Comparison(
        scenario="monitor_alert_via_engine",
        oracle="declared (A5; was: legacy loop, receipt 65364174a172)",
        expected={"alert_count": 1, "severities": ["critical"],
                  "current_values": [1200.0]},
        observed={"alert_count": len(alerts),
                  "severities": sorted(a.severity for a in alerts),
                  "current_values": sorted(a.current_value for a in alerts)},
        note="one breaching tick through the engine = one critical alert with the real reading",
        detail={"automation_outcome": getattr(run, "outcome", ""),
                "effect_statuses": [o.status for o in getattr(run, "effects", [])],
                "alerts": [_alert_shape(a) for a in alerts]},
    )


@scenario("monitor_quiet_via_engine")
def _monitor_quiet_via_engine() -> Comparison:
    """A quiet check appends nothing — the receipt has to cover the silence too, or a loop
    that alerted on everything would still pass the firing case."""
    with throwaway_warehouse(_SALES_HEALTHY, label="engine-quiet") as wh:
        run, alerts = _run_engine(_revenue_monitor(wh.conn_id, "eqv-engine-quiet"))

    return Comparison(
        scenario="monitor_quiet_via_engine",
        oracle="declared (A5; was: legacy loop, receipt 65364174a172)",
        expected={"alert_count": 0},
        observed={"alert_count": len(alerts)},
        note="healthy metric: the engine may not append an alert",
        detail={"automation_outcome": getattr(run, "outcome", ""),
                "effect_messages": [o.message for o in getattr(run, "effects", [])]},
    )


@scenario("monitor_debounce_via_engine")
def _monitor_debounce_via_engine() -> Comparison:
    """Two consecutive breaching ticks leave ONE alert.

    This is the claim the wiring tests can only assert indirectly (they check that
    ``suppress=True`` was passed): the anti-flap grace window must actually suppress the
    repeat on the engine path, not merely be requested. With the engine as the only loop,
    this is also what "no double fire" means now — the structural guarantee replaced the
    fire-time skip the deleted `no_double_fire_under_adoption` scenario proved."""
    with throwaway_warehouse(_SALES_BREACH, label="engine-debounce") as wh:
        monitor = _revenue_monitor(wh.conn_id, "eqv-engine-debounce")
        _run_engine(monitor)
        _, alerts = _run_engine(monitor)

    return Comparison(
        scenario="monitor_debounce_via_engine",
        oracle="declared (A5; was: legacy loop, receipt 65364174a172)",
        expected={"alert_count": 1, "severities": ["critical"]},
        observed={"alert_count": len(alerts),
                  "severities": sorted(a.severity for a in alerts)},
        note="two breaching ticks: the grace window must suppress the repeat",
    )


# ── scenarios: automations.source_probes ─────────────────────────────────────────

_EVENTS_DDL = (
    "CREATE TABLE events (id INTEGER, updated_at TIMESTAMP)",
    "INSERT INTO events VALUES (1, TIMESTAMP '2026-01-01 00:00:00'), "
    "(2, TIMESTAMP '2026-01-02 00:00:00')",
)
#: No integer key and no timestamp column, so there is no change SIGNAL — but there is still a
#: row count, which A3 uses as the version on its own. See `no_signal_column_versions_by_count`.
_NO_SIGNAL_DDL = (
    "CREATE TABLE blobs (label VARCHAR)",
    "INSERT INTO blobs VALUES ('a'), ('b')",
)


def _probe_automation(conn_id: str, automation_id: str, *, kind: str, table: str):
    """A stored automation carrying one source condition and one inert effect.

    Stored (not virtual) on purpose: ``probe_state`` cascades on delete through a subquery over
    the automations table, so a virtual automation's baselines would outlive the fixture.
    """
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import upsert_automation

    return upsert_automation(Automation(
        id=automation_id, conn_id=conn_id, name=f"eqv {kind}",
        conditions=[Condition(kind=kind, config={"table": table})],
        effects=[Effect(kind="notify", config={"trigger_id": "eqv-inert"})],
        max_retries=0,
    ))


def _inert_dispatch(effect, automation):
    """Record the effect, do nothing. The probe scenarios are about the CONDITION; dispatching
    a real ``notify`` would fire an Action Hub trigger — an outward send with no bearing on
    whether the source version was computed correctly."""
    from aughor.automations.models import EffectOutcome
    return EffectOutcome(kind=effect.kind, target="inert", status="executed",
                         message="inert (equivalence harness)")


def _tick(automation) -> str:
    """One engine tick with source probes on; returns the outcome ("fired" / "not_fired")."""
    from aughor.automations.engine import run_automation

    run = run_automation(automation, persist=False, dispatch=_inert_dispatch)
    return run.outcome


@scenario("source_change_detects_insert")
def _source_change_detects_insert() -> Comparison:
    """First tick establishes the baseline and fires; an unchanged table then does not; an
    INSERT makes it fire again. The middle step is the one that matters — a probe that always
    fired would pass a test that only checked the insert."""
    with throwaway_warehouse(_EVENTS_DDL, label="probe-insert") as wh:
        a = _probe_automation(wh.conn_id, "eqv-probe-insert", kind="source_change", table="events")
        first = _tick(a)
        unchanged = _tick(a)
        wh.mutate("INSERT INTO events VALUES (3, TIMESTAMP '2026-01-03 00:00:00')")
        after_insert = _tick(a)

    return Comparison(
        scenario="source_change_detects_insert",
        oracle="declared (A3 source-version contract)",
        expected={"first": "fired", "unchanged": "not_fired", "after_insert": "fired"},
        observed={"first": first, "unchanged": unchanged, "after_insert": after_insert},
        note="baseline commits only on a fired tick, so an unchanged table must go quiet",
    )


@scenario("source_change_detects_delete")
def _source_change_detects_delete() -> Comparison:
    """A DELETE must register too. The version is compared by INEQUALITY rather than growth, so
    a shrinking table is a change — a monotonic comparison would read a delete as "unchanged"."""
    with throwaway_warehouse(_EVENTS_DDL, label="probe-delete") as wh:
        a = _probe_automation(wh.conn_id, "eqv-probe-delete", kind="source_change", table="events")
        first = _tick(a)
        wh.mutate("DELETE FROM events WHERE id = 2")
        after_delete = _tick(a)

    return Comparison(
        scenario="source_change_detects_delete",
        oracle="declared (A3 source-version contract)",
        expected={"first": "fired", "after_delete": "fired"},
        observed={"first": first, "after_delete": after_delete},
        note="deletes and backfills register because the comparison is inequality, not growth",
    )


@scenario("entity_appears_ignores_updates")
def _entity_appears_ignores_updates() -> Comparison:
    """``entity_appears`` restricts the signal to insertions: touching ``updated_at`` is not a
    new entity, inserting a row is. This is the distinction that separates the two condition
    kinds, and the only place the ``insertions_only`` path is observable."""
    with throwaway_warehouse(_EVENTS_DDL, label="probe-entity") as wh:
        a = _probe_automation(wh.conn_id, "eqv-probe-entity", kind="entity_appears", table="events")
        first = _tick(a)
        wh.mutate("UPDATE events SET updated_at = TIMESTAMP '2026-06-01 00:00:00'")
        after_update = _tick(a)
        wh.mutate("INSERT INTO events VALUES (9, TIMESTAMP '2026-01-04 00:00:00')")
        after_insert = _tick(a)

    return Comparison(
        scenario="entity_appears_ignores_updates",
        oracle="declared (A3 entity_appears semantics)",
        expected={"first": "fired", "after_update": "not_fired", "after_insert": "fired"},
        observed={"first": first, "after_update": after_update, "after_insert": after_insert},
        note="an updated_at touch is not a new entity",
    )


@scenario("unreadable_table_fails_open")
def _unreadable_table_fails_open() -> Comparison:
    """A table the probe cannot read fails OPEN to "changed", every tick.

    Noisy and diagnosable beats silently never-firing: the failure mode this rules out is a
    source automation that looks healthy and has in fact been unable to observe its table since
    the day it was created. The trigger is a probe that ERRORS (here: the table does not exist)
    — see `no_signal_column_versions_by_count` for the case that merely lacks a change signal,
    which A3 handles differently from how its flag description reads.
    """
    with throwaway_warehouse(_EVENTS_DDL, label="probe-open") as wh:
        a = _probe_automation(wh.conn_id, "eqv-probe-open", kind="source_change", table="absent")
        first = _tick(a)
        second = _tick(a)

    return Comparison(
        scenario="unreadable_table_fails_open",
        oracle="declared (A3 fail-open contract)",
        expected={"first": "fired", "second": "fired"},
        observed={"first": first, "second": second},
        note="an unprobeable table fails open to changed on every tick, never silently quiet",
    )


@scenario("no_signal_column_versions_by_count")
def _no_signal_column_versions_by_count() -> Comparison:
    """A table with no timestamp and no integer key is versioned by ``COUNT(*)`` ALONE.

    This scenario exists because the measurement disagreed with the documentation. The
    ``automations.source_probes`` flag description says "a table with no usable version column
    fails OPEN to 'changed'"; the implementation returns ``n=<count>`` for such a table, which is
    a usable version, so the tick goes QUIET when the count is stable. That is the better
    behaviour — a count still catches inserts and deletes — but it is not what the description
    promises, and the gap is not cosmetic: for a no-signal table, an UPDATE, or an insert and a
    delete in the same window, leaves the count unchanged and the automation silently never
    fires. Pinned here as the ACTUAL contract so a future reader gets the behaviour from a
    measurement rather than from the prose.
    """
    with throwaway_warehouse(_NO_SIGNAL_DDL, label="probe-count") as wh:
        a = _probe_automation(wh.conn_id, "eqv-probe-count", kind="source_change", table="blobs")
        first = _tick(a)
        unchanged = _tick(a)
        wh.mutate("INSERT INTO blobs VALUES ('c')")
        after_insert = _tick(a)
        wh.mutate("UPDATE blobs SET label = 'zzz' WHERE label = 'a'")
        after_update = _tick(a)

    return Comparison(
        scenario="no_signal_column_versions_by_count",
        oracle="declared (measured contract, not the flag description)",
        expected={"first": "fired", "unchanged": "not_fired",
                  "after_insert": "fired", "after_update": "not_fired"},
        observed={"first": first, "unchanged": unchanged,
                  "after_insert": after_insert, "after_update": after_update},
        note="count-only versioning: inserts/deletes register, in-place updates cannot",
    )


# ── the evaluator ────────────────────────────────────────────────────────────────

class DeterministicEquivalenceEvaluator:
    """Pass iff ``observed`` equals ``expected`` exactly.

    ``requires=()`` deliberately: the runner skips an evaluator whose needs the case cannot
    supply, and a skipped evaluator scores as passed. For a suite whose entire purpose is to
    certify a flag, "we could not check" must never round to "it checks out" — so this one can
    never be skipped for missing inputs, and an observation carrying no comparison is a FAILURE
    rather than a skip.
    """

    name = "deterministic_equivalence"
    severity = BLOCK
    requires: tuple[str, ...] = ()
    deterministic = True

    def evaluate(self, case: EvalCase, obs: EvalObservation) -> EvalScore:
        meta = obs.meta or {}
        if "expected" not in meta or "observed" not in meta:
            return EvalScore(
                evaluator=self.name, passed=False, value=0.0,
                rationale="the scenario produced no comparison — nothing was verified",
                checks=(Check(name=self.name, ok=False, severity=BLOCK,
                              reason="no expected/observed pair on the observation"),))

        expected, observed = meta["expected"], meta["observed"]
        ok = expected == observed
        reason = (f"{meta.get('scenario', case.id)}: observed matches the oracle "
                  f"({meta.get('oracle', 'unknown')})" if ok else
                  f"{meta.get('scenario', case.id)}: expected {expected!r}, observed {observed!r}")
        return EvalScore(
            evaluator=self.name, passed=ok, value=1.0 if ok else 0.0, rationale=reason,
            checks=(Check(name=self.name, ok=ok, severity=BLOCK, reason=reason,
                          detail={"oracle": meta.get("oracle", ""),
                                  "note": meta.get("note", "")}),))


# ── the target ───────────────────────────────────────────────────────────────────

def equivalence_target() -> Callable[[EvalCase], EvalObservation]:
    """A suite target that runs the scenario named in ``case.expected["scenario"]``.

    An unknown scenario is an ERROR, not an empty pass: a suite that silently skipped a case it
    could not resolve would report a pass rate over fewer cases than it claims to cover.
    """
    def target(case: EvalCase) -> EvalObservation:
        name = str((case.expected or {}).get("scenario") or case.id)
        fn = SCENARIOS.get(name)
        if fn is None:
            return EvalObservation(error=f"unknown equivalence scenario: {name!r}")
        comparison = fn()
        return EvalObservation(narrative=comparison.note, meta=comparison.to_meta())

    return target


# ── suite management ─────────────────────────────────────────────────────────────

def ensure_suite() -> str:
    """Create the suite (idempotent by name) with one case per scenario, and return its id.

    Idempotent by NAME rather than by a generated id, because the alternative — a fresh suite
    per invocation — would give each run its own history and make the graduation route's
    baseline derivation blind to every earlier run.
    """
    from aughor.evals import store

    existing = next((s for s in store.list_suites(200) if s["name"] == SUITE_NAME), None)
    if existing is None:
        existing = store.create_suite(
            SUITE_NAME,
            description=("Wave L4 — deterministic pass/fail receipts on real rows. Originally "
                         "legacy-loop-vs-engine comparisons; since flag endgame Wave 4 "
                         "(2026-08-06, legacy schedulers deleted on receipt 65364174a172) the "
                         "cases assert the engine path against declared expectations on a real "
                         "throwaway DuckDB warehouse; nothing is patched."),
            target="equivalence")
    suite_id = existing["id"]

    have = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    missing = [n for n in SCENARIOS if n not in have]
    if missing:
        store.add_cases(suite_id, [
            {"question": f"Does {n} hold?", "expected": {"scenario": n},
             "tags": ["l4", "equivalence"]}
            for n in missing
        ])
    return suite_id


def run_suite(*, iterations: int = 1, persist: bool = True):
    """Run every scenario and return the :class:`~aughor.evals.runner.RunSummary`."""
    from aughor.evals import runner
    from aughor.evals.registry import get_evaluator, register_evaluator

    if get_evaluator(DeterministicEquivalenceEvaluator.name) is None:
        register_evaluator(DeterministicEquivalenceEvaluator())

    suite_id = ensure_suite()
    return runner.run_suite(
        suite_id, equivalence_target(), iterations=iterations, persist=persist,
        evaluators=[DeterministicEquivalenceEvaluator.name])
