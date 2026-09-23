"""PENDING.md item 9 — the company-brain map: every store behind the "brain", one box each,
with a live count and the door that serves it (ROADMAP §3.21, Arc CB's closing ask).

The roadmap's rule for it: "every box is a store that exists, with a door and a live count, and
every arrow is a measurement — so the map is a screen, never a picture." Eight Arc CB waves were
built with no screen between them — the built-and-never-used failure this project keeps
repeating — and two of them (CB-1's fact dates and history, CB-8's claims) had no screen at all.

A READ, NEVER A BUILD — the hub map's rule (`hub/map.py`): every box is a store read or a fold
over one; no graph is built, no probe fires, no model is called. A box whose store cannot be
read says so (``count: None`` and the reason) — an empty box that means "could not read" would
teach the reader the store is empty. Three vaults, as IDEAS.md 21 and §3.21 name them:

* **company** — what the platform knows: dated facts (the context graph), approved metrics,
  how much of the business it can see;
* **engagement** — what it did with people: findings, recommendations and their outcomes,
  claims people made and what the data said, messages held at the gate;
* **working memory** — what people told it: this quarter's priorities, owners it can reach.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

#: How many recently changed facts the facts box shows with their history (CB-1's owed screen).
RECENT_FACTS = 8


def _box(box_id: str, vault: str, title: str, door: str, read: Callable[[], dict]) -> dict:
    """One box. ``read`` returns ``{"count", "unit", "detail", "line"}``; a failure becomes a box
    that says it could not be read — never a silent zero."""
    base = {"id": box_id, "vault": vault, "title": title, "door": door}
    try:
        return {**base, **read()}
    except Exception as exc:  # noqa: BLE001 — one unreadable store never blanks the map
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"brain map: the {box_id} store could not be read", counter="brain_map.box")
        return {**base, "count": None, "unit": "", "detail": {},
                "line": f"could not be read ({type(exc).__name__})"}


# ── company ────────────────────────────────────────────────────────────────────────────────

def _graphs(org_id: str, connection_id: str) -> list:
    from aughor.ontology.context_graph_store import load_graphs_for_connection
    return load_graphs_for_connection(org_id, connection_id)


def _facts(org_id: str, connection_id: str) -> dict:
    """CB-1: every fact dated, what it replaced kept. Per-schema graphs, never the merged one
    (the merge keeps only the first schema's retired nodes)."""
    graphs = _graphs(org_id, connection_id)
    if not graphs:
        return {"count": None, "unit": "facts", "detail": {},
                "line": "no context graph is built for this connection yet"}
    nodes = [n for g in graphs for n in g.nodes.values()]
    dated = [n for n in nodes if getattr(n.provenance, "observed_at", "")]
    from_source = [n for n in dated if getattr(n.provenance, "observed_basis", "") == "source"]
    changed = sorted((n for n in nodes if n.history), key=lambda n: n.last_changed or "", reverse=True)
    retired = sum(len(g.retired) for g in graphs)
    recent = [{"id": n.id, "kind": n.kind, "label": getattr(n, "label", "") or n.id,
               "first_seen": n.first_seen, "last_changed": n.last_changed,
               "observed_at": n.provenance.observed_at, "observed_basis": n.provenance.observed_basis,
               "history": [h.model_dump() for h in n.history[-3:]]}
              for n in changed[:RECENT_FACTS]]
    by_kind: dict[str, int] = {}
    for n in nodes:
        by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
    return {"count": len(nodes), "unit": "facts",
            "detail": {"dated": len(dated), "dated_from_source": len(from_source),
                       "with_history": len(changed),
                       "revisions": sum(len(n.history) for n in nodes), "retired": retired,
                       "edges": sum(len(g.edges) for g in graphs), "by_kind": by_kind,
                       "recent": recent},
            "line": f"{len(dated)} of {len(nodes)} dated · {len(changed)} changed since first seen "
                    f"· {retired} retired, kept"}


def _metrics(connection_id: str) -> dict:
    from aughor.semantic.metrics import list_metrics
    rows = list_metrics(connection_id=connection_id)
    approved = [m for m in rows if getattr(m, "status", "") == "approved"]
    drafts = [m for m in rows if getattr(m, "status", "") in ("draft", "proposed")]
    return {"count": len(approved), "unit": "approved metrics",
            "detail": {"approved": len(approved), "draft_or_proposed": len(drafts), "total": len(rows)},
            "line": f"{len(approved)} approved · {len(drafts)} draft or proposed"}


def _visibility(org_id: str, connection_id: str) -> dict:
    """CB-5: the share of the business the platform can see, and the one fix that unblocks most."""
    from aughor.agent.framing import served_graph
    from aughor.ontology.visibility import visibility
    graph = served_graph(connection_id, None)
    if graph is None:
        return {"count": None, "unit": "", "detail": {}, "line": "no ontology is built for this connection yet"}
    schema = getattr(graph, "schema_name", "") or "default"
    context_graph = None
    try:
        from aughor.ontology.context_graph_store import load_graph
        context_graph = load_graph(org_id, connection_id, schema)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "brain map: no context graph for the joins share", counter="brain_map.visibility")
    out = visibility(connection_id, schema, graph, context_graph=context_graph)
    tables = out.get("tables") or {}
    share = tables.get("share")
    return {"count": share, "unit": "share of tables seen",
            "detail": {"tables": tables, "joins": out.get("joins"), "top_blocker": out.get("top_blocker")},
            "line": out.get("line") or ("the table share reads unknown" if share is None else "")}


