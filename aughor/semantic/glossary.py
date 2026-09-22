"""
Business Glossary — Milestone 1a.

Loads data/glossary.yaml and enriches any raw schema string produced by
DuckDBConnection.get_schema() or PostgresConnection.get_schema() with:
  - Table descriptions and grain
  - Column business definitions, known values, and caveats
  - Known join hints between tables

The enrichment is pure string transformation — no dependency on the DB
connection type. Both schema paths call apply_glossary() at the end.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aughor.tools.table_names import qualify, resolve_in, same_table

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── The two layers (IN, the overlay — the metrics catalogue's split, for the same reason) ─────
#
# The autoseed sidecar took the model-written entries out of `data/glossary.yaml`, but the file
# was still shipped content AND this install's glossary: a person's edit, the explorer's column
# caveats and an agent's grain notes all rewrote it, and every save rewrote it whole. A modified
# tracked file that upstream also edits refuses the fast-forward that would fix it. So the seed
# ships at `data/shipped/glossary.yaml` and is never written, this install's entries go to an
# ignored instance file, and `data/glossary.yaml` is frozen.
_DATA = Path(__file__).parent.parent.parent / "data"
#: The INSTANCE layer. Ignored by `.gitignore`; not authored, so `migrate-state` carries it home.
_DEFAULT_PATH = _DATA / "glossary.instance.yaml"
#: The SEED layer — what the repo ships. Tracked, and read-only to the app.
_SEED_DEFAULT = _DATA / "shipped" / "glossary.yaml"
#: FROZEN. Where every install kept its glossary before the overlay; never written again, never
#: changed upstream (`test_seed_overlay_frozen`). Read, in memory, until this install's first save.
_LEGACY_PATH = _DATA / "glossary.yaml"
#: A byte copy of what `_LEGACY_PATH` shipped as: an entry still equal to it was never this install's.
_LEGACY_BASELINE = _DATA / "shipped" / "glossary.legacy.yaml"

INSTANCE_FORMAT = "aughor.glossary.instance/1"
_ABSENT = object()
_YAML_ERRORS: tuple[type[BaseException], ...] = (yaml.YAMLError,) if yaml is not None else ()


class GlossaryStoreError(RuntimeError):
    """The instance layer cannot be read. Raised, never answered with a thinner glossary."""


def _default_path() -> Path:
    """The INSTANCE file, honouring the ``AUGHOR_GLOSSARY_PATH`` override. The suite points it at a
    throwaway temp copy (conftest) so the autoseed / knowledge-sync WRITES can never mutate live
    data — the non-hermeticity that leaked a glossary edit into two commits (task_213affac).
    Resolved per call so it always reflects the current env."""
    from aughor.db.sqlite_util import resolve_db_path
    return resolve_db_path("AUGHOR_GLOSSARY_PATH", _DEFAULT_PATH)


def _seed_path() -> Path:
    """The SEED file, honouring ``AUGHOR_GLOSSARY_SEED_PATH``."""
    from aughor.db.sqlite_util import resolve_db_path
    return resolve_db_path("AUGHOR_GLOSSARY_SEED_PATH", _SEED_DEFAULT)


# ── Load / Save ───────────────────────────────────────────────────────────────

def generated_path(authored: Path | None = None) -> Path:
    """The sidecar file holding the ``auto_generated: true`` entries.

    Derived from the authored path (``glossary.yaml`` → ``glossary_generated.yaml``) rather
    than configured separately, so it follows ``AUGHOR_GLOSSARY_PATH`` automatically: the
    suite's temp copy gets a temp sidecar, a caller passing an explicit path gets one beside
    it, and there is no second env var to forget to isolate.

    With no path it is where it has ALWAYS resolved — beside `data/glossary.yaml`, which never
    rehomes — not beside the instance, which does: an install that already ran `migrate-state`
    keeps writing its sidecar in the checkout, and must keep reading it there.
    """
    if authored:
        p = Path(authored)
    else:
        env = os.environ.get("AUGHOR_GLOSSARY_PATH")
        p = Path(env) if env else _LEGACY_PATH
    return p.with_name(f"{p.stem.removesuffix('.instance')}_generated{p.suffix}")


def _read_yaml(p: Path) -> dict:
    if not p.exists() or yaml is None:
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def _generated(entry: Any) -> bool:
    """Whether a glossary entry is one a model wrote (autoseed marks it ``auto_generated``)."""
    return isinstance(entry, dict) and bool(entry.get("auto_generated"))


# ── The overlay: seed + instance, by shadowable unit ─────────────────────────

Unit = tuple[str, ...]


def _flatten(doc: dict) -> dict[Unit, Any]:
    """A glossary as its SHADOWABLE units, in order: each table entry, each connection's table
    entry and other keys, each other top-level key. The instance replaces a unit WHOLE — patching
    fields would carry a shipped description's caveat across a person's rewrite of it."""
    out: dict[Unit, Any] = {}
    for k, v in (doc or {}).items():
        if k == "tables":
            out.update({("tables", t): e for t, e in (v or {}).items()})
        elif k == CONNECTIONS_KEY:
            for cid, section in (v or {}).items():
                for sk, sv in (section or {}).items():
                    if sk == "tables":
                        out.update({(CONNECTIONS_KEY, cid, "tables", t): e for t, e in (sv or {}).items()})
                    else:
                        out[(CONNECTIONS_KEY, cid, sk)] = sv
        else:
            out[(k,)] = v
    return out


def _unflatten(units: dict[Unit, Any]) -> dict:
    out: dict = {}
    for u, v in units.items():
        if u[0] == "tables":
            out.setdefault("tables", {})[u[1]] = v
        elif u[0] == CONNECTIONS_KEY and len(u) == 4:
            out.setdefault(CONNECTIONS_KEY, {}).setdefault(u[1], {}).setdefault("tables", {})[u[3]] = v
        elif u[0] == CONNECTIONS_KEY:
            out.setdefault(CONNECTIONS_KEY, {}).setdefault(u[1], {})[u[2]] = v
        else:
            out[u[0]] = v
    return out


@dataclass
class _Instance:
    """This install's layer: the units it holds shadow the seed's, and ``hidden`` are units the
    seed ships that this install removed."""
    units: dict[Unit, Any] = field(default_factory=dict)
    hidden: set[Unit] = field(default_factory=set)
    converted_from: Optional[dict] = None


def derive(doc: dict, against: dict) -> _Instance:
    """What ``doc`` holds of its own, relative to ``against``: a unit equal to it is an echo and
    follows the seed; any other unit is this install's; a unit ``against`` has and ``doc`` lacks
    was removed here, and stays hidden. Read out of the frozen file it is judged against the
    frozen baseline; on a save, against the current seed the writer read its view from."""
    base, mine = _flatten(against), _flatten(doc)
    return _Instance(units={u: v for u, v in mine.items() if base.get(u, _ABSENT) != v},
                     hidden={u for u in base if u not in mine})


def _converted_marker(p: Path) -> Path:
    """Written beside the instance on this install's first save. It outlives the instance file, so
    a MISSING instance afterwards is an error, not a quiet re-read of the frozen file."""
    return p.with_name(p.stem + ".converted" + p.suffix)


def _parse_instance(p: Path) -> _Instance:
    doc = yaml.safe_load(p.read_text()) if yaml is not None else {}
    doc = {} if doc is None else doc
    if isinstance(doc, dict) and doc.get("format") == INSTANCE_FORMAT:
        return _Instance(units=_flatten(doc.get("glossary") or {}),
                         hidden={tuple(h) for h in doc.get("hidden") or []},
                         converted_from=doc.get("converted_from"))
    if isinstance(doc, dict):
        # A plain glossary is a WHOLE one written before the overlay (a named AUGHOR_GLOSSARY_PATH,
        # or a test's own): all of it is this install's, and a shipped unit it lacks was removed
        # there — so it reads as it read alone, and only units shipped since arrive.
        present = _flatten(doc)
        return _Instance(units=present, hidden={u for u in _flatten(_read_yaml(_LEGACY_BASELINE))
                                                if u not in present})
    raise ValueError(f"not a glossary instance file (a {type(doc).__name__})")


def _instance() -> _Instance:
    """This install's layer. Reading it never writes."""
    p = _default_path()
    if p.exists():
        try:
            return _parse_instance(p)
        except (OSError, ValueError, TypeError, AttributeError, *_YAML_ERRORS) as exc:
            logger.error("glossary instance %s is unreadable: %s", p, exc)
            raise GlossaryStoreError(f"the glossary instance file {p} is unreadable ({exc}). It was left "
                                     "as it is: repair it or restore it from a backup — do not delete it, "
                                     "since without it this install's glossary entries are gone") from exc
    if os.environ.get("AUGHOR_GLOSSARY_PATH"):
        # A path somebody named IS the instance; an absent one is empty. Falling through to the
        # checkout's file would hand a test the developer's live glossary.
        return _Instance()
    marker = _converted_marker(p)
    if marker.exists():
        raise GlossaryStoreError(f"this install's glossary was converted into {p} (recorded in {marker}), "
                                 f"and that file is missing. Restore it from a backup; {_LEGACY_PATH} no "
                                 "longer describes this glossary")
    if not _LEGACY_PATH.exists():
        return _Instance()
    return derive(_read_yaml(_LEGACY_PATH), _read_yaml(_LEGACY_BASELINE))


