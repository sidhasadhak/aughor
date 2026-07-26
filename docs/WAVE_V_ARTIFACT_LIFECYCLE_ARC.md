# Wave V — Artifact lifecycle: versions, publish, staleness. PR arc

**Status:** scoping doc (2026-07-26). No code yet.
**Plan of record:** [`PLATFORM_PROGRAM_2026-07-24.md`](PLATFORM_PROGRAM_2026-07-24.md) — A → R → E → **C ✅** → **V** → G → S.
**Origin:** [`PALANTIR_FOUNDRY_STUDY_2026-07-22.md`](PALANTIR_FOUNDRY_STUDY_2026-07-22.md) §"Wave V" (L334-340).
**Joint:** **J5 — V generalizes C's freshness rather than inventing its own.**

---

## 0. What this is, and what it is not

**Not** a new staleness system. The survey below found **thirteen** existing dialects of "this is out
of date" in this codebase. The last thing Aughor needs is a fourteenth.

Wave V is **consolidation** — the same shape Wave E took for evals (five mutually-unaware eval
surfaces → one), applied to the lifecycle axis. Wave C's #1 stated risk was *"building a parallel
graph instead of promoting the ontology — the single biggest way to waste this wave."* V inherits
that risk verbatim, with thirteen ways to trip over it instead of one.

### The three findings that set the scope

**Finding 1 — there is no shortage of staleness machinery; there are 13 incompatible dialects of
it.** Every one is defensible in isolation. Together they mean no two subsystems can compare notes,
and each new store re-derives the hazards from scratch.

| # | Dialect | Compare primitive | Home |
|---|---|---|---|
| 1 | `fresh \| dirty \| stale \| unknown` + `skip/partial/full` | dual fingerprint equality | `ontology/graph_freshness.py` — **the only typed one** |
| 2 | Schema-fingerprint equality | md5 `!=` ⇒ cache miss | **5 independent implementations** |
| 3 | Merkle `content_hash` / `child_checksums` | hash equality, hierarchical | `ontology/doctree.py:116` |
| 4 | `enriched_hash == content_hash` | "computed-for-this-version" pin | `doctree.py:79-90` |
| 5 | Wall-clock TTL | `now - stored > ttl` | **~10 modules, 6 distinct windows** (300 s · 1 h · 2 h · 3 h · 6 h · 24 h) |
| 6 | LRU / `max_entries` | insertion order | 5 sites, **3 implementations** |
| 7 | `version` int + `superseded_by` | write-time supersede | `kernel/ledger.py:371` |
| 8 | `version` int + content `receipt` + immutable log | receipt inequality ⇒ bump | `playbook/store.py:103` |
| 9 | Watermark high-water mark | `ts_col > wm` | `explorer/watermark.py:84` |
| 10 | Source-version fingerprint | `!=` (explicitly *not* `>`) | `automations/probes.py:91` |
| 11 | Snapshot `data_version` → `confirmed/drifted/error` | token `!=` + AS-OF replay | `db/snapshot.py` + `explorer/revalidate.py:67` |
| 12 | `schema_changed \| stale \| skip` | fingerprint `!=` **OR** age > 7 d | `explorer/continuous.py:35` |
| 13 | Producer-logic version constants | int/string `<` or `!=` | **6 modules** (`ENRICHMENT_VERSION`, `VALIDATION_VERSION`, `PACK_FORMAT`, `DOSSIER_VERSION`, `PUBLIC_RECEIPT_VERSION`, and a `"v4-valsample"` string baked into a hash input) |

**The divergence already costs correctness, not just tidiness.** Two of the five schema-fingerprint
implementations faced the identical hazard — *structure alone does not identify a schema, so a dev
and a prod copy of one DDL hash the same* — and solved it **by different conventions**:

