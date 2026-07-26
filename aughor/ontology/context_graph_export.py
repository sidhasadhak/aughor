"""Distribution — the committed artifact + the skills pack (Wave C6).

The mechanic that converts a single user into a team: the graph is *just a file*, so a
teammate consumes it with **no LLM, no API key, and no Aughor running**. Generation is
paid once (C1's deterministic projection); consumption is free. An agent sitting in a
dbt repo can answer "what does ``net_revenue`` mean and which tables feed it" from an
exported pack with this process not running at all.

What ships in a pack:

* ``graph.json`` — the C1 artifact re-emitted **self-contained**: the same nodes, edges
  and provenance, wrapped in an envelope that carries the source spine, the graph
  version, and the **typed freshness state** (C3's ``fresh|dirty|stale|unknown``). The
  staleness travels *with* the data, because a consumer offline cannot re-derive it.
* ``skills/*.md`` — the read-back protocol (C2) written for an agent to run **offline**:
  freshness-check → grep names/summaries/tags → pull the 1-hop subgraph → answer only
  from that subgraph, citing tables. Every skill opens with the freshness-gate preamble
  — a trust receipt in prose.
* ``install.sh`` — symlinks the skills into agent platforms. No MCP server, no daemon.

**No coercive hook injection.** The anti-pattern table forbids the "You MUST … do not
ask" auto-update hook that the studied tool used: a pack Aughor writes *surfaces*
staleness and lets the reader act on it. ``install.sh`` therefore only ever links files
into place — it never registers a hook, and no skill instructs an agent to refuse the
user or to hide the freshness state.

Gated behind ``graph.export`` (default off) so ``main`` is byte-identical: the export is
never assembled and nothing is written.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aughor.kernel.errors import tolerate
from aughor.kernel.flags import flag_enabled
from aughor.ontology.context_graph import ContextGraph

# Bumped when the on-disk pack shape changes incompatibly. A consumer reads this FIRST
# and can refuse a format it does not understand, instead of silently mis-parsing.
PACK_FORMAT = 1

# The staleness states a consumer should treat as "answer, but say the graph may lag".
# `stale` means the schema itself moved (tables/columns added or removed) — the one
# state where an answer can name a table that no longer exists.
_DEGRADED = ("dirty", "stale", "unknown")


@dataclass
class ExportedPack:
    """What an export produced — the receipt the CLI/test prints."""

    root: Path
    files: list[Path] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    staleness: str = "unknown"
    node_count: int = 0
    edge_count: int = 0

    @property
    def graph_json(self) -> Path:
        return self.root / "graph.json"


def export_enabled() -> bool:
    return flag_enabled("graph.export")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _freshness_prose(state: str, reason: str) -> str:
    """The trust receipt in prose that rides in the envelope and heads every skill.

    Deliberately *informative*, not coercive: it tells a reader what the state means
    and what it implies for an answer, and leaves the decision with them.
    """
    if state == "fresh":
        return (
            "FRESH — the exported graph matched the warehouse's structure and row counts "
            "when it was written. Answers grounded in it can be given plainly."
        )
    if state == "dirty":
        return (
            "DIRTY — the data moved (row counts changed) but the structure did not. "
            "Table, join and definition answers still hold; any COUNT or magnitude "
            "quoted from a finding may be out of date. Say so when quoting a number."
        )
    if state == "stale":
        return (
            "STALE — the warehouse's structure changed after this pack was written "
            f"({reason or 'tables or columns added/removed'}). A table or column named "
            "here may no longer exist. Answer if the pack supports it, but state plainly "
            "that the pack lags the warehouse and that the reader should re-export."
        )
    return (
        "UNKNOWN — the freshness of this pack could not be determined at export time "
        "(Aughor could not read the live ontology). Treat it as possibly out of date and "
        "say so when it matters."
    )


def build_pack_payload(
    graph: ContextGraph, *, staleness: str = "unknown", reason: str = ""
) -> dict:
    """The self-contained ``graph.json`` envelope.

    Nodes and edges are emitted as **id-sorted lists** rather than the store's keyed
    dicts: a list of one-object-per-block pretty-printed JSON is what makes the file
    *greppable*, which is the whole consumption story (an agent greps names, summaries
    and tags — it does not load a graph library). Provenance is carried verbatim, so a
    consumer can audit an edge (J4) exactly as the live read-back can.
    """
    nodes = [n.model_dump() for _, n in sorted(graph.nodes.items())]
    edges = [e.model_dump() for _, e in sorted(graph.edges.items())]
    return {
        "format": PACK_FORMAT,
        "generator": "aughor",
        "exported_at": _now(),
        "source": {
            "org_id": graph.org_id,
            "connection_id": graph.connection_id,
            "schema_name": graph.schema_name,
            "graph_version": graph.version,
            "graph_generated_at": graph.generated_at,
            "structural_fingerprint": graph.structural_fingerprint,
        },
        # The typed C3 state, travelling with the data because a consumer cannot re-derive it.
        "freshness": {
            "state": staleness,
            "reason": reason,
            "degraded": staleness in _DEGRADED,
            "gate": _freshness_prose(staleness, reason),
        },
        "counts": graph.counts(),
        "nodes": nodes,
        "edges": edges,
    }


# ── the skills (markdown, offline, non-coercive) ──────────────────────────────

def _preamble(state: str, reason: str) -> str:
    """The freshness-gate preamble every skill ships with (§C6.3)."""
    return (
        "## Freshness gate — read this first\n\n"
        f"This pack's graph was exported in state **`{state}`**.\n\n"
        f"> {_freshness_prose(state, reason)}\n\n"
        "`graph.json` → `freshness.state` is the authority; re-read it rather than "
        "trusting this sentence, because the pack may have been re-exported since.\n"
        "If the state is anything other than `fresh`, include that caveat in your answer "
        "— the reader decides what to do about it. Re-export with "
        "`aughor graph-export <connection-id> --out <dir>` where Aughor runs.\n"
    )


def _skill_answer_from_graph(state: str, reason: str) -> str:
    return f"""---
