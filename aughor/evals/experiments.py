"""Run-scoped experiment configuration — the override plane Wave E4 measures through.

A grid experiment asks "does variant X beat the baseline?" and answers it by running the
same suite under several configurations. Until now nothing in the process could express a
*per-run* configuration: the model came from a contextvar (``set_run_model``, the one piece
that already worked), but flags resolved through the ledger and the environment, and both
are process-global. Two cells of one grid could not disagree.

This module is the missing half. A :class:`Cell` names a configuration; :func:`applied`
puts it in force for a block; and — the part that matters more than either — it yields the
**resolved** configuration read back through the very resolvers the product calls, not the
one the caller asked for.

That read-back is the whole point. ``verify-features-actually-ran`` is the standing lesson
here: an override that silently no-ops looks *exactly* like a variant that did not help,
and the second reading is far more flattering to the harness than the first. So the cost of
an unnoticed no-op is not a missing measurement, it is a confident wrong one. Three defences,
cheapest first:

1. :func:`~aughor.kernel.flags.flag_overrides` raises on an unregistered flag name, so a
   typo in a dotted name cannot quietly do nothing.
2. :func:`applied` yields ``effective`` alongside ``requested`` and marks any disagreement,
   so a report can show the run refused a setting rather than omit it.
3. :func:`assert_measurable` refuses to start when the environment cannot attribute a
   result at all.

⚠️ **Graph-topology flags are read at COMPILE time** — ``agent/graph.py`` lines 128/140/229
sit inside ``_compile()``, which runs during ``build_graph_generic``. The ``applied`` block
must therefore wrap the *graph construction*, not merely the graph's invocation. Wrapping
only the run leaves topology at whatever the process-global layers said while every other
axis moves, which produces the worst possible artifact: a cell that is half-overridden and
reports as fully overridden. ``tests/unit/test_experiments.py`` pins this as an executable
fact rather than a comment.
"""
from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Optional

from aughor.kernel.errors import tolerate
from aughor.kernel.flags import active_flag_overrides, flag_enabled, flag_overrides

# The roles whose bindings a report cites. Both are recorded because a grid that varies only
# the coder still needs the narrator on record — a synthesis change would otherwise be
# invisible in the config and get attributed to the axis that did move.
_RECORDED_ROLES = ("coder", "narrator")


class MeasurementIntegrityError(RuntimeError):
    """The environment cannot produce an attributable measurement.

    Raised *before* any request is spent, because the failure this guards against is not a
    crash — it is a plausible number that belongs to a configuration nobody chose.
    """


@dataclass(frozen=True)
class Cell:
    """One configuration in a grid: what to hold different, and what to call it.

    ``label`` is required and is what a report shows; an unlabelled cell in a five-way grid
    is a row of numbers nobody can act on. Every other axis is optional, and an all-default
    cell is the legitimate way to express "the baseline" — it still records what the
    baseline resolved to, which is what makes two runs a week apart comparable at all.
    """

    label: str
    model: Optional[str] = None
    temperature: Optional[float] = None
    flags: Mapping[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "model": self.model,
            "temperature": self.temperature,
            "flags": dict(self.flags),
        }


def fallback_disabled() -> bool:
    """Whether the provider's failover chain is off for this process.

    ``AUGHOR_FALLBACK_DISABLED`` is read the same way ``provider._flag`` reads it, so this
    cannot drift from the behaviour it describes.
    """
    return os.environ.get("AUGHOR_FALLBACK_DISABLED", "").strip().lower() in (
        "1", "true", "yes", "on")


def assert_measurable() -> None:
    """Refuse to measure while the failover chain can swap the model mid-run.

    The chain is a *reliability* feature and a *measurement* hazard: on a quota or transport
    failure it silently completes the run on a different model, and the resulting number is
    then a blend of two bindings that the report will attribute to one. `run_golden.py` and
    `spider2.py` both already set ``AUGHOR_FALLBACK_DISABLED=1`` before measuring — this
    makes that convention a precondition, because a convention only protects the runs whose
    author remembered it.
    """
    if not fallback_disabled():
        raise MeasurementIntegrityError(
            "refusing to measure with the provider fallback chain live: a quota or transport "
            "failure would silently finish the run on a different model and the result would "
            "be attributed to the binding that started it. Set AUGHOR_FALLBACK_DISABLED=1 "
            "for measured runs (evals/run_golden.py and evals/spider2.py already do)."
        )