- `db/schema_cache.py:26` folds the scope **into the hash** (NUL-separated), keeping a legacy
  structure-only path when scope is omitted (`:32-39` documents the bug: *"the second inherited the
  first's 'fully seeded' marker without ever being seeded"*).
- `tools/profile_cache.py:41` keeps the fingerprint **structure-only** and scopes the **cache key**
  instead (`_cache_key(connection_id, fingerprint)`, `:57`).
- `ontology/store.py:262-269` uses a third shape again (`{conn}:{schema}:{fp}`, with `row_count`
  folded into the fp).

Three conventions, one hazard. A fourth author cannot infer the rule from any one of them.

**Finding 2 — the pins Foundry asks for mostly exist; they are just not called the same thing.**
Only **three** genuine "reproduce this exact thing later" mechanisms exist, and each is real:

| Mechanism | What it pins | Where |
|---|---|---|
| `ledger.artifact_by_id` | the exact artifact version a receipt was handed | `kernel/ledger.py:434` — *"so a receipt link is immutable"* |
| `playbook.get_version` | the frozen content of one past version | `playbook/store.py:95` |
| `snapshot.data_version` + `execute_as_of` | the data version, replayable `AT (VERSION => n)` | `db/snapshot.py:95,115` |

Everything else this codebase calls "pinned" or "frozen" is something else — `DashboardCard`'s
"pinned" is a *UI* pin (`dashboard/models.py:44`), a direct vocabulary collision. So **freeze is a
promotion of three existing mechanisms, not a new build.**

**Finding 3 — save≠publish is missing exactly where Foundry says it is needed, while four
incompatible draft lifecycles exist elsewhere.**

*Missing entirely* (no version, no status; update is destructive): `savedquery/models.py:14-21` ·
`canvas/models.py:40-76` · `dashboard/models.py:44` · monitor definitions · **eval suites and cases**
(`evals/store.py:73-81` — a case edit silently invalidates historical comparisons).

*Present but divergent:* `semantic/governance.py:14` (`draft|proposed|approved|deprecated` + a
transition table — the richest) · `playbook/models.py:21` (3 states, no `proposed`) ·
`packs/models.py:14` (3, different set) · `routers/metrics.py:347` (a free string, no gate at all).

And `superseded` is overloaded **four** ways: the ledger's row pointer, `evidence/models.py:40`'s
`outcome_status`, the playbook's append log, and `BriefingPanel.tsx:2319`'s request-sequence guard.

### So what Wave V actually is

**One lifecycle vocabulary every artifact speaks, assembled by promoting what exists:**

1. **Lift** C3's typed vocabulary out of the graph into a kernel every store can call (§V1).
2. **Resolve** staleness on *inputs AND logic*, not wall-clock (§V2) — the Foundry rule.
3. **Give** the artifacts that lack one a save≠publish lifecycle, on the ledger's existing version
   model, converging the four draft state machines (§V3).
4. **Promote** the three real pins into one freeze concept that errors loudly (§V4).
5. **Replace** the hand-maintained invalidation call list with a registry (§V5).
6. **Surface** it — including the `fresh|dirty|stale|unknown` banner C3's flag already promises and
   which **no UI renders today** (§V6).

### The honest ceilings, stated up front

- **Unifying a fingerprint's *inputs* would silently invalidate every live cache.** A changed hash
  is a mass cache miss — an expensive, invisible rebuild on someone's warehouse. V1 therefore ships
  **adapters that reproduce each legacy fingerprint byte-for-byte**, with a test pinning each one.
  Convergence of *hash inputs* is explicitly out of scope; convergence of the *vocabulary and the
  decision* is the goal.
- **13 → 1 is not achievable and not the target.** TTL caching (§5) is correct for genuinely
  time-bound things; a watermark's `>` is correct where `!=` is not (`automations/probes.py:11-12`
  argues this deliberately). V converges the ones that answer *"is this artifact out of date?"* — it
  does not abolish caches.
- **Business data-freshness (SLA lag hours) is a different axis** and stays separate
  (`monitors/runner.py:461`, `routers/metrics.py:41`). It shares the word "stale" and nothing else.
  Naming must keep them apart or V makes the collision worse.
- **Loud failure on a frozen artifact can turn cosmetic staleness into an outage.** Scoped strictly
  to *explicitly frozen* artifacts (§V4), never to the live-by-default path.

---

## PR-V1 — The freshness kernel: one vocabulary, one logic-version registry

