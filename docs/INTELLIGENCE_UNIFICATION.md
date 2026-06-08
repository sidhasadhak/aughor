# Unifying Aughor Intelligence — Briefing · Hub · Domains

*Architecture review + SOTA design. 2026-06-08.*

## TL;DR

**Briefing, Hub, and Domains are not three tools — they are one body of intelligence shown at
three levels of synthesis, over a single underlying corpus (the explorer's Phase‑8 domain
insights + computed patterns + promoted org knowledge).** They feel confusing for three concrete,
fixable reasons:

1. They're presented as **peer tabs** when they're a **synthesis ladder** (raw → structured → narrated).
2. Their **scope is inconsistent** — Ontology is schema-scoped, Domains is connection *or* canvas,
   Hub and Briefing are connection-only. Inside a Canvas, Domains narrows to your tables but the
   Brief and Hub still talk about the whole connection. That mismatch is the core "I don't know
   what I'm looking at."
3. They go **silently empty** when the explorer's Phase‑8 ontology gate fails — exploration is
   marked "complete" with zero insights and no error, so all three surfaces look broken.

**Scope answer to your direct question:** Briefings are **connection-level** today. There *is* an
optional `?schema=` filter but it's a half-wired refinement, not the scope. The right canonical
scope is **Canvas-first, Connection-default, Schema-as-filter** — the Databricks Genie-Space /
Palantir object-set model.

---

## 1. What each surface actually is (code-grounded)

All three read the **same data substrate**:
- `data/exploration_{conn_id}.json` → `insights[]` (per-domain, novelty 1–5, with SQL) — produced
  by `aughor/explorer/agent.py` Phase 8 (the curiosity loop).
- computed `patterns` (`aughor/knowledge/patterns.py`) — cross-domain angle/entity/convergence.
- Qdrant `org_intelligence` — insights promoted via "Promote to Org →".

| Surface | Component | What it is | LLM? | Scope (today) |
|---|---|---|---|---|
| **Domains** | `DomainIntelPanel` / `ExplorationPanel` | **Raw evidence** — per-domain insights, SQL, episode traces, filters | no | connection **or** canvas |
| **Hub** | `IntelligenceHub` | **Deterministic synthesis** — KPI strip, top-8 headline findings, cross-domain patterns, schema profile, domains grid | no | **connection only** |
| **Briefing** | `BriefingPanel` / `knowledge/briefing.py` | **Narrative** — Monday-morning brief with inline citations [1][2], 2h cache | yes | **connection only** (`briefing_cache.json` keyed by `connection_id`) |
| **Ontology** | `OntologyPanel` | **Structure** — entities, relationships, metrics, actions | no | **schema** (`{conn}:{schema}:{fp}`) |
| **Org** | `OrgIntelPanel` | **Promotion store** — everything pushed org-wide | no | **global** (cross-connection) |

The ladder, made explicit:

```
ORG (cross-connection promoted knowledge)
  └─ BRIEFING      "what should I care about?"     ← narrative over ↓
       └─ HUB      "show me the synthesis"          ← deterministic rollup of ↓
            └─ DOMAINS  "show me the evidence"       ← raw insights + SQL
                 └─ ONTOLOGY  "the object model"     ← the structural spine under everything
```

Briefing literally consumes Hub's data sources and adds prose; Hub literally rolls up Domains'
insights. They are the *same findings* at three zoom levels — which is exactly why three peer tabs
reads as redundant and unleverageable.

## 2. The scope/containment model (confirmed)

```
WORKSPACE  (named grouping of connections — no artifacts of its own)
  └─ CONNECTION  (one DSN; may expose several schemas)
        ├─ SCHEMA   (logical; ontology + learned actions are keyed here)
        └─ CANVAS   (curated subset = {connection, schema?, tables[]}; a Genie Space)
```

Artifact → scope (with the inconsistency that drives confusion):

| Artifact | Scope key | Honors Canvas? |
|---|---|---|
| Ontology | `{conn}:{schema}:{fingerprint}` | schema only |
| Exploration / Domains | `{conn}` **and** `canvas_{id}` | ✅ yes |
| **Hub** | `{conn}` | ❌ no |
| **Briefing** | `{conn}` (cache), optional `?schema` | ❌ no |
| Metrics | global | n/a |
| Org intelligence | global (Qdrant) | n/a |
| Annotations / KB | `{conn}` (not schema-segregated) | ❌ |

**The HIGH-severity inconsistency:** open a Canvas focused on 5 tables → *Domains* correctly shows
canvas-scoped insights, but *Hub* and *Briefing* still render the entire connection. The user is
told "this is about your 5 tables" and "this is about the whole database" at the same time.

## 3. Why intelligence is often empty (the "not triggering" problem)

Exploration **auto-starts** on connection creation (`_kickoff_exploration` in
`routers/connections.py`). But Phase 8 — the only phase that produces *domain insights* — sits
behind an **ontology gate** (`explorer/agent.py` ~L301–316): it calls `build_intelligence()`, and
**if that throws, Phase 8 is skipped, the run is marked COMPLETE, and zero insights are written —
with no surfaced error.** Downstream, Domains/Hub/Briefing all show a generic "nothing here yet."

