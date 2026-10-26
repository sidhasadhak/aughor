"""Arc MC, MC-0 — the gates a metric's FIGURES pass before it is approved (ROADMAP §3.62).

The audit checks the SQL; nothing checked the figure. LuxExperience carried two approved metrics that read 1 in every
period — `return_rate` and `cart_to_order_conversion_rate`, retail's only two recipes, their roles bound to the wrong
tables (`order_item` → `returns`, whose every row has a return date; `cart` → `events`, an id bound to a date) — and the
return-rate recipe declared a sane range of 0–30% beside a figure of 100%. The user's call (2026-10-26, §6 item 55(d)):
**refuse at approval**, as the window check does. Three gates, each said in words a person approving can act on:

- **It moves.** Measured over the last six complete months of its own data — anchored at the day its data ends, never
  the server's today, so a source that stopped in 2025 is still read — a metric that reads one value in every month with
  figures is refused with that value.
- **It sits in its sane range.** A recipe's declared band (`metrics/*.yaml`, with the basis and the sources that
  published it) is enforced on the metric made from it: the median of those months outside it is refused, with the band
  and its basis. A share written as a percent is read at both scales.
- **Its roles are bound to the right things.** A recipe's role attributes are checked against the columns they are bound
  to: by type (an id is not a date, money is numeric), and a column the formula tests for emptiness must have empty rows
  — a return date that is never empty makes every line a return.

A gate that cannot read its figures says so and does not refuse: not known is said, never taken for a pass or a fail.
Every verdict is ``{"ok": True | False | None, "why": str}``.
"""
from __future__ import annotations

import logging
import re
import statistics
import time
from datetime import timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: The complete months a metric's figures are read over, newest last.
MONTHS = 6
#: The fewest months with a figure before "it reads the same in every one" is a finding.
MIN_MONTHS = 3
FLAG = "metrics.figure_gates"

REFUSALS = {"moves": "reads_constant", "sane_range": "outside_sane_range", "binding": "binding_mistyped"}

_UNREAD = {"ok": None, "why": ""}


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _fmt(v: float) -> str:
    return f"{v:.4g}" if abs(v) < 1e6 else f"{v:,.0f}"


# ── the figures ─────────────────────────────────────────────────────────────────────────────────────────────────────

def recent_figures(m: Any, run_sql: Callable[[str], tuple], dialect: str,
                   months: int = MONTHS) -> tuple[Optional[list], list[str], str]:
    """The metric's figure in each of the last ``months`` complete months its own data covers: ``(figures, month
    labels, why)`` — ``figures`` None, with why, when they could not be read."""
    from aughor.briefing.ranges import data_span, read_value
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metric_twins import complete_months

    if not mt.declared(m):
        return None, [], "its dates are not set"
    _first, last = data_span(m, run_sql, dialect)
    if last is None:
        return None, [], "the last day of its data could not be read"
    windows = complete_months(last + timedelta(days=1), months)
    rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect)
    if why:
        return None, [], why
    got = {r["window"]: r for r in rows}
    return ([read_value(got.get(w.label)) for w in windows],
            [w.start.strftime("%b %Y") for w in windows], "")


def moves(figures: Optional[list], why: str = "") -> dict:
    """Whether the figures move: False when every month with a figure reads the same value."""
    if figures is None:
        return {"ok": None, "why": f"its figures could not be read: {why}" if why else "its figures could not be read"}
    have = [v for v in figures if v is not None]
    if len(have) < MIN_MONTHS:
        return {"ok": None, "why": f"only {len(have)} of the last {len(figures)} months have a figure — too few to say "
                                   "whether it moves"}
    if all(_same(v, have[0]) for v in have):
        return {"ok": False, "why": (f"it reads {_fmt(have[0])} in every one of the last {len(have)} months with "
                                     "figures — a figure that never moves is measuring its own population, not the "
                                     "business (a denominator that is also the numerator, or a date read as a flag)")}
    return {"ok": True, "why": ""}


