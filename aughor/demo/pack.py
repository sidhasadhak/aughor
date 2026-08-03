"""The demo pack — finished intelligence as a shippable, self-contained artifact.

A pack holds what one connection's exploration ALREADY produced: its investigations,
its curation, its context graph. A reader consumes it with **no model call, no API key
and no live database** — the same bet ``ontology/context_graph_export`` made for the
graph ("generation is paid once; consumption is free"), extended to the answers.

That is what makes a hosted demo possible without hosting an agent: the visitor sees real
completed work, and asking a NEW question is what requires them to connect their own
backend.

Layout::

    <pack_dir>/
      pack.json          envelope — version, connection, counts, provenance
      investigations/    one file per frozen run, named by id
      curation.json      ontology/interchange.export_bundle()
      graph/graph.json   the context-graph pack, when one exists

**Why JSON files rather than a seeded SQLite.** ``interchange.py`` sets the rule this has
to respect — a bundle is "a VIEW over the stores that already exist … never a parallel
format with its own copy of the truth". For investigations that inverts cleanly:
``report_json`` is *already* a JSON column, so a JSON file is the same representation
moved, not a second one to drift from. Shipping ``history.db`` instead would be wrong three
times over: it is a live store the suite mutates, it is opaque in review, and it carries
every OTHER connection's investigations.

**The connection filter is a safety gate, not a convenience.** The reference store held 724
investigations of which 670 were real business data on an unrelated connection. Exporting
by connection is what keeps those out of a public artifact, so this module is DEFAULT-DENY:
the caller names one connection, and a row belonging to any other aborts the export rather
than being silently skipped. Skipping would make a leak look like a successful run.

Deterministic; no model call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

#: Pack format version. Carried in the envelope so a reader refuses a FUTURE pack rather
#: than mis-reading it — the rule `interchange.BUNDLE_VERSION` already applies.
PACK_VERSION = 1

#: Investigation fields that travel. Deliberately explicit rather than `dict(row)`: a new
#: column added upstream should not silently start shipping in a public artifact.
_INV_FIELDS = (
    "id", "question", "connection_id", "started_at", "completed_at", "status",
    "hypothesis_count", "query_count", "headline", "kind", "canvas_id", "purpose",
    "report", "hypotheses", "query_history",
)


class PackError(RuntimeError):
    """Refused to build or read a pack. Never raised for 'nothing to export'."""


@dataclass
class Pack:
    """A pack in memory — what `read_pack` returns and `export_pack` wrote."""
    version: int
    connection_id: str
    investigations: list[dict] = field(default_factory=list)
    curation: dict = field(default_factory=dict)
    graph: Optional[dict] = None

    def envelope(self) -> dict:
        return {
            "version": self.version,
            "connection_id": self.connection_id,
            "counts": {
                "investigations": len(self.investigations),
                "curation_sections": len(self.curation or {}),
                "graph": bool(self.graph),
            },
        }


# ── export ───────────────────────────────────────────────────────────────────────

def _collect_investigations(connection_id: str,
                            investigation_ids: Optional[list[str]]) -> list[dict]:
    """The connection's finished investigations, newest first.

    Raises when a requested id belongs to a different connection. That is the whole
    safety property: a filter that silently drops a foreign row reports success while
    having been asked to do something it must never do.
    """
    from aughor.db.history import get_investigation, list_investigation_ids

    ids = investigation_ids if investigation_ids is not None else list_investigation_ids(connection_id)
    out: list[dict] = []
    for inv_id in ids:
        rec = get_investigation(inv_id)
        if rec is None:
            raise PackError(f"investigation {inv_id!r} not found")
        owner = rec.get("connection_id") or ""
        if owner != connection_id:
            raise PackError(
                f"refusing to export {inv_id!r}: it belongs to connection {owner!r}, "
                f"not {connection_id!r}. A demo pack carries ONE connection.")
        if rec.get("status") != "complete":
            continue          # an unfinished run is not an artifact
        out.append({k: rec.get(k) for k in _INV_FIELDS})
    out.sort(key=lambda r: (r.get("started_at") or "", r.get("id") or ""), reverse=True)
    return out


def _collect_curation(connection_id: str) -> dict:
    """The connection's curation, through the real stores (Wave O7's interchange)."""
    try:
        from aughor.ontology.interchange import export_bundle
        return dict(export_bundle(connection_id).sections or {})
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "curation unavailable — pack ships without it",
                 counter="demo_pack.curation_failed")
        return {}


def _collect_graph(connection_id: str) -> Optional[dict]:
    """The context-graph pack payload, or None when the connection has no graph.

    `build_pack_payload` takes the graph itself, not a connection — the graph is stored
    per (org, connection, schema), so it has to be loaded and, for a multi-schema
    connection, merged first.
    """
    try:
        from aughor.ontology.context_graph_export import build_pack_payload
        from aughor.ontology.context_graph_search import merge_graphs
        from aughor.ontology.context_graph_store import load_graphs_for_connection
        from aughor.org.context import current_org_id

        graphs = load_graphs_for_connection(current_org_id(), connection_id)
        if not graphs:
            return None
        graph = graphs[0] if len(graphs) == 1 else merge_graphs(graphs)
        if graph is None:
            return None
        # Staleness travels WITH the data: a consumer reading the pack offline cannot
        # re-derive it, which is the same reason context_graph_export carries it.
        return build_pack_payload(graph)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "context graph unavailable — pack ships without it",
                 counter="demo_pack.graph_failed")
        return None


def export_pack(connection_id: str, out_dir: str | Path, *,
                investigation_ids: Optional[list[str]] = None) -> Pack:
    """Write a demo pack for ONE connection. Reads only; never mutates a store.

    `investigation_ids` narrows the selection; omitted, every completed investigation for
    the connection travels. Either way each row's ownership is checked — naming an id from
    another connection is an error, not a filtered-out row.
    """
    if not connection_id:
        raise PackError("connection_id is required — a pack is always scoped to one")

    pack = Pack(
        version=PACK_VERSION,
        connection_id=connection_id,
        investigations=_collect_investigations(connection_id, investigation_ids),
        curation=_collect_curation(connection_id),
        graph=_collect_graph(connection_id),
    )
    write_pack(pack, out_dir)
    return pack


def write_pack(pack: Pack, out_dir: str | Path) -> Path:
    """Serialise a pack to disk. Split from `export_pack` so a round-trip check can write
    a pack it did not read from the stores."""
    d = Path(out_dir)
    (d / "investigations").mkdir(parents=True, exist_ok=True)
    # sort_keys so two exports of the same content are byte-identical — the round-trip
    # gate compares bytes, and dict ordering would otherwise fail it for no reason.
    _dump(d / "pack.json", pack.envelope())
    _dump(d / "curation.json", pack.curation)
    if pack.graph is not None:
        (d / "graph").mkdir(parents=True, exist_ok=True)
        _dump(d / "graph" / "graph.json", pack.graph)
    for inv in pack.investigations:
        _dump(d / "investigations" / f"{inv['id']}.json", inv)
    return d


def _dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


# ── read ─────────────────────────────────────────────────────────────────────────

def read_pack(pack_dir: str | Path) -> Pack:
    """Load a pack from disk. Refuses a version this build does not understand."""
    d = Path(pack_dir)
    env_path = d / "pack.json"
    if not env_path.exists():
        raise PackError(f"no pack.json in {d} — not a pack directory")
    env = json.loads(env_path.read_text())
    version = int(env.get("version") or 0)
    if version > PACK_VERSION:
        raise PackError(
            f"pack is version {version}; this build understands {PACK_VERSION}. "
            "Refusing rather than mis-reading a newer format.")

    inv_dir = d / "investigations"
    investigations = [json.loads(p.read_text())
                      for p in sorted(inv_dir.glob("*.json"))] if inv_dir.exists() else []
    investigations.sort(key=lambda r: (r.get("started_at") or "", r.get("id") or ""), reverse=True)

    graph_path = d / "graph" / "graph.json"
    return Pack(
        version=version,
        connection_id=env.get("connection_id") or "",
        investigations=investigations,
        curation=json.loads((d / "curation.json").read_text()) if (d / "curation.json").exists() else {},
        graph=json.loads(graph_path.read_text()) if graph_path.exists() else None,
    )


# ── the round-trip gate ──────────────────────────────────────────────────────────

def pack_round_trips(pack_dir: str | Path) -> bool:
    """Read a pack, write it back out, and compare every file byte-for-byte.

    `interchange.py` sets this bar and the reasoning carries over unchanged: "a lossy
    round-trip is worse than no interchange at all: it looks like a backup". A pack that
    loses a finding on re-bake would still open, still render, and still be wrong.
    """
    import tempfile

    src = Path(pack_dir)
    original = read_pack(src)
    with tempfile.TemporaryDirectory(prefix="aughor-pack-rt-") as tmp:
        write_pack(original, tmp)
        return _same_tree(src, Path(tmp))


def _same_tree(a: Path, b: Path) -> bool:
    names_a = {p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file()}
    names_b = {p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file()}
    if names_a != names_b:
        return False
    return all((a / n).read_bytes() == (b / n).read_bytes() for n in sorted(names_a))
