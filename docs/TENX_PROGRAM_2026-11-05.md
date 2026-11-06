# Aughor 10× Program — the enterprise foundation under the intelligence loop (2026-11-05)

**What this is.** The plan that puts an enterprise foundation under the 2027 study's phases
without letting the foundation become the product. It sits *under*
[`PLATFORM_2027_STUDY_2026-10-04.md`](PLATFORM_2027_STUDY_2026-10-04.md) §W (phases 0–7), whose
phase 0 "Architecture" row said *nothing new* — an outside assessment and a read of the code on
2026-11-04 showed that row was optimistic. `ROADMAP.md` stays the plan of record; this document
is the program for one slice of it, the way `PLATFORM_PROGRAM_2026-07-26.md` was for the waves.

**Scope authority.** Three sources, each measured against `main` at `11aa35b0` before a line of
this was written:

1. *Aughor Enterprise Architecture, Security and Engineering Assessment* (outside review,
   2026-11-04, from public files, no clone, no tests run). Sixteen findings; most of the
   OBSERVED ones hold, four are stale, and it missed the two holes that matter most (§1).
2. The four architecture decisions the user set beside it (§2.1).
3. [PipesHub](https://github.com/pipeshub-ai/pipeshub-ai) (Apache-2.0, read 2026-11-05) — not a
   competitor on figures, but the clearest worked example of three things this program needs
   and the assessment only asked for (§2.3).

**The one-sentence thesis.** *Hardening a platform one person uses does not 10× it; it makes it
safe to be used by ten.* So every track below carries a gate that stops it from starving the
intelligence loop, and the program's own exit is measured on the loop, not on the foundation.

---

## 0 · What 10× means here, measured

The 2027 study chose the North Star: **closed loops per quarter, guarded by calibration error**
(§X). A loop is closed when a Decision with a resolved owner carried a prediction, an Outcome was
measured on settled days, both verdicts were written and the write-back ran. Its value today is
**zero, measured** — "nobody has ever recorded an outcome" (`PENDING.md`, loose ends). Ten times
zero is zero, so the program needs three numbers that can move first, in the order the flywheel
turns:

| Number | Today (live install, 2026-11-05) | 10× target | Where it is counted |
|---|---|---|---|
| People who asked a question this month | 1 (the user) | 10, in one organisation, each owning something | study §W phase 0 metrics; the audit feed by actor |
| Numbers that left the platform and were acted on by someone who is not the analyst, with a receipt | 0 | 10 a month | the departure gate's receipt + an Outcome row |
| Closed loops a quarter · calibration error | 0 of 16 outcomes · 0.40 over 101 predictions (published 2026-11-06, Record › Decisions) | 10 · published on the Briefing's data-health line | the study §X query, on the ledger |

What the install does today, for scale (the last 1,000 audit events over HTTP on 2026-11-05):
500 `query.execution`, 468 `llm_call`, 21 `action.approval`, 6 `metric.enforcement`, 3
`mcp.tool_call`; 117 explorer first-findings, p50 52 s, p90 447 s; the Actions log's newest row is
a disabled trigger named `slack-ops` with the recommendation "hi". A platform used by one person,
heavily, on their own machine. That is the premise everything below has to respect.

---

## 1 · The premise, measured

### 1.1 What the outside assessment got right (observed in code)

| Its finding | Where | Note |
|---|---|---|
| Identity and auth are off by default | `aughor/security/authz.py:45`, `SECURITY.md` | deliberate: a local single-user tool |
| An unresolved owner authorises | `aughor/security/authz.py:213` | and a resource kind with no registered resolver resolves to None → allowed |
| RBAC skips without `RBAC_SSO` | `aughor/rbac/deps.py:45,100` | latent: `AUGHOR_TIER` defaults to `enterprise` (`licensing/resolver.py:18`), and the tier is an unsigned env var, not a licence |
| Job slots are process-local; exploration exempt | `aughor/kernel/jobs.py:207` | a job PENDING at a crash is failed, not resumed; only explorations resume |
| Postgres via sqlglot translation | `aughor/db/backend.py` | built for the Vercel design, now historical; its tests **skip in CI** (`tests/unit/test_db_backend.py:29`) |
| Compose: `qdrant:latest`, ports 6333/6334 published | `docker-compose.yml:3` | Qdrant runs embedded by default anyway |
| CI omits `e2e` and `eval` | `.github/workflows/ci.yml:80` | by design; there is no nightly |
| No SBOM or CodeQL; actions pinned by tag | `.github/` | the repository is public. *Corrected 2026-11-05: Dependabot was there (`.github/dependabot.yml`, pip + npm + actions, weekly); the assessment and my first reading both missed it* |
| `page.tsx` is large; four UI systems | `web/app/page.tsx` (2,385 lines); antd, Radix Themes, radix-ui, shadcn in `web/package.json` | |

### 1.2 What it got wrong or stale

- Its E05 "SQL entry-point census" exists: `tests/unit/test_sql_door_census.py` holds
  `docs/SQL_DOORS.json` to the code. An `internal=True` statement is still parsed and read-only
  checked in the engine's dialect (`aughor/db/connection.py:55`); it skips the safety checker, the
  audit row and redaction, and who may declare it is enforced by the census.
- A restore was proven on copies of two live backups on 2026-10-28 (ROADMAP, Arc SV). Single-node
  only — but not "unverified".
- Its `AUGHOR_DEPLOYMENT_PROFILE=enterprise` is a feature flag by another name. This repo has none
  (ROADMAP §3.65, 2026-10-28). The same outcome needs no mode: refuse the unsafe combinations at
  startup, always (§3, Track A).
- Two of its twenty-two source anchors point at unrelated text (R01, R16); it recorded no commit.
- It never read `docs/architecture-review-2026-07-03/`, which found SEC-01/SEC-05/DATA-06 in July
  and whose fixes are the seams it reviewed.

### 1.3 What it missed — read from the code, not yet proven by a test

1. **`GET /slack-bots/runtime` returns every organisation's plaintext Slack tokens.**
   `store.list_bots` is not organisation-scoped (`aughor/slackbots/store.py:260`); the route's
   guard admits any identified caller once identity is on and the tier is enterprise
   (`aughor/routers/slackbots.py:330`), and the first identified user of an organisation becomes its
   owner by default (`aughor/rbac/resolver.py:86`). With two organisations, B's owner reads A's
   `xoxb-`/`xapp-` tokens.
2. **Identity required without an OIDC issuer is a spoofable identity, and nothing says so.** The
   `X-Aughor-Org`/`X-Aughor-User` headers *are* the principal then (`authz.py:54`). Anyone on the
   port names any organisation and becomes its first owner. With (1), anyone on the port gets every
   Slack token.
3. **Failed writes are silent.** The JSON-file stores are "best-effort (a failed write never
   raises)" and fall back to a local file when the ledger is unavailable (`aughor/util/json_store.py`).
   On one host that is quiet loss; on two it is two truths. This breaks *withheld is said* more than
   anything in the assessment.
