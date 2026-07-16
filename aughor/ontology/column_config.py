"""R11 — per-column semantic config: ``{visible, sample, index}`` — persisted + editable.

The Databricks ``column-configs`` analog (wire study #2,
docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md): at canvas birth Databricks
persists a per-(table, column) decision — ``is_visible`` / ``is_sampling`` /
``is_indexing`` — that the whole downstream stack reads. This module is Aughor's
version, with two deliberate differences:

  • **Deterministic defaults, no LLM.** Databricks spends 13.8 s of silent model
    time deciding the flags; our profiler already knows the answer. Defaults are
    computed from ``ColumnProfile`` facts (semantic_type / null_rate / name), and
    the ``index`` default is exactly the R5 value-sample gate — persisted and
    overridable instead of recomputed each build.
  • **Human-override-wins, rebuild-proof.** Stored OUTSIDE the fingerprint caches,
    keyed by ``{conn}/{schema}`` only (the ``ontology/overrides.py`` pattern), as a
    readable YAML file per table — the runtime store IS the version-controllable,
    hand-editable artifact. Entries with ``source: human`` are never overwritten by
    a defaults refresh.

The three flags, and who consumes them (all consumption is gated by the
``ontology.column_config`` flag — default-off, byte-identical when off):

  visible — render the column into agent prompt schemas at all. ``False`` prunes
      the column line (and its value enumeration) from the schema text — DB-info
      compression at the column grain. Consumed by
      ``tools/schema.apply_schema_enrichment`` via
      :func:`apply_column_config_to_schema`.
  sample — enumerate the column's values in the schema context. Consumed by
      ``tools/schema.inject_value_annotations`` (profile-backed values) and the
      same pruning pass (first-run render enumerations).
  index — build the R5 offline value index over the column. Consumed by the
      profiler's value-sample capture gate (``build_column_profiles``) and by
      ``semantic/answer_resolution`` (retires already-persisted samples when a
      human turns a column off).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel

_DEFAULT_ROOT = Path(__file__).parent.parent.parent / "data" / "ontology_column_config"


def _root() -> Path:
    """Store root; ``AUGHOR_COLUMN_CONFIG_ROOT`` overrides (test hermeticity)."""
    env = os.environ.get("AUGHOR_COLUMN_CONFIG_ROOT")
    return Path(env) if env else _DEFAULT_ROOT


# ── deterministic default policy ─────────────────────────────────────────────
# The name/type gates mirror tools/profiler.py (_TEXT_TYPES / _KEY_PATTERN /
# _ENTITY_DIM_RE) — duplicated, not imported, so this module stays import-light
# and the profiler can consult it lazily without a cycle. Keep them in sync.

_TEXT_RE = re.compile(r"\b(VARCHAR|TEXT|STRING|CHAR|BPCHAR)\b", re.IGNORECASE)
_KEY_RE = re.compile(
    r"(_id|_key|_code|_num|_number|_identifier|_pk|_uuid|_guid)$", re.IGNORECASE
)
_ENTITY_RE = re.compile(
    r"(name|platform|brand|franchise|company|merchant|vendor|segment|category|"
    r"channel|region|country|city|store|entity|product|customer|owner|type|status|label)",
    re.IGNORECASE,
)

# Free-text blob names safe to hide by default. Deliberately tight: `description`
# and `*_reason` style columns are often load-bearing (LIKE filters, honesty about
# cancellations) and stay visible; a human can hide them per connection.
_FREETEXT_RE = re.compile(
    r"(comment|notes?$|_notes?_|memo|remarks|free_?text|_raw$|^raw_|payload|"
    r"_json$|_xml$|blob|user_?agent)",
    re.IGNORECASE,
)

# A column with (almost) no values at all — nothing to render, sample, or index.
_DEAD_NULL_RATE = 0.999


class ColumnFlags(BaseModel):
    """One column's config entry, with provenance.

    ``source`` is the override-wins switch: ``default`` entries are refreshed on
    every intelligence build (the policy may improve); ``human`` entries are never
    touched by a refresh and always win.
    """
    visible: bool = True
    sample: bool = True
    index: bool = False
    source: str = "default"          # "default" | "human"
    edited_at: str = ""
    note: str = ""

    def policy(self) -> tuple[bool, bool, bool]:
        """The three decisions, for change detection during a defaults refresh."""
        return (self.visible, self.sample, self.index)


def default_flags(
    *,
    name: str,
    dtype: str = "",
    semantic_type: str = "",
    is_fk: bool = False,
    null_rate: float = 0.0,
) -> ColumnFlags:
    """The deterministic per-column policy (no model, no I/O).

    index  — exactly the R5 value-sample gate: text-typed, entity-name-ish, not
             key-named. (The 30<distinct≤2000 cardinality band stays a live
             capture constraint in the profiler, not policy — a column's
             cardinality moves with the data; its nature doesn't.)
    sample — true categorical dimensions only (the inject_value_annotations gate).
    visible — everything except dead (all-null) columns and free-text blobs.
    """
    lname = (name or "").lower()
    index = bool(
        _TEXT_RE.search(dtype or "")
        and not _KEY_RE.search(lname)
        and _ENTITY_RE.search(lname)
    )
    sample = bool(semantic_type in ("dimension", "flag", "ordinal") and not is_fk)
    visible = not (
        (null_rate or 0.0) >= _DEAD_NULL_RATE
        or (semantic_type == "text" and _FREETEXT_RE.search(lname))
    )
    return ColumnFlags(visible=visible, sample=sample, index=index)


def defaults_from_profiles(column_profiles: dict) -> dict[str, dict[str, ColumnFlags]]:
    """Compute the default config for every profiled column.

    ``column_profiles`` is the profiler cache shape — ``{"table.column":
    ColumnProfile}`` — duck-typed (attrs or dict) like doctree's adapter, so this
    stays decoupled from the profiler class."""
    out: dict[str, dict[str, ColumnFlags]] = {}
    for key, cp in (column_profiles or {}).items():
        def g(attr: str, default: Any = None, _cp=cp):
            return _cp.get(attr, default) if isinstance(_cp, dict) else getattr(_cp, attr, default)
        table = g("table") or (key.split(".", 1)[0] if "." in key else "")
        column = g("column") or (key.split(".", 1)[1] if "." in key else key)
        if not table or not column:
            continue
        out.setdefault(table, {})[column] = default_flags(
            name=column,
            dtype=g("dtype", "") or "",
            semantic_type=g("semantic_type", "") or "",
            is_fk=bool(g("is_fk", False)),
            null_rate=float(g("null_rate", 0.0) or 0.0),
        )
    return out


# ── filesystem store (one readable YAML per table) ───────────────────────────

def _safe(s: str) -> str:
    """Filesystem-safe slug (same rule as overrides.py)."""
    return re.sub(r"[^A-Za-z0-9_.=-]", "_", s or "default")


def _dir(conn: str, schema: str) -> Path:
    return _root() / _safe(conn) / _safe(schema)


def _path(conn: str, schema: str, table: str) -> Path:
    return _dir(conn, schema) / f"{_safe(table)}.yaml"


def save_table_config(conn: str, schema: str, table: str, columns: dict[str, ColumnFlags]) -> None:
    """Write (replace) one table's config file. Best-effort — never raises."""
    try:
        p = _path(conn, schema, table)
        p.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "table": table,
            "columns": {c: columns[c].model_dump(exclude_defaults=False) for c in sorted(columns)},
        }
        p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "column-config save is best-effort",
                 counter="ontology.column_config", conn_id=conn or None)


