# Teable — a spreadsheet section people make and then chat with (study, 2026-10-26)

**The ask.** The user, 2026-10-26:

> *"Chuck grist.. check this: https://github.com/teableio/teable. Its ability to run custom apps is also quite unique
> along with its way to combine excels, csv and many connectors that come along with it.. we have to have a spreadsheet
> section that will be another database which users will end up creating and may want to start chatting with.. and it
> also comes with a chatbox experience.. all we need to do is push our chat experience there.. framework already
> exists!"*

> **Decided 2026-10-27 — Teable dropped.** The user: *"See if the chat and the app Builder is cloud only and then chuck
> it.. my point is that within our platform users should be able to work with spreadsheets the way screenshots
> suggest."*
>
> Measured that day: the chat and App Builder are not cloud-only. Teable's "full-featured" self-host runs them, but
> from closed images, with no source and no licence file (`teableio/teable-deployment`, whose env example has no
> licence key). So nothing of them can be built into Aughor, and Teable is not used.
>
> The direction is option B: spreadsheets inside Aughor. That makes Aughor a writer of its *own* sheets, never of a
> customer's warehouse (§4.7 stands for warehouses). What follows stays as the record of why.
>
> Recorded as ROADMAP §4.12; the spreadsheet work is Arc SH (§3.64), adopted 2026-10-27. PENDING 65.

**What was read.** `teableio/teable` at `feae0c71` (2026-10-26), about 1.57 million lines of TypeScript:
- the open repository: licence, the backend's features, the web app's slots, AI, import, plugins, storage and sign-in;
- the deployment repository's README and image list, `teableio/teable-deployment`, through the GitHub API.

Nothing was installed or run. Aughor was measured on `main` `e25badee`: the upload door, the Postgres connector, the
parked side assistant, and the component-library study.

---

## The verdict

**The premise does not hold.** "The framework already exists" is false for the chat: Teable's chat box is not in its
open code. It also cannot be used without changing Teable:
- **The chat is missing.** The chat panel is commented out in the open table view (`Table.tsx:249`,
  `{/* <ChatPanel /> */}`). The only mention of `ChatContainer` is a comment in the panel's state store. The open web
  app has no chat code at all: no `useChat`, no agent.
- **The open AI is one call.** The backend's single AI route, `POST /api/:baseId/ai/generate-stream`, sends one prompt
  and streams back text (`ai.service.ts:702-716`). It fills a field or writes a formula; it is not a conversation.
- **The chat lives in closed images.** AI chat, the App Builder and app hosting come only with Teable Cloud or the
  "full-featured" self-host. That deployment adds three prebuilt images whose source is not in the open repository:
  `teable-sandbox-agent`, `teable-infra-service` and `teable-app-runtime`. The deployment repository carries no licence.
- **The open "App" page is a notice.** It shows only "Enterprise feature" (`blocks/App.tsx`), and the web app has twelve
  `@overridable/*` slots where the paid edition swaps in its own screens. Import and the workflow panel are among them.

**What *is* true, and it is the half Aughor lacks.** Teable's open code is a good spreadsheet:
- **Real tables.** Every sheet is a real PostgreSQL table, and each base is its own schema
  (`bseXXX.tblYYY`, `table.service.ts:109`).
- **Views:** grid, form, kanban, gallery and calendar.
- **Imports:** CSV and Excel (`openapi/src/import/types.ts`), plus Airtable and Google Sheets.
- **Formulas, comments, record history, undo, permissions and a REST API.**
- **Sign-in** through OIDC, Google, GitHub or Apple.
- **Its pages may be framed** by another site (`frame-ancestors *`, `next.controller.ts:28`).

**Aughor already has the other half.** It has the chat, the ontology, dashboards and the Briefing. It reads Postgres
today: the LuxExperience connection is one. Its upload door already reads CSV, TSV, Parquet, XLSX, XLS and JSON
(`connectors/file/local_upload.py:84-96`).

**So turn the plan around: do not push our chat into Teable; bring Teable's sheets into Aughor.** Every sheet a person
makes in Teable is a Postgres table Aughor can read, with no new store and no new chat. And "our chat beside the
screen" is already on the roadmap: the side assistant the user parked on 2026-10-24 (§3.61, PENDING 59).

---

## 1. The three things the user named, measured

| Named | What Teable's open code has | What Aughor has |
|---|---|---|
| **Custom apps** | Two official iframe plugins, a chart and a sheet form (`features/plugin/official`). The App Builder — a prompt becomes generated code deployed to its own container — is closed and needs the runtime plane | The App builder on Dashboards (Arc AP: wired sets, choices, actions, variables). Hosted generated code was **refused** (ROADMAP §6 item 50(d); the Palantir study refused Pilot, the same idea) |
| **Combine Excel, CSV and connectors** | One-time imports: CSV, Excel, Airtable, Google Sheets. No live connector to a database | The upload door (six formats) and live connectors to BigQuery, Postgres, DuckDB, Google Sheets, HubSpot, Stripe and Salesforce |
| **A chat box** | Closed (above). The open AI is one prompt in, text out | The chat, the Data Canvas, *Ask this briefing*, and the parked side assistant (§3.61) |

