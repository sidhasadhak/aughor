"""Schema annotators — the AGENT's schema enrichment, plugged into the platform.

The platform renders a connection's raw schema (``db.schema_render.render_raw_schema``
for DuckDB; the connector's own raw renderer for Postgres/SQLite) and runs these
annotators over it (``aughor.kernel.registries.schema_annotators``). They reproduce,
on top of the raw schema, exactly what each connection's ``get_schema()`` /
``build_intelligence()`` used to bake in directly — so the schema string the NL2SQL
prompt sees is unchanged, but ``db/connection.py`` no longer imports the agent.

  • **enrichment**   (fast+heavy) — glossary + join hints + the metrics catalog
    (``tools.schema.apply_schema_enrichment``).
  • **intelligence** (heavy)      — value profiles + the structural/semantic ontology
    (build → enrich → validate → explorer-merge → human overrides), setting
    ``conn._ontology`` / ``conn.last_build`` and journaling the build outcome. The
    former ``DatabaseConnection.build_intelligence`` body, made connection-agnostic
    (tables come from the rendered schema; profiles via ``conn.execute``).
  • **exploration**  (fast+heavy) — the exploration findings block.

This unifies what had drifted into three near-duplicate per-connection recipes into
one pipeline; the DuckDB hot path stays byte-identical (a golden-diff gate), and the
Postgres/SQLite connections gain the same full enrichment.
"""
from __future__ import annotations


def _cid(conn) -> str:
    return getattr(conn, "_connection_id", None) or "fixture"


def _enrichment(conn, base: str) -> str:
    from aughor.tools.schema import apply_schema_enrichment
    return apply_schema_enrichment(base, connection_id=_cid(conn))


def _exploration(conn, base: str) -> str:
    from aughor.explorer.store import render_exploration_annotations
    expl_block = render_exploration_annotations(_cid(conn))
    if expl_block:
        base += "\n\n" + expl_block
    return base


def _intelligence(conn, base: str) -> str:
    """Value profiles + ontology — the former build_intelligence body, connection-
    agnostic (tables parsed from the rendered schema; profiles via conn.execute)."""
    from aughor.tools.profile_cache import get_or_build_profiles
    from aughor.tools.profiler import render_profile_annotations
    from aughor.tools.schema import compute_join_map, inject_value_annotations, parse_schema_tables
    from aughor.tools.table_names import bare

    cid = _cid(conn)
    table_cols = parse_schema_tables(base)
    tables = [bare(t) for t in table_cols]
    jmap = compute_join_map(table_cols)
    fk_hints: dict[str, set] = {t: set() for t in tables}
    for j in jmap.get("joins", []):
        fk_hints.setdefault(j["t1"], set()).add(j["c1"])

    # Record the build outcome so a failure surfaces as an actionable status.
    conn.last_build = {"ok": True, "stage": None, "error": None}
    _stage = "profiling"
    try:
        tp, cp = get_or_build_profiles(conn, cid, tables, fk_hints)
        base = inject_value_annotations(base, cp)
        annotation = render_profile_annotations(tp, cp)
        if annotation:
            base += "\n\n" + annotation

        from aughor.ontology.builder import render_ontology_annotations
        from aughor.ontology.store import get_or_build_ontology, save_ontology
        from aughor.semantic.glossary import load_merged_glossary
        _glossary = load_merged_glossary()
        _schema_label = getattr(conn, "_schema_name", None) or "default"
        _stage = "ontology"
        graph = get_or_build_ontology(
            connection_id=cid,
            schema_name=_schema_label,
            table_profiles=tp,
            column_profiles=cp,
            join_map=jmap,
            glossary=_glossary,
        )
        if graph is None:
            conn.last_build = {
                "ok": False, "stage": "ontology",
                "error": "the object model could not be built from this schema — it may "
                         "be too sparse to model (no entities/relationships inferred).",
            }
        if graph is not None:
            from aughor.ontology.enricher import ENRICHMENT_VERSION
            from aughor.stats import stats as _st
            if not graph.enriched or graph.enrichment_version < ENRICHMENT_VERSION:
                _st.inc("enrichment_runs")
                _stage = "enrichment"
                try:
                    from aughor.llm.provider import get_provider
                    from aughor.ontology.enricher import enrich_ontology_semantics
                    graph = enrich_ontology_semantics(graph, get_provider("coder"), _glossary, base)
                    save_ontology(graph.connection_id, graph.schema_name, graph.schema_fingerprint, graph)
                except Exception as _enr_exc:
                    conn.last_build = {
                        "ok": True, "stage": "enrichment",
                        "error": f"semantic enrichment failed (ontology still usable): {str(_enr_exc)[:200]}",
                    }
                _stage = "ontology"
            else:
                _st.inc("enrichment_cache_hits")
            from aughor.ontology.validator import VALIDATION_VERSION
            if not graph.validated or graph.validation_version < VALIDATION_VERSION:
                try:
                    from aughor.ontology.validator import validate_semantics
                    graph = validate_semantics(graph, conn)
                    save_ontology(graph.connection_id, graph.schema_name, graph.schema_fingerprint, graph)
                except Exception as _val_exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(_val_exc, "semantic validation is best-effort; ontology still usable "
                             "unvalidated", counter="ontology.validation", conn_id=cid or None)
            _apply_explorer_to_ontology(graph, cid)
            # Human overrides win LAST.
            from aughor.ontology.store import overlay_human_overrides
            graph = overlay_human_overrides(graph, cid, graph.schema_name)
            conn._ontology = graph
            onto_block = render_ontology_annotations(graph)
            if onto_block:
                base += "\n\n" + onto_block
    except Exception as _build_exc:
        conn.last_build = {"ok": False, "stage": _stage, "error": str(_build_exc)[:400]}

    # Journal the build outcome (K2 event spine).
    try:
        from aughor.kernel.jobs import current_job_id
        from aughor.kernel.ledger import Ledger
        _ents = len(getattr(conn._ontology, "entities", {}) or {}) if getattr(conn, "_ontology", None) else 0
        _lb = getattr(conn, "last_build", {}) or {}
        Ledger.default().emit(
            "ontology.build",
            {"ok": bool(_lb.get("ok", True)) and _ents > 0,
             "entities": _ents, "stage": _lb.get("stage"), "error": _lb.get("error")},
            conn_id=cid or None, job_id=current_job_id(),
        )
    except Exception as _j_exc:
        import logging as _logging
        _logging.getLogger(__name__).debug("ontology.build journal emit failed: %s", _j_exc)

    return base