def sane(figures: Optional[list], band: Optional[dict], label: str = "its recipe") -> dict:
    """Whether the figures' median sits in a declared band (``{"min", "max", "basis"}``) — a fraction's band read as a
    percent when the figures are written as one."""
    if not band or (band.get("min") is None and band.get("max") is None):
        return {"ok": None, "why": "no sane range is declared for it"}
    have = [v for v in (figures or []) if v is not None]
    if not have:
        return {"ok": None, "why": "its figures could not be read"}
    median = statistics.median(have)
    lo, hi = band.get("min"), band.get("max")

    def inside(v: float) -> bool:
        return (lo is None or v >= float(lo) - 1e-12) and (hi is None or v <= float(hi) + 1e-12)

    # A share written as a percent reads above 1 where its band is a fraction; a figure of 1 or less is read as it is,
    # or a return rate of 100% would pass as 1%.
    read = median / 100.0 if (median > 1.0 and hi is not None and float(hi) <= 1.0) else median
    if inside(read):
        return {"ok": True, "why": ""}
    span = f"{lo}–{hi}" if lo is not None and hi is not None else (f"at least {lo}" if lo is not None else f"at most {hi}")
    basis = " ".join(str(band.get("basis") or "").split())
    return {"ok": False, "why": (f"its median over the last {len(have)} months, {_fmt(median)}, is outside {label}'s "
                                 f"sane range of {span}" + (f" ({basis[:240]})" if basis else ""))}


# ── the binding ─────────────────────────────────────────────────────────────────────────────────────────────────────

_ROLE = re.compile(r"\{\{\s*role\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\}\}")
_PRESENCE = re.compile(r"\{\{\s*role\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\}\}\s+IS\s+(NOT\s+)?NULL", re.IGNORECASE)


def as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _a(word: str) -> str:
    return f"{'an' if word[:1].lower() in 'aeiou' else 'a'} {word}"


def _category(dtype: str) -> str:
    d = (dtype or "").lower()
    if not d:
        return ""
    if "bool" in d:
        return "flag"
    if "date" in d or "time" in d:
        return "time"
    if any(t in d for t in ("int", "numeric", "decimal", "float", "double", "real", "number", "money", "bignumeric")):
        return "integer" if "int" in d and not any(t in d for t in ("interval",)) else "number"
    if any(t in d for t in ("char", "text", "string", "varchar", "uuid")):
        return "text"
    return ""


#: An attribute type and the column kinds that cannot carry it — only the plain mismatches, so a code may be a number
#: and a flag a 0/1 integer.
_WRONG = {
    "id": {"time"},
    "timestamp": {"number"},
    "money": {"time", "flag", "text"},
    "number": {"time", "flag", "text"},
    "flag": {"time"},
    "code": {"time"},
}