def resolved_config(*, roles: tuple[str, ...] = _RECORDED_ROLES) -> dict:
    """What the current context will ACTUALLY run under.

    Read back through the product's own resolvers — ``resolve_binding`` for the bindings and
    ``flag_enabled`` for the flags — so this reports behaviour rather than intent. Every
    lookup is tolerated individually: a config that cannot be read is a degraded report, but
    a config that *raises* would abort a run whose measurement was otherwise fine.
    """
    cfg: dict[str, Any] = {}
    try:
        from aughor.llm.provider import current_run_temperature, resolve_binding
        cfg["backend"] = resolve_binding("coder")[0]
        cfg["models"] = {role: resolve_binding(role)[1] for role in roles}
        cfg["temperature"] = current_run_temperature()
    except Exception as exc:
        cfg["backend"] = "unknown"
        tolerate(exc, "experiment config: model binding unavailable; recorded as unknown",
                 counter="evals.experiment.config.model")
    overrides = active_flag_overrides()
    cfg["flag_overrides"] = overrides
    try:
        # Only the overridden names: the effective value of every registered flag would bury
        # the axis that moved under two hundred that did not.
        cfg["flags"] = {name: flag_enabled(name) for name in overrides}
    except Exception as exc:
        tolerate(exc, "experiment config: flag read-back unavailable",
                 counter="evals.experiment.config.flags")
    cfg["fallback_disabled"] = fallback_disabled()
    return cfg


def data_version_of(conn: Any, tables: Optional[list[str]] = None) -> Optional[str]:
    """A token proving the fixture did not move between two runs, or ``None``.

    Two cells are only comparable if they saw the same data. Recording this makes "the
    fixture changed underneath us" a visible fact in the report instead of an unexplained
    delta someone attributes to the variant.
    """
    try:
        from aughor.db.snapshot import data_version
        return data_version(conn, tables or [])
    except Exception as exc:
        tolerate(exc, "experiment config: data version unprobeable",
                 counter="evals.experiment.config.data_version")
        return None


@contextlib.contextmanager
def applied(cell: Cell, *, require_measurable: bool = True) -> Iterator[dict]:
    """Put ``cell`` in force for the block; yield the resolved configuration.

    The yielded dict carries ``requested`` (what the cell asked for) beside ``effective``
    (what the resolvers now report) and a ``discrepancies`` list naming any flag where the
    two disagree. That list should always be empty — it exists so that when it is not, the
    run says so instead of quietly measuring something else.

    Set ``require_measurable=False`` only for a dry run that spends no requests; a run that
    calls a model and skips the check is exactly the run whose number cannot be trusted.

    ⚠️ Build the graph INSIDE this block — see the module docstring.
    """
    if require_measurable:
        assert_measurable()

    from aughor.llm.provider import (
        reset_run_model, reset_run_temperature, set_run_model, set_run_temperature,
    )

    model_token = set_run_model(cell.model) if cell.model else None
    temp_token = (set_run_temperature(cell.temperature)
                  if cell.temperature is not None else None)
    try:
        with flag_overrides(dict(cell.flags)):
            effective = resolved_config()
            discrepancies = [
                {"flag": name, "requested": bool(want),
                 "effective": bool(effective.get("flags", {}).get(name))}
                for name, want in cell.flags.items()
                if bool(effective.get("flags", {}).get(name)) != bool(want)
            ]
            yield {
                "label": cell.label,
                "requested": cell.to_dict(),
                "effective": effective,
                "discrepancies": discrepancies,
            }
    finally:
        # Reset in reverse order of setting, and unconditionally: a cell that raised must not
        # leak its model pin into the next cell of the grid, which would silently make the
        # baseline a copy of the variant.
        if temp_token is not None:
            reset_run_temperature(temp_token)
        if model_token is not None:
            reset_run_model(model_token)


def grid(labels_and_flags: Mapping[str, Mapping[str, bool]], *,
         model: Optional[str] = None,
         temperature: Optional[float] = None) -> list[Cell]:
    """Build a one-axis grid: a baseline plus one cell per named variant.

    ``model`` and ``temperature`` are held CONSTANT across the cells on purpose — varying
    two axes at once is how a grid produces a delta nobody can attribute. A model bakeoff is
    the same call with an empty flag map per cell and the model varied instead.
    """
    return [Cell(label=label, model=model, temperature=temperature, flags=dict(flags))
            for label, flags in labels_and_flags.items()]
