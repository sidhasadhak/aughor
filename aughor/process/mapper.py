"""
Build a live ProcessMap for any entity that has a lifecycle column.

Node counts: simple GROUP BY on lifecycle_column.
Edge counts: LAG() SQL ordered by created_at_col (if available) to capture
             state-to-state transitions within each identity_key partition.
             Falls back to nodes-only when no temporal column exists.
"""
from __future__ import annotations

from aughor.process.models import ProcessEdge, ProcessMap, ProcessNode


def build_process_map(entity_id: str, connection_id: str) -> ProcessMap:
    from aughor.db.registry import BUILTIN_ID
    from aughor.db.connection import open_connection_for
    from aughor.ontology.store import load_latest_ontology

    graph = load_latest_ontology(connection_id)
    if graph is None:
        raise ValueError("Ontology not available for this connection")

    entity = graph.entities.get(entity_id)
    if entity is None:
        raise ValueError(f"Entity '{entity_id}' not found")
    if not entity.has_lifecycle or not entity.lifecycle_column:
        raise ValueError(f"Entity '{entity_id}' has no lifecycle column")
    if not entity.source_tables:
        raise ValueError(f"Entity '{entity_id}' has no source tables")

    table = entity.source_tables[0]
    col   = entity.lifecycle_column
    pk    = entity.identity_key
    ts    = entity.created_at_col   # may be None

    db = open_connection_for(connection_id)
    try:
        # ── Node counts ───────────────────────────────────────────────────────
        node_sql = f"SELECT {col} AS state, COUNT(*) AS cnt FROM {table} GROUP BY {col} ORDER BY cnt DESC LIMIT 100"
        node_res = db.execute("process_map_nodes", node_sql)
        if node_res.error:
            raise RuntimeError(node_res.error)

        state_counts: dict[str, int] = {
            str(r[0]): int(r[1]) for r in (node_res.rows or []) if r[0] is not None
        }
        total = sum(state_counts.values())

        terminal_set = set(entity.terminal_states)
        known_order  = entity.lifecycle_states  # preserves ontology ordering

        # Sort nodes: follow known order first, then alphabetical for unknowns
        def _sort_key(s: str) -> tuple:
            try:
                return (0, known_order.index(s))
            except ValueError:
                return (1, s)

        nodes = [
            ProcessNode(
                state=s,
                count=state_counts.get(s, 0),
                is_terminal=s in terminal_set,
            )
            for s in sorted(state_counts.keys(), key=_sort_key)
        ]

        # ── Edge transitions (LAG) ─────────────────────────────────────────────
        edges: list[ProcessEdge] = []
        has_transitions = False

        if ts:
            lag_sql = f"""
WITH ordered AS (
  SELECT
    {pk},
    {col} AS curr_state,
    LAG({col}) OVER (PARTITION BY {pk} ORDER BY {ts}) AS prev_state
  FROM {table}
)
SELECT prev_state, curr_state, COUNT(*) AS cnt
FROM ordered
WHERE prev_state IS NOT NULL
  AND prev_state <> curr_state
GROUP BY prev_state, curr_state
ORDER BY cnt DESC
LIMIT 500
"""
            edge_res = db.execute("process_map_edges", lag_sql)
            if not edge_res.error and edge_res.rows:
                has_transitions = True
                # Compute outgoing totals per from_state for rate calculation
                from_totals: dict[str, int] = {}
                raw_edges: list[tuple[str, str, int]] = []
                for row in edge_res.rows:
                    if row[0] is None or row[1] is None:
                        continue
                    fs, ts_, cnt = str(row[0]), str(row[1]), int(row[2])
                    raw_edges.append((fs, ts_, cnt))
                    from_totals[fs] = from_totals.get(fs, 0) + cnt

                edges = [
                    ProcessEdge(
                        from_state=fs,
                        to_state=ts_,
                        count=cnt,
                        rate=cnt / from_totals[fs] if from_totals.get(fs) else 0.0,
                    )
                    for fs, ts_, cnt in raw_edges
                ]

    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "process-map DB close is best-effort; the map is already built",
                     counter="mapper.db.close")

    return ProcessMap(
        entity_id=entity_id,
        display_name=entity.display_name,
        lifecycle_column=col,
        nodes=nodes,
        edges=edges,
        total_records=total,
        has_transitions=has_transitions,
    )
