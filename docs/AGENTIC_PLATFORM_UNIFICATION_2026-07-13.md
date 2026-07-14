# Agentic Platform Unification — 2026-07-13

*Status: PROGRAM + first wave BUILT on branch `agentic-platform`. This document composes three
same-week documents into one program and records what shipped. It supersedes none of them — each
remains the detail reference:*

1. *`docs/GROUND_FIRST_RESOLUTION_2026-07-13.md` — grounding: resolve entity + time grain BEFORE
   generation; abstain honestly; delete post-hoc guards.*
2. *`docs/COPILOTKIT_AGUI_ADOPTION_PLAN_2026-07-13.md` — conversation: token streaming, dead-air
   fixes, the AG-UI protocol seam (CK-0 → CK-1 → CK-2 gate).*
3. *`docs/PLATFORM_STUDIES_COMBINED_2026-07-11.md` — platform: Capabilities Auto-mode (E3), the
   receipts family (S3), task_history (Rec 4), the connector/acceleration program.*

---

## The thesis

The user-stated goal — *"conversational, free-flowing, and grounded in utter grip on the dataset;
wire it tremendously well, lose weight, intelligent by nature (not feature flags), a breeze to set
up"* — maps 1:1 onto what the three documents already prescribe. The missing move was never a new
subsystem; it was **unification + graduation**:

- The three documents' work sat on three unpushed sibling branches (`ground-first-resolution`,
  `2026-07-13-task-history`, `2026-07-08-ui-ux-uplift`) — the platform-review diagnosis ("features
  stall at TESTED, never LEVERAGED") applied to the fixes themselves.
- 45 registered flags, 41 default-OFF — including the six self-gating guards whose deterministic
  triggers already decide per run, the receipts that make autonomy inspectable, and the ground-first
  resolution itself. The intelligence existed; the *default posture* said "off".

## The five pillars

| Pillar | Source doc | What it means | State after this wave |
|---|---|---|---|
| **Grounded** | ground-first | One deterministic resolution (entity + grain, measure-first) runs before generation, constrains it, speaks through the whole answer, abstains honestly on DB-confirmed absence | `ask.resolve_first` AUTO-elevated by default; inspect LLM call collapsed when resolution runs |
| **Conversational** | CK plan | Token streaming, no dead air, arrival motion, then the AG-UI seam | CK-0.1 feel branch MERGED; CK-0.2 insight token streaming SHIPPED (`ask.stream_text`, dual-emit); CK-0.4 `ada.progress_events` default-ON. CK-0.3 (figure-first reorder) found MOOT — the success burst already lands figure-first (headline is coder-predicted, not narrator-late) |
| **Intelligent by nature** | studies E3 | Tri-state Auto: the platform decides per run via deterministic triggers; receipts explain every activation; operator override always wins | `capabilities.auto` default-ON; AUTO_ELIGIBLE grew to 8 (added `ask.resolve_first`, `ada.pin_canonical_metric`); all receipt flags default-ON |
| **Breeze to run** | (new; spicepod ops-ergonomics lesson, Study II Part B) | One command: clone → `uv run aughor up` → seeded fixture + API + web + honest LLM-readiness report | `aughor up` CLI; /health `llm` readiness; .env.example/README aligned with code defaults; no more kill -9 |
| **Lose weight** | ground-first §deletion + studies E3/E5 | Delete what the resolution subsumes; remove superseded machinery; graduate-or-delete flags | `grain.feasibility` (superseded post-hoc verdict) fully removed; staged guard-deletion roadmap below |

## The graduation policy (the durable rule)

The house lifecycle gains a final stage: **BUILT → WIRED → TESTED → LEVERAGED → GRADUATED**.

A capability GRADUATES to default-on when it is (a) **self-gating** — a deterministic runtime
trigger decides per run, so the flag is only a master enable — or (b) a **pure
observability/receipt surface** with negligible cost. Cost-dangerous capabilities (`ai_sql`,
`federation.*`, `semops.champion_validate`) never auto-graduate. An explicit env `=0` or runtime
override always wins: every kill switch survives graduation. Autonomy requires receipts: the same
wave that turns a guard on by default turns its activation receipt on by default.

The stage after GRADUATED is **DELETED**: once a graduated capability has run on real traffic long
enough that nobody would turn it off, the flag (and any code path it replaced) is removed.

## What shipped this wave (branch `agentic-platform`)

1. **Consolidation** — the three sibling branches merged into one line. One conflict
   (`investigations.py`, resolved with ground-first as the authority); the superseded
   `grain.feasibility` machinery removed during the merge rather than carried (its one durable
   improvement — the schema-grounded semantic inspect — kept for the resolution-off path).
2. **Capability graduation** (`flags.py`) — defaults flipped per the policy above:
   `capabilities.auto`, `capabilities.receipt`, `learning.receipt`, `ask.context_receipt`,
   `obs.task_table`, `ada.progress_events`, `ask.stream_text` → ON; `ask.resolve_first` +
   `ada.pin_canonical_metric` → AUTO_ELIGIBLE. Tests re-pinned to the graduated contract plus the
   explicit-off byte-identical path.
3. **CK-0.2 token streaming** — `LLMProvider.complete_streaming` (instructor partial streaming,
   drained inside the resilience wrapper, blocking-fallback on any error) + `insight_delta` SSE
   dual-emission (full-partial-text replace semantics; terminal `insight` event stays
   authoritative and self-healing) + frontend reducer/render (auto-reveal prose while streaming,
   arrival fade for post-done insight/followups).
4. **Setup breeze** — `aughor up` (deps preflight, no-kill port handling, both processes, health
   wait, honest LLM-readiness line), /health `llm` field, CORS 3210, `.env.example` un-trapped
   (code default is ollama, not groq), README quickstart at three steps, `start.sh` a shim.

## The deletion roadmap (staged, each gated on real-traffic evidence)

Ground-first §Pending-2, now sequenced. When `ask.resolve_first` has held on real traffic
(fixture + workspace canvases, no false abstains, constraints obeyed):

**Grounded per-guard analysis (2026-07-14 — before cutting anything).** A close read of the
`_stream_chat` guards found that most are NOT redundant with the resolution and must NOT be deleted
outright — they are the safety net, and the "subsumed" claim holds only in the sub-case where the
resolution actually bound the relevant thing. The honest classification:

| Guard (line) | Verdict | Why |
|---|---|---|
| semantic `inspect` | **DELETED** (Phase 3) | The resolution re-decides the exact five things it checked. Done. |
| `grain.feasibility` | **DELETED** (merge) | A genuine post-hoc duplicate of the resolution's grain verdict. Done. |
| entity-column alignment (~1551) | **conditional skip only** | Overlaps `entity_bindings` but catches misalignments on entities the resolution did NOT bind (a second entity, a non-filter column). Skip only when bindings cover the question's entities. |
| measure-grain caveat (~1790) | **conditional skip only** | The resolution's caveat goes to the **narrator**; this one caveats the **headline** — different surfaces. Skipping it when `_resolution.caveat` is present would strip the *headline's* honest caveat. |
| id-arithmetic backstop (~1802) | **KEEP — not a duplicate** | It re-runs on the **post-repair** SQL to caveat honestly when repair could NOT eliminate a measure×key product. The pre-exec run (~1678) only *hints the repair*. Different jobs; deleting the backstop loses the fabricated-magnitude caveat when repair fails. |
| breakdown-grain, ratio-of-sums, scope guard | **KEEP for now** | Detect SQL shapes (grouped-by-id, AVG(a/b), sibling-schema refs) the resolution does not model. Not subsumed. |

So the remaining cuts are **conditional skips** (skip-when-resolution-bound), each needing its own
regression corpus AND a real-traffic soak — one live session is not a soak. Sequence:

1. Soak `ask.resolve_first` on real traffic; then land the two conditional skips (entity-column,
   measure-grain) one PR each, gated on `_resolution` having bound the exact thing.
2. The fan-out battery collapses into "emit the fan-out-safe shape from the resolved join topology".
3. Deep-path adoption: thread the same Resolution through `build_data_understanding` /
   `grounding_block()` so ADA inherits the verdict and its intake validators unify with it.
4. Flag deletions: graduated flags whose off-path nobody exercises get removed entirely
   (candidate order: `ada.progress_events`, receipts, then `capabilities.auto` itself once the
   Capabilities page is the only control surface anyone uses).

## Next waves (unchanged verdicts, resequenced)

- **CK-1 — AG-UI protocol seam** (`POST /agui/run` translator + `@ag-ui/client` adapter under the
  existing reducer; interrupts for clarify/plan gates). All CK-plan guardrails remain binding —
  never replace the shell, exact-pin dep waves, parity harness before default-flip. The `insight_delta`
  contract shipped this wave maps 1:1 onto `TextMessageContent`.
- **Ground-first breadth** — high-cardinality entities via the DB-probe path, multi-entity
  questions, disambiguation across measure tables (ground-first §Pending-4).
- **P7 decision run** — one quiet-machine bake-off through the shipped MLflow harness; still the
  single biggest answer-quality lever.
- **Connector program** (studies Wave 3) — Iceberg-REST → UC harvest → `spice` connector → Delta
  paths/Sharing; then accelerated datasets (Wave 4) with staleness receipts joining the family.
- **Agentic depth** (studies Wave 5) — double-texting, reviewer fix-loop, per-agent execution-level
  table allowlists, operational agents + MCP exposure.

## Verification playbook for this branch

- `uv run --extra dev pytest` (hermetic; stores env-pointed by conftest) + `uv run ruff check aughor/`.
- Web: `npx tsc --noEmit && npm run build` + the three design gates (`lint:tokens`, `lint:format`,
  `lint:elements`).
- Live (when a responsive LLM is configured): the luxexperience "month-wise sales for Mytheresa"
  canvas — expect the honest grain caveat, no `fiscal_month` invention, insight text streaming in,
  and a Trust Receipt whose learning/activation sections populate. The `⌘⇧L` drawer should show
  `insight_delta` frames between `done` and `insight`.
- The abstain path needs no LLM and is already regression-pinned
  (`tests/integration/test_resolve_first_runtime.py`).
