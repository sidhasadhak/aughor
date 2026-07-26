# Wave L — Leverage / activation arc

**Program:** [`PLATFORM_PROGRAM_2026-07-26.md`](PLATFORM_PROGRAM_2026-07-26.md) §2.
**Branch:** `2026-07-26-wave-l1-graph-live-path` (off `260c37a`). **Nothing pushed.**

> **Thesis.** A fresh clone must behave like the platform the docs describe. 87 flags,
> 17 default-ON; every `graph.*` flag, `closed_loop` and `automations.*` off. L is
> measurement plus wiring, almost no new machinery — except where the wiring turns out
> never to have existed, which is what L1 found.

---

## Status

| Item | State |
|---|---|
| **L1** — background build + live-path writers | ✅ **built, 3 commits, local** (live HTTP gate still owed) |
| **L2** — graduate `graph.readback` | ⭕ next |
| **L3** — graduate `closed_loop` | ⭕ |
| **L4** — graduate `automations.source_probes` + `engine` | ⭕ |
| **L5** — seed curation on the demo connection + export the C6 pack | ⭕ |
| **L6** — A/B `ada.evidence_stubs` (the Wave-R measurement debt) | ⭕ |
| **L7** *(opt)* — V3b artifact wiring | ⭕ |

Commits so far: `251ce6e` (glossary fix) · `b682f80` (investigations → graph) ·
`c2cad8b` (brief projector + exploration trigger).

---

## L1 — what was actually wrong

The plan assumed the graph was empty because nothing *triggered* a build. Verifying
first showed three separate causes, only one of which was a missing trigger.

**Measured before:** three committed graphs, all with zero `finding`, zero `brief`,
zero `grounded_in`, zero `defines`, zero `resolves`.

1. **`defines` — a total-loss bug.** `load_merged_glossary()` returns the envelope
   `{"tables": {...}}`; the projection iterates its argument as `{table: meta}`. The
   loop ran once, on the literal key `"tables"`, failed the connection-scope check and
   `continue`d — **199 tables dropped on every connection, always.** Green tests: the
   fixtures hand-built the unwrapped shape while production called the real loader.
   *Fixed at the boundary (`_load_glossary`). Live: workspace 3 → 255 glossary terms,
   samples 1 → 111.*
2. **`finding`/`grounded_in` — the wrong source, not a missing trigger.**
   `load_findings` enumerates the **explorer** store; an investigation or chat answer
   writes a Ledger receipt under `ada:`/`chat:` keys. Investigations were
   **structurally invisible** — 412 receipts on `workspace`, never a node. No trigger
   could have fixed that. *Fixed with a new source + a live incremental write.*
3. **`brief` — a declared kind with no projector.** In `NodeKind`, in the header, never
   emitted by anything. *Fixed with `_project_briefs` + a `briefs=` source.*