What Aughor does **not** have is the thing Teable is best at: **a place where a person makes a table, types into it,
shares it and keeps it up to date.** That is the real gap the user's idea points at.

---

## 2. The options

### Option A — Teable beside Aughor, unchanged, read as a database (recommended, and proved first)

- **Run it.** Teable standalone (one app image, Postgres, Redis), unmodified, next to Aughor. It cannot use port 3000,
  which Aughor's web app holds.
- **Connect it.** Aughor connects to Teable's Postgres with a read-only role, as one connection. Each base is a schema,
  and each sheet appears in the Catalog. The chat, the ontology explorer, dashboards and the Briefing work on it as they
  do on any connection.
- **Show it.** A *Spreadsheets* page inside Aughor's rail opens the sheet (Teable allows framing), with Aughor's chat
  beside it. That is the side assistant of §3.61, on one screen first.
- **Write back later, the Aughor way.** A person asks; the agent proposes a change as a declared action; a person
  approves; the outbox calls Teable's REST API. Aughor still writes nothing itself.

What it costs:
- **A second app to run**, and two sign-ins until one OIDC provider serves both.
- **Teable's branding** stays: its licence forbids removing it.
- **AGPL duties if Aughor ships Teable** to customers: their source is offered, and it is upstream's own while it is
  unmodified. A lawyer's reading is needed before shipping, never before a local proof.
- **Freshness.** A sheet people edit all day is not a warehouse whose days settle. The settling and caching rules
  (`settling/`, `db/matcache`) must treat a sheet as live.
- **Who sees which sheet.** Teable's per-base sharing does not carry over to a database reader: one Aughor connection
  would show every base to everyone who has the connection (call 3).

### Option B — a spreadsheet section built into Aughor

- **The build.** Aughor-owned tables, held as uploads are now, plus an editable grid and the chat already there. The
  grid could be Teable's own canvas grid, which is MIT-licensed and makes no server calls (`packages/sdk/src/components/grid`,
  about 14,700 lines), or the TanStack `ResultsGrid` the component-library study chose.
- **One login, one theme,** and every Aughor law from the first row. A typed cell has a source: who typed it, and when.
- **The cost: L.** Typing, cell types, undo, history and sharing are a product of their own.
- **It reverses a refusal.** It makes Aughor a writer of rows, which ROADMAP §4.7 refused in dbx's "inline row editing"
  (for a warehouse). A sheet a person owns is not a warehouse, but the reversal is the user's to make (call 1).

### Option C — fork Teable and put Aughor's chat inside it (not recommended)

- **AGPL:** every change must be published to the people it is served to, and the brand cannot be removed.
- **Size and pace:** 1.57 million lines of TypeScript whose upstream syncs daily (its last commit is the day of this
  study).
- **Nothing to replace:** the chat slot has no open code to replace, so this means writing the chat into their app.

This is the refusal of ROADMAP §4.2 (Langflow: "the editor is not extractable") and §4.4 (a TypeScript agent runtime)
again.

### Option D — Teable's own chat calling Aughor as a tool (not possible from the open code)

There is no MCP server in the open repository. It has only the OAuth registration MCP clients use
(`oauth-server.controller.ts:67`), and the chat that would call one is closed.

---

## 3. The proof, before anything is built

One sitting on this machine, with nothing written into Aughor's code:
1. Run Teable standalone with Docker, on a port other than 3000. The images are pulled from `ghcr.io/teableio`: a
   download that needs the user's yes.
2. Make a sheet from a CSV, and a second sheet that links to it.
3. Add Teable's Postgres to Aughor as a connection, read-only, through the UI.
4. Ask Aughor's chat three questions about the sheets, and check each answer against the sheet.
5. Edit a cell in Teable, then ask again.

**Falsifiers:**
- the sheets do not appear as tables;
- a linked field does not read as a link;
- the answer after an edit is still the old one, served from a cache.

Any one of them means option A needs work in Aughor before a page is drawn.

---

## 4. Decisions for you

1. **Which way?** *Recommended:* option A, proved first (§3). Option B only if one login and one theme matter more than
   time, and it means reversing a refusal: Aughor would write rows.
2. **Run the proof?** It pulls Teable's image, Postgres and Redis (sizes not measured) and runs them on this machine,
   beside, never inside, `~/.aughor/state`.
3. **Who sees which sheet?** *Recommended:* one Aughor connection per Teable space, never one for the whole server, so
   a reader sees only the sheets of a space shared with them.
4. **Custom apps?** Teable's App Builder is closed, and generated hosted code was refused here. *Recommended:* keep the
   refusal; the Dashboards App builder is Aughor's answer.
5. **The Grist commit (`7d753f9c`, local).** It is unaffected by "chuck Grist". Its Arc SV is about Aughor's own state,
   and its breakdown piece is about Dashboards. *Recommended:* keep it.
