"""
Metrics Catalog — Phase 1e + M21.

Named business KPI formulas stored in data/metrics.json and injected into
every schema context so the LLM uses the same approved SQL expression for
MRR, CAC, LTV, etc. rather than re-deriving them on every investigation.

M21 elevates metrics from SQL formulas to governed semantic contracts:
each metric can carry an owner, freshness SLA, quality tests, lineage,
and documented anti-patterns that the LLM is instructed to never use.

Relationship to the Business Glossary:
  Glossary  = what data IS  (table/column semantics, grain, caveats)
  Metrics   = what to COMPUTE (approved SQL formulas, dimensions, filters)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# ── The two layers (IN, the overlay) ─────────────────────────────────────────
#
# `data/metrics.json` was shipped seed content AND this install's catalogue, in one tracked
# file. The app rewrote it, so every used install carried a modified tracked file — and git
# refuses a fast-forward over one the moment upstream edits it too, which #514 did. The
# update that would fix that is delivered BY a fast-forward, so the only repair is to stop
# both sides writing one path: the seed is shipped at `data/shipped/metrics.json` and never
# written here, and this install's rows live in an instance file git ignores. The view is
# the seed with the instance laid over it.
_DATA = Path(__file__).parent.parent.parent / "data"

#: The INSTANCE layer — what this install wrote. Ignored by `.gitignore` (`data/*.json`), so no
#: update can ship a file here; not an authored entry, so `migrate-state` carries it home.
_DEFAULT_PATH = _DATA / "metrics.instance.json"
#: The SEED layer — what the repo ships. Tracked, and read-only to the app.
_SEED_DEFAULT = _DATA / "shipped" / "metrics.json"
#: FROZEN. Where every install before the overlay kept its catalogue. Never written again and
#: never changed upstream (`test_seed_overlay_frozen` holds both), so an install that modified
#: it still fast-forwards. Until this install's first write it is where the instance is READ from.
_LEGACY_PATH = _DATA / "metrics.json"
#: A byte copy of what `_LEGACY_PATH` shipped as, frozen with it: a row that still equals it was
#: never this install's, so it is left to follow the seed rather than pinned as instance data.
_LEGACY_BASELINE = _DATA / "shipped" / "metrics.legacy.json"

INSTANCE_FORMAT = "aughor.metrics.instance/1"

#: Save, delete and the one-time conversion are read-modify-write on one file; the routes are
#: sync, so two requests can interleave. Per process only — as before, a second writing process
#: can still lose an update.
_WRITE_LOCK = threading.RLock()


class MetricsStoreError(RuntimeError):
    """The instance layer cannot be read or converted. Raised, never answered with an emptier
    catalogue: several readers swallow exceptions, and "no metrics" would read as a clean one."""


def _default_path() -> Path:
    """The INSTANCE file, honouring ``AUGHOR_METRICS_PATH`` (test-isolated in conftest so the
    suite can't mutate live instance data — same non-hermeticity class as the glossary,
    task_213affac). Resolved per call so it always reflects the current env."""
    from aughor.db.sqlite_util import resolve_db_path
    return resolve_db_path("AUGHOR_METRICS_PATH", _DEFAULT_PATH)


def _seed_path() -> Path:
    """The SEED file, honouring ``AUGHOR_METRICS_SEED_PATH``."""
    from aughor.db.sqlite_util import resolve_db_path
    return resolve_db_path("AUGHOR_METRICS_SEED_PATH", _SEED_DEFAULT)


#: A metric that applies to every connection. Wave O2: the store was keyed by NAME
#: alone, so two connections could not hold different definitions of `revenue` — the
#: #198 shape (a store keyed without the dimension distinguishing its owners), for the
#: third time in this codebase.
#:
#: An entry with no `connection` IS this value, so the existing tracked `data/metrics.json`
#: needed no migration at all: every entry in it was already a global default, and
#: rewriting the file to say so would have been churn with a data-loss risk attached, on a
#: repo that has destroyed `data/` twice with non-hermetic writes.
GLOBAL_CONNECTION = "*"


class MetricDefinition(BaseModel):
    name: str = Field(description="Unique snake_case identifier, e.g. 'mrr'")
    connection: str = Field(
        default=GLOBAL_CONNECTION,
        description="Connection this definition applies to; '*' is the default for all")
    label: str = Field(description="Human-readable display name, e.g. 'Monthly Recurring Revenue'")
    sql: str = Field(description="Approved SQL expression, e.g. \"SUM(amount) FILTER (WHERE status='active')\"")
    tables: list[str] = Field(default_factory=list, description="Tables this metric draws from")
    dimensions: list[str] = Field(default_factory=list, description="Columns the metric can be sliced by")
    filters: list[str] = Field(default_factory=list, description="Default WHERE conditions always applied")
    unit: Optional[str] = Field(default=None, description="Display unit: '$', '%', 'days', etc.")
    caveats: Optional[str] = Field(default=None, description="Finance/data-team approved caveats or exclusions")
    additivity: Optional[str] = Field(
        default=None,
        description="Declared additivity: 'additive' (summable across groups → share-of-total "
                    "valid) or 'non_additive' (a ratio/avg/rate → never share-of-total). When "
                    "set it OVERRIDES the SQL inference; omit to infer from the formula.",
    )
    # Health scorecard fields (M13a)
    target_value: Optional[float] = Field(default=None, description="Target value for health scorecard")
    warning_threshold: Optional[float] = Field(default=None, description="Yellow-zone boundary (absolute value)")
    critical_threshold: Optional[float] = Field(default=None, description="Red-zone boundary (absolute value)")
    target_period: Optional[str] = Field(default=None, description="'monthly', 'quarterly', 'ytd'")
    benchmark_source: Optional[str] = Field(default=None, description="e.g. 'internal: FY2025 plan'")
    # Governance fields (M21)
    owner: Optional[str] = Field(default=None, description="Team or person responsible, e.g. 'Revenue team'")
    freshness_sla: Optional[str] = Field(default=None, description="Human description of SLA, e.g. 'daily by 6am UTC'")
    freshness_check_sql: Optional[str] = Field(default=None, description="SQL returning the latest data timestamp for this metric")
    quality_tests: list[str] = Field(default_factory=list, description="SQL assertions that must be true; failure = metric flagged unreliable")
    lineage: list[str] = Field(default_factory=list, description="Source tables and transformation descriptions")
    wrong_usage_examples: list[str] = Field(default_factory=list, description="Anti-patterns with explanations — injected as NEVER rules")
    approved_by: Optional[str] = Field(default=None, description="Who approved this definition, e.g. 'Finance'")
    approved_at: Optional[str] = Field(default=None, description="ISO date of approval, e.g. '2026-01-15'")
    # Time semantics (Arc BR-2, ROADMAP §3.48) — how the metric is measured for a date range.
    # Empty = not known; `aughor/semantic/metric_time.py` sets them automatically by rule and
    # measurement (the user's call, §6 item 34(b)) and records where they came from, and a
    # person corrects them. Nothing reads them while they are empty.
    time_column: Optional[str] = Field(
        default=None, description="The date that puts a row in a range, e.g. 'created_at'")
    time_kind: Optional[str] = Field(
        default=None, description="'flow' (adds up over a range), 'stock' (a level at a date) or "
                                  "'cohort' (tied to one date, completed by a later event)")
    outcome_column: Optional[str] = Field(
        default=None, description="A cohort's completing event, e.g. 'returned_at'")
    until_column: Optional[str] = Field(
        default=None, description="A stock's end: a row counts until this date, e.g. 'sold_at'")
    settles_after_days: Optional[int] = Field(
        default=None, description="A cohort's maturity: days until its outcome stops arriving")
    time_source: Optional[str] = Field(
        default=None, description="Where the time fields came from, in words")
    time_confirmed_by: Optional[str] = Field(
        default=None, description="The person who confirmed or corrected them; empty = set "
                                  "automatically and not yet confirmed")
    # Governance lifecycle (B-8) — propose → review → approve → version → audit.
    status: str = Field(default="draft", description="Lifecycle: draft|proposed|approved|deprecated")
    version: int = Field(default=0, description="Revision counter — bumps on each approval")
    proposed_by: Optional[str] = Field(default=None, description="Who proposed this (draft→proposed)")
    proposed_at: Optional[str] = Field(default=None, description="ISO timestamp of the proposal")

    @model_validator(mode="before")
    @classmethod
    def _govern_defaults(cls, data):
        """Back-compat: pre-B-8 metrics have no status/version. An already-approved
        metric (has `approved_by`) is treated as approved/v1; everything else is a
        draft. Explicit values are never overridden."""
        if isinstance(data, dict):
            patched = dict(data)
            if not patched.get("status"):
                patched["status"] = "approved" if patched.get("approved_by") else "draft"
            if patched.get("version") in (None, 0) and patched.get("approved_by"):
                patched["version"] = 1
            return patched
        return data


# ── Persistence ───────────────────────────────────────────────────────────────

def _read_rows(p: Path) -> list[dict]:
    """One file's rows, the way every catalogue file was read before the overlay."""
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _load_raw(path: Path | None = None) -> list[dict]:
    """The catalogue: ``path`` alone when a caller names a file, else the layered view."""
    return _read_rows(path) if path is not None else _view()


