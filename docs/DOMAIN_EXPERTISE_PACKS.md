# Specialist Agents & Domain Expertise Packs

*Design doc. Drafted 2026-06-26. Companion to [`MODE_ARCHITECTURE_AND_CROSS_POLLINATION.md`](MODE_ARCHITECTURE_AND_CROSS_POLLINATION.md) and [`PLATFORM_ARCHITECTURE.md`](PLATFORM_ARCHITECTURE.md).*

> **One-line thesis.** The core engine (ADA / Insight / Explorer) **stays exactly as it is**.
> On top of it we add **Specialist Agents** — *Customer Analytics*, *Supply Chain*, *Finance
> Reporting*, *Web & Tracking* — that a **user builds and deploys** as a declarative **folder**.
> The folder declares *intent*; aughor's existing grounding (profiler, KB, semantic compiler,
> SQL guards) **compiles that intent against the real warehouse**. A specialist is a persona +
> vocabulary + workflow that *steers* the engine, never a parallel engine.

---

## 1 · Why this, and why now

Aughor today is a single generalist analyst. It is very good, but every team sees the same
generic lens. A Customer Analytics team wants cohorts, churn, NRR and RFM as first-class
citizens; a Supply Chain team wants fill-rate, lead-time variance and stockout risk; Finance
wants close-cycle, variance-to-plan and margin bridges. These are not different *engines* —
they are different **vocabularies, mental models, default questions, and surfaces** over the
same trusted substrate.

The trap (the "Eve trap") is to let each team hand-roll an agent: write the SQL, wire the
tables, maintain the prompts. That does not scale and it throws away aughor's single biggest
asset — **grounded correctness**. The resolution:

> **The folder declares intent. Aughor is the compiler that grounds it.**

A specialist author declares *what metrics matter, what questions this expert owns, what the
entity model is*. They never write SQL or hardcode a table name. Binding to a specific
warehouse happens at **deploy time** through aughor's profiler and ontology — which is exactly
why the same pack is portable across connections and customers.

This is also the concrete, shippable first instance of the "agent/playbook as a folder" idea:
we earn the convention by being its first user (we build the Retention specialist *through* the
mechanism, not beside it).

---

## 2 · The three layers

```
┌──────────────────────────────────────────────────────────────────────┐
│  AUTHORING            folder-native · UI builder · AI-authored          │  ← how a user builds
├──────────────────────────────────────────────────────────────────────┤
│  SPECIALIST PACK      pack.yaml · expertise.md · metrics/ · entities/   │  ← the declaration (NEW)
│  (declares INTENT)    questions/ · playbooks/ · surface/ · evals/       │
├──────────────────────────────────────────────────────────────────────┤
│  RESOLUTION / RUNTIME router (question→expert) · entity-binding resolver │  ← the compiler (mostly NEW glue
│  (grounds INTENT)     · pack injection into the modes                    │     over existing retrieval)
├──────────────────────────────────────────────────────────────────────┤
│  CORE ENGINE          Insight · ADA (investigate.py) · Explorer          │  ← UNCHANGED
│  (executes + guards)  semantic compiler · KB · join/grain guards · jobs  │
└──────────────────────────────────────────────────────────────────────┘
```

**What changes vs what is untouched:**

| Layer | Status |
|---|---|
| ADA phase path, Insight, Explorer, the SQL safety pipeline, the Job Kernel, Trust Receipts | **Untouched.** A specialist is steering metadata injected at intake; the executors and guards are byte-identical. |
| Semantic metrics, KB (`data/kb/*`), industry KB (`data/kb/industry/*`), BusinessProfile, Playbooks, metastore Grants | **Reused.** A pack is a *curated, named, grantable* bundle expressed in these same shapes. |
| Pack spec + loader, entity-binding resolver, pack-aware router, pack→mode injection, authoring surfaces | **New.** Mostly thin glue; the one genuinely novel grounding seam is the entity-binding resolver (§5). |

---

## 3 · Anatomy of a Specialist Pack (the folder)

A pack is a directory. The folder layout *is* the definition (convention over configuration).