def _merge(seed: dict, inst: _Instance) -> dict:
    """Seed order, each unit the instance holds in the seed's place, hidden units dropped, the
    instance's own units after."""
    units: dict[Unit, Any] = {}
    for u, v in _flatten(seed).items():
        if u in inst.units:
            units[u] = inst.units[u]
        elif u not in inst.hidden:
            units[u] = v
    for u, v in inst.units.items():
        units.setdefault(u, v)
    return _unflatten(units)


def _authored_view() -> dict:
    return _merge(_read_yaml(_seed_path()), _instance())


def _refuse_shipped(p: Path) -> None:
    """The seed, the frozen legacy file and its baseline are never a write target."""
    target = Path(p).resolve()
    for shipped in (_seed_path(), _LEGACY_PATH, _LEGACY_BASELINE):
        if target == Path(shipped).resolve():
            raise GlossaryStoreError(f"{p} is shipped content; the glossary is written to the instance "
                                     f"file ({_default_path()}), never to it")


def _atomic_write_yaml(p: Path, data: dict) -> None:
    """Write-then-rename, so a crash leaves the old file or the new one, never half of either."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def _write_instance(authored: dict) -> None:
    """Persist the authored half of a save as this install's layer: what differs from the seed,
    and what the seed ships that the writer's glossary no longer holds."""
    p = _default_path()
    _refuse_shipped(p)
    current = _instance()                     # raises if a converted instance went missing
    inst = derive(authored, _read_yaml(_seed_path()))
    inst.converted_from = current.converted_from
    first = not p.exists() and not os.environ.get("AUGHOR_GLOSSARY_PATH") and _LEGACY_PATH.exists()
    if first:
        raw = _LEGACY_PATH.read_bytes()
        inst.converted_from = {"path": str(_LEGACY_PATH), "sha256": hashlib.sha256(raw).hexdigest(),
                               "size": len(raw), "at": datetime.now(timezone.utc).isoformat()}
    payload: dict = {"format": INSTANCE_FORMAT, "glossary": _unflatten(inst.units),
                     "hidden": [list(u) for u in sorted(inst.hidden)]}
    if inst.converted_from:
        payload["converted_from"] = inst.converted_from
    _atomic_write_yaml(p, payload)
    if first:
        _atomic_write_yaml(_converted_marker(p), inst.converted_from)
        logger.info("glossary: converted %s into %s (%d units, %d hidden)",
                    _LEGACY_PATH, p, len(inst.units), len(inst.hidden))


