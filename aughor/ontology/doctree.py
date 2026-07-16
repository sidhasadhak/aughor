"""Ontology docs as a build artifact (R8) — the autodoc architecture on existing stores.

*Understanding is a build artifact.* Project the already-built :class:`OntologyGraph`
(the deterministic column→table rollup Aughor computes from profiles + grain + joins) into a
persisted, **Merkle-checksummed** doc tree — column → table → schema → connection — where every
parent summarizes its children's *summaries*, never their raw content. That bottom-up rollup is
the ReFoRCE "DB-info compression is lever #1" finding made **persistent**: a wide schema's
understanding is compiled once and re-read cheaply, and only the nodes whose inputs actually
changed are rebuilt.

What this module ships (deterministic-first, no model in the core):

* a file-per-node artifact (mirrors ``recommendations.py`` / ``overrides.py``) under
  ``data/ontology_docs/{conn}/{schema}/`` — git-reviewable, one YAML per node;
* **Merkle checksums** (a node's checksum = hash of its own content-hash + its children's
  checksums) driving an **incremental rebuild** that reuses unchanged nodes and *counts the
  cache hits* (so "it re-used N nodes" is verifiable, not assumed — verify-features-actually-ran);
* deterministic per-table **"3 analyst questions"** seeded from the table's measures / dimensions
  / time / grain — suggestion-chip + overview-seed material;
* **table ignore-globs** (``tmp_%``, ``_airbyte_%``, ``dbt_%``, …) with the dropped tables
  *logged*, never silently skipped;
* an **estimate-then-confirm** dry-run that walks the identical pipeline and reports node/token
  counts before any (future) LLM spend.

Deferred (see the R8 follow-ons): embedding the docs into the knowledge store with FQN
provenance (the retrieval consumer); optional per-node LLM enrichment + width-routing; a
clickable Hub deep-link (the web app has no URL router yet — the FQN is the provenance today).
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from aughor.ontology.models import OntologyEntity, OntologyGraph

logger = logging.getLogger("aughor.ontology.doctree")

_ROOT = Path(__file__).parent.parent.parent / "data" / "ontology_docs"

# Tables that are pipeline scaffolding, not business entities — documented understanding
# should skip them. SQL-LIKE-style globs (``%`` ⇒ ``*``) matched case-insensitively against the
# bare table name. An operator can pass their own list; these are the sane defaults.
_DEFAULT_IGNORE = (
    "tmp_%", "%_tmp", "temp_%", "%_temp",
    "_airbyte_%", "airbyte_%",
    "dbt_%", "stg_%", "%_stg", "staging_%",
    "_scratch%", "scratch_%",
)


class DocNode(BaseModel):
    """One node of the doc tree — a column, table, schema, or connection.

    ``content_hash`` is the hash of this node's OWN inputs (its facts); ``checksum`` is the
    Merkle hash over ``content_hash`` + the children's checksums. A node is unchanged iff both
    its content_hash and every child checksum are unchanged — the incremental-rebuild key.
    """
    kind: str                                   # column | table | schema | connection
    fqn: str                                    # conn / schema / schema.table / schema.table.column
    title: str
    summary: str                                # deterministic rolled-up prose
    facts: dict = Field(default_factory=dict)   # structured signals (grain, row_count, semantic_type, …)
    questions: list[str] = Field(default_factory=list)   # 3 analyst questions (tables only)
    children: list[str] = Field(default_factory=list)    # child fqns
    content_hash: str = ""                      # hash of this node's own inputs (the leaf epoch)
    checksum: str = ""                          # Merkle: hash(content_hash + sorted child checksums)
    child_checksums: dict = Field(default_factory=dict)  # child fqn → checksum (for incremental diff)
    provenance: dict = Field(default_factory=dict)


class DocTree(BaseModel):
    connection_id: str
    schema_name: str = ""
    root_checksum: str = ""                     # the connection node's checksum
    nodes: dict[str, DocNode] = Field(default_factory=dict)   # fqn → node
    built_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # verify-features-actually-ran: how the incremental rebuild actually behaved.
    stats: dict = Field(default_factory=dict)   # {tables, columns, cache_hits, rebuilt, skipped_tables}

    def tables(self) -> list[DocNode]:
        return [n for n in self.nodes.values() if n.kind == "table"]


# ── checksums ────────────────────────────────────────────────────────────────

def _hash(*parts: Any) -> str:
    h = hashlib.md5()  # noqa: S324 — content-addressing, not security
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _merkle(content_hash: str, child_checksums: dict) -> str:
    """A node's checksum = hash of its own content + its children's checksums (sorted for
    determinism). Parents fold child *checksums*, never child content — the Merkle property that
    lets an unchanged subtree short-circuit a rebuild."""
    return _hash(content_hash, *[child_checksums[k] for k in sorted(child_checksums)])


# ── ignore globs ─────────────────────────────────────────────────────────────

def _like_to_glob(pat: str) -> str:
    return pat.replace("%", "*")


def _ignored(table: str, ignore: tuple[str, ...]) -> bool:
    bare = table.split(".")[-1].lower()
    return any(fnmatch.fnmatch(bare, _like_to_glob(p.lower())) for p in ignore)


# ── deterministic per-node summaries + facts ────────────────────────────────

def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _column_facts(prop, config_flags=None) -> dict:
    f = {
        "data_type": prop.data_type or "",
        "semantic_type": prop.semantic_type or "",
        "is_primary_key": bool(prop.is_primary_key),
        "is_foreign_key": bool(prop.is_foreign_key),
        "null_rate": round(prop.null_rate or 0.0, 3),
        "unit": prop.unit or "",
        "value_interpretation": prop.value_interpretation or "",
        "measure_grain": prop.measure_grain or "",
    }
    if prop.sample_values:
        f["sample_values"] = list(prop.sample_values[:8])
    for k in ("p25", "p50", "p75", "distribution_shape"):
        v = getattr(prop, k, None)
        if v not in (None, ""):
            f[k] = v
    # R11 — stamp the per-column config into the facts (docs describe hidden
    # columns rather than dropping them). Folding into the facts means the values
    # flow into the node's content_hash, so a config edit Merkle-invalidates
    # exactly the touched column node on the next incremental build.
    if config_flags is not None:
        f["visible"] = bool(getattr(config_flags, "visible", True))
        f["sample"] = bool(getattr(config_flags, "sample", True))
        f["index"] = bool(getattr(config_flags, "index", False))
    return f


def _column_summary(prop, facts: dict) -> str:
    bits = [f"`{prop.name}`"]
    typ = " / ".join(x for x in (facts["data_type"], facts["semantic_type"]) if x)
    if typ:
        bits.append(f"({typ})")
    tail = []
    if facts.get("value_interpretation"):
        tail.append(facts["value_interpretation"])
    if facts.get("unit"):
        tail.append(facts["unit"])
    if facts.get("measure_grain"):
        tail.append(f"grain {facts['measure_grain']}")
    if facts["is_primary_key"]:
        tail.append("primary key")
    elif facts["is_foreign_key"]:
        tail.append("foreign key")
    if facts["null_rate"] > 0:
        tail.append(f"{_pct(facts['null_rate'])} null")
    if facts.get("visible") is False:
        tail.append("hidden from agent prompts")
    if facts.get("sample_values"):
        tail.append("e.g. " + ", ".join(str(v) for v in facts["sample_values"][:4]))
    if tail:
        bits.append("— " + "; ".join(tail))
    return " ".join(bits)


def _measures(entity: OntologyEntity) -> list:
    return [p for p in entity.properties.values() if p.semantic_type == "measure"]


def _dimensions(entity: OntologyEntity) -> list:
    return [p for p in entity.properties.values()
            if p.semantic_type in ("dimension", "flag", "ordinal")
            and not p.is_primary_key and not p.is_foreign_key]


def _timestamps(entity: OntologyEntity) -> list:
    return [p for p in entity.properties.values() if p.semantic_type == "timestamp"]


def _label(prop) -> str:
    return prop.display_name or prop.name


def _analyst_questions(entity: OntologyEntity) -> list[str]:
    """Three questions an analyst would ask of this table — deterministic, seeded from the
    entity's own measures / dimensions / time / lifecycle. Suggestion-chip + overview-seed
    material; never fabricates columns it doesn't have."""
    name = entity.display_name or entity.id
    plural = name if name.endswith("s") else name + "s"
    measures, dims, times = _measures(entity), _dimensions(entity), _timestamps(entity)
    out: list[str] = []

    if measures and dims:
        out.append(f"What is total {_label(measures[0])} by {_label(dims[0])}?")
    if measures and times:
        out.append(f"How has {_label(measures[0])} changed over time by {_label(times[0])}?")
    if measures:
        out.append(f"Which {plural} have the highest {_label(measures[0])}?")
    if entity.has_lifecycle and entity.active_filter:
        out.append(f"What share of {plural} are active ({entity.lifecycle_column})?")
    if dims and len(out) < 3:
        out.append(f"How are {plural} distributed across {_label(dims[0])}?")
    if len(out) < 3:
        out.append(f"How many {plural} are there?")
    # de-dupe preserving order, cap at 3
    seen: set[str] = set()
    uniq = [q for q in out if not (q in seen or seen.add(q))]
    return uniq[:3]