# ── engagement ─────────────────────────────────────────────────────────────────────────────

def _findings(connection_id: str) -> dict:
    from aughor.explorer import store
    keys = [connection_id] + list(store.schema_run_keys(connection_id))
    seen: dict[str, dict] = {}
    for key in keys:
        for f in store.get_findings(key):
            seen.setdefault(str(f.get("id")), f)
    newest = max((str(f.get("generated_at") or "") for f in seen.values()), default="")
    domains = {str(f.get("domain") or "") for f in seen.values()}
    return {"count": len(seen), "unit": "findings",
            "detail": {"domains": len(domains - {""}), "newest": newest},
            "line": f"{len(seen)} across {len(domains - {''})} domains"
                    + (f" · newest {newest[:10]}" if newest else "")}


def _outcomes(connection_id: str) -> dict:
    """CB-2: recommendations accepted with a baseline, reviews due, reviews measured."""
    from aughor.playbook.outcomes import load_all_outcomes
    mine = [o for o in load_all_outcomes() if o.connection_id == connection_id]
    baselined = [o for o in mine if o.baseline_value is not None]
    reviewed = [o for o in mine if o.reviewed_at]
    asked = [o for o in mine if o.review_asked_to]
    return {"count": len(mine), "unit": "accepted recommendations",
            "detail": {"with_baseline": len(baselined), "reviewed": len(reviewed),
                       "review_asked": len(asked),
                       "due": len([o for o in mine if o.review_at and not o.reviewed_at])},
            "line": f"{len(baselined)} with a baseline · {len(reviewed)} reviewed · "
                    f"{len(asked)} asked of an owner"}


def _claims(connection_id: str) -> dict:
    """CB-8: numbers people said in filed Slack replies, checked against the data."""
    from aughor.hub.claims import claims_summary
    counts = claims_summary(connection_id)["counts"]
    total = sum(counts.values())
    return {"count": total, "unit": "claims",
            "detail": counts,
            "line": f"{counts['measured']} measured · {counts['contradicted']} contradicted · "
                    f"{counts['unchecked']} not checked"}


def _departures() -> dict:
    """What left the platform and what the gate held — every connection (the departures ledger
    carries no organisation filter, so this box says so rather than pretending to be scoped)."""
    from aughor.govern.departure_store import summary_counts
    counts = summary_counts()
    by_state = dict(counts.get("by_state") or {})
    total = int(counts.get("total") or 0)
    held = sum(v for k, v in by_state.items() if str(k).startswith("held") and isinstance(v, int))
    return {"count": total, "unit": "messages judged at the gate",
            "detail": {"by_state": by_state, "held": held, "awaiting_a_person": counts.get("awaiting", 0),
                       "scope": "every connection"},
            "line": f"{held} held of {total} judged — across every connection"}


# ── working memory ─────────────────────────────────────────────────────────────────────────