def _atomic_write(p: Path, payload: object) -> None:
    """Write-then-rename, so a crash leaves the old file or the new one, never half of either."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def _invalidate_hints() -> None:
    # Metrics feed the schema-linker's table/column hints — refresh that cache.
    try:
        from aughor.tools.schema_linker import invalidate_hints
        invalidate_hints()  # metrics are global → clear all connections
    except Exception:
        pass


def _save_raw(metrics: list[dict], path: Path) -> None:
    """A named single file, written whole — the pre-overlay shape, kept for callers that pass one."""
    _refuse_shipped(path)
    _atomic_write(path, metrics)
    _invalidate_hints()


# ── The overlay: seed + instance ──────────────────────────────────────────────

Key = tuple[str, str]


def _key(raw: dict) -> Key:
    return (_conn_of(raw), str(raw.get("name") or ""))


def _grouped(rows: list[dict]) -> dict[Key, list[dict]]:
    out: dict[Key, list[dict]] = {}
    for m in rows:
        out.setdefault(_key(m), []).append(m)
    return out


@dataclass
class _Instance:
    """This install's layer. A key it holds rows for SHADOWS the seed's rows for that key, whole;
    a key in ``hidden`` is one the seed ships and this install deleted."""
    rows: list[dict] = field(default_factory=list)
    hidden: set[Key] = field(default_factory=set)
    converted_from: Optional[dict] = None

    def owns(self, k: Key) -> bool:
        return any(_key(m) == k for m in self.rows)


def _parse_instance(p: Path) -> _Instance:
    data = json.loads(p.read_text())
    if isinstance(data, list):
        # A bare list is a WHOLE catalogue written before the overlay (a named AUGHOR_METRICS_PATH,
        # or a test's own registry). Every row is this install's, and a shipped key it lacks was
        # deleted here — so it reads exactly as it read alone, and only keys shipped since arrive.
        present = _grouped(data)
        return _Instance(rows=data, hidden={k for k in _grouped(_read_rows(_LEGACY_BASELINE))
                                            if k not in present})
    if isinstance(data, dict) and data.get("format") == INSTANCE_FORMAT:
        return _Instance(rows=list(data.get("rows") or []),
                         hidden={(str(h["connection"]), str(h["name"])) for h in data.get("hidden") or []},
                         converted_from=data.get("converted_from"))
    raise ValueError(f"not a metrics instance file (format {data.get('format') if isinstance(data, dict) else type(data).__name__!r})")


def derive(legacy: list[dict], baseline: list[dict]) -> _Instance:
    """This install's layer, read out of the pre-overlay file.

    A key whose rows still equal what the file shipped with is an ECHO — never this install's —
    and is left to follow the seed. Every other row is this install's. A shipped key missing from
    the file was deleted here, and stays hidden. Judged against the frozen baseline, never the
    current seed, which is free to move."""
    base, leg = _grouped(baseline), _grouped(legacy)
    return _Instance(rows=[m for m in legacy if leg[_key(m)] != base.get(_key(m))],
                     hidden={k for k in base if k not in leg})


def _converted_marker(p: Path) -> Path:
    """Written beside the instance once a conversion is verified. It outlives the instance file,
    so a MISSING instance after a conversion is an error rather than a quiet re-read of the frozen
    file, which by then describes a catalogue this install has moved on from."""
    return p.with_name(p.name.removesuffix(".json") + ".converted.json")


def _instance() -> _Instance:
    """This install's layer, for writers and the view. Reading it never writes."""
    p = _default_path()
    if p.exists():
        try:
            return _parse_instance(p)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error("metrics instance %s is unreadable: %s", p, exc)
            raise MetricsStoreError(f"the metrics instance file {p} is unreadable ({exc}). It was "
                                    "left as it is: repair it or restore it from a backup — do not "
                                    "delete it, since without it this install's metrics are "
                                    "gone") from exc
    if os.environ.get("AUGHOR_METRICS_PATH"):
        # A path somebody named IS the instance; an absent one is empty. Falling through to the
        # checkout's file here would hand a test the developer's live catalogue.
        return _Instance()
    marker = _converted_marker(p)
    if marker.exists():
        raise MetricsStoreError(f"this install's metrics were converted into {p} "
                                f"(recorded in {marker}), and that file is missing. Restore it from "
                                f"a backup; {_LEGACY_PATH} no longer describes this catalogue")
    if not _LEGACY_PATH.exists():
        return _Instance()
    return derive(_read_rows(_LEGACY_PATH), _read_rows(_LEGACY_BASELINE))


