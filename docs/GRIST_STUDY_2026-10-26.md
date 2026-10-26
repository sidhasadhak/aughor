# Grist — what a relational spreadsheet teaches a platform that owns none of the data (study, 2026-10-26)

> **Adopted in part, 2026-10-27:** Arc SV's SV-1 and SV-2, as Arc SH's precondition (ROADMAP §3.63, §6 item 56).
> The §8 calls 2–4 were decided the same day, each as recommended: SV-1 with no flag; backups keep the newest 5,
> hourly 24, daily 14, weekly 8; every store but `checkpoints.db`. **SV-1 built 2026-10-27** (ROADMAP §3.63). Open: SV-2's
> build, SV-3 and §10.5. PENDING 64.

**The ask.** The user, 2026-10-26: *"https://github.com/gristlabs/grist-core — We have to get the most out of this -
truly incredible repo."*

**What was read.** `gristlabs/grist-core` at `61d631c8` (2026-10-25), Apache-2.0: about 300,000 lines — the browser app
(`app/client`, 143k), the server (`app/server`, 60k), the Python data engine (`sandbox/grist`, 48k), the shared layer
(`app/common`, 31k) and the home database (`app/gen-server`, 17k). Four areas were read in full by four readers working
in parallel — the engine and its action model, access control and sharing, storage and history and outbound delivery,
widgets and linking and collaboration — and every mechanism this study builds on was re-read at its source line before
it was written down. Nothing of Grist was run. Aughor was measured on `main` `e25badee` and on the live install: routes
read over HTTP, the state directory listed, no store opened.

**The verdict.** Grist owns its data, and Aughor writes nothing to a customer's warehouse (ROADMAP §4.7). So Grist's
*product* mostly does not transfer: Python formulas over a document loaded into memory, a sandboxed interpreter, forms
that write rows, custom widgets with full access. Its *substrate* does. Grist is an install of SQLite files that must
not lose a write, and it has the most worked answer in open source to the failure Aughor has paid for four times:

- one writer per file;
- a labelled backup before every migration;
- a retention schedule that is a pure, tested function;
- a restore that moves the current file aside before it swaps;
- a test that proves incrementally maintained state equals state rebuilt from scratch.

None of these exists here today (§3). Take them as one small arc, **Arc SV — the platform's own state survives**.
Beyond that, Grist adds five disciplines to work already planned (§4). In nine places Aughor is already ahead and
should stay as it is (§5). Grist also has its own defects, which are listed so that nobody copies them (§7).

**And Grist's widgets add three pieces of work to Dashboards** (§10, added at the user's question):
- a breakdown piece: an entity's objects grouped by a property, a measure per group, and a click on a group that
  narrows the rest;
- rows marked by a declared rule;
- comments on a figure or an object, as said claims.

Most of the rest of Grist's widget model is already in Dashboards.

Measuring the premise also found a live defect, latent today: an API connector's incremental sync writes values into
the wrong columns without an error. It was reproduced on a scratch database (§3, SV-3).

---

## 1. What Grist is, by subsystem