def _load_raw(path: Path | None = None) -> dict:
    """The glossary as one dict, re-joined from its two files.

    **Why two files.** 147 of this glossary's 151 entries are written by the ontology
    autodoc — it appends an ``auto_generated: true`` entry per table whenever a connection
    is explored — so merely RUNNING the app rewrote a tracked file (1,435 lines from one
    session). The four hand-authored entries were buried in that churn, and the only ways
    out were to keep committing machine output or to untrack the authored guidance with it.

    Splitting by ``auto_generated`` costs nothing conceptually because that marker was
    ALREADY the weakest layer in :func:`load_merged_glossary`'s precedence. This makes the
    storage agree with the layering that existed: authored terms in a tracked file,
    generated ones in a gitignored sidecar.

    The re-join is per table key, authored winning — the same direction as the merge below,
    so a key present in both reads exactly as it did when both lived in one file. Reading
    is therefore unchanged for every caller, marker and all.

    With no ``path`` the authored half is the overlay: the shipped seed with this install's
    instance laid over it (`_authored_view`). A named ``path`` is read alone, as before.
    """
    authored_p = Path(path) if path else None
    authored = _read_yaml(authored_p) if authored_p else _authored_view()
    generated = _read_yaml(generated_path(authored_p))
    if not generated:
        return authored          # nothing split out (yet, or ever) — byte-identical behaviour

    out = dict(generated)
    out.update({k: v for k, v in authored.items() if k not in ("tables", CONNECTIONS_KEY)})
    tables = dict(generated.get("tables") or {})
    tables.update(authored.get("tables") or {})
    out["tables"] = tables
    # A connection's section is re-joined the same way, per connection and per table: what a model wrote for that
    # connection is in the sidecar, what a person wrote is in the tracked file, and a person's words win.
    sections: dict = {}
    for source in (generated, authored):
        for cid, section in (source.get(CONNECTIONS_KEY) or {}).items():
            section = section or {}
            mine = sections.setdefault(cid, {})
            mine.update({k: v for k, v in section.items() if k != "tables"})
            if "tables" in section or "tables" in mine:
                mine["tables"] = {**(mine.get("tables") or {}), **(section.get("tables") or {})}
    if sections:
        out[CONNECTIONS_KEY] = sections
    return out