4. **No threat model for an agent.** What leaves for the model provider (`aughor/orgsettings/allows.py`
   governs it; the assessment never mentions it) and text-in-data steering a send or an action
   (in scope per `SECURITY.md`; the assessment lists it only as an eval category).
5. The browser keeps the Google ID token in `localStorage` (`web/lib/auth.ts:12`) and sends it as
   the API credential.

### 1.4 What the 2027 study already says, and this program must not forget

- Phase 0's install exit — one organisation, at least five owners, identity on, the first number
  acted on by someone who is not the analyst — is **still open on the install half** (2026-10-05
  status: code built; waits on an identity provider and on people).
- "Features here stall at *tested*, not at *leveraged*" (§A). Every track below therefore ends in
  a receipt taken live, never a green suite.
- The intelligence loop (§I) is ledger-driven: settle → triage → inquire → deliver. The 10-30
  decision made it concrete: the explorer runs 300 coverage queries per run; the Briefing reads the
  platform's own findings, deep analyses and decisions first. That work is the 10×; §3 Track G
  keeps it in front.

---

## 2 · Decisions adopted

### 2.1 The user's four (2026-11-04), with the repo's corrections

| Decision | Adopted as | Correction from the code |
|---|---|---|
| **Modular control plane; API, scheduler and workers separately deployable processes** | yes — one package, one image, more than one entry point | farthest from today: jobs are `asyncio.create_task` on the API's loop (`jobs.py:357`), the schedulers are APScheduler threads in the API (`api.py:1010`), and `aughor` is the only entry point. Two processes on one SQLite directory is the crash this repo has paid for four times (`db/serving.py`), so this comes **after** the next decision, and only when a second host exists |
| **Postgres as the enterprise source of truth; SQLite local, DuckDB analytical, Qdrant vectors** | yes | "source of truth" is unproven: the Postgres tests skip in CI; the LangGraph checkpointer is off the seam (`agent/graph.py:86`); the materialization cache, mirrors, uploads and backups are files; the ledger falls back to a local file silently. Qdrant *server* for a cluster — embedded Qdrant is a file too |
| **Stateless, recoverable execution; intents, checkpoints, artifacts, policies and authorization context outside the worker** | yes | intents and states are in the ledger already; **authorization context is the hole** — a job carries `org_id` and nothing else (`jobs.py:468`): no person, no grant, no policy version |
| **Data stays in the customer's warehouse; materialization and copies need policy and lineage** | yes — already the rule | two places copy quietly: cross-source joins pull both sides into DuckDB (`routers/query.py:1118`) with consent-by-endpoint, and the materialization cache keeps rows an hour (`db/matcache.py`) with no retention record. API/file connectors mirror by design and already carry lineage; that is not a violation |