def _table_facts(entity: OntologyEntity, stats: Optional[dict], rel_summ: list[str]) -> dict:
    f = {
        "entity_id": entity.id,
        "entity_type": entity.entity_type,
        "identity_key": entity.identity_key,
        "grain_verified": bool(entity.grain_verified),
        "source_tables": list(entity.source_tables),
        "n_measures": len(_measures(entity)),
        "n_dimensions": len(_dimensions(entity)),
        "has_lifecycle": bool(entity.has_lifecycle),
        "relationships": rel_summ,
    }
    if entity.lifecycle_column:
        f["lifecycle_column"] = entity.lifecycle_column
    if stats:
        for k in ("row_count", "date_range", "time_grain", "primary_timestamp", "grain_columns"):
            v = stats.get(k)
            if v not in (None, "", []):
                f[k] = v
    return f


def _table_summary(entity: OntologyEntity, facts: dict, n_cols: int) -> str:
    name = entity.display_name or entity.id
    bits = [f"{name} ({facts['entity_type'].replace('_', ' ')})"]
    grain = facts["identity_key"] or "—"
    bits.append(f"grain: {grain}{' (verified)' if facts['grain_verified'] else ''}")
    if facts.get("row_count") is not None:
        bits.append(f"{facts['row_count']:,} rows")
    if facts.get("date_range"):
        bits.append(f"dates {facts['date_range']}")
    col_bit = f"{n_cols} columns ({facts['n_measures']} measures, {facts['n_dimensions']} dimensions)"
    bits.append(col_bit)
    if facts.get("relationships"):
        bits.append("relates to " + ", ".join(facts["relationships"][:5]))
    if entity.description:
        bits.insert(1, entity.description.strip().rstrip("."))
    return " — ".join(bits) + "."