#: Top-level key holding per-connection overlays: ``connections: {<conn_id>: {tables: …}}``.
#: Wave O2 — the glossary was keyed by TABLE NAME alone, so two connections could not hold
#: different descriptions of `orders`.
#:
#: An OVERLAY rather than a re-key of every entry, which is the whole migration story: the
#: existing tracked `data/glossary.yaml` is already the global default by construction, so
#: it needed no rewrite. Rewriting 151 entries to stamp `connection: "*"` on each would
#: have been pure churn carrying a data-loss risk, in a repo that has destroyed `data/`
#: twice with non-hermetic writes — and a migration that silently narrowed the glossary to
#: one connection would break every other connection's answers with no error anywhere.
CONNECTIONS_KEY = "connections"


def connection_overlay(data: dict, connection_id: str | None) -> dict:
    """The overlay declared for one connection, or ``{}``."""
    if not connection_id:
        return {}
    conns = (data or {}).get(CONNECTIONS_KEY) or {}
    return conns.get(connection_id) or {}


def load_glossary(path: Path | None = None,
                  connection_id: str | None = None) -> dict:
    """The manual YAML glossary (no dbt or auto-seed merging).

    With ``connection_id``, the connection's overlay is deep-merged over the global
    entries — override-wins, the same direction as every other layer here. Without it the
    return is exactly what it always was, so every existing caller is unchanged.
    """
    data = _load_raw(path)
    overlay = connection_overlay(data, connection_id)
    if not overlay:
        return data
    merged = _deep_merge(data, overlay)
    # The overlay section itself is scaffolding, not content: leaving it in the returned
    # dict would let a caller iterating `tables` also walk every OTHER connection's
    # entries, which is the leak this scoping exists to prevent.
    merged.pop(CONNECTIONS_KEY, None)
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Deep-merge override into base. override wins at every scalar field.
    For nested dicts (e.g. columns), merge recursively.
    Returns a new dict; neither input is mutated.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _align_keys(dbt_tables: dict, yaml_keys: set[str]) -> dict:
    """Re-key dbt entries onto the YAML key space so the two layers can actually meet.

    The layering below unions on EXACT keys. dbt keys by what the manifest declares and the
    YAML by what the connector's ``TABLE:`` header carried, and those disagree on both
    qualification and case — so ``orders`` and ``analytics.orders`` were layered as two
    unrelated tables and a dbt description never reached the entry anyone reads.

    Aligns only when the match is UNAMBIGUOUS. With both ``beauty.orders`` and
    ``ecommerce.orders`` in the YAML, a bare dbt ``orders`` could belong to either; picking
    one would attach a description to the wrong table, which is the bug this is fixing. Such
    an entry keeps its own key — visible and separate rather than silently misfiled. A dbt
    node that declares its schema is already qualified and matches exactly, so the ambiguous
    case only arises for manifests that omit it.
    """
    aligned: dict = {}
    for key, entry in dbt_tables.items():
        if key not in yaml_keys:
            matches = [y for y in yaml_keys if same_table(y, key, schema_strict=True)]
            if len(matches) == 1:
                key = matches[0]
        aligned[key] = entry
    return aligned