| Subsystem | What it does | The mechanism worth knowing | Where |
|---|---|---|---|
| Action model | Every change is a bundle of primitive doc actions, with the exact inverse of each recorded **before** it mutates | Access is checked on the *result*; a refusal is undone by replaying the bundle's own inverse; if the revert fails, the document shuts down rather than diverge | `sandbox/grist/docactions.py:52-125`, `app/server/lib/Sharing.ts:62-301` |
| Reactive engine | Per-cell dependency graph recorded while formulas evaluate; lazy within a bundle, complete before it returns | Errors are values in the cell; the explanation is computed only when someone opens that one cell; the log records only the error class, because "the traceback may contain document data" | `engine.py:523-543, 876-882`, `depend.py:124-164` |
| Reload oracle | A test utility: a fresh engine loaded from stored data must equal the incrementally maintained one | Used across the lookup and summary suites, and as the base of a randomized fuzzer | `sandbox/grist/test_reload_oracle.py` |
| Schema migrations | Additive only; built by a deliberately "dumb" loader, not the live engine; down-migration refused | `_beforeMigration` takes a labelled backup (`migrate-schema-last-v45-before-v46`) before any migration, numbered and never overwriting | `ActiveDoc.ts:3499-3507`, `DocStorageManager.ts:160-195`, `SQLiteDB.ts:555-640` |
| Backups ("snapshots") | Pushed 15 s after the first change; pruned by a pure function | Keep the newest 5, the latest per hour (25), day (32), ISO week (12), month (96) and year; keep a labelled one for 32 days; bucket in the data's own timezone; tested with `+t1 -t2 …` strings | `DocSnapshots.ts:335-404`, `test/server/lib/DocSnapshots.ts` |
| Restore | Flush, move the current file aside as `-replacing`, fetch the backup, put the original back on error | A restore is a new version; history is not rewound | `HostedStorageManager.ts:301-330` |
| Online backup | SQLite's backup API on the live connection, 1,024 pages a step | After 10 `SQLITE_BUSY` errors the next write is held until the backup ends; a partial copy is deleted | `backupSqliteDatabase.ts` |
| Action history | Append-only, hash-chained (`sha256` over number, parent hash, info, stored actions), written in the same transaction as the data | Undo re-verifies the hash ("Hash mismatch") before replaying; trimmed at 1,000 rows or 1 GB | `ActionHistoryImpl.ts:81-99, 670`, `ActiveDoc.ts:1690-1730` |
| Access rules | Rules stored in the document; a whitelisted Python-subset predicate parsed to JSON, then compiled to closures | A rule that needs row data answers "some"; anything still undecided at the end is **deny**; an author-written *reason* and *remedy* per rule, the remedy dropped when an earlier rule shadows it | `ACLPermissions.ts:12-187`, `PermissionInfo.ts:256-346`, `predicate_formula.py` |
| Refusals | Anything that cannot apply row and column rules itself is refused, by name, for a reader who does not see everything | SQL endpoint, compare, download, fork, attachments archive, Python code | `runSQLQuery.ts:34-36`, `DocApi.ts:716-721, 1114, 2412-2417`, `ActiveDoc.ts:1906-1910` |
| Webhooks | Ready-column semantics: a record *enters* or *leaves* a condition, compared before and after the change | The payload is a frozen copy of the row at enqueue; capped exponential backoff; a hard queue cap pushes back on writers | `TriggerConditionEval.ts:80-104`, `WebhookQueue.ts` |
| Proposals | A fork's changes kept as a frozen net diff against a common ancestor hash, rebased when applied | Owners apply; one linked undo group | `DocApi.ts:1159`, `ActiveDoc.ts:1023`, `Patch.ts` |
| Widget linking | A link is stored on the *target* as (source widget, source column, target column) | One pure `isValidLink` shared by client and server decides what the picker offers | `app/common/LinkNode.ts:189-315` |
| Custom widgets | A sandboxed iframe declares the access it needs (none · read table · full) and named typed inputs | A person accepts the access and maps real columns onto the inputs, stored by column id so renames survive | `CustomWidget.ts`, `ColumnToMap.ts`, `WidgetFrame.ts` |

---

## 2. The one difference that decides what transfers

A Grist document is the data. Its engine loads every row into memory — the architecture overview calls this "limiting
and not great" — and evaluates user Python on it, so most of Grist is the work of making that safe: sandboxes (gVisor,
Pyodide, macOS), per-cell censoring, rewriting every formula when a column is renamed.

Aughor reads data it does not own, compiles every computed property to SQL (§3.46), and runs no user code. So the
spreadsheet half of Grist answers problems Aughor does not have.

What both share is everything *underneath* the data. That is a pile of SQLite files that one process must own, migrate,
copy and restore without losing a write, together with the rules about who may see what and what is said when they may
not. Aughor holds 46 SQLite stores (1,109 MB), 26 JSON files and several YAML trees under `~/.aughor/state`. That is
where Grist teaches the most.

---

## 3. Take — Arc SV, the platform's own state survives

### The premise, measured