def binding_problems(formula: str, roles: dict, bound: dict, columns: dict) -> list[str]:
    """What is wrong with how a recipe's roles are bound, in sentences.

    ``roles`` — the pack's role specs (`RoleSpec`, attribute → type); ``bound`` — the connection's binding (role →
    ``{"table", "columns": {attribute: column}}``); ``columns`` — the profiler's columns (``"table.column"`` → its
    profile, with ``dtype`` and ``null_rate``)."""
    from aughor.semantic.metric_time import bare_name

    def profile(table: str, column: str) -> dict:
        want = (bare_name(table), column.lower())
        for key, prof in (columns or {}).items():
            if not isinstance(prof, dict):
                continue
            t = bare_name(str(prof.get("table") or str(key).split(".", 1)[0]))
            c = str(prof.get("column") or str(key).split(".", 1)[-1]).lower()
            if (t, c) == want:
                return prof
        return {}

    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    presence = {(r, a): bool(neg) for r, a, neg in _PRESENCE.findall(formula or "")}
    for role, attr in _ROLE.findall(formula or ""):
        if (role, attr) in seen:
            continue
        seen.add((role, attr))
        b = bound.get(role) or {}
        table, column = str(b.get("table") or ""), str((b.get("columns") or {}).get(attr) or "")
        if not (table and column):
            continue                                   # unbound is the catalogue's `needs_binding`, said there
        spec = roles.get(role)
        attrs = (spec.get("attributes") if isinstance(spec, dict) else getattr(spec, "attributes", None)) or {}
        declared = attrs.get(attr)
        want = str((declared.get("type") if isinstance(declared, dict) else getattr(declared, "type", "")) or "")
        prof = profile(table, column)
        kind = _category(str(prof.get("dtype") or ""))
        if want and kind and kind in (_WRONG.get(str(want)) or set()):
            out.append(f"{role}.{attr} is {_a(want)}, and it is bound to {table}.{column}, {_a(str(prof.get('dtype')))} "
                       "column")
        if (role, attr) in presence and prof.get("null_rate") is not None:
            nulls = as_float(prof["null_rate"])
            if nulls == 0.0:
                out.append(f"the formula counts a row when {role}.{attr} is set, and {table}.{column} is never empty — "
                           f"every row of {table} would count, so {table} is not the table whose rows are {role}s")
    return out


def binding(m: Any, connection_id: str, schema_name: Optional[str]) -> dict:
    """The binding gate for a definition made from a recipe (its lineage names the package): its roles' columns. A
    metric that only shares a recipe's name was not written over the package's roles, so its binding says nothing."""
    recipe = recipe_of(m, connection_id, schema_name, by_name=False)
    if recipe is None:
        return {"ok": None, "why": "it is not made from a recipe with roles"}
    pack_id, pm, pack = recipe
    try:
        from aughor.packs.bindings import load_binding
        from aughor.semantic.metrics import ALL_DATASETS
        from aughor.tools.profile_cache import merged_profile_entry
        ds = "" if schema_name in (None, "", ALL_DATASETS) else schema_name
        bound = ((load_binding(pack_id, connection_id, ds) or {}).get("bindings") or {})
        columns = (merged_profile_entry(connection_id) or {}).get("columns") or {}
    except Exception as exc:  # noqa: BLE001 — not read is said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a recipe's binding could not be read for its gate", counter="metric_gates.binding")
        return {"ok": None, "why": f"its binding could not be read ({type(exc).__name__})"}
    problems = binding_problems(pm.formula, pack.entities, bound, columns)
    if problems:
        return {"ok": False, "why": "; ".join(problems)}
    return {"ok": True, "why": ""}


def recipe_of(m: Any, connection_id: str, schema_name: Optional[str] = None, *,
              by_name: bool = True) -> Optional[tuple]:
    """``(pack_id, PackMetric, Pack)`` — the recipe a definition is made from (its lineage names the package and its
    name is the recipe's) or, with ``by_name``, the recipe whose own name or title it carries word for word — or None.

    Never by an ALIAS: an alias lets the platform recognise a name, it does not say two metrics are one. Measured live
    2026-10-26: LuxExperience's Item Return Rate — an explorer metric, ~31% a month, plausible for luxury fashion — met
    retail's return-rate recipe through its alias "item return rate", and its 0–30% band would have refused it."""
    from aughor.packs.loader import load_pack
    from aughor.semantic.metric_catalogue import industry_packages, normalize_name

    lineage = " ".join(str(x) for x in (getattr(m, "lineage", None) or []))
    named = {normalize_name(getattr(m, "name", "")), normalize_name(getattr(m, "label", "") or "")} - {""}
    for pkg in industry_packages(connection_id, schema_name):
        try:
            pack = load_pack(pkg.directory)
        except Exception as exc:  # noqa: BLE001 — an unloadable package offers no recipe, and says so
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"package {pkg.pack_id} did not load; its recipes are not matched", counter="metric_gates.pack")
            continue
        for pm in pack.metrics:
            made_from = pkg.pack_id in lineage and normalize_name(pm.name) in named
            same_name = by_name and bool(named & {normalize_name(pm.name), normalize_name(pm.title)})
            if made_from or same_name:
                return pkg.pack_id, pm, pack
    return None