```
packs/customer-analytics/
  pack.yaml            # manifest: identity, persona, owner team, defaults, scope
  expertise.md         # the mental model / system-persona (markdown, loaded like a Skill)
  metrics/             # grounded metric recipes — formula + grain + anti-patterns
    cohort-retention.yaml
    nrr-grr.yaml
    rfm.yaml
  entities.yaml        # ROLE bindings (customer, event, cohort_anchor, active_definition) — NOT table names
  questions.yaml       # canonical + diagnostic questions this expert owns (drives routing + explorer angles)
  playbooks/           # investigation routines (trigger → recommendation)
    retention-drop.yaml
  surface.yaml         # optional: the dedicated view this expert renders
  evals/               # optional: golden questions + expected behaviour (the per-pack scored suite)
    retention.eval.yaml
```

### 3.1 `pack.yaml` — the manifest

```yaml
id: customer-analytics              # stable slug; the pack's identity in the registry
name: Customer Analytics
version: 1                          # bumps on any content change (mirrors PlaybookEntry.version)
persona: >                         # short — the long form lives in expertise.md
  A customer-data analyst who reasons in cohorts and lifecycles. Defaults to
  retention/repeat behaviour and is sceptical of acquisition-mix confounds.
owner_team: Customer Analytics      # who this expert serves (routing + surfacing hint)
default_temporal_grain: cohort      # cohort | period | point — overrides the generic MAX(date) default
domains:                            # the high-level areas this expert claims (routing weight)
  - retention
  - churn
  - customer lifetime value
  - segmentation
extends: []                         # optional: inherit metrics/questions from another pack
scope:                              # where it may run; resolved against metastore at deploy
  connections: ["*"]               # or explicit conn ids
status: draft                       # draft | active | deprecated
```

### 3.2 `expertise.md` — the mental model

Free-form markdown, loaded the way a Learned Skill is. This is the *persona and reasoning
stance*, not facts the KB already holds. It is injected into the mode prompt when this pack is
selected. Example excerpt:

```markdown
# Customer Analytics — reasoning stance

You think in **cohorts and lifecycles**, never raw aggregates over a moving population.

Before answering any retention question, settle three things:
1. **Anchor** — is a cohort defined by signup date or first-purchase date? They diverge.
2. **Activity** — what counts as "active"? Contractual (still subscribed) vs non-contractual
   (purchased in the window). This business is `{{business_model}}`.
3. **Confound** — a retention drop is *genuine cohort decay* until you have ruled out
   acquisition-mix shift (newer cohorts skewing to a worse channel). Always decompose.

Prefer the **cohort-retention** and **rfm** recipes over generic GROUP BY. When a number looks
like a win, check whether it is survivorship (churned users silently leaving the denominator).
```

`{{business_model}}`, `{{currency_code}}` etc. are filled from the connection's `BusinessProfile`
at injection time, so the same persona reads correctly per customer.

### 3.3 `metrics/*.yaml` — grounded metric recipes

One file per metric. **Same shape as `data/kb/industry/*.json` metric entries** (`name`,
`aliases`, `definition`, `formula`, `grain`, `anti_patterns`) plus a binding hint that references
*roles*, not columns:

```yaml
name: Cohort Retention
aliases: [retention, cohort retention, day-30 retention, m3 retention, repeat rate]
definition: >
  Share of a cohort (customers acquired in period P) still active N periods later.
  Isolates product/relationship quality from acquisition volume.
unit_or_range: ratio 0-1
formula: >
  COUNT(DISTINCT active customers in period P+N) / NULLIF(COUNT(DISTINCT customers in cohort P), 0)
grain: >
  Cohort defined at {{role.cohort_anchor}} grain; activity measured from {{role.event}}.
  Build the cohort set ONCE, then LEFT JOIN activity per offset. Never re-derive the cohort
  inside the activity scan (drops never-returning customers from the denominator).
anti_patterns:
  - "Counting only returning customers — survivorship inflates retention."
  - "Mixing signup-anchored and purchase-anchored cohorts in one triangle."
  - "AVG of per-cohort rates instead of weighting by cohort size."
binds:                              # which entity ROLES this recipe needs to be groundable
  required: [customer, event, cohort_anchor]
```