def _merge(seed: list[dict], inst: _Instance) -> list[dict]:
    """Seed order, with each key the instance holds replaced by the instance's rows for it (once,
    where the seed had it), hidden keys dropped, and the instance's own keys after.

    Whole keys, never fields: patching fields would carry a seed row's `status` or `version`
    across a person's edit. And never a concatenation: `get_metric` returns the FIRST row of a
    name and `_dedupe_by_name` keeps the LAST, so two rows of one key would answer differently."""
    mine = _grouped(inst.rows)
    owned = set(mine)
    out: list[dict] = []
    for m in seed:
        k = _key(m)
        if k in owned:
            out += mine.pop(k, [])           # at the key's first seed row, every instance grain, once
        elif k not in inst.hidden:
            out.append(m)                    # an unowned seed key keeps all of its grains
    for rows in mine.values():
        out += rows
    return out


def _view() -> list[dict]:
    return _merge(_read_rows(_seed_path()), _instance())


def _refuse_shipped(p: Path) -> None:
    """The seed, the frozen legacy file and its baseline are never a write target."""
    target = Path(p).resolve()
    for shipped in (_seed_path(), _LEGACY_PATH, _LEGACY_BASELINE):
        if target == Path(shipped).resolve():
            raise MetricsStoreError(f"{p} is shipped content; metrics are written to the instance "
                                    f"file ({_default_path()}), never to it")


def _write_instance(inst: _Instance) -> None:
    p = _default_path()
    _refuse_shipped(p)
    payload: dict = {"format": INSTANCE_FORMAT, "rows": inst.rows,
                     "hidden": [{"connection": c, "name": n} for c, n in sorted(inst.hidden)]}
    if inst.converted_from:
        payload["converted_from"] = inst.converted_from
    _atomic_write(p, payload)
    _invalidate_hints()


def _unconverted(view: list[dict], legacy: list[dict], baseline: list[dict],
                 seed: list[dict]) -> list[str]:
    """What a converted view gets wrong about the file it came from — computed WITHOUT `derive`,
    so a defect there cannot also approve itself. Empty means nothing was lost or resurrected."""
    leg, base, sd, got = _grouped(legacy), _grouped(baseline), _grouped(seed), _grouped(view)
    problems = []
    for k, rows in leg.items():
        expected = sd.get(k, []) if rows == base.get(k) else rows
        if got.get(k, []) != expected:
            problems.append(f"{k[1]!r} on {k[0]!r} would read differently after conversion")
    problems += [f"{k[1]!r} on {k[0]!r} was deleted on this install and would come back"
                 for k in base if k not in leg and k in got]
    problems += [f"{k[1]!r} on {k[0]!r} would appear from nowhere"
                 for k in got if k not in leg and k not in sd]
    return problems


def _inode(p: Path) -> int | None:
    try:
        return os.stat(p).st_ino
    except OSError:
        return None


