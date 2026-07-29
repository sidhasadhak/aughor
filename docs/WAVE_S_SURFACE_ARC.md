# Wave S — Surface & composition (scoping doc)

The last wave in the L→G→O→Q→S program, and the only one that mostly *composes* rather than
builds. Written before code, as C, V, O and Q were.

**Plan of record:** [`PLATFORM_PROGRAM_2026-07-26.md`](PLATFORM_PROGRAM_2026-07-26.md) §6.

---

## 0. What S composes — and what is genuinely ready

S's items are each "render a thing another wave built", so the honest first question is
which of those things now exist. Surveyed 2026-07-29:

| S needs | Built by | State |
|---|---|---|
| Domains to render (S1) | **G2** tag plane | ✅ store + clearances, flag-gated |
| Entity pages (S1, J6) | **C** context graph | ✅ committed artifact + `GET /graph` + panel |
| Format spec for answer rendering (S2, #189) | **O1c** | ✅ declared; **rendering is S2's half** |
| Freshness-rung label (S2) | **V** + **C3** | ✅ `fresh\|dirty\|stale\|unknown` |
| Verified badge (S2) | trusted queries + **N1** pinning | ✅ store + `human_pinned` warrant |
| Health caveats on answers (S2) | **Q4** | ✅ **wired to the live receipt** |
| Fix-it loop (S3) | **E5/E6**, **O4**, L3 | ⚠️ `closed_loop` measured and OFF |
| Digests (S4) | **A5** automations + **G3** usage | ✅ engine default-on; usage rollup exists |
| MCP `describe_entity` / `search_graph` (S6) | **C** | ✅ graph + search exist |
| MCP `get_table_health` (S6) | **Q3** | ✅ one results store |
| MCP `list_trusted_queries` (S6) | trusted-query store | ✅ exists |

**The finding that shapes the order: S6 is ready today and S1–S3 are not.** Every backing
store S6 needs landed in this program, and S6 is backend — no design pass, no component
library, no `web/` restructure. S1–S3 are the largest frontend work in the repo's history
against a `web/app/page.tsx` that is **2,469 lines and a single-page shell**, and the
program itself says "pair with a design pass".

So S6 goes first. That is not the program's order, and the reason to depart from it is
that shipping the composition layer that is ready beats blocking it behind a design pass
nobody has scheduled.

## 1. The items

### S6 — distribution · ~2 PRs · **first, because it is ready**

- **MCP extension**: `describe_entity`, `search_graph`, `get_table_health`,
  `list_trusted_queries` beside the ten tools already served. Each reads a store this
  program built; none needs new machinery.
  ⚠️ **The clearance question is real here and easy to miss.** MCP is an *external agent*
  surface: `search_graph` returns graph nodes and `get_table_health` returns table names.
  Both must go through **G5's trim** or the MCP server becomes the hole in the wall G5
  built. This is the same dependency O1b hit, and it is stated here so it is not
  rediscovered.
- **`llms.txt` + `AGENTS.md`**: neither exists. Cheap, and the audience is exactly the
  agents this platform expects to be consumed by.
- **OpenAI Responses-compatible façade** over ask/investigate, with R4's typed errors
  slotted into its taxonomy. Larger; its own PR.

### S1 — the consumer surface · ~2 PRs · needs a design pass

Routing (curated-first), listing pages with Certified/Favorite filters, **For you**
(recently opened / favorites / trending from drill records), **Domains = G2's tags
rendered** (J13 — no separate domain store), **entity pages = graph nodes rendered** (J6).

### S2 — answer anatomy · ~2 PRs · **closes #189**

Receipt rendered as expandable analysis; **verified badge** when a trusted query served the
answer; **freshness-rung label** on every answer; **per-column formats from O1c's spec** —
#189 closes here, and J11 says no chart-level formatting hack in between. Q4's caveats
render in this anatomy rather than beside it.

### S3 — the loop UX · ~1–2 PRs

Fix-it flow (typed what-was-wrong → `record_verdict` → priors); add-as-instruction /
add-as-benchmark on any answer; accuracy as a per-connection product number with trend.
⚠️ **`closed_loop` is measured and OFF** (a no-op on ~90% of the corpus). S3 must not
present a loop the platform does not run; either the flag graduates on new evidence first,
or the UX is scoped to what does run.

### S4 — digests · ~1 PR

Weekly workspace brief on Aughor's own exhaust — volume, abstentions, feedback trend, top
curation actions from the O4/Q2 queues. Briefs dogfooded, on the A5 engine that is already
default-on.

### S5 — task + document surfaces · ~1–2 PRs

Scheduled-task threads, document canvas with click-through citations, opt-in cited memory.
**V6b** (lifecycle React panel) and **K5** ("annotate this cell") land here — the two
deferrals the program has been carrying since Wave V.

## 2. Structural rules set before code

- **J6 — an entity page is the graph rendered.** No second entity store, no per-page
  queries the graph already answers. Gate: the page renders from the committed artifact
  with no extra source queries.
- **J13 — Domains are G2's tags rendered.** No separate domain store.
- **J11 — #189 has one fix across two waves.** O1c declares, S2 renders. A chart-level
  format hack in between is the bug.
- **One caveat path holds.** Q4's assembler is the renderer; S2 displays what it returns
  and does not re-derive or re-word.
- **G5 applies to every new surface**, including MCP. An external-agent surface that skips
  the trim is a bigger hole than an internal one, because its consumer is not a person who
  might notice.
- **Nothing renders a number the platform did not compute.** S2 displays formats, badges
  and caveats produced upstream; a surface that computes its own version of a governed
  number is the drift every prior wave paid to remove.

## 3. Order and gates

**S6 → S4 → S2 → S1 → S3 → S5.** Backend-ready first; digests next (they need no new
surface); then the answer anatomy that closes #189; then the consumer surface and loop that
want the design pass.

Gates: an entity page renders from the committed graph with no extra source queries; the
accuracy number and its history render per connection; an end-to-end Fix-it (thumbs-down →
typed correction → next answer cites it); an unmodified OpenAI SDK client completes an ask
round-trip against the façade; **new:** every MCP tool that returns table-derived data goes
through the G5 trim, tested.

**Effort:** 6–8 PRs. S6 and S4 are deterministic; S1–S3 and S5 are the frontend wave and
should be paired with a design pass rather than improvised.