### 2.2 From the assessment, kept

Its "five decisions" (§Executive) minus the deployment profile: security as an invariant, build on
the existing seams, separate work classes, evidence as the contract, respect the product record.
Its §6.5 adversarial table becomes tests (Track A/C). Its "what not to build" list is adopted
whole (§6).

### 2.3 From PipesHub, borrowed as design, never as stack

| Borrow | Theirs | Ours |
|---|---|---|
| **Fail-closed per-node access** (`docs/connectors/06-permissions.md`): hierarchy + inheritance + grants; `OPEN/STRICT/RESTRICTED`; an unrecognised rule hides; "unknown is not empty"; `check_access` raises on error, never returns empty or full | a graph DB | `authorize_resource` returns one of OWNED · SHARED · FOREIGN · NOT_FOUND · UNRESOLVED; only the first two allow; a resolver exception is UNRESOLVED and denies. A week for Aughor's handful of kinds |
| **One image, many entry points** (`connectors_main.py`, `indexing_main.py`, `query_main.py`…; Redis Streams locally, Kafka at scale, by one env var) | six stateful services | `aughor worker` beside `aughor serve`, same package, the ledger as the queue; a broker only when measured |
| **A production chart** (`helm/values.yaml`: replicas 2, PDB, HPA, NetworkPolicy, External Secrets, 300 s grace) | | the shape of the assessment's F-10 manifest, written when Track E ships |
| Connector docs written for coding agents first, "ask for the test account before the first record" | | already ours (`AGENTS.md`); the reminder is that their rule 5 is our *withheld is said* |

**Not borrowed:** MongoDB + Neo4j/Arango + Qdrant server + Kafka + Zookeeper + etcd (decision 2
covers the need with one store); index-everything-at-rest (decision 4 is its deliberate opposite
for figures); the 23-line `edition.py` posture (ours must not gate access on a tier either).
**Possible later tie-in, not asked for:** Aughor is an MCP client (`aughor/mcpservers/`); a
customer's PipesHub could be one MCP server Aughor reads discussion context from under its own
organisation check — the 10-30 "Slack/Gmail as context" wish without ingesting a mailbox.

---

## 3 · The tracks

Not phases: tracks, because they run beside the 2027 study's phases and most of them must not
block the loop. Each has an **exit** that is a receipt taken live, a **falsifier** that would show
it did nothing, and a **starvation gate** — the rule that keeps it from eating the week.

```
  A  Close the doors ──────► B  One truth ──────► C  Authority rides the job ──► E  Separate processes
     (two weeks)                (Postgres proven)     (JobAuthContext)               (second host only)
  D  Data stays home ─────── any time, one week
  F  Release gates ───────── beside B; nightly, never on the PR path
  G  The loop ────────────── the reason; never below half the week; the only track with a 10× exit
```

### Track A · Close the doors — the holes that bite the install you have