def _create_if_absent(p: Path, text: str) -> int | None:
    """Create ``p`` holding ``text`` only if nothing is there. Returns the new file's inode, or
    None when another writer got there first. Never replaces a file."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.convert.tmp")
    try:
        with open(tmp, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, p)                      # atomic: a reader sees nothing or the whole file
            return _inode(tmp)
        except FileExistsError:
            return None
        except OSError as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "no hard links on this filesystem (exFAT, FAT, some network/FUSE mounts); "
                          "creating the metrics instance exclusively instead",
                     counter="metrics.instance.no_hardlink", level=logging.INFO)
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return None
        with os.fdopen(fd, "w") as f:            # still create-if-absent, though not atomic to a reader
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            return os.fstat(f.fileno()).st_ino
    finally:
        tmp.unlink(missing_ok=True)


def materialize() -> _Instance:
    """Create the instance file from the pre-overlay one — once, verified, and only if absent.

    Runs under the write lock on this install's first metric write. The legacy file is read and
    never written. A conversion that would change what the catalogue says raises with the keys
    and writes nothing, so reads keep serving the view they served before."""
    with _WRITE_LOCK:
        p = _default_path()
        if (p.exists() or os.environ.get("AUGHOR_METRICS_PATH") or not _LEGACY_PATH.exists()
                or _converted_marker(p).exists()):
            return _instance()               # converted already, or nothing to convert (raises if lost)
        raw = _LEGACY_PATH.read_bytes()
        legacy = json.loads(raw)
        legacy = legacy if isinstance(legacy, list) else []
        baseline, seed = _read_rows(_LEGACY_BASELINE), _read_rows(_seed_path())
        inst = derive(legacy, baseline)
        inst.converted_from = {"path": str(_LEGACY_PATH), "sha256": hashlib.sha256(raw).hexdigest(),
                               "size": len(raw), "at": datetime.now(timezone.utc).isoformat()}
        problems = _unconverted(_merge(seed, inst), legacy, baseline, seed)
        if problems:
            raise MetricsStoreError("the metrics catalogue was not converted, and nothing was "
                                    "written: " + "; ".join(problems))
        _refuse_shipped(p)
        text = json.dumps({"format": INSTANCE_FORMAT, "rows": inst.rows,
                           "hidden": [{"connection": c, "name": n} for c, n in sorted(inst.hidden)],
                           "converted_from": inst.converted_from}, indent=2)
        ours = _create_if_absent(p, text)
        if ours is None:
            return _instance()                   # another process converted first — use its
        back = _instance()
        problems = _unconverted(_merge(seed, back), legacy, baseline, seed)
        if problems:
            if _inode(p) != ours:
                # Another process has written since, over our conversion: its file carries its own
                # change, so it is not ours to judge — and never ours to delete.
                return _instance()
            p.unlink(missing_ok=True)            # ours, just made; the legacy file is untouched
            raise MetricsStoreError("the converted metrics file did not read back as written, "
                                    "and was removed: " + "; ".join(problems))
        _atomic_write(_converted_marker(p), inst.converted_from)
        logger.info("metrics: converted %s into %s (%d rows, %d hidden)",
                    _LEGACY_PATH, p, len(back.rows), len(back.hidden))
        return back


# ── Public API ────────────────────────────────────────────────────────────────

def _conn_of(raw: dict) -> str:
    return str(raw.get("connection") or GLOBAL_CONNECTION)


def list_metrics(path: Path | None = None,
                 connection_id: str | None = None) -> list[MetricDefinition]:
    """Every metric, or the ones that apply to ``connection_id`` with scoped shadowing.

    Wave O2 resolution, and the ONLY rule here: a connection-scoped entry SHADOWS the
    global entry of the same name. Override-wins, the same discipline
    `data/ontology_overrides/` already practises — a specific answer beats a general one,
    and never the reverse.

    ``connection_id=None`` returns everything unfiltered, so every existing caller is
    byte-identical. That is deliberate: the alternative — making the connection argument
    required — turns a re-key into a caller migration across the whole tree, and each
    unconverted site becomes a silent global read that looks correct.
    """
    rows = _load_raw(path)
    if connection_id is None:
        return [MetricDefinition(**m) for m in rows]

    scoped_names = {m.get("name") for m in rows if _conn_of(m) == connection_id}
    out = [m for m in rows if _conn_of(m) == connection_id]
    out += [m for m in rows
            if _conn_of(m) == GLOBAL_CONNECTION and m.get("name") not in scoped_names]
    return [MetricDefinition(**m) for m in out]


def get_metric(name: str, path: Path | None = None,
               connection_id: str | None = None) -> MetricDefinition | None:
    rows = _load_raw(path)
    if connection_id is not None:
        for m in rows:                       # scoped first — it shadows
            if m.get("name") == name and _conn_of(m) == connection_id:
                return MetricDefinition(**m)
    for m in rows:
        if m.get("name") != name:
            continue
        if connection_id is None or _conn_of(m) == GLOBAL_CONNECTION:
            return MetricDefinition(**m)
    return None


def save_metric(metric: MetricDefinition, path: Path | None = None) -> None:
    """Upsert a metric by (connection, name).

    The identity is the PAIR. Upserting by name alone would mean scoping `revenue` to one
    connection silently overwrote the global definition every other connection reads —
    which is the exact failure this wave exists to make impossible.
    """
    if path is not None:
        raw = _read_rows(path)
        _upsert(raw, metric.model_dump())
        _save_raw(raw, path)
        return
    with _WRITE_LOCK:
        inst = materialize()
        k = _key(metric.model_dump())
        if not inst.owns(k) and k not in inst.hidden:
            # Copy the seed's rows for this key up first, so a key with several grains keeps the
            # ones this save does not touch — the instance shadows a key WHOLE.
            inst.rows += [m for m in _read_rows(_seed_path()) if _key(m) == k]
        inst.hidden.discard(k)
        _upsert(inst.rows, metric.model_dump())
        _write_instance(inst)


def _upsert(rows: list[dict], dump: dict) -> None:
    for i, m in enumerate(rows):
        if _key(m) == _key(dump):
            rows[i] = dump
            return
    rows.append(dump)


def delete_metric(name: str, sql: str | None = None, path: Path | None = None,
                  connection_id: str | None = None) -> bool:
    """Remove a metric by name. Returns True if anything was deleted.

    Grain-aware: a name can carry several governed grains, each with a distinct
    formula (e.g. ``revenue`` over ``orders`` vs ``order_items``). When ``sql`` is
    given, only the entry whose formula matches is removed — so deleting one grain
    from the UI doesn't wipe the others. Without ``sql`` every entry sharing the
    name is removed (legacy behaviour, used by bulk cleanup paths).

    A shipped row is not deleted from the seed, which is never written: its key is hidden in the
    instance, so it stays gone however the seed moves."""

    def _target(m: dict) -> bool:
        if m.get("name") != name:
            return False
        # A connection-scoped delete must not reach the global entry other connections
        # depend on; without the connection filter, un-scoping one connection's metric
        # would delete it for everybody.
        if connection_id is not None and _conn_of(m) != connection_id:
            return False
        return sql is None or (m.get("sql") or "") == sql

    if path is not None:
        raw = _read_rows(path)
        new = [m for m in raw if not _target(m)]
        if len(new) == len(raw):
            return False
        _save_raw(new, path)
        return True
    with _WRITE_LOCK:
        inst = materialize()
        seed = _read_rows(_seed_path())
        keys = {_key(m) for m in _merge(seed, inst) if _target(m)}
        if not keys:
            return False
        for k in keys:
            if not inst.owns(k):
                inst.rows += [m for m in seed if _key(m) == k]    # copy up, then delete from the copy
        inst.rows = [m for m in inst.rows if not _target(m)]
        seed_keys = {_key(m) for m in seed}
        inst.hidden |= {k for k in keys if k in seed_keys and not inst.owns(k)}
        _write_instance(inst)
        return True


# ── Quality validation + freshness ────────────────────────────────────────────

# ── the governed value ───────────────────────────────────────────────────────────
#
# DS-12 — lifted here from `routers/metrics.py`, where it lived twice and ran zero
# times. Both copies called `db.execute(query)` against a signature that has always
# been `execute(hypothesis_id, sql)`, so both raised TypeError on every call: the
# value route swallowed it into its `note` field ("Could not compute against …") and
# the health scorecard swallowed it into `status: "unknown"`. A governed metric's
# number — the thing the MCP tool's own docstring promises is "the exact governed
# number, not an LLM re-derivation" — has never once been computed.
#
# They also disagreed about WHAT to compute. The value route applied the metric's
# declared filters over its first table; the scorecard ran the bare aggregate with no
# FROM and no filters. Two numbers for one governed definition is the failure this
# module exists to prevent, so there is now one builder and one runner, here, beside
# the definition they read.

class MetricValue(BaseModel):
    """One metric's current value, the SQL that produced it, and why it could not be."""

    value: Optional[float] = None
    sql: str = ""
    error: str = ""