def _priorities(workspace_id: Optional[str]) -> dict:
    """CB-6: what the organisation is trying to do this quarter, written by its people."""
    from aughor.orgsettings import effective_settings
    rows = list(effective_settings(workspace_id).priorities or [])
    return {"count": len(rows), "unit": "priorities",
            "detail": {"metrics": [str(getattr(p, "metric", "")) for p in rows]},
            "line": ", ".join(str(getattr(p, "metric", "")) for p in rows[:3]) or "none declared"}


def _owners(org_id: str, connection_id: str) -> dict:
    """CB-3: the owners the declarations name, and how many the platform can actually reach."""
    from aughor.rbac.owners import owner_inventory
    rows = owner_inventory(org_id, connection_ids=[connection_id])
    reached = [r for r in rows if r.get("resolved") or r.get("principal")]
    return {"count": len(reached), "unit": "owners reachable",
            "detail": {"reachable": len(reached), "named": len(rows)},
            "line": f"{len(reached)} of {len(rows)} named owners reachable"}


# ── edges ──────────────────────────────────────────────────────────────────────────────────

def _edges(org_id: str, connection_id: str, boxes: dict[str, dict]) -> list[dict]:
    """Only arrows that are measurements: how many of one store's records landed in another."""
    out: list[dict] = []
    try:
        graphs = _graphs(org_id, connection_id)
        kinds: dict[str, int] = {}
        for g in graphs:
            for n in g.nodes.values():
                kinds[n.kind] = kinds.get(n.kind, 0) + 1
        briefs_cite = sum(1 for g in graphs for e in g.edges.values()
                          if e.kind == "derived_from" and g.nodes.get(e.from_id) is not None
                          and g.nodes[e.from_id].kind == "brief")
        if graphs:
            out.append({"from": "findings", "to": "facts", "count": kinds.get("finding", 0),
                        "label": "findings landed in the graph as facts"})
            out.append({"from": "metrics", "to": "facts", "count": kinds.get("metric", 0),
                        "label": "metrics in the graph"})
            out.append({"from": "facts", "to": "findings", "count": briefs_cite,
                        "label": "Briefing citations of findings"})
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "brain map: the graph edges could not be read", counter="brain_map.edges")
    asked = (boxes.get("outcomes", {}).get("detail") or {}).get("review_asked")
    if asked is not None:
        out.append({"from": "outcomes", "to": "owners", "count": asked,
                    "label": "reviews asked of an owner"})
    contradicted = (boxes.get("claims", {}).get("detail") or {}).get("contradicted")
    if contradicted is not None:
        out.append({"from": "claims", "to": "owners", "count": contradicted,
                    "label": "contradicted claims raised as a question"})
    return out


def brain_map(connection_id: str, *, workspace_id: Optional[str] = None) -> dict[str, Any]:
    """The map for one connection: the boxes, grouped by vault, and the measured edges."""
    from aughor.org.context import current_org_id
    org = current_org_id() or ""
    boxes = [
        _box("facts", "company", "Dated facts", "GET /graph", lambda: _facts(org, connection_id)),
        _box("metrics", "company", "Approved metrics", "GET /metrics", lambda: _metrics(connection_id)),
        _box("visibility", "company", "What the platform can see", "GET /visibility",
             lambda: _visibility(org, connection_id)),
        _box("findings", "engagement", "Findings", "GET /exploration/{conn}/domains",
             lambda: _findings(connection_id)),
        _box("outcomes", "engagement", "Recommendations and outcomes", "GET /investigations/{id}/outcomes",
             lambda: _outcomes(connection_id)),
        _box("claims", "engagement", "Claims checked", "GET /arrivals/claims", lambda: _claims(connection_id)),
        _box("departures", "engagement", "Messages judged at the gate", "GET /departures/summary", _departures),
        _box("priorities", "working_memory", "This quarter's priorities", "GET /org-settings",
             lambda: _priorities(workspace_id)),
        _box("owners", "working_memory", "Owners reachable", "GET /owners",
             lambda: _owners(org, connection_id)),
    ]
    by_id = {b["id"]: b for b in boxes}
    return {"connection_id": connection_id, "boxes": boxes, "edges": _edges(org, connection_id, by_id),
            "vaults": [{"id": "company", "title": "What it knows"},
                       {"id": "engagement", "title": "What it did with people"},
                       {"id": "working_memory", "title": "What people told it"}]}