| # | Change | Receipt |
|---|---|---|
| A1 | **Built 2026-11-05.** `/slack-bots/runtime` opens only to the deployment's own credentials — the supervisor key issued from the app, or the operator's shared `AUGHOR_API_KEY` — never to an identified person. The supervisor is one process for the whole deployment, so the route is deployment-wide by nature; what went was the third door ("identity required and the tier grants RBAC"), which admitted any organisation's first user. Adjacent, not done: the masked `/slack-bots` listing and the Teams bots carry no organisation either (A4's resolver work) | `test_an_identified_caller_from_another_org_cannot_read_the_tokens`: rival's owner gets 503 and no token; the supervisor key still returns them raw. Receipt printed from the app 2026-11-05 |
| A2 | **Built 2026-11-05** (the user chose *refuse unless declared*). `AUGHOR_REQUIRE_IDENTITY=1` with no `AUGHOR_OIDC_ISSUER` refuses every request but `/health` and `/auth/config` with the sentence that says what to set — unless the operator declares `AUGHOR_IDENTITY_FROM_PROXY=1`, the one deployment (an authenticating proxy that sets and strips the `X-Aughor-*` headers) where the seam is a credential. Said at boot, on `/health` (`identity` block, `degraded`), on `/auth/config` (`refusal`) and by `aughor doctor`. With identity off the headers stay a label. The suite is such a proxy and declares it in `tests/conftest.py` | `tests/unit/test_identity_unverifiable.py`: 503 with the reason, a dead seam, health and auth-config answer, a declared proxy opens it, identity-off byte-identical, the doctor reads the same predicate |
| A3 | **Built 2026-11-05.** The tier is read by no access decision: the two early returns in `rbac/deps.py`, the role ceiling in `rbac/capabilities.py` and the row policy's gate in `db/connection.py` all dropped their `RBAC_SSO` check. `Capability.RBAC_SSO` stays as a plan label (owner-only) and gates no decision | `test_the_decision_is_the_same_at_every_tier`: a viewer is 403 on free, pro and enterprise; `test_the_ceiling_applies_at_every_tier`; `test_tenancy_does_not_depend_on_the_tier` |
| A4 | **Built 2026-11-05.** `security/authz.resolve_ownership` answers OWNED · SHARED · FOREIGN · NOT_FOUND · UNRESOLVED; only the first two allow. `check_owner` says which: 403 for another organisation's, 404 *"no such {kind} here, or not yours"*, and — a deviation from this row as written — **503** for UNRESOLVED (*"could not resolve who owns this {kind}; refusing rather than guessing"*): an outage reported as 404 would send someone looking for a resource that exists. SHARED is by record: a builtin connection id, a saved connection with no organisation, a `domain:` carrier, a document whose resolver says `""`. The resolver registry no longer swallows failures, and a kind nobody registered is UNRESOLVED. Three fixtures that relied on "unknown → allow" now register their connection or name their user | `tests/unit/test_ownership_is_five_valued.py`: the property runs over the live registry's kinds, every resolver that raises refuses; missing/shared/own/foreign through a conn resolver and an org resolver. Receipt printed from the app: 200 / 403 / 200 (builtin) / 404 / 503 (resolver down) at one door |
| A5 | **Built 2026-11-05.** `rbac/resolver.bootstrappable`: only a NAMED PERSON becomes an organisation's first owner — never `anonymous` (the header seam with an org and no user; before, "nobody in particular" owned the org and every later user-less request was owner), never a service principal (`service:<name>`, a vendor's agent). Verified is what a principal already is since A2 (OIDC, a service key, or the declared proxy); a refused bootstrap is not cached, so the first named person still claims the organisation. 29 DATA-06 test requests that signed as an anonymous org now name their user | `tests/unit/test_owner_bootstrap_needs_a_named_person.py`; receipt: first caller with no user → `viewer`, first named person → `owner`, a later one → `viewer` |
| A6 | **Built 2026-11-05.** Every image in `docker-compose.yml` pinned to a digest (Qdrant `v1.15.4`, MLflow, Jaeger), every port bound to `127.0.0.1`, the file labelled dev-only; `latest` nowhere | `docker compose config` validates; `host_ip: 127.0.0.1` on every published port |
| A7 | **Built 2026-11-05.** Dependabot already existed; added `.github/workflows/security.yml` — CodeQL (python, javascript-typescript) and `pip-audit` over `uv export` + `npm audit --omit=dev`, weekly and on push to main, never on the PR path — and pinned all twelve action uses in `ci.yml`/`install.yml` to commits with the tag as a comment | the first scheduled run's report is still owed (it runs on GitHub, after the merge) |
| A8 | **Built 2026-11-05, the second form.** The fallback keeps its best-effort contract (31 stores depend on it) and is now SAID: `/health` carries `store_fallbacks` — count since boot, by operation, what it means (a read is stale, a write is orphaned) and what to do — and the status is `degraded` while the count is above zero. Read from the same counter the swallow bumps (`util/json_store._fell_back` → `stats`), so the door and the diagnostic cannot disagree. Not done: raising, and the doctor (it reads files only, and the counters live in the process) | `tests/unit/test_health_says_store_fallbacks.py` |
| A9 | **Built 2026-11-05, the cookie form.** `POST /auth/session` takes the ID token once as a bearer, verifies it as every bearer is, and answers with an `HttpOnly` `SameSite=Lax` cookie (`Secure` behind TLS); `DELETE /auth/session` ends it; the ledger holds the cookie's SHA-256, never the cookie; twelve hours, then nobody. `authz.resolve_principal` reads the cookie as the deferred verification — unknown, expired or revoked resolves nothing and never falls through. The page keeps only the signed-in email; `web/lib/auth.ts` sends `credentials: "include"` to the API and clears the old `aughor_id_token` key on sight. CORS allows credentials only when every origin is named: with `*`, Starlette would echo any origin beside `allow-credentials: true`, so a wildcard keeps the cookie-less behaviour and says so at boot | `tests/unit/test_auth_session_cookie.py` (cookie flags, hash in the ledger, sign-out, expiry, nothing weaker mints, CORS); `web/lib/auth.test.ts`; the token is absent from `localStorage` by construction |