def _connection_layers(path: Path | None, connection_id: str) -> tuple[dict, dict, dict]:
    """``(glossary, a model's words, a person's words)`` as ONE connection reads them.

    A person's words are the global entries with the connection's own section merged over them (O2 — the specific
    answer wins). A model's words are only those written for THIS connection: a model-written global entry names no
    connection, so it may describe another connection's table of the same name, and no connection reads it until
    autoseed writes it again for the connection that does. The user's rule (2026-09-14): the explorer does not look
    beyond its connection.
    """
    data = _load_raw(path)
    section = connection_overlay(data, connection_id)
    own = section.get("tables") or {}
    peoples = {t: e for t, e in (data.get("tables") or {}).items() if not _generated(e)}
    for table, entry in own.items():
        if not _generated(entry):
            peoples[table] = _deep_merge(peoples.get(table) or {}, entry)
    models = {t: e for t, e in own.items() if _generated(e)}
    rest = _deep_merge({k: v for k, v in data.items() if k not in ("tables", CONNECTIONS_KEY)},
                       {k: v for k, v in section.items() if k != "tables"})
    return {**rest, "tables": {**models, **peoples}}, models, peoples


def load_merged_glossary(path: Path | None = None,
                         connection_id: str | None = None) -> dict:
    """
    Return the fully merged glossary with three-layer precedence:

        manual YAML  >  dbt manifest  >  auto-seed (auto_generated: true in YAML)

    The dbt layer is skipped if AUGHOR_DBT_MANIFEST is not configured.
    Entries written by autoseed (auto_generated: true) are treated as the
    weakest layer — dbt and manual YAML both override them.

    With ``connection_id`` the glossary is that connection's (`_connection_layers`): a person's
    global words, the connection's own section, and a model's words written for that
    connection only — never a model-written global entry, which names no connection.
    """
    from aughor.semantic.dbt import load_dbt_glossary

    dbt = load_dbt_glossary()
    if connection_id:
        yaml_data, auto_tables, manual_tables = _connection_layers(path, connection_id)
    else:
        yaml_data = load_glossary(path)
        yaml_tables = yaml_data.get("tables", {})
        # Split YAML entries: auto-generated (weak) vs manually provided (strong)
        auto_tables = {t: e for t, e in yaml_tables.items() if e.get("auto_generated")}
        manual_tables = {t: e for t, e in yaml_tables.items() if not e.get("auto_generated")}
    dbt_tables:    dict = _align_keys(dbt.get("tables", {}) if dbt else {},
                                      set(auto_tables) | set(manual_tables))

    all_names = set(auto_tables) | set(dbt_tables) | set(manual_tables)
    merged_tables: dict = {}

    for table in all_names:
        # Layer 1 (weakest): auto-seed
        entry: dict = dict(auto_tables.get(table, {}))
        # Layer 2: dbt overrides auto-seed
        if table in dbt_tables:
            entry = _deep_merge(entry, dbt_tables[table])
        # Layer 3 (strongest): manual YAML overrides everything
        if table in manual_tables:
            entry = _deep_merge(entry, manual_tables[table])
        # The merged entry's `auto_generated` must name the layer that WON, not the layer
        # it started from. `_deep_merge` only overrides keys the override supplies, so a
        # hand-written entry that does not bother to say `auto_generated: false` used to
        # inherit `true` from the auto layer underneath it — and any reader treating the
        # flag as "this text is machine-written" (the P2 warrant class does) would then
        # report authored definitions as generated. The RAW store is untouched: autoseed
        # still reads it to decide what to re-seed.
        if table in manual_tables or table in dbt_tables:
            entry.pop("auto_generated", None)
        merged_tables[table] = entry

    result = dict(yaml_data)
    result["tables"] = merged_tables
    return result