def _apply_explorer_to_ontology(graph, connection_id: str) -> None:
    """
    Merge verified exploration findings into an already-built ontology graph,
    in-memory only.  Not persisted — re-applied each time get_schema() renders.

    Upgrades:
      • lifecycle_states / terminal_states / active_filter from explorer's
        verified state-machine maps (overrides the profiler's heuristic values).
      • join_confidence from "inferred" to "verified" for joins confirmed by
        the orphan-count check in Phase 4.
    """
    try:
        from aughor.explorer.store import load as _load_exploration
        state = _load_exploration(connection_id)
        phase = state.get("phase", "pending")
        if phase in ("pending", "failed"):
            return

        # ── Lifecycle merge ───────────────────────────────────────────────────
        import re as _re

        def _valid_lifecycle_state(s: str) -> bool:
            """Same heuristic used by the ontology builder's _is_valid_state."""
            s = s.strip()
            if not s or s == "null":
                return False
            if "/" in s:
                return False
            if _re.fullmatch(r"[A-Z]{2}", s):   # bare ISO-2 codes
                return False
            if len(s) > 30:
                return False
            return True

        def _plausible_lifecycle_states(states: list) -> bool:
            """Reject columns whose states look like descriptions, not process stages."""
            valid = [s for s in states if _valid_lifecycle_state(s)]
            if not valid:
                return False
            avg_len = sum(len(s) for s in valid) / len(valid)
            avg_words = sum(len(s.split()) for s in valid) / len(valid)
            return avg_len <= 15 and avg_words <= 2

        lifecycle_maps: dict = state.get("lifecycle_maps", {})
        if lifecycle_maps:
            for entity in graph.entities.values():
                for src_table in entity.source_tables:
                    if src_table in lifecycle_maps:
                        lm = lifecycle_maps[src_table]
                        col = lm.get("status_column")
                        if not col:
                            break
                        raw_states = lm.get("states", [])
                        if not _plausible_lifecycle_states(raw_states):
                            # Explorer found something that looks like a
                            # description column (KPI names, formula strings,
                            # etc.) — skip silently.
                            break
                        entity.has_lifecycle     = True
                        entity.lifecycle_column  = col
                        entity.lifecycle_states  = [s for s in raw_states if _valid_lifecycle_state(s)]
                        entity.terminal_states   = lm.get("terminal_states", entity.terminal_states)
                        terminal = lm.get("terminal_states", [])
                        if terminal:
                            tl = ", ".join(f"'{s}'" for s in terminal)
                            entity.active_filter = f"{col} NOT IN ({tl})"
                        # Rebuild object sets to reflect the explorer-verified lifecycle
                        try:
                            from aughor.ontology.builder import _build_object_sets
                            entity.object_sets = _build_object_sets(
                                entity_id=entity.id,
                                lifecycle_col=entity.lifecycle_column,
                                lifecycle_states=entity.lifecycle_states,
                                terminal_states=entity.terminal_states,
                                active_filter=entity.active_filter,
                            )
                        except Exception:
                            pass
                        break

        # ── Null meaning merge (phase 3 → EntityProperty.null_meaning) ──────────
        # Explorer state keys are "table:col" (colon-separated).
        null_meanings: dict = state.get("null_meanings", {})
        if null_meanings:
            for entity in graph.entities.values():
                src_table_set = set(entity.source_tables)
                for key, meaning_obj in null_meanings.items():
                    if ":" not in key:
                        continue
                    tbl_part, col_part = key.split(":", 1)
                    if tbl_part not in src_table_set:
                        continue
                    if col_part not in entity.properties:
                        continue
                    prop = entity.properties[col_part]
                    if prop.null_meaning:
                        continue  # already set — don't overwrite
                    if isinstance(meaning_obj, dict):
                        meaning_text = meaning_obj.get("meaning", "")
                    else:
                        meaning_text = str(meaning_obj)
                    if meaning_text and meaning_text not in ("unknown", "Unknown", ""):
                        prop.null_meaning = meaning_text

        # ── Distribution stats merge (phase 6 → EntityProperty numeric fields) ──
        # Explorer state key: "table:col", value: {shape, p25, p50, p75, ...}
        distributions: dict = state.get("distributions", {})
        if distributions:
            for entity in graph.entities.values():
                src_table_set = set(entity.source_tables)
                for key, dist_info in distributions.items():
                    if ":" not in key or not isinstance(dist_info, dict):
                        continue
                    tbl_part, col_part = key.split(":", 1)
                    if tbl_part not in src_table_set:
                        continue
                    if col_part not in entity.properties:
                        continue
                    prop = entity.properties[col_part]
                    shape = dist_info.get("shape", "")
                    if shape:
                        prop.distribution_shape = shape
                    for pct_field in ("p25", "p50", "p75"):
                        raw = dist_info.get(pct_field)
                        if raw is not None:
                            try:
                                setattr(prop, pct_field, float(raw))
                            except (TypeError, ValueError):
                                pass

        # ── Insights merge (phase 8 → OntologyEntity.exploration_insights) ──────
        # Each insight has {entities_involved: list[str], finding: str, novelty: int}.
        # Match by source table name (most reliable — explorer uses table names).
        insights: list = state.get("insights", [])
        if insights:
            sorted_insights = sorted(
                insights, key=lambda x: x.get("novelty", 0) if isinstance(x, dict) else 0,
                reverse=True,
            )
            for entity in graph.entities.values():
                entity_name_set = {t.lower() for t in entity.source_tables}
                entity_name_set.add(entity.id.lower())
                entity_name_set.add(entity.display_name.lower())
                findings: list[str] = []
                seen: set[str] = set()
                for item in sorted_insights:
                    if not isinstance(item, dict):
                        continue
                    involved = {e.lower() for e in item.get("entities_involved", [])}
                    if not (entity_name_set & involved):
                        continue
                    finding = item.get("finding", "").strip()
                    if finding and finding not in seen:
                        findings.append(finding)
                        seen.add(finding)
                entity.exploration_insights = findings[:10]

        # ── Join confidence upgrade ───────────────────────────────────────────
        verifications: list = state.get("join_verifications", [])
        verified_keys = {
            (j["from_table"], j["from_col"], j["to_table"], j["to_col"])
            for j in verifications
            if j.get("verified")
        }
        if verified_keys:
            for rel in graph.relationships.values():
                if (rel.from_table, rel.from_col, rel.to_table, rel.to_col) in verified_keys:
                    rel.join_confidence = "verified"
    except Exception:
        pass  # exploration data is best-effort — never block schema rendering


# ── Base class ────────────────────────────────────────────────────────────────

_PG_OID_MAP: dict[int, str] = {
    16: "BOOLEAN", 21: "SMALLINT", 23: "INTEGER", 20: "BIGINT",
    700: "REAL", 701: "DOUBLE PRECISION", 1700: "NUMERIC",
    1082: "DATE", 1083: "TIME", 1266: "TIMETZ",
    1114: "TIMESTAMP", 1184: "TIMESTAMPTZ", 1186: "INTERVAL",
    25: "TEXT", 1042: "CHAR", 1043: "VARCHAR",
    18: "CHAR", 19: "NAME", 114: "JSON", 3802: "JSONB",
    17: "BYTEA", 2950: "UUID",
}


def register() -> None:
    """Plug the schema annotators into the platform registry (called by bootstrap)."""
    from aughor.kernel.registries.schema_annotators import register_schema_annotator
    register_schema_annotator("enrichment", _enrichment, phase="all")
    register_schema_annotator("intelligence", _intelligence, phase="heavy")
    register_schema_annotator("exploration", _exploration, phase="all")