`resolves` stays empty **by design**: resolution subjects are natural-language phrases
("GMV by marketing channel") that match no term/metric/table, so nodes are emitted as
orphans. Revisit in Wave O (O1's synonym plane is the natural fix).

## L1 — what was built

- `Ledger.artifacts_of_kind(kinds, conn_id=, org_id=)` — the missing enumeration
  (every other artifact API needs a natural_key the caller already knows).
- `load_investigation_findings` — receipts → findings, provenance `evidence_ledger`.
  A receipt without a headline concluded nothing and is not a finding.
- `note_finding` / `note_brief` — incremental writes, wired at
  `_write_answer_receipt` (the ONE place chat/ADA/monitor answers are receipted) and
  at the brief cache write in `get_briefing`.
- `context_graph.add_findings` / `add_briefs` — public projectors returning emitted
  node ids, so the incremental and rebuild paths cannot drift (a test asserts the
  nodes are byte-identical).
- `_project_briefs` — `brief` nodes + `derived_from` → cited findings.
- `SchemaExplorer._rebuild_context_graph()` at COMPLETE → `refresh_context_graph(force=True)`.
- `refresh_context_graph(..., force=True)` — the new bypass.

## Decisions worth not re-litigating

- **`force` exists because the classifier is schema-only.** A run that discovers a
  dozen findings and changes no column classifies SKIP. `force` also bypasses
  `graph.freshness` (that flag governs *classification*; a forced caller isn't asking
  for one). `graph.build` still gates the write ⇒ flag-off byte-identical.
- **Serialize graph writes; never declare them parallel-safe.** `save_graph` is
  read-modify-write. R5's rule: the check sits on the dangerous side.
- **Decline rather than guess the schema.** With several graphs and no schema named,
  `note_finding`/`note_brief` return False — attaching a finding to whichever schema
  sorted first grounds it in data it never read.
- **The receipt path's `schema` is schema TEXT** (it feeds metric enforcement), not a
  schema name. Passing it to the store addresses a file named after a DDL blob.
- **Bounds are declared and counted, never silent.** `_MAX_RECEIPT_FINDINGS = 100`,
  chosen by measurement (~36 serialized lines/finding on a 5,455-line baseline;
  100 → 0.32 MB/9.4k lines, 400 → 0.76 MB/20k and breaks C1's diff-readable premise).
  Truncation bumps `context_graph.receipts_truncated`.
- **Projectors return emitted ids**, replacing a node-count delta that could not tell
  an update from a rejection (a regenerated brief reuses its id).
- **The private-cross-import ratchet (22) fired** on reaching into `_project_findings`
  → fixed by adding a public API, never by raising the baseline.

## L1 proof (live path, isolated `AUGHOR_STATE_DIR`; real `data/` verified untouched)

```
glossary   workspace glossary_term  3 → 255      samples  1 → 111
findings   400 finding nodes / 549 grounded_in from real receipts (pre-cap)
flag OFF   artifact sha256 unchanged — byte-identical
flag ON    finding:ONPROOF at v2, grounded_in → table:Order, table:Return
brief      v1→v2, brief:workspace "Refund Pressure On Margin" prov=briefing,
           3 derived_from from 4 citations (ghost dropped), canvas brief refused
explorer   plain refresh on unchanged schema → change=skip, rebuilt=False
           completion hook → v1→v2 rebuilt anyway
```

Gate: `uvx ruff@0.15.20 check .` clean · **518 passed**
(`-k "graph or context or ledger or ratchet or boundary or swallow or private or brief or explor"`).

## L1 remainder (owed)

**The live HTTP gate.** The program's L1 gate is: fresh clone + demo connection + one
`/investigate` ⇒ graph has ≥1 finding node and its `grounded_in` edge, no manual build
step. Proven so far through the helper the receipt path calls, plus flag-off
byte-identity — **not yet through a running server**. Needs `aughor-api` up (no
`--reload`), `AUGHOR_GRAPH_BUILD=1`, one real investigation, then inspect the
committed artifact.

---

## Next: L2 — graduate `graph.readback`

**Customer:** the C2 read-back protocol is wired into the live answer path
(`verify/priors.py:213`) and ships OFF. Now that L1 makes the graph actually contain
findings, briefs and glossary terms, read-back finally has something to read.

**Method (J9 — receipts-only graduation):**
1. Build an E4 grid: `graph.readback` on vs off, same cases, same connection.
2. Floor first (J3): reference-vs-reference before any delta is attributed.
3. Report pass-rate delta, robustness, and request/token cost per answer.
4. If the gate holds, flip the default and cite the E6 `GraduationDecision` receipt in
   the commit. **A flip without a receipt is the bug.**

Run as a scheduled batch inside the free 1,000 req/day. Then L3 (`closed_loop`) and
L4 (`automations.*`) by the same recipe.

## Operating notes for whoever picks this up

- `.venv/bin/python -m pytest` — system python3.14 has no pytest.
- ⚠️ Never run the full suite (`pytest` bare): it has destroyed live `data/` twice.
  Targeted `-k` only; snapshot `data/` first if a full run is unavoidable.
- Ratchets are runnable locally: `pytest -k "ratchet or boundary or swallow or private"`.
- Live scripts need `export AUGHOR_SECRET_KEY=$(grep ^AUGHOR_SECRET_KEY= .env | cut -d= -f2-)`
  or they 401 silently (fail-open looks like abstention).
- Point proofs at a scratch `AUGHOR_STATE_DIR` so `data/` is never the test subject;
  verify with `git status --short data/` afterwards.
- `data/context_graph/` and `data/ontology_overrides/` are deliberately **tracked**
  (`.gitignore:95`) and currently untracked-in-tree — they want their own review PR,
  not a ride on a code change.