At deploy, `binds.required` is checked against the resolved entity bindings (§5). A metric whose
roles cannot be bound is surfaced as *unavailable for this connection* rather than silently
producing wrong SQL — the recipe never reaches the engine ungrounded.

### 3.4 `entities.yaml` — the role-binding contract (the crux)

The author declares **roles**, never tables. This is what makes a pack portable.

```yaml
roles:
  customer:
    description: The party whose behaviour we track over time.
    expects: { kind: entity, identity: true }     # an entity table with a stable id
  event:
    description: The dated activity that proves a customer is "active".
    expects: { kind: event, has_timestamp: true, references: customer }
  cohort_anchor:
    description: The date that places a customer in a cohort.
    expects: { kind: date, of: customer }          # e.g. signup_date OR first event date
    default: first_event                           # if no explicit signup field, derive from event
  active_definition:
    description: What makes a customer count as active in a period.
    one_of: [purchased_in_window, session_in_window, subscription_open]
    default: purchased_in_window                   # business_model-aware default (see §5)
```

The resolver (§5) proposes a concrete mapping per connection (`customer → dim_customers`,
`event → fct_orders`, `cohort_anchor → dim_customers.signup_ts`) which the deployer confirms.

### 3.5 `questions.yaml` — what the expert owns

Drives two things: (a) **routing** — matching an incoming question to this expert; (b)
**proactive angles** — what Explorer hunts when this pack is active.

```yaml
canonical:                          # questions this expert is the right answerer for
  - "How is retention trending by cohort?"
  - "Which segment is churning fastest?"
  - "What is our net revenue retention?"
  - "Who are our highest-LTV customers and what do they share?"
diagnostic:                         # the follow-ups an expert asks itself (decomposition)
  - "Is the decline genuine cohort decay or an acquisition-mix shift?"
  - "Does retention flatten (loyal core) or trend to zero?"
  - "Is the NRR change driven by expansion, contraction, or churn?"
explorer_angles:                    # proactive hypotheses for the autonomous Explorer
  - "A recent cohort whose M3 retention dropped > 10pp vs the trailing median."
  - "A segment whose repeat-purchase rate diverges sharply from the base."
intent_tags: [retention, cohort, churn, nrr, ltv, rfm, repeat purchase]
```

`intent_tags` reuse the exact mechanism the KB retriever already uses, so routing is the same
embedding/keyword match aughor already runs — no new ranking stack.

### 3.6 `playbooks/*.yaml` — investigation routines

**Same shape as `PlaybookEntry`** (`aughor/playbook/models.py`): `trigger_metric`,
`trigger_condition`, `recommendation`, etc. A pack ships curated, domain-correct plays:

```yaml
trigger_metric: cohort_retention
trigger_condition: M3 retention for a recent cohort drops materially vs trailing cohorts
trigger_operator: lt
recommendation: >
  Decompose the drop: (1) confirm it is the cohort, not the population; (2) split by acquisition
  channel to rule out mix-shift; (3) check first-week activity for an onboarding regression.
expected_impact: Recover repeat-purchase revenue on the affected cohort.
owner_role: Customer Analytics
tags: [retention, cohort, churn]
```

These flow into the existing playbook store/retriever — they are simply *seeded by the pack*
instead of learned from a Governed Dive, and carry the pack id in `tags`.

### 3.7 `surface.yaml` (optional) — the dedicated view

Declares the expert's home screen, composed from existing chart primitives:

```yaml
title: Retention
panels:
  - { kind: cohort_triangle, metric: cohort_retention, anchor: cohort_anchor }
  - { kind: line, metric: churn_rate, label: "Churn curve" }
  - { kind: waterfall, metric: nrr, label: "NRR bridge: expansion / contraction / churn" }
  - { kind: grid, metric: rfm, label: "RFM segments" }
```

Each panel resolves to a `chart_sql`-style grounded query (the same path `NorthStarMetric.chart_sql`
already uses), so the surface is correct-by-construction and reuses the briefing chart renderer.