**Why first.** Everything downstream compares against a verdict type that lives in one module today
and is spelled twelve other ways elsewhere. `ontology/graph_freshness.py:13-15` already says it is
*"written to be lifted by Wave V (J5): one staleness dialect for graph, briefs, profiles, and
caches, not four."* This PR cashes that in.

**Scope**

1. `aughor/kernel/freshness.py` — move `StalenessState`, `ChangeClass`, `FreshnessVerdict` and
   `classify`'s *shape* (not its ontology-specific inputs) into the kernel. `graph_freshness`
   becomes its first caller and keeps its public API byte-identical.
2. A **fingerprint registry**: named fingerprint kinds with adapters that reproduce today's hashes
   exactly (`schema_cache`, `profile_cache`, `ontology.store`, `suggestions_cache`,
   `graph_freshness`). One documented rule for the structure-vs-identity hazard, so the next author
   inherits it instead of re-deriving it.
3. A **logic-version registry** replacing the six ad-hoc encodings — one place that answers *"has
   the producer's logic changed?"*, including the `"v4-valsample"` string currently baked into a
   hash input (`profile_cache.py:53`).

**Flag** ~~`freshness.kernel`~~ → **none, deliberately** · **Tests** 29 · **Decision gate:** every
legacy fingerprint adapter reproduces its current hash **byte-for-byte** on a fixture corpus (no live
cache is invalidated by this PR), and `graph_freshness` emits identical verdicts through the kernel on
C3's existing test corpus — a differential test, not a rewrite that "looks equivalent".

> ✅ **BUILT** (2026-07-26). Gate met: the six golden hashes are pinned as **literals captured before
> the refactor** (a hash recomputed from the function under test would pass through the very change it
> exists to catch), and C3's existing corpus is green unchanged. Live proof: all three real committed
> connections still hit the ontology cache and return `skip / fresh` through the new path. Full unit
> suite 4,266 green; `data/` byte-identical before and after.
>
> **Deviation — no flag.** This PR was pre-registered with a `freshness.kernel` flag. V1 turned out to
> gate *nothing*: it is a pure consolidation whose behaviour is byte-identical by construction, so a
> flag would switch nothing and become exactly the flag-drift this repo has already paid for once (19
> features ON in one ledger while the code shipped them OFF). The first *gated* behaviour is V2's
> resolved rebuild. Recorded here rather than quietly dropped.
>
> Also landed, because the inventory needed them nameable: `PROFILE_LOGIC_VERSION` extracted from an
> inline `"v4-valsample"` hash-input literal, and `compute_ontology_fingerprint` lifted verbatim out
> of `get_or_build_ontology`. Both pinned byte-for-byte. And `structural_fingerprint` now shares one
> pass with the per-table map, which removes a double-hash the delegation would otherwise have added.

## PR-V2 — Staleness-resolved rebuild: inputs AND logic, not wall-clock

**Why.** Foundry's rule (study L44): *an output is fresh iff its inputs and its logic-hash are
unchanged.* Aughor rebuilds on a **timer** in 9 places. A 2-hour brief TTL
(`knowledge/briefing.py:25`) is wrong in both directions: it rebuilds a brief whose inputs never
moved (pure cost, and each rebuild is LLM spend), and it serves a brief for up to two hours after
its source table changed (a wrong number, which is the expensive failure).

The input signal already exists: A3's `automations/probes.py:91 current_version` computes a table's
source fingerprint in **one bounded aggregate**, and its docstring notes it already *"generalizes the
shape of `explorer.watermark`"* — the precedent for this kind of lift.

**Scope**

1. `resolve(artifact_key, inputs, logic_version) -> FreshnessVerdict` on the V1 kernel, consuming
   A3's source probe for inputs and V1's registry for logic.
2. Convert the caches where a timer is the *wrong* primitive — brief, profile, patterns — to
   resolved rebuild, with TTL retained only as a backstop where the input probe is unavailable
   (fail-open, counted through `tolerate`, never silent).
3. An explicit `force` path, and an "as-of" stamp recording which source view an output was computed
   on (Foundry L340).