def value_query(metric: "MetricDefinition") -> str:
    """The governed value query for this metric.

    A metric whose ``sql`` is already a full SELECT is run verbatim — it has stated its
    own shape. Otherwise the aggregate expression is wrapped over the metric's first
    table with its declared filters applied, because those filters ARE the definition:
    revenue that includes cancelled orders is a different metric from the one Finance
    approved, and computing it without them would answer the wrong question precisely.
    """
    expr = (metric.sql or "").strip()
    if expr.lower().startswith("select"):
        return expr
    query = f"SELECT ({expr}) AS _v"
    if metric.tables:
        query += f" FROM {metric.tables[0]}"
        if metric.filters:
            query += " WHERE " + " AND ".join(metric.filters)
    return query


def compute_value(metric: "MetricDefinition", db) -> MetricValue:
    """Run the governed query on an open connection. Never raises.

    ``__metric_value__`` is an INTERNAL query label (dunder-wrapped, the convention
    `_is_internal_query` reads and the one `__monitor_window__` already uses): this
    reads a single aggregate, never rows, so there is nothing for the PII post-pass to
    redact. A step that reads ROWS must not borrow this label.
    """
    query = value_query(metric)
    try:
        result = db.execute("__metric_value__", query)
    except Exception as exc:                       # a connector that cannot run it at all
        return MetricValue(sql=query, error=str(exc))
    if getattr(result, "error", None):
        return MetricValue(sql=query, error=str(result.error))
    rows = getattr(result, "rows", None) or []
    if not rows or rows[0] is None:
        # A metric that legitimately matches no rows. Distinct from an error, and the
        # caller renders it as such: "no value" is an answer, "could not ask" is not.
        return MetricValue(sql=query)
    first = rows[0]
    raw = first[0] if isinstance(first, (list, tuple)) else list(first.values())[0]
    # This layer hands back STRINGIFIED rows and spells SQL NULL as the literal "NULL"
    # (the convention in `connectors/base.py` and four sibling call sites). An aggregate
    # over zero matching rows is exactly that — an answer of "nothing", not a fault. The
    # first version of this function called it a non-numeric value and reported an ERROR,
    # which would have paged someone about a connection that was working perfectly.
    if raw is None or (isinstance(raw, str) and raw.strip() in ("", "NULL")):
        return MetricValue(sql=query)
    try:
        return MetricValue(value=float(raw), sql=query)
    except (TypeError, ValueError):
        return MetricValue(sql=query,
                           error=f"{metric.name} returned a non-numeric value: {raw!r}")


class QualityTestResult(BaseModel):
    test_sql: str
    passed: bool
    error: Optional[str] = None


class ValidationResult(BaseModel):
    metric: str
    passed: bool
    results: list[QualityTestResult]
    message: str


class FreshnessResult(BaseModel):
    metric: str
    latest_data_at: Optional[str]
    sla: Optional[str]
    ok: bool
    message: str