name: answer-from-aughor-graph
description: Answer a question about this warehouse's tables, joins, metrics or
  established findings from the exported Aughor connection graph — offline, with no
  database access and no Aughor running. Use when asked what a column or metric means,
  which tables relate, how two tables join, or what has already been established about
  an entity.
---

# Answer from the Aughor connection graph

This directory holds `graph.json` — a typed, provenance-carrying graph of one database
connection, exported by [Aughor](https://github.com/sidhasadhak/aughor). It is the
product of a deterministic projection over the warehouse's schema, its profiler output,
its governed metric definitions, its glossary and the findings of past investigations.
Every edge carries the evidence that produced it.

You can answer from it **without a database connection, an API key, or Aughor running**.

{_preamble(state, reason)}

## Protocol

1. **Check freshness.** Read `freshness.state` and `freshness.gate` from `graph.json`.
   Carry any caveat into your answer.
2. **Grep for seeds.** Search `graph.json` for the question's nouns against node
   `label`, `summary`, `tags`, and the payload in `data` (a table's `columns`, a
   metric's `formula_sql`, a term's `column`). Take the best few matches as *seeds*.
   The file is pretty-printed and id-sorted so plain `grep -n` works.
3. **Pull the 1-hop subgraph.** Collect every edge whose `from_id` or `to_id` is a
   seed, plus the nodes at the far end. That neighbourhood is your evidence — it is
   where a table reaches its joins, its glossary terms, its metrics and the findings
   already established on it.
4. **Answer only from that subgraph.** Do not infer a column, table or relationship
   that is not in it. If the subgraph does not support an answer, say so and name what
   you searched — that is a useful answer, and inventing schema is not.
5. **Cite tables.** Name the `table` nodes your answer rests on, and quote the
   provenance on any join you rely on (`provenance.measured` is a real measured
   value-domain overlap, not a guess). Node and edge `id`s are stable — cite them.

## What the types mean

| Node kind | What it is |
|---|---|
| `table` | a real table; `data.columns` are its columns, `data.domain` its business domain |
| `metric` | a governed metric; `data.formula_sql` is the definition of record |
| `glossary_term` | a table+column definition (human, dbt, or auto-seeded) |
| `domain` | a business grouping of tables |
| `finding` | something a past investigation established — build on it, don't re-derive it |
| `brief` | a synthesized executive narrative |

| Edge kind | Reading |
|---|---|
| `joins_on` | these tables join; `provenance.measured` is the measured value overlap |
| `derived_from` | a metric's formula reads this table — **this is metric lineage** |
| `defines` | a glossary term defines a column on this table |
| `grounded_in` | a finding rests on this table |
| `resolves` | a settled reading of an ambiguous term on this connection |

## Honesty rules

- An answer names its tables, or it is not an answer.
- `provenance.source` is never `llm_inferred` — there is no such source. If you cannot
  find provenance for a claim, you are inferring it; say that.
- A `finding` node is a past conclusion, not a live number. Quote it as "a previous
  investigation found …", and note the freshness state when you quote a magnitude.
"""


def _skill_trace_lineage(state: str, reason: str) -> str:
    return f"""---
name: trace-aughor-metric-lineage
description: Trace what feeds a metric or column — which tables a governed metric's
  formula reads, and which definitions and findings attach to it — from the exported
  Aughor connection graph, offline. Use for "what feeds X", "where does X come from",
  "what is X built on", or metric-definition questions.
---

# Trace lineage from the Aughor connection graph

Answers "what feeds `<metric>`?" from `graph.json` alone — no warehouse access, no
Aughor running.

{_preamble(state, reason)}

## Protocol

1. **Find the metric node.** Grep `graph.json` for the name against `label` and `id`
   (metric ids are `metric:<name>`). If the match is a column rather than a metric,
   look for a `glossary_term` node instead and follow its `defines` edge to the table.
2. **Read the definition of record.** `data.formula_sql` on the metric node *is* the
   governed formula. Quote it verbatim; do not paraphrase SQL.
3. **Walk `derived_from` to the tables.** Every edge with `kind: "derived_from"` whose
   `from_id` is the metric points to a table the formula reads. Those tables **are** the
   answer to "what feeds it".
4. **Extend one hop for context** (optional): from each feeding table, `joins_on` edges
   give the tables it relates to, `defines` edges give the documented columns, and
   `grounded_in` edges give the findings already established on it.
5. **Answer with the formula, the feeding tables, and the owner** if
   `data.owner` is set — then cite the node/edge ids you used.

## Worked shape

> **`net_revenue`** is defined as `SUM(price) - SUM(discount)`
> (`metric:net_revenue`, `data.formula_sql`).
> It is fed by **`order_items`** (`metric:net_revenue--derived_from-->table:order_items`)
> and **`orders`** (`metric:net_revenue--derived_from-->table:orders`).
> `order_items` joins `orders` with a measured 98% value-domain overlap
> (`table:order_items--joins_on-->table:orders`).

If no `derived_from` edge exists, say the pack does not record what feeds it, and name
what you did find (the formula, the domain) rather than guessing a table.
"""


_INSTALL_SH = """#!/bin/sh
# Install this Aughor graph pack's skills into the agent platforms on this machine.
#
# Symlinks (never copies) so a re-export is picked up without re-installing, and
# removing the pack removes the skills. Idempotent: re-running relinks.
#
# Deliberately NOT done here: registering any hook, prompt injection, or
# auto-update daemon. Aughor surfaces the graph's freshness state and lets you act
# on it — a pack does not install something that speaks for you.
set -eu

PACK_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$PACK_DIR/skills"
NAME="$(basename "$PACK_DIR")"

if [ ! -d "$SKILLS_DIR" ]; then
  echo "No skills/ directory in $PACK_DIR — nothing to install." >&2
  exit 1
fi

installed=0
for target in "$HOME/.claude/skills" "$HOME/.config/agent/skills"; do
  parent="$(dirname "$target")"
  [ -d "$parent" ] || continue          # platform not present on this machine
  mkdir -p "$target"
  for skill in "$SKILLS_DIR"/*.md; do
    [ -e "$skill" ] || continue
    base="$(basename "$skill" .md)"
    ln -sfn "$skill" "$target/aughor-$NAME-$base.md"
    installed=$((installed + 1))
  done
  echo "Linked $NAME skills into $target"
done

if [ "$installed" -eq 0 ]; then
  echo "No known agent skills directory found. Point your agent at:"
  echo "  $SKILLS_DIR"
  exit 0
fi

echo "Done. The skills read $PACK_DIR/graph.json — no Aughor process required."
"""


def _readme(graph: ContextGraph, state: str, reason: str, counts: dict) -> str:
    shape = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    schema = graph.schema_name or "(default)"
    return f"""# Aughor graph pack — `{graph.connection_id}` / `{schema}`

A self-contained export of one database connection's **knowledge graph**: tables,
governed metrics, glossary definitions, business domains, and the findings past
investigations established — with the evidence behind every edge.

Consume it with **no LLM, no API key, and no Aughor running**. Generation was paid
once; reading is free.

- **Graph:** `graph.json` (format {PACK_FORMAT}, graph version {graph.version})
- **Shape:** {shape}
- **Freshness:** `{state}` — {_freshness_prose(state, reason)}

## Use it

```sh
./install.sh          # symlink the skills into your agent (see the script; no hooks)
```

Or point any agent at `skills/` and let it read `graph.json` directly. The skills carry
the protocol: check freshness → grep for the question's nouns → pull the 1-hop
subgraph → answer from that subgraph, citing tables.

Plain `grep` works too — the file is pretty-printed and id-sorted:

```sh
grep -n '"label"' graph.json | head              # what's in here
grep -n -A3 'metric:' graph.json                 # governed metrics + formulas
grep -n -B2 -A6 'derived_from' graph.json        # metric lineage
```

## Re-export

This pack is a snapshot. Where Aughor runs:

```sh
aughor graph-export {graph.connection_id} --out <dir>
```

Nothing in this pack phones home, watches your filesystem, or updates itself.
"""


# ── the export ────────────────────────────────────────────────────────────────

def export_pack(
    connection_id: str,
    out_dir: Path | str,
    *,
    org_id: str = "",
    schema_name: Optional[str] = None,
    staleness: Optional[str] = None,
    graph: Optional[ContextGraph] = None,
) -> Optional[ExportedPack]:
    """Write a self-contained pack for ``connection_id`` into ``out_dir``.

    Returns ``None`` when ``graph.export`` is off (nothing is assembled or written) or
    when the connection has no committed graph to export — an export of an absent graph
    would ship an empty pack that answers confidently from nothing, which is worse than
    no pack. Pass ``graph`` to export an in-memory graph directly (the callers that
    already hold one, and the tests).

    The freshness state is computed from the live ontology unless ``staleness`` is given;
    if it cannot be determined the pack ships ``unknown`` — never a cheerful default.
    """
    if not export_enabled():
        return None

    org = org_id or _current_org()
    cg = graph if graph is not None else _load_graph(org, connection_id, schema_name)
    if cg is None or not cg.nodes:
        return None

    state, reason = (staleness, "") if staleness else _staleness(
        connection_id, schema_name, org_id=org
    )

    root = Path(out_dir)
    skills = root / "skills"
    skills.mkdir(parents=True, exist_ok=True)

    payload = build_pack_payload(cg, staleness=state, reason=reason)
    written: list[Path] = []

    def _write(path: Path, text: str, *, executable: bool = False) -> None:
        path.write_text(text)
        if executable:
            path.chmod(0o755)
        written.append(path)

    # Pretty-printed + key-sorted: greppable by construction, and a re-export of an
    # unchanged graph produces an identical file except the timestamps.
    _write(root / "graph.json", json.dumps(payload, indent=2, sort_keys=True, default=str))
    _write(root / "README.md", _readme(cg, state, reason, payload["counts"]))
    _write(root / "install.sh", _INSTALL_SH, executable=True)
    _write(skills / "answer-from-graph.md", _skill_answer_from_graph(state, reason))
    _write(skills / "trace-lineage.md", _skill_trace_lineage(state, reason))

    return ExportedPack(
        root=root,
        files=written,
        counts=payload["counts"],
        staleness=state,
        node_count=len(cg.nodes),
        edge_count=len(cg.edges),
    )


def _current_org() -> str:
    from aughor.org.context import current_org_id

    return current_org_id()


def _load_graph(
    org_id: str, connection_id: str, schema_name: Optional[str]
) -> Optional[ContextGraph]:
    """The committed graph for a connection — the specific schema when named, otherwise
    every schema merged into one export (a consumer asks about a connection, not a
    schema)."""
    from aughor.ontology.context_graph_search import merge_graphs
    from aughor.ontology.context_graph_store import (
        load_graph,
        load_graphs_for_connection,
    )

    if schema_name is not None:
        return load_graph(org_id, connection_id, schema_name)
    return merge_graphs(load_graphs_for_connection(org_id, connection_id))


def _staleness(
    connection_id: str, schema_name: Optional[str], *, org_id: str
) -> tuple[str, str]:
    """The live freshness verdict, or ``unknown`` when it cannot be read.

    Best-effort by design: a pack must still be exportable on a machine whose warehouse
    is unreachable. But the failure is *counted* and lands as ``unknown`` in the
    envelope — never silently as ``fresh``.
    """
    try:
        from aughor.ontology.graph_freshness import staleness_of

        state = staleness_of(connection_id, schema_name, org_id=org_id)
        return (state or "unknown"), ""
    except Exception as exc:  # pragma: no cover - defensive
        tolerate(
            exc,
            "graph export could not determine freshness; the pack ships state=unknown "
            "so a consumer is warned rather than misled",
            counter="context_graph.export_freshness",
        )
        return "unknown", str(exc)