- **No store is ever backed up on a schedule.** `~/.aughor/state` holds 46 SQLite stores totalling 1,109 MB. Four of
  them make up 1,085 MB: `system.db` 372 MB, `audit.db` 324, `checkpoints.db` 226 and `automations.db` 163. The other
  42 together are about 24 MB, and those 24 MB are most of the hard-to-rebuild state: decisions, edit history, grants,
  evals.
- **The recovery recipe is to salvage the damaged file.** The ledger's startup `quick_check` (`kernel/ledger.py:647-668`)
  tells the operator to `sqlite3 .recover` into a new file. Nothing better exists, because there is no good copy to
  return to. Three `system.db.corrupt*.bak` files and two `lost_and_found.sql` files from August sit in the state
  directory. The newest whole-state backups (`_backup_freshrun_*`, `_wipe_backup_*`) are from June, taken by hand.
- **No backup is taken before a migration.** Seventeen stores call `db/migrations.run_migrations` as they open, inside
  the serving API:
  - `actions/grants.py`, `actions/inbox.py`, `actions/overlay.py`;
  - `automations/store.py`, `custom_agents/store.py`, `db/history.py`, `db/registry.py`, `evals/store.py`;
  - `feedback/verdicts.py`, `kernel/ledger.py`, `metastore/store.py`, `monitors/store.py`;
  - `obs/agent_alert_store.py`, `packs/bindings.py`, `security/audit.py`, `semantic/ambiguity_ledger.py`,
    `workspace/store.py`.

  None of them copies the store first. On 2026-08-14 a ledger migration committed its ALTERs and a 63,000-row UPDATE
  but left `user_version` at 8, so the next open would have run it again. The recovery came from a backup taken by hand.
  AGENTS.md says "snapshot before any migration" as a rule for people; nothing in the code does it.
- **The migration test lists five stores by hand.** `tests/unit/test_migrations.py::test_converted_stores_migrate_cleanly`
  names metastore, workspace, audit, verdicts and pack bindings, while seventeen stores migrate. A hand-listed
  population cannot fail when one is missing.
  Grist has the same flaw: 4 of its 53 home-database migrations, `Proposals` among them, are missing from
  `test/gen-server/migrations.ts`'s list, though its README says to add each one.
- **The one copy that is done right refuses to run while serving.** `db/migrate.py` (IN-4) copies through
  `sqlite3.Connection.backup()` so the WAL is not lost, and verifies each copy with `integrity_check` and per-table row
  counts. It is the one-time move of the state directory and refuses while the API serves. Its copy-and-verify is what
  SV-2 reuses.

### The waves