def load_table_config(conn: str, schema: str, table: str) -> dict[str, ColumnFlags]:
    """Read one table's config file → {column: ColumnFlags}; {} when absent/corrupt."""
    try:
        p = _path(conn, schema, table)
        if not p.exists():
            return {}
        doc = yaml.safe_load(p.read_text()) or {}
        cols = doc.get("columns") or {}
        return {c: ColumnFlags.model_validate(v or {}) for c, v in cols.items()}
    except Exception:
        return {}


def load_column_configs(conn: str, schema: str) -> dict[tuple[str, str], ColumnFlags]:
    """Read every table config under {conn}/{schema} → {(table, column): ColumnFlags}."""
    out: dict[tuple[str, str], ColumnFlags] = {}
    base = _dir(conn, schema)
    if not base.exists():
        return out
    for f in sorted(base.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text()) or {}
            table = doc.get("table") or f.stem
            for c, v in (doc.get("columns") or {}).items():
                out[(table, c)] = ColumnFlags.model_validate(v or {})
        except Exception as exc:
            # One hand-edited/corrupt file must not blind the others.
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"column-config file unreadable, skipped: {f.name}",
                     counter="ontology.column_config", conn_id=conn or None)
            continue
    return out


def ensure_column_configs(
    conn: str, schema: str, column_profiles: dict
) -> dict[tuple[str, str], ColumnFlags]:
    """Refresh persisted defaults from fresh profiles and return the effective config.

    Human entries (``source: human``) are preserved verbatim; ``default`` entries
    are recomputed and rewritten only when the policy outcome changed (so an
    untouched schema build is a no-op on disk). Columns that exist on disk but not
    in the profiles (unprofiled tables, prior fingerprints) are kept. Never raises.
    """
    try:
        defaults = defaults_from_profiles(column_profiles)
        effective: dict[tuple[str, str], ColumnFlags] = {}
        for table, cols in defaults.items():
            stored = load_table_config(conn, schema, table)
            merged: dict[str, ColumnFlags] = dict(stored)
            changed = False
            for col, dflt in cols.items():
                cur = merged.get(col)
                if cur is not None and cur.source == "human":
                    continue
                if cur is None or cur.policy() != dflt.policy():
                    merged[col] = dflt
                    changed = True
            if changed:
                save_table_config(conn, schema, table, merged)
            for col, fl in merged.items():
                effective[(table, col)] = fl
        # Tables on disk that this build didn't profile still count.
        for key, fl in load_column_configs(conn, schema).items():
            effective.setdefault(key, fl)
        return effective
    except Exception:
        return {}