def _relationship_summaries(graph: OntologyGraph, entity_id: str) -> list[str]:
    out = []
    for r in graph.relationships.values():
        if r.from_entity == entity_id:
            out.append(f"{r.to_entity} ({r.cardinality})")
        elif r.to_entity == entity_id:
            out.append(f"{r.from_entity} ({r.cardinality})")
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))]


# ── the builder ──────────────────────────────────────────────────────────────

def build_doc_tree(
    graph: OntologyGraph,
    *,
    table_stats: Optional[dict[str, dict]] = None,
    ignore: tuple[str, ...] = _DEFAULT_IGNORE,
    prior: Optional[DocTree] = None,
    column_config: Optional[dict] = None,   # R11: {(table, column): ColumnFlags}
) -> DocTree:
    """Project ``graph`` (+ optional per-table ``table_stats``) into a Merkle-checksummed doc tree.

    Deterministic — no model. ``table_stats`` maps a table (or entity id) → a fact dict
    (``row_count`` / ``date_range`` / ``time_grain`` / …) to enrich table docs; absent stats just
    omit those facts. ``prior`` is a previously-built tree: any node whose content_hash and child
    checksums are unchanged is reused verbatim (a cache hit), so a rebuild only touches what moved.
    """
    conn = graph.connection_id
    schema = graph.schema_name or ""
    table_stats = table_stats or {}
    prior_nodes = prior.nodes if prior else {}
    nodes: dict[str, DocNode] = {}
    cache_hits = 0
    rebuilt = 0
    skipped: list[str] = []

    def _emit(node: DocNode) -> DocNode:
        """Reuse the prior node when nothing under it moved; else keep the fresh one. The
        content_hash + child_checksums equality IS the Merkle short-circuit."""
        nonlocal cache_hits, rebuilt
        old = prior_nodes.get(node.fqn)
        if (old is not None and old.content_hash == node.content_hash
                and old.child_checksums == node.child_checksums):
            cache_hits += 1
            nodes[node.fqn] = old
            return old
        rebuilt += 1
        nodes[node.fqn] = node
        return node

    schema_prefix = f"{schema}." if schema else ""

    # entity id → (table fqn, table checksum); built as we go so schema/connection can fold them.
    table_checks: dict[str, str] = {}

    for entity in graph.entities.values():
        # Skip pipeline-scaffolding tables (logged, not silent).
        primary_table = (entity.source_tables[0] if entity.source_tables else entity.id)
        if _ignored(primary_table, ignore):
            skipped.append(primary_table)
            continue

        table_fqn = f"{schema_prefix}{entity.id}"
        child_checks: dict[str, str] = {}

        # ── column nodes (leaves) ──
        for prop in entity.properties.values():
            col_fqn = f"{table_fqn}.{prop.name}"
            cflags = None
            if column_config:
                cflags = (column_config.get((primary_table, prop.name))
                          or column_config.get((entity.id, prop.name)))
            cfacts = _column_facts(prop, cflags)
            ch = _hash(sorted(cfacts.items(), key=lambda kv: kv[0]))
            col = DocNode(
                kind="column", fqn=col_fqn, title=prop.name,
                summary=_column_summary(prop, cfacts), facts=cfacts,
                content_hash=ch, checksum=_merkle(ch, {}),
                provenance={"connection_id": conn, "schema": schema, "table": entity.id},
            )
            _emit(col)
            child_checks[col_fqn] = nodes[col_fqn].checksum

        # ── table node (folds its columns' checksums) ──
        rel_summ = _relationship_summaries(graph, entity.id)
        tstats = table_stats.get(entity.id) or table_stats.get(primary_table)
        tfacts = _table_facts(entity, tstats, rel_summ)
        tch = _hash(sorted(tfacts.items(), key=lambda kv: str(kv[0])))
        table = DocNode(
            kind="table", fqn=table_fqn, title=entity.display_name or entity.id,
            summary=_table_summary(entity, tfacts, len(entity.properties)),
            facts=tfacts, questions=_analyst_questions(entity),
            children=sorted(child_checks), content_hash=tch,
            child_checksums=child_checks, checksum=_merkle(tch, child_checks),
            provenance={"connection_id": conn, "schema": schema, "table": entity.id,
                        "fqn": f"{schema_prefix}{primary_table}"},
        )
        _emit(table)
        table_checks[table_fqn] = nodes[table_fqn].checksum

    # ── schema node (folds table checksums) ──
    # A distinct fqn from the connection node even when the schema is unnamed (no collision).
    schema_fqn = schema or "default"
    schema_content = _hash(len(table_checks), graph.schema_fingerprint,
                           sorted(_entity_names(graph)))
    schema_node = DocNode(
        kind="schema", fqn=schema_fqn,
        title=schema or "(default schema)",
        summary=_schema_summary(schema, nodes, table_checks, graph),
        facts={"n_tables": len(table_checks), "n_relationships": len(graph.relationships),
               "schema_fingerprint": graph.schema_fingerprint,
               "skipped_tables": sorted(skipped)},
        children=sorted(table_checks), content_hash=schema_content,
        child_checksums=dict(table_checks), checksum=_merkle(schema_content, table_checks),
        provenance={"connection_id": conn, "schema": schema},
    )
    _emit(schema_node)

    # ── connection node (root; folds the schema) ──
    conn_children = {schema_fqn: nodes[schema_fqn].checksum}
    conn_content = _hash(conn, schema_fqn)
    conn_node = DocNode(
        kind="connection", fqn=conn, title=conn,
        summary=f"{conn}: schema {schema or '(default)'} — {len(table_checks)} documented tables.",
        facts={"schemas": [schema_fqn], "n_tables": len(table_checks)},
        children=[schema_fqn], content_hash=conn_content,
        child_checksums=conn_children, checksum=_merkle(conn_content, conn_children),
        provenance={"connection_id": conn},
    )
    _emit(conn_node)

    if skipped:
        logger.info("doctree: skipped %d ignore-glob table(s) for %s/%s: %s",
                    len(skipped), conn, schema, ", ".join(sorted(skipped)))

    return DocTree(
        connection_id=conn, schema_name=schema, root_checksum=nodes[conn].checksum,
        nodes=nodes,
        stats={
            "tables": len(table_checks),
            "columns": sum(1 for n in nodes.values() if n.kind == "column"),
            "cache_hits": cache_hits, "rebuilt": rebuilt,
            "skipped_tables": sorted(skipped),
        },
    )