So "they aren't triggering" is usually: *exploration ran, Phase 8 silently no-op'd.* Secondary
causes: novelty-decay short-circuits to very few insights; Briefing's narrative needs a manual
"Generate AI Brief" the first time.

---

## 4. How Databricks / Palantir would do it

- **Databricks (Genie + Unity Catalog):** intelligence is *not* a set of sibling tabs. You pick a
  **Genie Space** (a curated table set = our Canvas); suggested questions, summaries, and dashboards
  live *inside that space*, scoped to it. Unity Catalog is the structural spine (our Ontology).
  **Principle: scope follows the data asset you're in — catalog → schema → table → space.**
- **Palantir (Ontology + AIP):** there is **one** semantic object model; AI and humans act *through*
  it. Insights and briefings attach to **object types / object sets**, and you drill org → type →
  instance. **Principle: one spine; everything else is a lens or an action over it, at a chosen
  granularity.**

Both converge on the same two ideas Aughor is missing: **(a) a single scoped surface, not parallel
tabs; (b) scope that follows a clear hierarchy and is consistent for every lens.**

## 5. The design — one Intelligence surface, two axes

Replace the 5-peer-tab switcher with **one surface controlled by two orthogonal axes:**

### Axis 1 — SCOPE ("the where"), one selector, consistent everywhere
A single scope control bound to the hierarchy: **Org · Connection · Schema · Canvas.** Whatever the
user picks re-scopes *every* lens (Brief, Synthesis, Evidence). Canonical default = **Canvas if one
is active, else Connection.** This is the single highest-leverage fix: it makes "what level am I
looking at" explicit and identical across all content.

> Concretely: give `IntelligenceWorkspace` a `scope: {level, id}` prop and thread it into Brief +
> Hub the way `DomainIntelPanel` already threads `canvasId`. Add the canvas variant of the briefing
> endpoint (`/exploration/canvas/{id}/briefing`) and key `briefing_cache.json` by `scope_key`, not
> just `connection_id`. Finish wiring the `?schema=` filter end-to-end.

### Axis 2 — ALTITUDE ("how much synthesis"), progressive disclosure, not tabs
Collapse Briefing/Hub/Domains into **one scrolling view at three depths** (the natural reading order):

```
┌── THE BRIEF ───────────────────────────────────────────────┐
│ 1–3 sentence narrative for the current scope, with [1][2]   │  ← was "Briefing"
│ citations. "Revenue concentration is worsening in EMEA…"    │
├── THE SYNTHESIS ───────────────────────────────────────────┤
│ KPI strip · top headline findings · cross-domain patterns   │  ← was "Hub"
├── THE EVIDENCE ────────────────────────────────────────────┤
│ per-domain insights, each with SQL + episode trace, filters │  ← was "Domains"
└────────────────────────────────────────────────────────────┘
   (Ontology stays as a peer "structure" view — it's the spine, not an altitude)
```

One scope, one scroll from story → synthesis → evidence. Drilling a brief citation scrolls you to
the exact finding and its SQL. This is the Palantir/Databricks shape: a story on top, the receipts
beneath, the object model underneath.

### Axis 3 (the payoff) — make it ACTIONABLE, and PUSH it
Heavy-duty intel earns its keep only if you can act on it and it comes to you:
- Every finding → one-click **Investigate** (exists), **Create Monitor/Alert**, **Promote to Org**,
  **Share/Assign**. (Aughor already has Action Hub + Monitors + Evidence Ledger — wire them in.)
- **Deliver the Brief, don't make users fetch it** — scheduled Monday-morning brief per scope
  (email/Slack via Action Hub). Databricks/Palantir push intelligence.
- Every brief claim already can cite SQL + freshness + confidence via the **Evidence Ledger
  (Sprint 44)** — surface that drill-through so intel is trustable, not just readable.

### Fix the silent-empty (prerequisite for any of this to land)
When Phase 8 is skipped because the ontology gate failed, show a **specific** state —
"Intelligence couldn't build: ontology failed to generate — [Retry]" — and make the gate
retry/repair instead of no-op'ing. An empty surface that can't explain itself reads as "broken."

---

## 6. Recommended sequencing (minimal-touch first)

1. **Scope consistency (highest leverage, low risk):** thread one `scope` into Hub + Briefing;
   add canvas briefing variant; key the briefing cache by scope. Kills the canvas/connection
   mismatch. *(backend: 1 endpoint + cache key; frontend: prop threading.)*
2. **Surface the silent-empty** and make the ontology gate retryable. *(explorer/agent.py + an
   error state in the panels.)*
3. **Merge the three tabs into one progressive surface** (Brief → Synthesis → Evidence) with the
   scope selector on top; keep Ontology and Org as peers. *(frontend IA; data layer unchanged.)*
4. **Actionability + push:** finding-level actions + scheduled brief delivery via Action Hub;
   Evidence-Ledger drill-through on every claim.

Net effect: one intelligence surface, at a scope the user chooses and that every lens respects,
that explains itself when empty, and that pushes trustable, actionable findings — instead of five
look-alike tabs over the same data at inconsistent scopes.