def set_column_flags(
    conn: str,
    schema: str,
    table: str,
    column: str,
    *,
    visible: Optional[bool] = None,
    sample: Optional[bool] = None,
    index: Optional[bool] = None,
    note: str = "",
) -> ColumnFlags:
    """Apply a human edit to one column (only the passed flags change) and persist.

    The entry becomes ``source: human`` — a defaults refresh will never touch it
    again. Unknown columns get a fresh entry (all-default flags + the edit)."""
    cols = load_table_config(conn, schema, table)
    cur = cols.get(column) or ColumnFlags()
    updates: dict[str, Any] = {
        "source": "human",
        "edited_at": datetime.now(timezone.utc).isoformat(),
    }
    if visible is not None:
        updates["visible"] = visible
    if sample is not None:
        updates["sample"] = sample
    if index is not None:
        updates["index"] = index
    if note:
        updates["note"] = note
    cols[column] = cur.model_copy(update=updates)
    save_table_config(conn, schema, table, cols)
    return cols[column]


# ── consumer helpers ─────────────────────────────────────────────────────────

def hidden_columns(config: dict[tuple[str, str], ColumnFlags]) -> set[tuple[str, str]]:
    return {k for k, f in config.items() if not f.visible}


def sample_disabled(config: dict[tuple[str, str], ColumnFlags]) -> set[tuple[str, str]]:
    """Columns whose values must not be enumerated (sample off, or hidden entirely)."""
    return {k for k, f in config.items() if not f.sample or not f.visible}


def load_index_disabled(conn: str) -> set[tuple[str, str]]:
    """(table, column) pairs with ``index: false``, merged across every schema of
    ``conn`` — the consumer-side retire filter for already-persisted value samples
    (``answer_resolution``), which loads samples per-connection without a schema."""
    out: set[tuple[str, str]] = set()
    base = _root() / _safe(conn)
    if not base.exists():
        return out
    for schema_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for key, fl in load_column_configs(conn, schema_dir.name).items():
            if not fl.index:
                out.add(key)
    return out


# Matches the raw renderer's line shapes (db/schema_render.py): a column line is
# two spaces + name + 2+ spaces + type; a value enumeration is `  -- col  [v, …]`.
_COL_LINE = re.compile(r"^\s{2}(.+?)\s{2,}\S")
_VALUES_LINE = re.compile(r"^\s{2}--\s+(\S+)\s+\[")
_TABLE_LINE = re.compile(r"^TABLE:\s+([\w.]+)")
_STOP_LINE = re.compile(
    r"^(DETECTED JOIN|NO DIRECT JOIN|METRICS CATALOG|Date range|GLOSSARY|JOIN HINTS|RELEVANT)"
)


def apply_column_config_to_schema(
    schema_str: str, config: dict[tuple[str, str], ColumnFlags]
) -> str:
    """Prune a rendered schema string per the config — a pure string transform.

    Drops the column line (name+type+inline annotation) of every non-visible
    column, and the ``-- col [values]`` enumeration line of every sample-disabled
    or hidden column. Tables are matched by bare name so schema-qualified
    ``TABLE:`` headers still match config keys. Everything else passes through
    byte-identical; an empty/irrelevant config is a no-op."""
    hidden = {(t.lower(), c.lower()) for (t, c) in hidden_columns(config)}
    no_sample = {(t.lower(), c.lower()) for (t, c) in sample_disabled(config)}
    if not hidden and not no_sample:
        return schema_str

    out: list[str] = []
    table: Optional[str] = None
    for line in schema_str.splitlines():
        tm = _TABLE_LINE.match(line)
        if tm:
            table = tm.group(1).split(".")[-1].lower()
            out.append(line)
            continue
        if _STOP_LINE.match(line):
            table = None
            out.append(line)
            continue
        if table:
            vm = _VALUES_LINE.match(line)
            if vm and (table, vm.group(1).lower()) in no_sample:
                continue
            if not line.lstrip().startswith("--"):
                cm = _COL_LINE.match(line)
                if cm and (table, cm.group(1).strip().lower()) in hidden:
                    continue
        out.append(line)
    return "\n".join(out)