def band_of(m: Any, connection_id: str, schema_name: Optional[str] = None) -> tuple[Optional[dict], str]:
    """The sane range of the recipe a definition is made from, and the recipe's title."""
    recipe = recipe_of(m, connection_id, schema_name)
    if recipe is None:
        return None, ""
    _pid, pm, _pack = recipe
    sr = pm.sane_range
    return (sr.model_dump() if hasattr(sr, "model_dump") else sr), (pm.title or pm.name)


# ── the check ───────────────────────────────────────────────────────────────────────────────────────────────────────

#: (connection, name, version, sql, time_column, time_kind) → (when, verdict). Read by the coverage view: an approved
#: metric checked within the hour is not measured again.
_CACHE: dict[tuple, tuple[float, dict]] = {}
_TTL = 3600.0


def _key(m: Any, connection_id: str) -> tuple:
    return (connection_id, getattr(m, "name", ""), int(getattr(m, "version", 0) or 0), str(getattr(m, "sql", "") or ""),
            str(getattr(m, "time_column", "") or ""), str(getattr(m, "time_kind", "") or ""))


def cached(m: Any, connection_id: str) -> Optional[dict]:
    hit = _CACHE.get(_key(m, connection_id))
    return hit[1] if hit and time.monotonic() - hit[0] < _TTL else None


def check(m: Any, connection_id: str, *, run_sql: Optional[Callable[[str], tuple]] = None,
          dialect: str = "", schema_name: Optional[str] = None) -> dict:
    """Every gate's verdict on ``m``, with the figures they read: ``{"moves", "sane_range", "binding", "figures",
    "months"}``. Opens the connection's warehouse unless a runner is handed in."""
    from aughor.semantic.metrics import home_schema

    schema = schema_name if schema_name is not None else home_schema(m)
    if run_sql is None:
        from aughor.knowledge import period_brief
        try:
            with period_brief.connection_runner(connection_id) as (run, dia):
                return check(m, connection_id, run_sql=run, dialect=dia, schema_name=schema)
        except Exception as exc:  # noqa: BLE001 — not known is said, never taken for a pass
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a metric's figures could not be read for its gates", counter="metric_gates.open")
            why = f"the connection could not be opened ({type(exc).__name__})"
            return {"moves": {"ok": None, "why": why}, "sane_range": {"ok": None, "why": why},
                    "binding": binding(m, connection_id, schema), "figures": None, "months": []}
    figures, months, why = recent_figures(m, run_sql, dialect or "duckdb")
    band, title = band_of(m, connection_id, schema)
    verdict = {"moves": moves(figures, why),
               "sane_range": sane(figures, band, f"the {title} recipe") if band else dict(_UNREAD, why="no sane range "
                                                                                          "is declared for it"),
               "binding": binding(m, connection_id, schema),
               "figures": figures, "months": months}
    _CACHE[_key(m, connection_id)] = (time.monotonic(), verdict)
    return verdict


def refusal(verdict: dict) -> Optional[tuple[str, str]]:
    """The first gate that failed, as ``(reason, why)``, or None."""
    for gate in ("binding", "moves", "sane_range"):
        v = verdict.get(gate) or {}
        if v.get("ok") is False:
            return REFUSALS[gate], v.get("why") or ""
    return None


def not_read(verdict: dict) -> str:
    """The gates that could not be read, in one line for the audit — "" when every gate read."""
    parts = [f"{g}: {(verdict.get(g) or {}).get('why')}" for g in ("moves", "sane_range", "binding")
             if (verdict.get(g) or {}).get("ok") is None and (verdict.get(g) or {}).get("why")]
    return "; ".join(parts)


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)