**Flag** `freshness.resolved_rebuild` · **Tests** 19 · **Decision gate (both halves, on the live
path):** a brief whose source tables did **not** change is **not** rebuilt after its TTL lapses
(cost saved, measured in requests + tokens); a brief whose source **did** change is rebuilt **before**
its TTL lapses (correctness gained). A PR that shows only the cost half has not met the gate.

> ✅ **BUILT** (2026-07-26) — `aughor/kernel/rebuild.py`, wired into `knowledge/briefing.py`'s cache
> decision. Gate met on the live path against the real `samples` connection (**5 real tables probed**,
> fingerprint `8dcad6c5…`, stable across re-probe):
> **cost half** — TTL expired ⇒ `rebuild=False, staleness=fresh, saved_a_rebuild=True`
> (*"TTL had lapsed but nothing moved"*); **correctness half** — source version differs, TTL still
> valid ⇒ `rebuild=True, staleness=stale, caught_a_stale_read=True`. (The warehouse was **not**
> mutated to stage the second half — that would be a user's real data; the prior version was seeded
> instead, while the probe, the tables and the comparison are all real.)
>
> Three refusals shipped: unversionable inputs **fail open to the caller's TTL and say so**
> (`resolved=False`, so a caller can never claim "nothing changed" on a probe that did not answer);
> a bitten probe cap **names how many tables it skipped**; and state is recorded **only after** a
> successful rebuild — recording on failure would consume the change and make a stale artifact read
> fresh (A3's fired-tick rule). The stamp reuses the **pre-generation** probe, so a source that moves
> during a slow LLM generation still triggers the next rebuild.
>
> V1's ratchet did its job unprompted: adding `BRIEFING_LOGIC_VERSION` failed the build until it was
> registered in `LOGIC_VERSIONS`.

## PR-V3 — The artifact lifecycle: save≠publish, semantic version, changelog diff, revert

**Why.** The artifacts a user actually authors — saved queries, canvases, dashboards, eval suites —
have **no version at all**, so an update is destructive and a viewer always sees an editor's
half-finished state. Meanwhile four incompatible draft state machines exist elsewhere.

**Scope**

1. One `ArtifactLifecycle` built on the ledger's existing `version` + `superseded_by`
   (`kernel/ledger.py:371`) — **not a new store**. Draft ⇢ published, viewers resolve published,
   editors resolve draft.
2. Converge the four draft state sets onto `semantic/governance.py`'s (the only one with a
   transition table); `playbook`/`packs` keep their auto-promotion rules as *policies over* that
   vocabulary, not as private state machines.
3. Auto semantic versioning + a **JSON changelog diff** that reports **moves**, not just
   add/delete/change (a move reported as delete+add is what makes a diff unreadable).
4. One-click revert = an `artifact_write` of a prior version's content (supersede-not-delete holds;
   history is never rewritten).
5. Give `savedquery`, `canvas`, `dashboard`, and **eval suites/cases** a version — the eval one
   closes a real correctness hole (an edited case silently invalidating historical comparisons).

**Flag** `lifecycle.publish` · **Tests** 33 · **Decision gate:** with the flag on, an editor's
unpublished edit is invisible to a viewer; publish makes it visible; revert restores **byte-identical**
prior content; and the changelog names a moved element as a move. With the flag off, every one of
these stores behaves byte-identically to today.