def lookup_table(tables_meta: dict, table: str, schema: str | None = None) -> dict:
    """The glossary entry for a table, tolerant of qualified-vs-bare keys. {} when absent.

    THE SCOPE SEAM. The store is keyed by whatever the ``TABLE:`` header carried when the
    entry was written, and the connectors disagree — DuckDB qualifies, Postgres/SQLite/
    Snowflake/MySQL/BigQuery don't. So the file holds BOTH forms (81 bare and 70 qualified
    keys, 61 colliding leaves: ``orders`` alone has five competing entries). An exact-string
    ``.get()`` therefore never found a qualified entry from a bare header, and vice versa —
    every schema's description silently overwrote the last one's.

    Resolution: qualify the lookup with the caller's schema, then match exact-first,
    schema-tolerant-second via the canonical ``resolve_in`` (``tools/table_names.py``, which
    exists precisely to stop this class of bug recurring). ``schema_strict=True`` means
    ``beauty.orders`` can never answer for ``ecommerce.orders`` — while a BARE key still
    matches any schema, so the pre-existing unqualified entries keep working as fallbacks
    until a scoped write supersedes them."""
    if not tables_meta:
        return {}
    return resolve_in(tables_meta, qualify(table, schema), schema_strict=True) or {}


def canonical_key(table: str, schema: str | None = None) -> str:
    """The key a glossary WRITE should use: schema-qualified whenever the schema is known.

    Canonical on write, tolerant on read. New entries stop colliding across schemas; old
    bare entries are left alone rather than migrated, because there is no way to know which
    schema an unqualified entry was written for — guessing would move one schema's
    description under another's name, which is the bug, not the fix."""
    return qualify(table, schema)