### 3.8 `evals/*.yaml` (optional) — the per-pack scored suite

Eve's "evals are first-class" idea, scoped per specialist. Golden questions + expected behaviour,
runnable in CI to catch regressions when the pack or the engine changes:

```yaml
- question: "Show retention by monthly cohort for the last year."
  expect:
    uses_recipe: cohort-retention
    grain: cohort
    must_not: ["survivorship in denominator"]
- question: "Is retention dropping?"
  expect:
    runs_decomposition: true          # must rule out acquisition-mix, not just report the number
```

---

## 4 · Resolution & runtime — how intent gets grounded and executed

A specialist never executes anything itself. At runtime the pack contributes **steering
metadata** that is injected into the *unchanged* engine.

### 4.1 Routing (question → expert)

1. A question arrives (chat, briefing, monitor).
2. The **router** scores it against every active pack's `questions.intent_tags` + `expertise`
   embedding — the *same retrieval the KB already does* (`aughor/semantic/kb_retriever.py`).
3. The best-matching pack (above a confidence floor) is selected. Below the floor → the
   generalist (today's behaviour) handles it. No pack ever *blocks* an answer; it only sharpens
   one.
4. Cross-domain questions can select **N packs** → fan out as sub-agents and synthesise (reuses
   the cross-pollination synthesis path).

### 4.2 Injection into the modes

Once a pack is selected, at **intake** the engine receives:

| Pack contributes | Injected into | Effect |
|---|---|---|
| `expertise.md` (persona, filled from BusinessProfile) | mode system prompt | reasoning stance |
| `metrics/*` recipes | semantic metric retrieval | the expert's metrics win over generic ones |
| `entities.yaml` resolved bindings | grounding / SQL synthesis | cohort/event grain is correct, not guessed |
| `questions.diagnostic` | ADA decomposition (`plan_phases`) | the expert's follow-ups become phases |
| `default_temporal_grain` | Adaptive Temporal Scope | cohort window instead of `MAX(date)` |
| `playbooks/*` | recommendation retrieval | domain-correct plays |

Everything downstream — the SQL safety pipeline, the join/grain guards, dry-run binding, Trust
Receipts — runs **unchanged**. The pack supplies *intent*; the kernel still enforces *grounding*.
This is the invariant that keeps specialists from ever regressing correctness.

### 4.3 Proactive (Explorer + monitors + briefing)

When a pack is active on a connection, its `explorer_angles` are added to the Explorer's
hypothesis set and its key metrics are eligible for monitors. The team gets a briefing written
in *their* vocabulary, surfaced (optionally) on the pack's own `surface.yaml` view, delivered
through the existing Action Hub / brief delivery.

---

## 5 · The entity-binding resolver (the one genuinely new grounding seam)

This is the piece that turns "declared roles" into "correct SQL on *this* warehouse," and the
reason packs are portable.

**At deploy/activation**, for a `(pack, connection)`:

1. **Propose.** Run the pack's `entities.yaml` roles against the connection's profile +
   ontology. Aughor already profiles every table (`aughor/profile/`, `aughor/tools/profiler.py`)
   and builds an entity graph. The resolver scores candidate tables/columns per role:
   - `customer` → the entity with a stable identity that other tables reference most.
   - `event` → a dated fact referencing `customer`.
   - `cohort_anchor` → an explicit `signup/created` date on `customer`, else `default: first_event`.
   - `active_definition` → chosen by `business_model` (subscription → `subscription_open`;
     transactional-retail → `purchased_in_window`).
2. **Confirm.** Present the proposed mapping to the deployer with evidence (the same
   "which columns led to this" evidence `BusinessProfile` already produces). They accept or
   correct. The correction is stored as the binding.
3. **Verify.** Each `metrics/*` recipe with `binds.required` is dry-run/EXPLAIN'd against the
   binding (the universal binder backstop already used in Phase-8 grounding). Recipes that bind
   and execute are **enabled**; those that cannot are listed as *unavailable on this connection* —
   never silently wrong.
4. **Pin.** The resolved binding is stored as a first-class record keyed by `(pack, connection,
   version)`, with a content receipt, so a re-deploy is reproducible and auditable.

The binding is data, not code. A pack ships zero table names; activation produces them; the same
pack lights up a different warehouse by re-running steps 1–3.

---

## 6 · How a user builds one — three on-ramps

All three produce the **same folder**. They differ only in who is comfortable with what.

### 6.1 Folder-native (power users / git)
Write the YAML + markdown, run `aughor pack validate` (schema + binding dry-run against a
connection), commit. Git-native: a commit is a pack version; rollback is `git revert`. This is
the Eve-style path and the ground truth all other paths serialise to.

### 6.2 UI builder (analysts)
A guided flow in the app:
1. Name the expert, pick its owner team, set the default grain.
2. **Add metrics** — pick from the KB/industry library, or define a new one through the existing
   **propose-to-define** governance gate (`aughor/semantic/governance.py`), so even
   user-authored metrics are governed.
3. **Bind entities** — aughor proposes the role mapping (§5); the analyst confirms with one click.
4. **Add questions** the expert owns; aughor suggests diagnostics from the KB.
5. Preview against a connection → deploy.

Under the hood this writes the folder and runs the same validator.

### 6.3 AI-authored (the killer path)
> *"Build me a Supply Chain Analytics expert for this warehouse."*

Aughor introspects the connection (it already profiles it), retrieves relevant KB + industry
recipes, and **drafts the entire pack** — persona, metrics, role bindings, questions, playbooks,
surface — then drops the user into the §6.2 review flow to edit and confirm. This is only
possible *because* of aughor's grounding: it can propose a *correct* expert, not a plausible one.
This is the demo that sells the platform.

---

## 7 · Deploy & lifecycle (reuses the metastore)

A pack is a **first-class metastore securable**, alongside Catalog/Schema/Volume
(`aughor/metastore/`):

- **Install** a pack into an org (the registry holds versions).
- **Grant** `workspace → pack` (USAGE), exactly like the existing `workspace → catalog` Grant
  (`aughor/metastore/models.py:Grant`). A pack is active for a workspace iff granted.
- **Bind** to one or more connections via the resolver (§5); binding records are versioned.
- **Version & rollback** mirror `PlaybookEntry.version`/`receipt` — content fingerprint per
  version, preview-before-promote, one-click rollback.
- **Audit** — install/grant/bind/route events land on the existing audit log + lineage.

Multi-tenant falls out for free: packs, grants and bindings are already `org_id`-keyed.

---

## 8 · Seam-by-seam impact map

| Existing seam | Role in specialists | Change |
|---|---|---|
| `aughor/profile/` (BusinessProfile, NorthStarMetric) | proposes entity bindings; fills persona templates | reuse |
| `data/kb/*`, `data/kb/industry/*` | metric-recipe shape; routing tags; diagnostic library | reuse (pack metrics extend this shape) |
| `aughor/semantic/` (compiler, governance, kb_retriever, metric_retrieval) | metric resolution, propose-to-define, routing | reuse |
| `aughor/playbook/` | pack playbooks are seeded `PlaybookEntry`s | reuse |
| `aughor/agent/` (graph, orchestrator, investigate, explore) | receives injected steering metadata at intake | **+injection hook**, executors unchanged |
| `aughor/explorer/` | `explorer_angles` extend the hypothesis set | reuse (+angle source) |
| `aughor/metastore/` (Grant, store, sync) | pack as securable; `workspace→pack` grants; bindings | **+pack securable type** |
| SQL safety / join+grain guards / dry-run | enforce grounding on pack-driven SQL | reuse (unchanged) |
| Action Hub / brief delivery | deliver specialist briefings | reuse |
| `aughor/kernel/flags.py` | gate the whole feature while it lands | reuse |

The new code is concentrated in: **pack spec + loader/validator**, **entity-binding resolver**,
**router + injection hook**, and the **authoring surfaces**.

---

## 9 · Reference pack #1 — Customer Analytics / Retention

We build this **through** the mechanism (dogfooding), not beside it.

```
packs/customer-analytics/
  pack.yaml            id: customer-analytics, default_temporal_grain: cohort
  expertise.md         the cohort/lifecycle reasoning stance (§3.2)
  metrics/
    cohort-retention.yaml   (§3.3)
    nrr-grr.yaml            net + gross revenue retention, expansion/contraction/churn bridge
    repeat-purchase.yaml    repeat-purchase rate, time-to-second-purchase
    rfm.yaml                recency/frequency/monetary segmentation
    clv.yaml                customer lifetime value (cohort-based, not naive AVG)
  entities.yaml        roles: customer, event, cohort_anchor, active_definition (§3.4)
  questions.yaml       canonical + diagnostic + explorer_angles (§3.5)
  playbooks/
    retention-drop.yaml     (§3.6)
    nrr-erosion.yaml        expansion stalls / contraction rises
  surface.yaml         cohort triangle · churn curve · NRR bridge · RFM grid (§3.7)
  evals/retention.eval.yaml  golden questions (§3.8)
```

Most of the *content* already exists in shallow form — `data/kb/domain_retention.json`,
`data/kb/customer_analytics.json` (12 entries incl. NRR/GRR, CAC, churn features),
`data/kb/sql_cohort_analysis.json`. Building the pack is largely **consolidation + deepening +
binding**, not greenfield authoring.

---

## 10 · Build plan

| Phase | Deliverable | Mostly… |
|---|---|---|
| **P0 — Spec & loader** | `packs/` format, schema, `aughor/packs/` loader + `pack validate`; a feature flag | new (small) |
| **P1 — Binding resolver** | role→column proposal + confirm + dry-run verify + pinned binding record (§5) | **new (the crux)** |
| **P2 — Routing & injection** | router (question→pack via existing retrieval) + intake injection hook into the modes | new glue over reuse |
| **P3 — Retention reference pack** | author `packs/customer-analytics/` end-to-end through P0–P2; live-verify on `missimi`/`beautycommerce` | content + curation |
| **P4 — Authoring surfaces** | UI builder, then AI-author; pack as metastore securable + `workspace→pack` grant | new + reuse |
| **P5 — Generalise** | Supply Chain, Finance Reporting, Web & Tracking packs; cross-pack fan-out/synthesis | content |

Each phase is independently shippable behind the flag. P3 is the proof: a real team's questions,
answered in their vocabulary, still passing every correctness guard.

---

## 11 · Invariants & non-goals

**Invariants (must always hold):**
1. **The engine is unchanged.** A specialist injects steering metadata at intake; ADA / Insight /
   Explorer executors and every SQL guard run identically with or without a pack.
2. **Packs declare intent, never SQL or table names.** Grounding happens at deploy via the
   resolver; a recipe that cannot bind is *disabled*, never silently wrong.
3. **Correctness lives in the kernel.** The pack cannot relax a guard. Worst case a pack is wrong
   *and unhelpful*; it can never be wrong *and confidently executed* — the guards still fire.
4. **A pack is data.** Versioned, granted, audited, `org_id`-keyed — a metastore securable, not a
   code deploy.

**Non-goals:**
- No parallel agent runtime, no per-pack process, no arbitrary code execution (that fights
  aughor's deterministic-SQL correctness story — explicitly rejected).
- Packs do not own connection access; the metastore gate (`membership ∪ grants`) is still the
  only authority on what data is reachable.

---

## 12 · Open questions

1. **Routing confidence floor** — when do we hand to the generalist vs a weak-match specialist?
   Probably a tunable flag, defaulting conservative.
2. **Conflicting metrics across packs** — if Customer Analytics and Finance both define `revenue`,
   which wins for a cross-domain question? Likely: governed canonical metric wins; packs may only
   *narrow*, not redefine, a governed metric.
3. **Binding drift** — schema changes after a pack is bound. Re-run resolver on profile change;
   surface a "binding stale" state rather than answering on a broken binding.
4. **Pack marketplace** — once packs are portable data, sharing/importing community packs is a
   natural extension. Out of scope now; the spec should not preclude it.