| # | Builds | Flag · size | Falsifier |
|---|---|---|---|
| **SV-1** | **A labelled backup before every migration.** Before the first pending migration on a file-backed SQLite store, `run_migrations` copies the store through `Connection.backup()`, beside it in a `backups/` folder, as `<store>.<UTC date>.v<old>-before-v<new>.bak`, numbered and never overwriting (Grist's `createBackupFile`). It verifies the copy with `quick_check`, then migrates. If the backup fails, the migration does not run: the store opens at its old version and the API's health names it. A Postgres store (`AUGHOR_DB_URL`) says it was not copied. **The migration test is enumerated from the code**: every caller of `run_migrations` found by an AST walk, never a hand list. Each store is checked twice, from empty and from its base schema with rows in it, and both must reach the same columns with the rows intact. | none — a substrate fix (call 2) · S | A pending migration on any of the 17 stores runs with no `.bak` beside it → stop |
| **SV-2** | **Rolling backups of the platform's own state, kept by Grist's retention function.** These run *inside* the API, which is already the one writer; never as a second process, since that is the shape of every corruption so far (`db/serving.py`). Each store is copied through the backup API, and each JSON file and YAML tree is archived. A backup is taken when something changed since the last one, and at most hourly. Each copy is verified by `db/migrate.py`'s own verifier and recorded in a manifest (store, SHA-256, rows per table, `user_version`). **Retention** is a port of `shouldKeepSnapshots`: a pure function, with Grist's `+/-` tests translated. Grist's years-long caps become a bounded window (call 3). **Restore** is `aughor restore <stamp>` and refuses while serving. It takes a labelled backup of the present first, moves the current files aside, verifies, then swaps; on any failure it puts the originals back. It rolls nothing back that a person removed without saying so (below). `checkpoints.db` is left out (call 4). | `state.backups` (off) · M | The API's p95 on `/health` or `/catalog/tree` rises by more than 20% while a backup runs → move backups to a quiet hour |
| **SV-3** | **Incremental equals rebuilt.** Grist's reload oracle, as a test helper: wherever Aughor maintains state incrementally, a from-scratch rebuild must produce the same result. Its first use is the API connectors' sync (`connectors/api/base_sync.py`), where reading for this study found three defects: <br>1. **Columns written by position.** `INSERT INTO t SELECT * FROM tmp` sorts each page's keys alone. A page that lacks one field and adds another writes values into the wrong columns without an error. Reproduced on a scratch DuckDB: after one incremental page, deal 2 read `email='2', id=7`. A later sync of deal 7 then deletes it. <br>2. **A watermark that skips updates.** It is stamped *after* the fetch (`datetime.now()`), so a change made while a sync runs is never fetched. <br>3. **Tables with no `id`, and deletions.** A table with no `id` gets duplicate rows on every incremental sync, and a source deletion is never seen. <br>The fixes: insert by name over the union of columns, take the watermark at fetch start, run a full sync where there is no key, and say that deletions are seen only by a full sync. | none — defect fixes · S | — |

**Why SV-3 waits for nothing but is not first.** No API connector is configured on this install: the six live
connections are DuckDB, BigQuery and Postgres, and `api_sync/` is empty. The defects cost nothing until someone connects
HubSpot, Stripe, Salesforce or a Google Sheet. SV-1 closes a failure already paid for. Order: SV-1, then SV-2, then
SV-3, unless the user wants SV-3 first (call 5).

**What a backup must never do: resurrect.** AGENTS.md: *"Reversing durable intent must clear the durable record before
acting."* A backup is a durable record.

Restoring one taken before a person removed a connection brings back its ontology, metrics and documents. That is the
seed-resurrection bug `connectors/file/local_upload.py` already paid for, at a larger scale.

So a restore reads every tombstone and every removal in the audit dated after the backup, lists them, and asks the
person before it runs. The SQL audit and the model-call logs are never restored over. They are append-only, and the
removal default keeps them. That default is the user's, 2026-10-11, quoted in `ontology/removal.py`: a removal takes
everything but the SQL audit and the model-call logs. Grist reaches the same law from the other
side: its external attachments are never deleted per file, only when the document is, "so we can re-attempt"
(`AttachmentFileManager.ts:84-93, 338-342`).

**The laws it keeps.** Store copies go through SQLite, never `shutil` (IN-4's lesson). One process writes `data/`.
Nothing opens a live store read-only to copy it. Supersede, do not delete: a restore is a new backup, never a rewind.
"Withheld is said": a store not copied, a Postgres store, a backup that failed verification each say so, on the health
route and in `aughor doctor`. It needs no new store: the manifest is a JSON file beside each backup, and the record of
backups is the folder itself, as Grist's inventory is a file.

---

## 4. Take into work already planned — no new wave

1. **FA-5, acting on each object a rule admits** (§3.60; being built on `claude/fa-5-objects-admitted`). Grist's
   trigger conditions answer three questions — *enters*, *leaves*, *updated* — by comparing a ready condition before
   and after the change (`TriggerConditionEval.ts:80-104`), and freeze the payload at enqueue so a later edit cannot
   change what is delivered (`WebhookQueue.ts`). FA-5 as written fires only on *newly admits*. An object **leaving** a
   segment (an order no longer late, a customer no longer at risk) is the same measurement with the sign flipped. Add
   it there or as the next step; and where an evaluation error means "does not fire", Aughor should say so on the
   run, where Grist is silent.
2. **When `ontology.security` graduates — stale policies named, with a fix.** Grist lists every rule that names a
   missing table or column as a problem on the rules page, with a button that removes it
   (`ACLRuleCollection.ts:462-534`). Aughor checks a row policy's conditions only when it is declared
   (`ontology/security.py:136`, `condition_problem`), and the dependents index (`ontology/dependents.py`) has no
   *property* kind. So withdrawing a property that a row policy or a mask reads is neither refused nor reported. And
   Grist's refinement for Aughor's existing "told which groups would": drop a remedy that an earlier rule has already
   shadowed, because it would mislead (`PermissionInfo.ts:128-144, 307-346`). `ontology.security` is off, and AP-6 found
   no policy declared on theLook, so this waits for the flag.
3. **The App as a widget others embed** (FA's next list, "an App takes values from its address or an embedding host").
   Grist's column mapping is the shape for its inputs (`ColumnToMap.ts`):
   - the embedded thing declares named, typed inputs, required or optional;
   - a person maps real fields onto them, stored by id so a rename survives;
   - the two empty states are told apart: "Some required columns aren't mapped" versus "Some required columns are
     hidden by access rules" (`CustomView.ts:244-257`).

   The access request and the iframe are refused (§6).
4. **Reading under a past release** (FA's next list). Grist's `TimeQuery` (`app/common/TimeQuery.ts`) answers "what was
   this table at time *t*" from the current state plus composed diffs, with an explicit *unknown* for a cell a bulk
   change did not keep (`ActionSummary.ts`, `mayBeIncomplete`). Aughor's version substrate (`kernel/lifecycle.py`) and
   the edit layer's history (`overlay_edit_history`) hold the same inputs. The lesson is the *unknown*: a past value the
   record never kept is said as unknown, never shown as empty.
5. **Errors as values, explained on demand** (`engine.py:876-882`, `objtypes.py:316-369`). A failed computed value
   stays where it is, as a typed error naming its location. Reading it names the cell it came from, the expensive
   explanation is built only when a person opens that one value, and nothing derived from data goes to a log. This is
   for whoever next touches computed properties (§3.46) or a dashboard piece that fails.

---

## 5. Already here — where Aughor matches or is ahead

| Grist | Aughor | Verdict |
|---|---|---|
| Webhook queue: in memory, mirrored to Redis only when configured; enqueue runs **after** the commit, so a crash between them loses events; a webhook whose URL is gone drops its events silently (`WebhookQueue.ts:455`) | The outbox (`actions/outbox.py`, OC-6, `actions.outbox`): every call is a row, claimed under a lease; an *unknown* outcome is never re-sent blind, and the action's own verification read decides; a call that cannot be delivered waits for a person under Actions ▸ Sends | Ahead. Keep |
| "View as" another user can **write** (`test/server/lib/GranularAccess.ts:3832-3853`) | Preview as a group (AP-6) adds one more party to the reader's, so a preview only ever sees less (`ontology/security.py`, `_previewing`) | Ahead. Keep |
| The SQL endpoint is refused to any reader whose access is filtered | Row policies are applied *inside* every statement at the connection's door (ED-1, `sql/rls.apply_entity_rules`) | Ahead: it applies the policy rather than refusing |
| An invalid link falls back to **unfiltered** data with a console warning (`ViewSectionRec.ts:858-866`) | Wiring is checked by the same rules file the browser draws with (`web/lib/dashboards/rules.ts` through the validator bundle); an invalid spec is refused, and the dashboard stays as it was | Ahead. Keep |
| A rename rewrites every formula, rule, dropdown condition and trigger by parsed position (`useractions.py:842-935`) | Declarations have stable ids, so a rename is a new version of the same element (`ontology/history.py`); a withdrawal that would break something is refused, naming it (`ontology/dependents.py`) | Ahead, by design: nothing needs rewriting |
| Proposals applied with **no check of the before value**: last writer wins, and a partial apply is possible (`Patch.ts`) | TC-1's `expected_rev` precondition on the doors | Ahead. Do not copy Grist's apply |
| API keys kept in `users.api_key` and looked up by equality; no hashing found (`UsersManager.ts:168-171`) | Service-principal keys are hashed and compared in constant time (`security/service_principals.py:101, 161`) | Ahead. Keep |
| Audit events emitted throughout, but recorded nowhere in core (`createNullAuditLogger`) | An audit that records (`security/audit.py`, 324 MB on the live install), with a required reason on payload reads behind TC-5's `govern.justifications` | Ahead |
| The model writes a suggestion carrying the exact action; nothing is applied by the server (`OpenAIAssistantV1.ts:428-446`) | "A model never adds or wires a piece, and never authors a declaration" (§3.60) | Same law. Keep |

---

## 6. Not taken — and why

- **Python formulas, the data engine, the sandboxes.** Aughor runs no user code and compiles computed properties to SQL
  (§3.46). An interpreter, even a sandboxed one, is a second execution path outside the doors.
- **Custom widgets in an iframe with *full* access, which can write.** "No code extension point" was decided in the
  Palantir study (§4.4) and the 2027 study (§6 item 50(d)). Only the input mapping is taken (§4, item 3).
- **Forms that write rows through a share key.** Aughor writes nothing to the warehouse. If a public door is ever
  wanted, for instance an owner without an account recording a decision's outcome, Grist's shape is the one to copy:
  - a separate deny-by-default policy layer generated from the share's own settings, never stored;
  - the secret kept outside the shared thing;
  - create-only, plus reading just the lookup values the form needs (`ACLRulesReader.ts:186-380`).

  No one has asked for it.
- **Incremental imports** — a keyed merge with a named strategy, a per-cell diff preview, one undoable step
  (`ActiveDocImport.ts:484-569`). Uploads here are files a connection reads, replaced whole. No one has asked for a
  monthly-append workflow; take the design if one is.
- **Staged usage limits** — approaching at 90%, then a grace period with days left, then delete-only, where only
  actions that reduce usage pass (`Limits.ts`, `ActiveDoc.ts:2763-2770`). It is a good shape, but no cap is declared on
  this install (`GET /governance/caps` → `caps: []`).
- **A 30-day trash with an hourly housekeeper** (`Housekeeper.ts`). The removal default is the user's: a removal takes
  everything but the SQL audit and the model-call logs (`ontology/removal.py`). SV-2's bounded window is the only way a removed thing outlives its removal, and
  it is call 3.
- **Hash-chaining the audit.** Grist chains its action history so undo and compare can prove *which* state they apply
  to, not for tamper evidence. Aughor's revision preconditions (TC-1) do the first job. Tamper evidence is a separate
  question nobody has asked.
- **A schema-drift report when a store opens** (`SQLiteDB.ts:236-246, 599-609`: build the expected schema in
  `:memory:`, then warn per table). Its premise is unmeasured here: no "no such column" incident on a platform store
  was found in history. SV-1's enumerated migration test covers the same risk at test time.
- **Comments anchored to cells, governed by the cell's read permission and censored rather than dropped**
  (`CellDataAccess.ts`). Aughor's comments sit on decisions. If comments ever attach to objects, this is the rule.

---

## 7. Grist's own defects — do not copy

- `CellAccessHelper.hasAccess` returns **true when the cell must be censored**, the opposite of its docstring
  (`GranularAccess.ts:3166-3181`).
- Rows hidden by a rule disappear from a fetch with no count, while usage counts say `"hidden"`. That is the very
  thing Aughor's "withheld is said" forbids.
- The formula assistant's schema check runs only on the first message, and the conversation state comes back from the
  client (`OpenAIAssistantV1.ts:93-96`; its own TODO says to move it server-side).
- `newRec` in a multi-action bundle means "the row at the end of the whole bundle", which the code itself calls
  slippery (`GranularAccess.ts:1894-1923`).
- Chart series are cut at 100 silently (`ChartView.ts:409-417`, "we should probably show some indicator").
- On download, a checksum mismatch only warns, though the class comment promises a retry (`ExternalStorage.ts:285`).
- The default SQLite mode is `synchronous=OFF` with no WAL (`DocStorage.ts:76, 737`). Grist can afford it because its
  durability is the S3 push. Aughor has no S3 push; its WAL and `synchronous=NORMAL` (`db/sqlite_util.py`) stay.

---

## 8. Decisions for you

1. **Adopt Arc SV (SV-1, then SV-2, then SV-3) into the roadmap?** *Recommended:* yes. SV-1 is small and closes the
   failure already paid for; SV-2 turns "salvage the damaged file" into "restore the last good copy".
2. **SV-1 without a flag?** Flags are off by default and byte-identical when off (AGENTS.md), but a backup beside a
   store changes no read, no answer and no prompt, and ED-0's fixes shipped the same way. *Recommended:* no flag, with
   a test that every pending migration leaves a `.bak`.
3. **How long do backups keep what a person removed?** Grist keeps monthly backups for 8 years and yearly ones for
   1,000. Here a backup outlives a removal for as long as it is kept. *Recommended:* the newest 5, plus the latest per
   hour (24), per day (14) and per week (8), with nothing older. A labelled pre-migration backup is kept for 30 days. A
   removal is then gone from every backup within eight weeks, and a restore lists every removal it would undo and asks
   first.
4. **Which stores does SV-2 copy?** *Recommended:* every store except `checkpoints.db` (226 MB, LangGraph's resume
   points for runs in flight, `agent/graph.py:56`). The four big stores follow the same schedule; disk use is measured
   on the first week, never estimated.
5. **SV-3 now or later?** The three sync defects are proven but latent, since no API connector is configured.
   *Recommended:* third, after SV-2. Earlier if a HubSpot, Stripe, Salesforce or Google Sheets connection is coming.

---

## 9. Licence

grist-core is Apache-2.0 (`LICENSE.txt`, `NOTICE.txt`). Porting `shouldKeepSnapshots` and its tests (SV-2) is
allowed: the port carries a header naming the source file and the licence. Everything else in this study is a design
taken, not code copied.

---

## 10. Dashboards — what Grist adds to them

*Added 2026-10-26 at the user's question: "Do you not see this as an addition to the Dashboard feature that we have?"*

The first pass of this study measured Grist's substrate in depth but checked its widgets only for overlap: that wiring
is validated, and that custom widgets were already refused. Below, Grist's widget model is compared piece by piece
against the Dashboard vocabulary (`web/lib/dashboards/catalog.ts`, version 11: fifteen pieces, the filter column and the
drawer).

### 10.1 What Dashboards already have of Grist's widget model

| Grist | Dashboards |
|---|---|
| Link by the same record; a cursor link | `chooses`, an object detail that `follows` it, a drawer that `opens_on` it (AP-2, AP-4) |
| Show the referenced records | A set's `traverse` to its linked objects (AP-8b) |
| A record card opened from any reference | The drawer, and the object page |
| Card list | `ObjectList` |
| Filter bar with relative dates | The filter column (each value with its count; a click narrows every piece over the entity, for that reader) and `PeriodPicker` (current or last day, week, month or year, and a custom range) |
| "Selector for" — the widgets a selection drives | The builder marks the pieces a set is read by (`ComposedDashboard.tsx:1125`) |
| Duplicate a widget | The builder's Duplicate |
| One shared function decides what may link | `rules.ts`, run on the server through the validator bundle. It refuses an invalid spec, where Grist shows unfiltered data |
| A form widget | `ActionButtons` with a form, through the declared action: it writes the edit layer, never the warehouse |

### 10.2 What Grist adds — three pieces of work

**1. A breakdown piece: Grist's summary table and its link.**

*The premise, measured.* No piece shows an entity's objects grouped by a property with a measure per group, and no
grouped figure can narrow the rest of the dashboard:
- `ObjectChart` draws only objects per day over the last 7 to 90 days (`catalog.ts:389-405`).
- `ObjectFigure` is a single aggregate.
- The filter column shows a count per value and nothing else.
- A query piece can draw bars, but from a person's own SQL, and it is not among the pieces a click chooses in
  (`CHOOSERS`, `catalog.ts:499`).

Yet the object door already groups: `ObjectQuery.by` (`semantic/object_query.py:166-179`). For this study it returned
theLook's revenue by customer country, live: 14 countries whose orders add to the whole, 125,396.

So the piece is a new view over a door that exists, not a new query path. Mockup:
`design-mockups/dashboard-breakdown.html`, with every number read from theLook through `POST /objects/query` and
`/objects/list`.
- **What it shows.** An entity's objects, or a set's, grouped by one property. The property is the object's own or
  reached through to-one links ("Customer country, via Customer"). Each group carries one to three measures: a count,
  an aggregate of a property, or a verified metric.
- **It always adds up.** The top *N* groups are shown. The rest are folded into one *Other* row that says how many
  groups it holds. Objects with no value are a *No value* row, never dropped. So the column always adds to the whole,
  and the line beneath says the whole. Grist treats a blank the same way: it is a value to select, not nothing.
- **Shown as** a table with share bars (the default), or as bars alone.
- **A click on a group is the filter column's click.** It narrows every piece over the same entity, for that reader
  only, and the bar above the dashboard shows it as a chip. The breakdown that was clicked keeps every group, with the
  chosen one tinted. Grist never filters a widget by its own selection, and neither does the filter column.
- **Through the object door, so row policies and masks hold.** Grouping by a masked property is refused, as the door
  refuses it today, and objects a row policy withholds are said.
- **Copy and CSV**, as every table offers.
- **A model may move it or take it off, never add or wire it** (the law in §3.60).

Flag `dashboard.breakdowns` (off) · M. Falsifier: on theLook, the groups' measures do not add up to the dashboard's own
figure for the same objects → stop.

**2. Rows marked by a rule: Grist's conditional formatting, in Aughor's terms.**

*The premise.* `ObjectTable` takes an entity or set, its wiring, a `segment`, columns and a sort (`catalog.ts:332-346`).
It can show only a segment's objects, but it cannot mark the objects of a rule or a segment inside a larger set.

Grist's rule is a hidden formula column. Aughor's is already declared: a business rule or a segment on the entity.
- **Build:** a `mark` (a rule or segment, and one of the five tones in `TONES`) on `ObjectTable` and `ObjectList`, read
  through the object door as `in_set`.
- **The legend** says what the mark means and how many objects it marks.
- **No formula:** nothing a dashboard defines that the ontology does not declare.

Flag `dashboard.marks` (off) · S–M.

**3. Comments on a piece or an object.**

*The premise.* Dashboards have no comments: there is no store or prop for them. Decisions do, and they are not a
comment store. A Google comment read onto a decision is a *said* claim in the Record, in its author's name
(`record/google_comments.py`; Arc CB, §3.21). So a comment on a figure or an object is a said claim too, anchored to
`<type>:<key>` or to a piece of a dashboard version. One store per concept: there is no new comment table.

From Grist come three rules:
- **Who may comment:** a person may comment only where they can read what the comment sits on.
- **Censored, not dropped:** a comment on something the reader may not see is shown as withheld, never hidden
  (`CellDataAccess.ts`).
- **Threads, mentions and resolve.**

Recorded, not proposed for building until someone asks to discuss a figure on a dashboard · M.

### 10.3 The smaller ones — mostly done

- **Relative dates.** `PeriodPicker` has them for cards. Object pieces read a fixed window (`days`, 7 to 90) and could
  follow the picker. S, with no ask.
- **A calendar piece.** None exists; `ObjectTimeline` is the nearest. No ask.
- **"Selector for" and Duplicate.** Both exist (§10.1).

### 10.4 Still refused

Iframe widgets with access to a document, formulas, and forms that write rows (§6). Grist's column mapping is taken
only for the App as a widget (§4.3).

### 10.5 Decisions for you

6. **Build the breakdown piece once the mockup is approved?** *Recommended:* yes, behind `dashboard.breakdowns`, on
   theLook first.
7. **What does a click on a group do?** *Recommended:* the filter column's click: one mechanism, already readable in
   the bar. The alternative is a named choice that wired pieces read (`chooses`). It is more powerful, but it is a
   second way to narrow a dashboard.
8. **Rows marked by a rule: with the breakdown, or after it?** *Recommended:* after it, as its own small step.
9. **Comments on figures and objects?** *Recommended:* keep the design recorded, and build when someone asks.