**Exit:** the assessment's §6.5 table, every row a test that passes. **Falsifier:** run the
two-organisation suite with A1–A5 reverted; every row must go red. **Starvation gate:** two weeks;
A1–A3 in the first.

### Track B · One truth — make decision 2 true before anyone relies on it

| # | Change | Receipt |
|---|---|---|
| B1 | **Built 2026-11-06.** The backend CI job starts a `pgvector/pgvector:pg16` service (pinned by digest) and points both `AUGHOR_PG_TEST_URL` and `AUGHOR_PGVECTOR_TEST_URL` at it. **Measured first:** the isolation, concurrency and migration tests F-08 asked for already existed — claim contention, peer-boot recovery, live cross-instance writes, schema isolation, migrations run once — and **CI skipped 23 of the 36 on every run**, plus the 4 pgvector tests. Locally against one throwaway pgvector server all 52 Postgres-backed tests pass, none skipped. `AUGHOR_REQUIRE_PG_TESTS=1` makes a missing service a failure, not 23 quiet skips, and `-rs` lists every skip with its reason in the log | `tests/unit/test_postgres_is_proven_in_ci.py`: red with its sentence when the promised Postgres does not answer (falsifier run), and a ratchet on the promise in `ci.yml`; the first CI run's log is the receipt |
| B2 | **Built 2026-11-06, the library's saver rather than the seam.** With `AUGHOR_DB_URL` naming a Postgres, `agent/graph._checkpointer` returns LangGraph's own `PostgresSaver` over a small pool, in the schema the seam would give `checkpoints.db` (`db/backend.store_schema`); SQLite is unchanged. New extra `shared-state` (`langgraph-checkpoint-postgres==3.1.2` + `psycopg[binary]`) — pinned below 3.1.3, which needs `langgraph-checkpoint ≥ 4.3` and would move LangGraph's core under every investigation; without the extra the first checkpoint names it | `tests/unit/test_checkpoints_on_shared_postgres.py`: a run paused here resumes and finishes in a SECOND PROCESS, and the rows are asserted in the Postgres schema and absent from the local file. The first falsifier run did NOT fire — two processes on one machine also share the SQLite file — so the location assertion was added; the mutant (Postgres branch off) now fails on it |
| B3 | Every write path classified — durable record · evidence · artifact · ephemeral — in `docs/STATE_CLASSES.md`, with the store that owns each; artifacts (sheets' projections, dashboards, uploads) get an object-store door beside the file one | the classification is a test: a new store without a class fails |
| B4 | The hourly-backup week is read and the second restore proven (Arc SV's owed graduation) | the receipt in ROADMAP |

**Exit:** a fresh install on Postgres runs the unit suite and serves theLook end to end — ask,
explore, Briefing — with a receipt. **Falsifier:** point the live install at Postgres on a copy of
state and diff every store's row counts against SQLite (`backups.restore`'s own oracle).
**Starvation gate:** B1 and B2 only, until a second host or a second organisation is on the
calendar. *B1–B2 built 2026-11-06; B3/B4 wait on that calendar.*

### Track C · Authority rides the job — decision 3's missing half

| # | Change | Receipt |
|---|---|---|
| C1 | **Built 2026-11-06.** `kernel/job_auth.job_auth_context`, written by `JobKernel.submit` into a new `jobs.auth` column (ledger Migration 13 — every branch checked, none carried a 13): `person` (the identified caller; the operator with sign-in off; EMPTY, said, when identity is on and nothing named anyone — a clock, the platform), `org`, `verified_by` (oidc · service principal · proxy · sign-in off · none), `roles` at submit, `policy` (`rbac/policy.policy_version`, a fingerprint of the permission table), `purpose`, `at`. `job_update` refuses the column, so it is written once. `_run` binds the person from the row, so a run off any request records under the same name. `GET /jobs` and `/jobs/{id}` show it. Not recorded, because nothing yet exists to record: an approval receipt (no submit path carries one) | `tests/unit/test_job_carries_its_authority.py` (8): operator, identified caller with roles, a clock says nobody, immutable, a run off any request acts for the row's person, a pre-C1 row reads None, the door shows it, the version moves with the table. Mutant (no write at submit) fails on *"the job row carries no authority"*. Receipt over `/jobs` recorded below |
| C2 | **Built 2026-11-06, as a law in the departure gate.** **Measured first:** every effect that leaves the platform — a Slack post, a briefing, a monitor alert, a webhook, an Action Hub send — already passes `govern/departure.gate_departure`, and `test_departure_every_exit_gated` fails the suite on a transport that skips it; so the re-check is one place, not one per effect. New first law `authority`: a departure made inside a job re-checks the person on the job's C1 record against their roles NOW, and holds from everyone when they no longer hold `resource.export` in the job's organisation (information leaving is an export), saying what they held at submit against what they hold now; the hold is a departures-ledger row with a remedy. Outside a job → not applicable (the door checked the person); sign-in off → exempt; a clock's job → not applicable, said. Fails CLOSED: under sign-in an unreadable authority holds — unlike an accuracy guard's hiccup | `tests/unit/test_effects_recheck_the_jobs_authority.py` (7): a real kernel job paused on an event, the role revoked in the real store, the send held with *"held analyst when the job was submitted"*; kept → departs; a viewer; outside a job; sign-in off; a clock; unreadable → held. Mutant (law always passes) fails: departed where held |
| C3 | Retries carry an idempotency key; a non-idempotent effect with no key needs a person | duplicate-effect test under a killed worker |

**Exit:** the §6.5 rows "grant revoked while queued" and "repeated external action after
timeout" green. *The first met 2026-11-06 (C2); the second waits on C3.* **Falsifier:** remove C2's check; the revoke test must go red. **Starvation gate:**
one week; C1 alone is most of the value.

### Track D · Data stays home — decision 4 made explicit

| # | Change | Receipt |
|---|---|---|
| D1 | **Built 2026-11-06.** `copy_rows_across_sources` in `orgsettings/allows.py` (born without a flag, off by default, in Settings ▸ Organization ▸ What Aughor may do). Where the federation engine cannot read a member in place (an upload, an API mirror, a bucket — anything ATTACH cannot reach), it used to copy the member's rows into DuckDB at init; now it copies only when the organisation allows it, and otherwise every answer over that federation refuses with the sentence naming the setting and where to turn it on — never a missing-view error from the engine. Postgres and DuckDB members ATTACH read-only and are read in place; a live read is not a copy. The batched cross-source join reads its right rows through the right connection's own door and joins in the platform; it moves no rows into a second engine, so it is not gated | `test_track_d_data_stays_home.py`: setting off → no tables, refusal names setting and place; setting on → copied, and said |
| D2 | **Built 2026-11-06.** Two door words in `db/doors.WORDS`: `copied:duckdb` on every answer a federation gives while a member's rows sit copied in it ("run over rows COPIED out of their source … the organisation allows it"), and `cross-source:<connection>` on a join made in the platform, after the left read's own doors — so the receipt says whose rows were joined. `docs/SQL_DOORS.json` is the census of door CALL SITES, not words, and gains nothing; the exit as written was imprecise | the two tests above; `test_de5d_count_and_more` holds every word seen to `WORDS` |
| D3 | **Measured 2026-11-06: already true, no code.** A removed connection takes its cache rows (`db/purge.py`, `test_connection_purge.py`); expired rows are evicted on the monitors' clock (`monitors/scheduler.py:47`, `test_matcache_evict.py`); `cache_stats()` says the retention (`ttl_default_s`, one hour, TTL on read); keys carry the tenancy. The program's row was written from the assessment's reading, not the code's — the repo's own rule, applied to the repo's own plan | the tests named |

**Exit (met 2026-11-06):** no copy without a setting, and every copy or join said on the trail. **Starvation gate:** one
week, any time — it took an afternoon.

### Track E · Separately deployable — decision 1, gated

Gated on **B exit + C1 + a second host**. Until then it is a design note, not a branch.

| # | Change | Receipt |
|---|---|---|
| E1 | `aughor worker`: claims PENDING jobs from the ledger by lease with a fencing token; the API stops attaching runners when a worker is registered; PENDING survives an API restart | kill the API mid-job; the worker finishes it; the result row is the same |
| E2 | One scheduler leader by ledger lease; APScheduler leaves the API process | two APIs, one tick |
| E3 | The Helm chart, in PipesHub's shape (§2.3 row 3), and a Compose labelled dev-only | `helm template` passes the assessment's F-10 policy checks |

**Exit:** the assessment's G04/G05 — two replicas, a killed worker, no lost job, no duplicate
effect — recorded live. **Falsifier:** remove the fencing token; the duplicate-effect test goes red.

### Track F · Release gates — beside, never on, the PR path

| # | Change |
|---|---|
| F1 | A nightly: `-m eval` on fixed datasets (theLook, LuxExperience, Olist) with golden SQL, abstention cases, organisation-denial questions, prompt-injection-through-data cases, a cost ceiling; per-model baselines; a regression budget that fails the night, not the PR |
| F2 | A release candidate is a nightly that passed plus the Postgres job plus the browser E2E; `SECURITY.md`'s support policy says which commits are candidates |
| F3 | SBOM and image signing when there is an image to sign (Track E) — not before |

**Starvation gate:** F1 is a workflow file and a marker; a day.

### Track G · The loop — the only track with a 10× exit

This is the 2027 study §W, phases 0–3, as already planned and partly built. It is listed here so
the foundation tracks are read against it, not instead of it.

| # | What | Status / receipt owed |
|---|---|---|
| G0 | Phase 0's install exit: one organisation, five owners, identity on, the first number acted on by someone who is not the analyst | **open**; needs the user's identity provider and people (§7) |
| G1 | The explorer covers a connection: 300 coverage queries per run across its domains; findings kept with their cell and range | built 2026-10-30 (#635); receipt owed: a connection whose Briefing cites findings from every domain |
| G2 | The Briefing reads the platform's own work first — deep analyses with verdicts, findings, decisions and reviews — and says *why* only on a causal-licensed analysis | built 2026-10-30; receipt owed: an edition on LuxExperience that reads >0 of each |
| G3 | Outcomes recorded: the review question delivered where the owner is, answered, the write-back run | **Measured 2026-11-06:** `PENDING`'s *"nobody has ever recorded an outcome"* is stale — 16 decisions carry one — but all 16 come from the 2026-10-26 scenario run, back-dated to 2026-09-01 with predictions booked 2026-10-25, so none can close a loop; and none of the 21 still waiting carries a prediction at all (metric approvals, cockpit proposals, a case). **Built (the user chose *ask, don't require*):** the Declare form already asked for an expectation; it now says what leaving it empty means (*on the record but cannot close a loop*) and, for a back-dated decision with one, that it becomes a case but not a loop; the reader names a prediction booked after its decision. The first real receipt is still a person's: a decision declared today with what it expects, answered at its review |
| G4 | Discussions as context: Slack threads and, when an account is connected, mail — read under the person's own grant, never stored as a mailbox | Slack built (#635); mail waits on a connected account; PipesHub-as-MCP-server is an option, not a plan |
| G5 | **Built 2026-11-06.** `record/north_star.py` — the study's §X definition as a query: a loop is closed when the decision names an owner, a prediction was booked at or before `decided_at` (five minutes' grace for one booking), an outcome was written on or after the review date with both verdicts (or *cannot tell* and why), and the write-back ran; it closes in the quarter its outcome was written; reliance without an expectation is counted apart. Calibration error is |stated − observed| interval coverage over the predictions that settled in the quarter, weighted by what each method × metric judged. `GET /record/north-star`; at the head of Record › Decisions (the user's choice) as one line with **Why** opening the reasons by rule and the table worst-first | `tests/unit/test_north_star.py` (12, real bookings; the hindsight mutant fails on *"counted as a closed loop"*), `NorthStarLine.test.tsx`. **Live, 2026-11-06:** *2026-Q4: 0 loops closed of 16 outcomes written · calibration error 0.40 over 101 settled predictions* — the history method's 80% intervals hold about half the time (`units_sold` 11%, `inventory_sell_through_rate` 0%). Shown in a browser on a copy of the 09:12Z backup, served by this branch on :8002 with no model key |

**Exit:** the three numbers in §0 move: ten people, ten numbers acted on a month, the first closed
loop. **Starvation gate:** the inverse — no week in which A–F take more than half the time until
G0's install exists, because a foundation nobody stands on is the study's "tested, not leveraged"
at program scale.

---

## 4 · Sequence and dependencies

```
week 1–2   A1 A2 A3 ─ then A4 A5 A8 ─ A6 A7 A9 ride along          G1/G2 receipts taken
week 3–4   B1 B2 ─ D1 D2 D3 ─ F1                                     G3: the first outcome asked for again
week 5–6   C1 C2 C3 ─ B3 B4                                          G0: the install, if the IdP decision lands
after      E1 E2 E3 only on a second host ─ F2 F3 with E             G5
```

- A before everything: A1 and A2 are live defects on a public repository.
- B before E: two processes on one state directory is the recorded crash.
- C1 before E1: a worker that resumes a job must know whose authority it carries.
- D is independent; it is a week and it protects every customer today.
- F1 is independent and cheap; F2/F3 wait for an image to sign.
- G is never "after"; its receipts are taken every week.

No engineer-week estimates: the assessment's 4–6-person, 14-week plan is honest about not being a
solo plan, and this is one. The gates above are the schedule.

---

## 5 · Receipts — how each track proves it did something

Every exit is **a receipt taken live** (study §W's rule), in ROADMAP §3 under this program's
entry, with the command or the screen it was read from. A track with green tests and no receipt is
*tested*, not *done*. The falsifiers in §3 are run once each at exit and their red output is kept
beside the green.

The assessment's §11 checklist (G01–G12) maps onto the tracks: G01–G03 → A, G04–G06 → B+C+E,
G07 → E's exit, G08 → F3, G09 → F1, G10 → unchanged product rules (the rail stays; one theme),
G11 → B4 + the doctor, G12 → a review someone else runs, after A.

---

## 6 · What not to do

From the assessment, adopted whole, and from the record:

- No rewrite, no twenty services, no new database platform, no navigation rail replacement
  (ROADMAP §4.10), no dark chrome on a light page (§4.11).
- No deployment profile, no feature flag of any spelling (§3.65). Unsafe combinations refuse;
  everything else is an organisation's setting, off by default.
- No access decision that depends on a tier (A3). A licence gates administration surfaces, never
  whether a permission is evaluated.
- No second copy of warehouse data "for the index" (decision 4; PipesHub's architecture is the
  opposite choice, made for documents).
- No enterprise track in a week where the loop's receipts were not taken (Track G's gate).
- No store that writes locally when the shared store fails without saying so (A8).

---

## 7 · Decisions only the user can make

1. **The identity provider for the install** (open since VA-10; G0 waits on it). Without it A2 is a
   refusal with nowhere to go, and A5 has no verified identity to bootstrap from.
2. **A second host, or not this year.** Track E does not start without one; with one, B becomes
   the gate on it.
3. **A second organisation on the calendar, or not.** A1–A5 are worth doing regardless (the
   repository is public and the header seam is a defect today); B3/B4, C2/C3 and E are only worth
   it with one.
4. **Postgres as the default for a new install**, or SQLite stays the default and Postgres is the
   enterprise choice. Decision 2 says the latter; B's exit is the evidence either way.
5. **PipesHub as a context source**: a customer's PipesHub as one MCP server Aughor reads
   discussions from (G4), or not. Nobody has asked; it is written down so it is not rediscovered.