def _entity_names(graph: OntologyGraph) -> list[str]:
    return [e.id for e in graph.entities.values()]


def _schema_summary(schema: str, nodes: dict, table_checks: dict, graph: OntologyGraph) -> str:
    tables = [nodes[fqn] for fqn in table_checks]
    tables.sort(key=lambda n: n.facts.get("row_count") or 0, reverse=True)
    top = ", ".join(t.title for t in tables[:5])
    label = schema or "(default schema)"
    bits = [f"{label}: {len(table_checks)} tables, {len(graph.relationships)} relationships"]
    if top:
        bits.append(f"key entities: {top}")
    return " — ".join(bits) + "."


# ── estimate-then-confirm ────────────────────────────────────────────────────

def estimate_doc_build(
    graph: OntologyGraph,
    *,
    table_stats: Optional[dict[str, dict]] = None,
    ignore: tuple[str, ...] = _DEFAULT_IGNORE,
    prior: Optional[DocTree] = None,
) -> dict:
    """Dry-run the identical pipeline and report what a build would touch — BEFORE any spend.

    The deterministic core costs no tokens, so ``llm_tokens`` is 0 here; the field exists so the
    same gate governs the (deferred) per-node LLM enrichment path once it lands. ``rebuilt`` vs
    ``cache_hits`` shows how much an incremental run would actually recompute."""
    tree = build_doc_tree(graph, table_stats=table_stats, ignore=ignore, prior=prior)
    s = tree.stats
    return {
        "nodes": len(tree.nodes),
        "tables": s["tables"], "columns": s["columns"],
        "would_rebuild": s["rebuilt"], "would_reuse": s["cache_hits"],
        "skipped_tables": s["skipped_tables"],
        "llm_tokens": 0,          # deterministic core — enrichment is a deferred, gated layer
        "deterministic": True,
    }