def _run_check_sql(conn, sql: str, label: str):
    """Execute one check statement against a connection of either arity.

    HB-2 found the tie-out plane broken at its only door: this module called
    ``conn.execute(sql)`` while every governed connection's signature is
    ``execute(hypothesis_id, sql)`` — so EVERY quality test errored with a
    TypeError that was then reported as "1 of N tests failed", a wrong number
    wearing a tie-out's verdict. Governed and bounded first (a check returns a
    scalar; five rows is generosity), single-arg as the fallback for a raw or
    stub connection."""
    if hasattr(conn, "execute_bounded"):
        return conn.execute_bounded(label, sql, 5)
    try:
        return conn.execute(label, sql)
    except TypeError:
        return conn.execute(sql)


def _truthy_scalar(val) -> bool:
    """A quality test's verdict, as the DATABASE meant it. The connection layer
    stringifies result cells, so a boolean False arrives as ``'False'`` — and
    ``bool('False')`` is True: a failing test that could not fail (found by HB-2's
    departure gate, the first caller that ever needed the verdict to be right).
    String forms are parsed as verdicts; anything unrecognized falls back to
    Python truthiness."""
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("false", "f", "no", ""):
            return False
        if s in ("true", "t", "yes"):
            return True
        try:
            return float(s) != 0.0
        except ValueError:
            return bool(s)
    return bool(val)


def validate_metric(metric: MetricDefinition, conn) -> ValidationResult:
    """Run all quality_tests for a metric against conn. Each test must return a truthy scalar."""
    if not metric.quality_tests:
        return ValidationResult(
            metric=metric.name,
            passed=True,
            results=[],
            message="No quality tests defined.",
        )

    results: list[QualityTestResult] = []
    all_passed = True
    for sql in metric.quality_tests:
        try:
            qr = _run_check_sql(conn, sql, "__metric_tieout__")
            rows = qr.rows if qr else []
            # A test passes when it returns a single truthy value
            if rows:
                first = rows[0]
                val = first[0] if isinstance(first, (list, tuple)) else list(first.values())[0]
                passed = _truthy_scalar(val)
            else:
                passed = False
            results.append(QualityTestResult(test_sql=sql, passed=passed))
            if not passed:
                all_passed = False
        except Exception as exc:
            results.append(QualityTestResult(test_sql=sql, passed=False, error=str(exc)))
            all_passed = False

    failed = sum(1 for r in results if not r.passed)
    message = (
        f"All {len(results)} test(s) passed."
        if all_passed
        else f"{failed} of {len(results)} test(s) failed."
    )
    return ValidationResult(metric=metric.name, passed=all_passed, results=results, message=message)


def check_freshness(metric: MetricDefinition, conn) -> FreshnessResult:
    """Run freshness_check_sql and return the latest data timestamp."""
    if not metric.freshness_check_sql:
        return FreshnessResult(
            metric=metric.name,
            latest_data_at=None,
            sla=metric.freshness_sla,
            ok=True,
            message="No freshness check SQL defined.",
        )

    try:
        qr = _run_check_sql(conn, metric.freshness_check_sql, "__metric_freshness__")
        rows = qr.rows if qr else []
        latest = None
        if rows:
            first = rows[0]
            raw = first[0] if isinstance(first, (list, tuple)) else list(first.values())[0]
            if raw is not None:
                latest = str(raw)
        return FreshnessResult(
            metric=metric.name,
            latest_data_at=latest,
            sla=metric.freshness_sla,
            ok=latest is not None,
            message=f"Latest data at: {latest}" if latest else "Could not determine latest data timestamp.",
        )
    except Exception as exc:
        return FreshnessResult(
            metric=metric.name,
            latest_data_at=None,
            sla=metric.freshness_sla,
            ok=False,
            message=f"Freshness check failed: {exc}",
        )


# ── Schema injection ──────────────────────────────────────────────────────────

def _schema_tables_and_columns(schema_text: str) -> tuple[set[str], set[str]]:
    """Parse a schema string into its real (table-name, column-name) sets.
    Uses the schema parser so we match against ACTUAL columns, not arbitrary
    text — a metric/description that merely mentions a column name in prose must
    not count as that column being present."""
    try:
        from aughor.tools.schema import parse_schema_tables
        parsed = parse_schema_tables(schema_text)
        tables = {t.split(".")[-1].lower() for t in parsed}
        cols = {c.lower() for cols in parsed.values() for c in cols}
        return tables, cols
    except Exception:
        return set(), set()