def _write_yaml(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def save_glossary(data: dict, path: Path | None = None) -> None:
    """Persist the glossary, routing each table entry to the file that owns it.

    ``auto_generated: true`` → the gitignored sidecar; everything else → the authored layer,
    which with no ``path`` is this install's INSTANCE (what differs from the shipped seed, and
    what the seed ships that ``data`` no longer holds) and never the tracked file. Every caller
    (``update_table``, ``update_column``, the autoseed writer) is unchanged: they still hand
    over one dict, and the partition happens here, in the one place that already knew how to
    write. A named ``path`` is written whole, as before.

    The sidecar is only created when there is something to put in it — a deployment that
    never runs the autodoc keeps exactly one file, as before.
    """
    if yaml is None:
        raise RuntimeError("PyYAML is required: uv add pyyaml")
    authored_p = Path(path) if path else None
    tables = (data or {}).get("tables") or {}

    generated = {t: e for t, e in tables.items() if _generated(e)}
    authored = {t: e for t, e in tables.items() if t not in generated}

    # A connection's section splits the same way: what a model wrote for THAT connection goes to the sidecar under the
    # same connection, and what a person wrote stays in the tracked file.
    sections_generated: dict = {}
    sections_authored: dict = {}
    for cid, section in ((data or {}).get(CONNECTIONS_KEY) or {}).items():
        section = section or {}
        own = section.get("tables") or {}
        written = {t: e for t, e in own.items() if _generated(e)}
        if written:
            sections_generated[cid] = {"tables": written}
        kept = {k: v for k, v in section.items() if k != "tables"}
        if "tables" in section and (len(written) < len(own) or not kept):
            kept["tables"] = {t: e for t, e in own.items() if t not in written}
        if kept and (kept.get("tables") or any(k != "tables" for k in kept) or not written):
            sections_authored[cid] = kept

    rest: dict = {}
    for k, v in (data or {}).items():
        if k == "tables":
            continue
        if k == CONNECTIONS_KEY:
            if sections_authored:
                rest[k] = sections_authored
            continue
        rest[k] = v
    authored_doc = ({**rest, "tables": authored} if tables or rest or sections_generated
                    else dict(data or {}))
    if authored_p is None:
        _write_instance(authored_doc)     # the overlay: never the tracked file
    else:
        _refuse_shipped(authored_p)
        _write_yaml(authored_p, authored_doc)

    gen_p = generated_path(authored_p)
    if generated or sections_generated:
        payload: dict = {"tables": generated}
        if sections_generated:
            payload[CONNECTIONS_KEY] = sections_generated
        _write_yaml(gen_p, payload)
    elif gen_p.exists():
        # The last generated entry was removed — leaving a stale sidecar would make it
        # reappear on the next read.
        _write_yaml(gen_p, {"tables": {}})


def update_table(table: str, description: str | None = None, grain: str | None = None,
                 joins: list[str] | None = None, path: Path | None = None,
                 schema: str | None = None, owner: str | None = None) -> None:
    """Upsert table-level glossary entry, keyed per schema when one is known. ``owner`` (CB-3)
    is the person or team responsible, free text a person may later link to a principal."""
    data = _load_raw(path)
    tables = data.setdefault("tables", {})
    entry = tables.setdefault(canonical_key(table, schema), {})
    if owner is not None:
        entry["owner"] = " ".join(owner.split())
    if description is not None:
        entry["description"] = description
    if grain is not None:
        entry["grain"] = grain
    if joins is not None:
        entry["joins"] = joins
    save_glossary(data, path)


def update_column(table: str, column: str, description: str | None = None,
                  values: str | None = None, caveats: str | None = None,
                  path: Path | None = None, schema: str | None = None,
                  owner: str | None = None) -> None:
    """Upsert column-level glossary entry, keyed per schema when one is known. ``owner`` (CB-3) as
    on a table."""
    data = _load_raw(path)
    col_entry = (
        data.setdefault("tables", {})
            .setdefault(canonical_key(table, schema), {})
            .setdefault("columns", {})
            .setdefault(column, {})
    )
    if owner is not None:
        col_entry["owner"] = " ".join(owner.split())
    if description is not None:
        col_entry["description"] = description
    if values is not None:
        col_entry["values"] = values
    if caveats is not None:
        col_entry["caveats"] = caveats
    save_glossary(data, path)


# ── Enrichment ────────────────────────────────────────────────────────────────

def apply_glossary(schema_str: str, path: Path | None = None, schema: str | None = None,
                   connection_id: str | None = None) -> str:
    """
    Enrich a raw schema string with business glossary annotations.

    Operates line-by-line:
    - TABLE: lines get description, grain, and join hints appended
    - Column lines get description, known values, and caveats appended

    Falls back to the unmodified schema_str if the glossary is empty or
    the YAML library is not installed.

    ``connection_id`` is the connection whose schema this is: its words are a person's global
    entries and that connection's own, never a model's words written for another connection.
    """
    glossary = load_merged_glossary(path, connection_id)
    tables_meta: dict[str, Any] = glossary.get("tables", {})
    if not tables_meta:
        return schema_str

    lines = schema_str.splitlines()
    out: list[str] = []
    current_table: str | None = None

    for line in lines:
        # Detect TABLE: header
        table_match = re.match(r"^TABLE:\s+([\w.]+)", line)
        if table_match:
            current_table = table_match.group(1)
            out.append(line)
            meta = lookup_table(tables_meta, current_table, schema)
            if meta.get("description"):
                out.append(f"  -- {meta['description']}")
            if meta.get("grain"):
                out.append(f"  -- Grain: {meta['grain']}")
            continue

        # Detect column lines (two leading spaces, then identifier + type)
        col_match = re.match(r"^  (\w+)\s+(\S+)(.*)", line)
        if col_match and current_table:
            col_name = col_match.group(1)
            col_match.group(3)
            meta = lookup_table(tables_meta, current_table, schema)
            col_meta = (meta.get("columns") or {}).get(col_name, {})

            annotation_parts: list[str] = []
            if col_meta.get("description"):
                annotation_parts.append(col_meta["description"])
            if col_meta.get("values"):
                annotation_parts.append(f"Values: {col_meta['values']}")
            if col_meta.get("caveats"):
                annotation_parts.append(f"⚠ {col_meta['caveats']}")

            if annotation_parts:
                # Append annotation inline, preserving existing hints
                annotation = " | ".join(annotation_parts)
                # Strip any existing inline hint so we don't double-up
                base_line = re.sub(r"\s+\[.*\]$", "", line)
                out.append(f"{base_line}  [{annotation}]")
            else:
                out.append(line)
            continue

        # Detect blank line after a table block — emit join hints before it
        if line == "" and current_table:
            meta = lookup_table(tables_meta, current_table, schema)
            joins = meta.get("joins") or []
            if joins:
                out.append(f"  -- Joins: {'; '.join(joins)}")
            current_table = None  # reset after blank line
            out.append(line)
            continue

        out.append(line)

    # Flush join hints if schema ended without a trailing blank line
    if current_table:
        meta = lookup_table(tables_meta, current_table, schema)
        joins = meta.get("joins") or []
        if joins:
            out.append(f"  -- Joins: {'; '.join(joins)}")

    return "\n".join(out)
