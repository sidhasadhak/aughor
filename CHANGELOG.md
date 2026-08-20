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
- **A deep analysis breaks the data down the way the question asked.** "Give me route
  wise number of flights" produced a report ranking market, origin, destination and haul
  — every dimension except route — and framed each one as a weakness scan ("does not
  represent a performance deficit") for a question that asked for a count. The intake
  model picks the drill-down dimensions and had simply dropped the one the question
  named; a breakdown the question states outright now leads them, matched against real
  schema columns (a table's own key is excluded, since grouping by it yields one row per
  record). A request to see the data also keeps its descriptive framing when it routes
  cross-sectionally, instead of being told to hunt for underperformance.
- **A deep analysis shows the queries it ran.** Only the four phase tools built a
  phase, and the report draws its exhibits from phase findings — so a turn the analyst
  answered with its own `run_sql` rendered as a few sentences with no table and no chart,
  while the quick path, which draws its rows directly, showed the whole breakdown. Deep
  read as thinner than quick for the same question. A query the model frames itself now
  becomes a finding in a phase of its own, streams as one, and is drawn by the same
  organs as every other finding, carrying its own SQL.
- **An answer no longer reports a change that never happened.** A quick answer opened
  "Compared to the previous report from August 20, 2026, the picture has expanded
  significantly. While the previous report only listed three routes… the current data
  reflects a much broader set of 84 routes." Nothing in the data had changed: the earlier
  turn was a run that reported it could not analyse anything and named three routes as
  examples, and the cross-session block offered it as a baseline and asked for a
  comparison. A run that reported no data is no longer offered as one, and the
  instruction now says what is comparable — a differing value for the same measure, never
  how many rows an answer happened to list.
- **A table in a chat answer renders as a table.** The answer surface had an
  inline-only renderer — bold, figures, currency — so a turn that tabulated its result
  put every pipe and dash on screen: `| Route ID | Number of Flights | | :--- | :--- |
  | ZRH-LHR | 108 |`. Answer text carrying a markdown table now renders it, and
  paragraphs separated by blank lines stay separate paragraphs instead of collapsing
  into one.
- **A question that asks to see the data is no longer answered as a failed
  comparison.** "Give me route wise number of flights" run deep came back framed around
  a comparison nobody asked for — "no prior period exists in the current dataset to
  facilitate a comparative analysis", a `vs No prior period exists in the data` subtitle,
  and a closing line about needing a broader historical dataset — printed over the
  breakdown that was actually requested. The deep path is built around "why did X
  change", and a listing fell through it. A request for a breakdown or a count is now
  recognised from the question and reported as what it is: the totals, how they are
  distributed, what leads and trails — including a question with no breakdown at all
  ("what is the average order value"), which fell through the same gap. A weakness scan
  ("which route is weakest") no longer carries the missing-period apology either: it
  compares dimensions, not periods. Cause questions keep their own framing, causal
  wording is honoured wherever it appears ("what is the reason revenue dropped" opens
  like a lookup and is not one), and a change question whose data holds no earlier period
  still says so.
- **A deep analysis no longer reports its own findings as a failure.** A run that
  answered from an ad-hoc query — no phase tool firing — published the headline "Data
  unavailable — flight count could not be analyzed" and the sentence "Every diagnostic
  query failed or returned zero rows" directly above the correct totals it had just
  computed. The guard that forces an evidence-free report to read as a failure counted
  only findings belonging to a phase, and an ad-hoc query produces none. It now also
  counts the rows the analysis gathered outside its phases: a run with real evidence
  keeps its own headline, while still being held to LOW confidence with its attribution
  and recommendations withheld, because no structured phase stands behind them. A run
  that genuinely gathered nothing still says so.
- **A quick answer can no longer cite numbers its own query did not return.** The
  chart, the table and the receipt all came from the result set; the sentence above them
  was whatever the model wrote, and nothing compared the two — so a question about
  flights per route was answered with a tidy table of 108 / 96 / 84 while the chart
  beside it, drawn from the same rows, showed 28 / 42 / 35. Every number in the closing
  answer is now checked against the rows the turn executed: a magnitude blown out of
  scale, and — new — a value cited next to a label the result actually contains. An
  unsupported answer gets one chance to be rewritten from the real values, and is
  withheld rather than shown if it still cannot be grounded. The guard appears in the
  receipt chain, so what it caught is inspectable.
- **A question about the data's own subject is no longer refused.** Asking "give me
  route wise number of flights" answered `"flights" is not present in this data.` on a
  warehouse whose first table is flights. The ground-first resolver takes the noun after
  a preposition as a filter candidate and asks every text column whether any row equals
  it; nothing equals "flights", and that honest "absent" became a dead end. A noun that
  names a table or a column is now read as the question's subject or breakdown, never as
  a missing value — decided against the schema in front of it rather than a stopword
  list. A genuinely absent entity still abstains exactly as before.
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