def _formula_columns(sql_expr: str) -> set[str]:
    """Bare column names referenced in a metric FORMULA fragment, via sqlglot.
    Best-effort: returns an empty set on any parse trouble so the caller adds NO
    formula-column constraint (over-injection is safer than wrongly dropping a
    valid metric). Function names / literals are not columns, so they're excluded."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(f"SELECT {sql_expr}", read="duckdb")
    except Exception:
        return set()
    if tree is None:
        return set()
    return {c.name.lower() for c in tree.find_all(exp.Column) if c.name}


def _metric_matches_schema(metric, tables: set[str], cols: set[str]) -> bool:
    """True if every table, dimension AND formula column the metric declares is
    present in the target connection's schema. Metrics are stored globally, so
    without this a metric authored for one connection (e.g. SALES on
    `final_price_usd`) leaks a wrong, column-mismatched formula into every other
    connection's prompt — a real NL2SQL-corrupting bug surfaced by the golden-SQL
    eval. The formula-column check closes the half the table/dimension checks
    miss: a metric like `revenue = SUM(total_amount)` must NOT inject into a
    connection whose orders has `o_totalprice`/`final_price_usd` and no
    `total_amount` (observed leaking AVG(total_amount) into beautycommerce, which
    has neither). Conservative: only drops when a declared name is genuinely absent."""
    for tbl in (metric.tables or []):
        if tbl.split(".")[-1].lower() not in tables:
            return False
    for dim in (metric.dimensions or []):
        if dim.split(".")[-1].lower() not in cols:
            return False
    for col in _formula_columns(getattr(metric, "sql", "") or ""):
        if col not in cols:
            return False
    return True


def _apply_ontology_overlay(
    metrics: list[MetricDefinition], connection_id: str
) -> list[MetricDefinition]:
    """M24c — unify metrics through the connection's validated ontology.

    The ontology lifts every metrics.json formula into an OntologyMetric, the
    enricher may *correct* the formula, and the validator executes it against the
    live DB. Here we overlay that result onto the global catalog so the generator
    receives the corrected formula — and never receives a formula the validator
    proved wrong on this connection (e.g. the SUM(a)*SUM(b) product-of-sums bug).

    Only applied when the ontology has actually been validated; otherwise the
    global catalog is returned unchanged (conservative — never drop blindly).
    """
    try:
        from aughor.ontology.store import load_latest_ontology
        graph = load_latest_ontology(connection_id)
    except Exception:
        graph = None
    if graph is None or not getattr(graph, "validated", False) or not graph.metrics:
        return metrics

    onto: dict[str, object] = {}
    for om in graph.metrics.values():
        onto[re.sub(r"[^\w]", "_", (om.display_name or om.id).lower())] = om
        onto[om.id] = om

    out: list[MetricDefinition] = []
    for m in metrics:
        om = onto.get(re.sub(r"[^\w]", "_", m.name.lower()))
        if om is None:
            out.append(m)
            continue
        if not getattr(om, "verified", False):
            # An unverified ontology metric means the validator could not confirm THE
            # ONTOLOGY'S formula — which says nothing about the curated catalog formula
            # unless they are the SAME. Drop the catalog metric ONLY when the failed
            # ontology formula matches it (the original SUM(a)*SUM(b) product-of-sums
            # case); otherwise the curated, Finance-approved catalog is highest
            # authority and wins. (Without this, a connection whose ontology carries a
            # wrong templated SUM(total_amount) — e.g. beautycommerce — silently strips
            # the correct catalog revenue/AOV from the LLM prompt.)
            om_sql = (getattr(om, "formula_sql", "") or "").strip()
            if om_sql and om_sql == (m.sql or "").strip():
                continue  # validator tested THIS exact formula and it failed → drop
            out.append(m)
            continue
        new_sql = getattr(om, "formula_sql", "") or ""
        if new_sql.strip() and new_sql.strip() != (m.sql or "").strip():
            m = m.model_copy(update={"sql": new_sql})  # corrected formula
        out.append(m)

    # Additive: inject VERIFIED ontology metrics that have NO catalog counterpart
    # (e.g. a human-authored metric override). The loop above only *corrects* an
    # existing catalog metric's formula — so without this a brand-new human metric
    # binds, persists, and then silently never reaches the prompt. Name-matched
    # metrics are already handled above; only genuinely-new verified ones are added.
    present = {re.sub(r"[^\w]", "_", m.name.lower()) for m in out}
    for om in graph.metrics.values():
        if not getattr(om, "verified", False):
            continue
        key = re.sub(r"[^\w]", "_", (om.display_name or om.id).lower())
        if key in present:
            continue
        note = getattr(om, "verification_note", "") or ""
        out.append(MetricDefinition(
            name=om.id,
            label=om.display_name or om.id,
            sql=om.formula_sql or "",
            unit=getattr(om, "unit", "") or "",
            tables=list(getattr(om, "tables", []) or []),
            caveats=getattr(om, "description", "") or "",
            approved_by=("Human-curated" if note.startswith("human") else ""),
        ))
        present.add(key)
    return out


def _dedupe_by_name(metrics: list) -> list:
    """Collapse duplicate metric NAMES to one survivor (the LAST occurrence,
    matching ``save_metric``'s most-recent-wins upsert) and log each conflict.

    A metric name is its identity — ``save_metric`` upserts by name — so two
    entries sharing a name is an invariant violation. It only surfaces once a
    schema keeps both grains of the same KPI (e.g. ``orders`` AND ``order_items``
    both present), and the damage is real: the catalog gets injected into the
    prompt twice with CONFLICTING formulas, enforcement double-counts, and the
    Trust Receipt collides React keys. We restore the invariant at the
    schema-scoped consumer boundary; the raw file is left untouched (so the
    metrics-management UI still shows the conflict for a human to clean)."""
    by_name: dict[str, object] = {}
    first_seen: list[str] = []
    for m in metrics:
        name = getattr(m, "name", None)
        if name is None:
            continue
        if name in by_name:
            logger.warning(
                "metric catalog has a duplicate name %r — keeping the most recent "
                "formula %r, dropping the earlier %r; clean data/metrics.json (a "
                "name must be unique, or scope these per connection)",
                name, getattr(m, "sql", ""), getattr(by_name[name], "sql", ""),
            )
        else:
            first_seen.append(name)
        by_name[name] = m
    return [by_name[n] for n in first_seen]


def filter_metrics_to_schema(metrics: list, schema_text: str, dedupe: bool = True) -> list:
    """Drop metrics whose declared tables/columns are absent from ``schema_text``,
    then (by default) collapse duplicate names to a single governed definition.
    Public boundary so other modules (the canonical resolver) reuse the schema
    match without importing this module's internals. Returns ``metrics``
    name-deduped when no schema parses (can't prove absence, but a duplicate
    name is always wrong).

    ``dedupe=False`` keeps EVERY surviving grain of a duplicated name. Two
    same-named metrics can be genuinely different formulas at different grains
    (e.g. ``revenue`` over ``orders`` = ``SUM(total_amount)`` vs over
    ``order_items`` = ``SUM(final_price_usd * quantity)``). A query can only match
    one grain, so collapsing here would drop the matching grain and mislabel a
    correct answer as drift — the enforcement path passes ``dedupe=False`` and
    lets ``check_metric_enforcement`` collapse its own verdicts (used > drift)
    instead. Callers that need a single definition per name (prompt, badges,
    canonical resolver) keep the default."""
    _fold = _dedupe_by_name if dedupe else (lambda xs: list(xs))
    if not schema_text:
        return _fold(metrics)
    tables, cols = _schema_tables_and_columns(schema_text)
    if not tables:
        return _fold(metrics)
    return _fold([m for m in metrics if _metric_matches_schema(m, tables, cols)])


def metric_matches_columns(metric, table_cols) -> bool:
    """Whether *metric* is computable on a schema given as ``{table: [columns]}`` — the
    parsed form the explorer's emission gate already caches on the conn, so a caller
    holding the parse skips the schema-text re-parse ``filter_metrics_to_schema``
    would do. Same predicate as the prompt filter: every declared table, dimension and
    formula column must be present. An empty/unparsed mapping can't prove absence → True,
    mirroring ``filter_metrics_to_schema``'s no-tables fallback. Public boundary so the
    trust guards judge a connection by the SAME applicability rule the prompt injects by."""
    tables = {str(t).split(".")[-1].lower() for t in (table_cols or {})}
    if not tables:
        return True
    cols = {str(c).lower() for _cs in (table_cols or {}).values() for c in (_cs or [])}
    return _metric_matches_schema(metric, tables, cols)


def metric_additivity(metric) -> bool:
    """Whether a metric is ADDITIVE (summable across groups, so a share-of-total / Pareto is
    valid). A DECLARED `additivity` field wins; otherwise infer from the formula via the same
    SQL-authoritative gate the answer-summary concentration check uses (an AVG/ratio is
    non-additive even behind an alias). Defaults to non-additive for unknowns — never claim a
    share-of-total we can't justify. Lets a curated metric override a wrong inference."""
    declared = (getattr(metric, "additivity", None) or "").strip().lower().replace("-", "_")
    if declared == "additive":
        return True
    if declared == "non_additive":
        return False
    from aughor.tools.postproc import is_additive_measure
    return is_additive_measure(getattr(metric, "name", "") or "", getattr(metric, "sql", "") or "")


def build_metrics_block(
    path: Path | None = None, schema_text: str = "", connection_id: str = "", question: str = ""
) -> str:
    """
    Return a METRICS CATALOG block to append to the schema context string.
    Returns "" if no metrics are defined.

    M21: now includes governance context — approved-by badge, freshness lag
    warnings, lineage, and NEVER rules from wrong_usage_examples so the LLM
    can't accidentally use a known-bad formula.

    When ``schema_text`` is supplied, metrics whose declared tables/columns are
    absent from that schema are filtered out — metrics are global, so this stops
    one connection's metric from polluting another connection's prompt.

    When ``connection_id`` is supplied, formulas are unified through that
    connection's validated ontology (M24c): corrected formulas are used and
    formulas the validator proved wrong are dropped — and the catalogue is that
    connection's own (its scoped metrics, and the global ones it has not scoped): a
    metric another connection scoped never reaches this prompt, even where the two
    share a table name. The explorer's schema text is built here, and the explorer
    does not look beyond its connection (the user's rule, 2026-09-14).
    """
    metrics = list_metrics(path, connection_id=connection_id or None)
    _tables, _cols = _schema_tables_and_columns(schema_text) if schema_text else (set(), set())
    if _tables:  # only filter when a schema actually parsed (else keep all)
        metrics = [m for m in metrics if _metric_matches_schema(m, _tables, _cols)]
    if connection_id:
        metrics = _apply_ontology_overlay(metrics, connection_id)
        # Re-filter AFTER the overlay: it can INJECT a verified ontology metric that has no
        # catalog counterpart, and that injection is NOT schema-checked — so a stale ontology
        # formula (e.g. revenue = SUM(total_amount) on a connection whose orders has
        # order_value, not total_amount) would leak a missing-column formula into the prompt.
        if _tables:
            metrics = [m for m in metrics if _metric_matches_schema(m, _tables, _cols)]
    metrics = _dedupe_by_name(metrics)  # never inject the same KPI twice with conflicting formulas
    if not metrics:
        return ""

    # R7a — rank the catalog by relevance to the question so the canonical metric is PROMOTED
    # (and, at scale, the long tail trimmed). Fail-open: keeps catalog order when there's no signal.
    _top_relevant = False
    if question:
        from aughor.semantic.metric_retrieval import rank_metrics_for_question
        metrics, _top_relevant = rank_metrics_for_question(question, metrics)

    lines = [
        "METRICS CATALOG (use these exact SQL expressions — do not re-derive"
        + ("; the FIRST is the most relevant to this question):" if _top_relevant else "):"),
    ]
    for m in metrics:
        header = f"  {m.name.upper()} ({m.label}): {m.sql}"
        if m.unit:
            header += f"  [{m.unit}]"
        if m.approved_by:
            header += f"  ✓ {m.approved_by}-approved"
        lines.append(header)
        if m.tables:
            lines.append(f"    Tables: {', '.join(m.tables)}")
        if m.dimensions:
            lines.append(f"    Slice by: {', '.join(m.dimensions)}")
        if m.filters:
            lines.append(f"    Always filter: {'; '.join(m.filters)}")
        if m.caveats:
            lines.append(f"    ⚠ {m.caveats}")
        if not metric_additivity(m):
            lines.append("    ∑ non-additive (a ratio/avg/rate): never sum across groups or "
                         "compute a share-of-total / Pareto on it.")
        if m.freshness_sla:
            lines.append(f"    ⏱ Freshness: {m.freshness_sla}")
        if m.lineage:
            lines.append(f"    Lineage: {'; '.join(m.lineage)}")
        for bad in m.wrong_usage_examples:
            lines.append(f"    ✗ NEVER: {bad}")
    return "\n".join(lines)