# ── file-per-node persistence (mirrors recommendations.py / overrides.py) ────

def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.=-]", "_", s or "default")


def _base(conn: str, schema: str) -> Path:
    return _ROOT / _safe(conn) / _safe(schema or "default")


def save_doc_tree(tree: DocTree) -> None:
    """Persist one YAML per node under ``data/ontology_docs/{conn}/{schema}/{kind}/`` plus a
    ``tree.yaml`` manifest (root checksum + stats). Best-effort — a persistence hiccup must never
    break the build that produced the (already-usable in-memory) tree."""
    try:
        base = _base(tree.connection_id, tree.schema_name)
        for node in tree.nodes.values():
            p = base / node.kind / f"{_safe(node.fqn)}.yaml"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(yaml.safe_dump(node.model_dump(), sort_keys=False, allow_unicode=True))
        manifest = base / "tree.yaml"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(yaml.safe_dump(
            {"connection_id": tree.connection_id, "schema_name": tree.schema_name,
             "root_checksum": tree.root_checksum, "built_at": tree.built_at,
             "stats": tree.stats, "node_index": sorted(tree.nodes)},
            sort_keys=False, allow_unicode=True))
    except Exception:
        logger.exception("doctree: persist failed for %s/%s",
                         tree.connection_id, tree.schema_name)