> ✅ **BUILT** (2026-07-26) — `aughor/kernel/lifecycle.py` + `Ledger.artifact_versions()`, wired into
> `savedquery` (the store with no version at all, whose update was a destructive `UPDATE`). All four
> gate parts proved live on a real saved query: after an edit **viewer=None while editor sees the
> draft** → publish → **viewer sees v2 while the author's WIP stays invisible** → revert to v2 landed
> as a **new v4 with byte-identical content** and history intact
> (`[(4,published),(3,draft,WIP),(2,published),(1,draft)]`).
>
> **Deviation — convergence by projection, not by rewrite.** This PR was scoped to "converge the four
> draft state machines onto `governance.py`'s". Building it showed that to be wrong: governance's
> `draft → proposed → approved → deprecated` is a *review workflow*, so pushing a saved query or a
> canvas through "proposed/approved" would invent review ceremony nobody asked for — and `playbook`'s
> auto-promotion (draft→active on ≥2 uses at ≥50%) is a *policy* that would have to be rewritten to
> fit. Shipped instead: a documented `PROJECTIONS` table mapping every existing vocabulary onto one
> publication axis that answers the only question a reader has — *what does a viewer see?* Nothing was
> forced to rename its states, and an unknown status projects to `draft` (the conservative direction —
> `routers/metrics.py:347` still accepts an ungated free-form status, which is why the default must
> not be `published`).
>
> Move detection needed a real list diff: an index-wise walk reports `[a,b,c] → [c,a,b]` as three
> unrelated changes — the exact noise the feature exists to remove — so elements are matched on
> content first, with an unmatched pair at the same index recursing so an in-place edit names the
> changed *field* rather than replacing the whole object.
>
> **Deferred to V3b:** giving `canvas`, `dashboard` and eval suites/cases the same treatment
> (`savedquery` is the wired proof; the others are the same three-line call site each).

## PR-V4 — Freeze: live-by-default, snapshot-by-choice, gone-data errors loudly

**Why.** Foundry L337: *live-by-default + explicit freeze with lock icon and as-of timestamp; frozen
artifacts whose backing data is gone error loudly.* All three ingredients exist (Finding 2); none is
composed, and "pinned" already means something else in `dashboard/`.

**Scope**

1. One `freeze(artifact, at=(version, data_version))` over the three existing pins, with an as-of
   timestamp; unfreeze returns to following live.
2. Reproduction through `snapshot.execute_as_of` (`db/snapshot.py:115`) where the connector supports
   AS-OF; where it does not, freezing is **refused with a named reason** rather than silently
   approximated.
3. A frozen artifact whose pinned data version no longer resolves **errors loudly** with the reason
   and the as-of stamp — it must never fall back to live data under a frozen label.
4. Rename the `dashboard` UI-pin to end the collision.

**Flag** `lifecycle.freeze` · **Tests** ~20 · **Decision gate:** freeze an artifact, remove/alter its
backing snapshot, and it **errors with a named reason** instead of rendering; a connector without
AS-OF support **refuses the freeze up front** instead of accepting one it cannot honour; unfreezing
restores live following.

## PR-V5 — The invalidation registry (retire the hand-maintained call list)

**Why.** `agent/bootstrap.py:177-201` and `:283-297` enumerate every cache **by name** to invalidate
it, with a partial second copy at `routers/_shared.py:38`. A new cache is correctly invalidated only
if its author remembers to edit that list — the classic "N hand-assembled copies of one shape" bug
this codebase has already paid for (Wave R: the error frame ×15, the guard battery ×5; the lesson was
*put the check on the dangerous side, not on every call site*).

**Scope** A registry a cache registers its own invalidator with; `connection_invalidated` fans out to
registrants; the hand-listed calls become registrations. A ratchet forbids new hand-added calls.

**Flag** `freshness.invalidation_registry` · **Tests** ~14 · **Decision gate:** a cache added in a
test is invalidated on `connection_invalidated` **without editing `bootstrap.py`**, and the ratchet
fires on a newly hand-added call.

## PR-V6 — The surface: staleness banner, version history, freeze control

**Why.** C4 already renders the typed state for **one** artifact: `ConnectionGraphPanel.tsx:111`
shows a `StatusChip` driven by `CGStaleness = "fresh" | "dirty" | "stale" | "unknown"`
(`web/lib/api.ts:1076`), served by `routers/ontology.py:249`. That is the pattern to *extend*, not
to invent — every other V artifact (brief, saved query, dashboard, canvas) shows nothing.

> *A survey pass for this doc initially recorded "no UI renders the staleness states"; checking it
> against the source before writing the PR found C4's chip. The claim is corrected here rather than
> shipped — a wave scoped on a wrong premise builds the wrong thing.*

