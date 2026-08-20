# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Aughor has not cut a tagged release yet. The sections below describe the state of
`main`; the first tagged release will become `0.1.0`.

## [Unreleased]

### Fixed
- **Quick answers no longer fail on their second step with Gemini.** Google signs a
  thinking model's reasoning and returns the signature attached to the tool call it
  made; the same signature has to come back on every replay of that call, or the API
  refuses the request (`400 INVALID_ARGUMENT`, "Function call is missing a
  thought_signature in functionCall parts"). The tool loop rebuilt each assistant
  message from the call's name and arguments alone, so the signature was dropped and
  any turn that needed more than one tool call died — reading the schema and then
  querying it was enough to trigger it. The transport now carries a tool call's vendor
  fields through verbatim, and the loop no longer invents a function call the model
  never made when handing back a parse error or a nudge.
- **A file dropped into the chat lands in the right place, and says so.** Attachments
  all went to the document store, so a dropped CSV became text the model could read
  about rather than a table it could query; upload failures were swallowed and the
  question was asked anyway, answered from whatever else was in scope. Data files now
  become tables on the active connection, other files remain documents, drag-and-drop
  works on the whole conversation, and every outcome — success or the backend's own
  refusal — is shown.

### Changed
- **Charts follow the exhibit spec (CA-4).** The chart palette is now computed, never
  eyeballed: a six-check validator (lightness band, chroma floor, colour-vision-deficiency
  separation, normal-vision floor, contrast against the real card surface) runs in CI on
  both themes, the light palette was re-ordered so no confusable hues sit adjacent, the
  dark palette re-stepped into its lightness band, and the 12-hue overflow ramp is gone —
  past six series a chart folds the tail into "Other" in a dedicated de-emphasis gray.
  Marks follow fixed specs (band-derived bar widths, rounded data ends, surface seams,
  selective labels, unit-titled axes). Findings gain an **emphasis form** (the question's
  subject in the accent hue, peers receding) and a **claim title** with a deterministic
  scope · period · unit subtitle. The model now names the data's JOB (magnitude, trend,
  identity, change, share, distribution, relation) instead of picking among two dozen
  chart shapes; a period-over-period pair renders as a signed delta bar, and dual-axis
  charts are banned outright. PDF/PPTX charts come from the web's own chart resolver
  (ECharts server-side-rendered SVG via a node subprocess, embedded as vectors in the
  PDF) — the separate matplotlib chart port is deleted, so the export can no longer
  drift from what the app shows.
- **Deep analysis became the analyst (CA-3).** Behind the `ask.converse` flag, a deep
  `/ask` turn now runs a tool loop instead of the fixed phase script: the phase library
  (baseline, decompose, cross-section) plus new deterministic probes (`z_score`,
  `premise_check`, `value_lookup`, `profile_column`) become tools the model sequences
  under a per-tier step budget (`deep_loop_steps`), with every guard and Verifier check
  still inside each tool body. Each tool choice and completed slice streams through the
  turn (`converse_step`, `phase_complete`, guard receipts, report deltas), and the
  narrator synthesizes the report from the loop's evidence, weighing the loop's own
  conclusion. Deep follow-ups carry the prior turn's spec — as a mandate when the turn
  is a recognized follow-up, as context otherwise. Flag off (the default in
  deployments), the phase script serves unchanged.
- **The chat crossed the seam (CA-1).** Every chat surface — the workspace panel, the
  full-page `/chat`, "Ask this briefing" and inline briefing threads — now streams
  through the AI-SDK parts model (`/api/chat`): the 107-case frame reducer is deleted,
  turns are a pure projection over typed message parts (an unrecognised backend frame
  renders as a labelled block instead of silence), thread restore is `setMessages` over
  a new `GET /chat-sessions/{id}/messages` returning the thread as `UIMessage[]`, and
  messages gain edit-and-resend and regenerate. Plan/clarify approvals remain side
  POSTs keyed by investigation id.

### Added
- **Conversations you can keep (CA-5).** The threads rail gained rename (inline; clearing
  the name restores the opening question), delete (with a confirm, and a real delete —
  the thread's turns, evidence claims and index entries go with it), and a filter that
  appears once there are enough threads to need one. A finished answer now offers
  actions beside its follow-up questions — run it as a deep analysis, or pin its result
  to the dashboard, where the server re-runs the SQL through the guard battery before
  accepting a card. A new org setting opens the app on the conversation instead of the
  workbench (off by default).
- **Ask this briefing** — a side panel holding one conversation, pinned to insights
  mode and scoped to the briefing's connection and schema. Grounded server-side in the
  same cached brief the page is showing (flag `ask.brief_context`, default off).
- **Chart and table display edits persist.** Chart type, view, axes, aggregation,
  colour binding, legend, number format, axis titles, labels, tooltip, transform and
  reference lines now survive collapse, remount and reload — for pinned cards and for
  charts that aren't cards (findings rows, digest tiles, KPI trends).
- **"Numbers that moved" tiles expand in place**, showing the finding's untruncated
  statement, its grounded chart or table, and Evidence / Investigate.
- A single number-format authority (`aughor/util/format.py`, mirrored in
  `web/lib/format.ts`) applied both to what the model is shown and to what is stored.

### Changed
- **Briefings are scope-guarded.** The response records the scope it was generated for
  and the client refuses to display a narrative belonging to a different schema; the
  schema filter now fails closed rather than serving another schema's findings.
- **The briefing is written about the dataset**, not about the organization reading it —
  so a workspace holding several unrelated datasets no longer attributes one schema's
  activity to the company that owns another.
- **The business glossary is scoped per schema.** Two schemas that share a table name no
  longer overwrite each other's descriptions; `PUT /glossary/{table}[/{column}]` accepts
  an optional `?schema=`, and the Catalog UI now passes it.
- Trust-gate reasons in a briefing are grouped with occurrence counts instead of
  repeating the same sentence once per finding.
- Numbers in briefings and answers no longer render raw floating-point precision
  (a verdict read `…is 43.959061407888164%`).

### Removed
- **The briefing's argument-graph ("Graph") lens**, including its backend builder and the
  `POST /cards/relations` endpoint. It did not help readers reach the conclusion, and a
  brief that argues one thing should have one reading order.

### Added (earlier)
- `LICENSE` (Apache-2.0), `NOTICE`, and `web/public/fonts/OFL.txt` — the project
  previously shipped no license at all.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, this changelog, and
  GitHub issue / pull-request templates.
- Dependabot configuration for the `pip`, `npm`, and `github-actions` ecosystems.

### Changed
- The README license badge now reads Apache-2.0 (it previously claimed MIT with
  no license file present) and links to `LICENSE`.
- `web/README.md` replaced the stock `create-next-app` boilerplate.
- `evals/spider2.py` no longer defaults `SPIDER2_ROOT` to a hardcoded home
  directory.

### Removed
- Unreferenced `create-next-app` boilerplate assets from `web/public/`.

---

## Before the changelog

Aughor's development history predates this file. The engineering record lives in:

- the [git history](https://github.com/sidhasadhak/aughor/commits/main) — ~930
  commits on `main`, each tied to a pull request;
- [`ROADMAP.md`](ROADMAP.md) — what shipped, and what is next;
- [`FEATURES.md`](FEATURES.md) — a reference for each major capability and the
  files behind it.