def load_doc_tree(conn: str, schema: str) -> Optional[DocTree]:
    """Load a persisted doc tree, or None if it hasn't been built. Used as the ``prior`` for an
    incremental rebuild and by any reader of the artifact."""
    base = _base(conn, schema)
    manifest = base / "tree.yaml"
    if not manifest.exists():
        return None
    try:
        meta = yaml.safe_load(manifest.read_text()) or {}
        nodes: dict[str, DocNode] = {}
        for kind_dir in base.iterdir():
            if not kind_dir.is_dir():
                continue
            for f in kind_dir.glob("*.yaml"):
                try:
                    node = DocNode.model_validate(yaml.safe_load(f.read_text()) or {})
                    nodes[node.fqn] = node
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, f"doctree: skipping an unreadable node file {f.name}",
                             counter="doctree.load_skip")
                    continue
        return DocTree(
            connection_id=meta.get("connection_id", conn),
            schema_name=meta.get("schema_name", schema),
            root_checksum=meta.get("root_checksum", ""),
            nodes=nodes, built_at=meta.get("built_at", ""),
            stats=meta.get("stats", {}),
        )
    except Exception:
        logger.exception("doctree: load failed for %s/%s", conn, schema)
        return None


# ── high-level build (loads graph + profiles, persists) ─────────────────────

def table_stats_from_profiles(table_profiles: Optional[dict[str, Any]]) -> dict[str, dict]:
    """Adapt cached ``TableProfile``s (the first element of ``profile_cache.load_profiles``'s
    tuple) → the builder's per-table fact dicts. Duck-typed (object OR dict) so doctree stays
    decoupled from the profiler internals. A caller that already holds profiles can pass the
    result as ``build_doc_tree(table_stats=…)`` to enrich table docs with row_count / dates."""
    out: dict[str, dict] = {}
    for table, tp in (table_profiles or {}).items():
        def g(name, _tp=tp):
            return _tp.get(name) if isinstance(_tp, dict) else getattr(_tp, name, None)
        d: dict = {}
        for k in ("row_count", "time_grain", "primary_timestamp", "grain_columns"):
            v = g(k)
            if v not in (None, "", []):
                d[k] = v
        dr = g("date_range") or g("effective_date_range")
        if dr:
            d["date_range"] = " → ".join(str(x) for x in dr) if isinstance(dr, (list, tuple)) else str(dr)
        out[table] = d
    return out


def build_and_persist(
    conn: str,
    schema: str = "",
    *,
    graph: Optional[OntologyGraph] = None,
    table_stats: Optional[dict[str, dict]] = None,
    incremental: bool = True,
    persist: bool = True,
) -> DocTree:
    """Build the doc tree for one (connection, schema) from the live ontology and persist it.

    ``incremental`` loads the prior tree so unchanged nodes are reused (Merkle short-circuit).
    ``graph`` / ``table_stats`` may be injected (tests, or a caller that already holds profiles);
    otherwise the graph is loaded from the ontology cache and table docs build from the graph alone
    (still carrying grain / identity / entity-type / lifecycle / typed columns). Row-count/date
    enrichment via the profile cache is available by passing ``table_stats`` (see
    :func:`table_stats_from_profiles`)."""
    if graph is None:
        from aughor.ontology.store import load_latest_ontology
        graph = load_latest_ontology(conn, schema or None)
        if graph is None:
            raise ValueError(f"no ontology built for {conn}/{schema!r} — run intelligence first")
    eff_schema = graph.schema_name or schema or ""
    prior = load_doc_tree(conn, eff_schema) if incremental else None
    # R11 — mark each column doc with its {visible,sample,index} config when the
    # feature is on (best-effort; docs build fine without it).
    column_config = None
    from aughor.kernel.flags import flag_enabled
    if flag_enabled("ontology.column_config"):
        try:
            from aughor.ontology.column_config import load_column_configs
            column_config = load_column_configs(conn, eff_schema or "default") or None
        except Exception:
            column_config = None
    tree = build_doc_tree(graph, table_stats=table_stats or {}, prior=prior,
                          column_config=column_config)
    if persist:
        save_doc_tree(tree)
    return tree