**Scope** Lift C4's chip into a shared staleness affordance and put it on the other V artifacts
(reusing C6's prose gate as its copy, so the pack and the UI say the same thing); a version-history
panel with diff + revert; a freeze/unfreeze control with the lock and as-of stamp.

**Flag** `lifecycle.surface` · **Tests** — typecheck + the 4 UI gates (no frontend unit tests exist;
see README "Project status") · **Decision gate:** a dirty graph shows the banner with its reason;
revert from the history panel round-trips; a frozen artifact renders its lock + as-of stamp.

---

## The joints

- **J5 (inbound) — V generalizes C's freshness, doesn't reinvent it.** V1 *is* J5: C3 was written to
  be lifted, and `graph_freshness` becomes the kernel's first caller rather than its competitor.
- **J5 (outbound) — C's graph is V's first-class versioned citizen.** `ContextGraph.version` already
  bumps on rebuild (`context_graph.py:122`) and C6's pack already carries the typed state
  (`context_graph_export.py:59`) — the graph is the *reference implementation* of a V artifact, not a
  special case.
- **A3 → V2.** The source-version probe is V2's input signal; V2 is its second consumer, which is
  what turns it from an automations feature into a platform primitive.
- **V → G.** G's lineage-aware cascade invalidation (study L352) lands on V5's registry instead of
  extending the hand-maintained list.
- **V → S.** S's entity pages render C's graph (J6); V4's live-vs-frozen badge is the state those
  pages display.

## Sequencing

```
PR-V1 (freshness kernel: vocabulary + fingerprint & logic-version registries)
   │
   ├─→ PR-V2 (staleness-resolved rebuild: inputs AND logic)   ← the cost+correctness bet
   │
   ├─→ PR-V3 (save≠publish + semantic version + changelog + revert)
   │      │
   │      └─→ PR-V4 (freeze / pin — freezing pins a V3 version)
   │
   ├─→ PR-V5 (invalidation registry)   ← independent; seam for Wave G
   │
   └─→ PR-V6 (surface: banner + history + freeze control)   ← renders V1–V4
```

V1 is the keystone. V2 is the bet worth landing second (it is the one with a measurable cost *and*
correctness result). V3/V5 are independent consumers of V1; V4 depends on V3; V6 renders the rest.
Arc total ≈ **110 tests** + the frontend gates.

## Risks

1. **Unifying fingerprint *inputs* silently invalidates every live cache** — a mass rebuild on a
   user's warehouse, invisible until the bill. *Mitigation:* V1 ships byte-for-byte adapters with a
   pinning test; hash-input convergence is explicitly out of scope.
2. **Building dialect #14.** The failure mode is a kernel nobody calls, leaving 13 + 1. *Mitigation:*
   V1's gate is a differential test against C3's existing corpus, and every later PR must convert a
   real caller — a PR that only adds kernel surface has not met its gate.
3. **Consolidating the four draft lifecycles breaks `playbook`/`packs` auto-promotion**
   (`playbook/outcomes.py:145` promotes draft→active after ≥2 uses at ≥50%). *Mitigation:* those stay
   as policies over the shared vocabulary; their existing tests are the regression gate.
4. **Loud freeze failures become outages.** *Mitigation:* strictly scoped to explicitly frozen
   artifacts; the live path never gains a new failure mode.
5. **Vocabulary collision makes things worse, not better** — "stale" already means SLA lag, quarantine,
   and cache miss. *Mitigation:* V owns *artifact* staleness only; the SLA axis keeps its own words,
   and the `dashboard` UI-pin gets renamed rather than overloaded.
6. **`superseded` is already overloaded four ways.** *Mitigation:* V3 uses the ledger's meaning and
   renames nothing else in this wave; the collisions get named in the doc so the next reader isn't
   misled.

## Rules of engagement (inherited, non-negotiable)

Per [`PLATFORM_PROGRAM_2026-07-24.md`](PLATFORM_PROGRAM_2026-07-24.md) §6: default-off flags,
byte-identical when off · pre-registered decision gates per PR · **prove it on the live path before
saying done** · snapshot `data/` before any full-suite run · push once per branch, CI advisory ·
strictly `:free` model bindings · the anti-patterns table is binding · an unused param is worse than
a missing one, ratchet the call site, a delete is durable only when intent is the authority.
