# Palantir Foundry public API and docs catalogue (2026-10-24)

**What this is.** A measured inventory of what Palantir publishes about Foundry on its public website, and a check of how much of it [the July study](PALANTIR_FOUNDRY_STUDY_2026-07-22.md) covered. Every number below comes from a file fetched from `www.palantir.com/docs` on 2026-10-24 or derived from one. No Palantir account was used and nothing behind a login was read.

**Method.** REA (the reverse-engineering MCP, `rea-agents` 6.7.0) inspected the live docs pages in a throwaway headless Chrome and recorded their network traffic. That showed every page is also served as structured JSON. The rest of the work read that JSON directly: the sidebar trees of the 11 capability areas, every v2 and v3 REST API reference page, and the search index the site ships. Requests ran at most two at a time, half a second apart. 449 API pages were fetched (156 MB) with 0 failures.

## 1. How the docs are served

- Both `palantir.com` and `/docs` are Next.js sites. REA found only first-party application scripts and no backend API behind either.
- Every docs page has a JSON twin at `https://www.palantir.com/docs/_next/data/development/<page path>.json`. The Next.js build id is literally `development`.
- An API reference page carries a structured `endpoint` record: operation id, HTTP method and path, OAuth scopes, typed path and query parameters, request and response bodies as typed field trees with examples, and error responses. It also carries the complete API sidebar, so one page lists every operation.
- Search is [Pagefind](https://pagefind.app/) 1.5.2, run in the browser. Its index metadata says how many pages it holds and has one filter, `product`.
- `docs/sitemap.xml` stops at exactly 5,000 links and nearly all are Japanese or Chinese pages. It is not usable as an inventory.

## 2. What exists

The search index splits its pages by product:

| Product | Pages in the search index |
| --- | ---: |
| Foundry | 3,742 |
| Apollo | 284 |
| Gotham | 106 |
| **Total** | 4,132 |

Foundry's pages sit in the trees below. The capability sidebars and the REST API sidebars were walked completely:

| Foundry tree | Pages | In the search index |
| --- | ---: | --- |
| User docs, 11 capability sidebars | 3,093 | yes, apart from pages that opt out |
| REST API v1 | 65 | not checked |
| REST API v2 | 425 | yes, every page checked |
| REST API v3 | 24 | yes, every page checked |
| Transforms Python library reference | 52 | no, the pages opt out |
| Monthly announcements, Jan to Oct 2026 | 10 | no, the pages opt out |

**Reconciliation.** The user docs and the three API versions add up to 3,607 pages. The index holds 3,742 Foundry pages. At least 135 indexed Foundry pages are therefore not reachable from any sidebar walked here. Which pages those are is unknown. The figure is a floor, because a sidebar page that opts out of the index would widen the gap, and the opt-out flag was read only on API pages.

The user docs by capability, with how much of each the July study names:

| Capability | Sections | Pages | Named by the July study | Named only by a common word | Not named |
| --- | ---: | ---: | ---: | ---: | ---: |
| AI Platform (AIP) | 14 | 96 | 50 | 0 | 35 |
| Data connectivity & integration | 33 | 1,179 | 455 | 14 | 703 |
| Model connectivity & development | 8 | 98 | 40 | 0 | 56 |
| Ontology building | 21 | 398 | 191 | 49 | 141 |
| Developer toolchain | 14 | 177 | 51 | 9 | 116 |
| Use case development | 12 | 316 | 231 | 0 | 80 |
| Observability | 3 | 26 | 15 | 0 | 8 |
| Analytics | 10 | 517 | 390 | 24 | 99 |
| Product delivery | 3 | 23 | 7 | 0 | 14 |
| Security & governance | 13 | 104 | 34 | 8 | 48 |
| Management & enablement | 17 | 159 | 0 | 6 | 152 |
| **Total** | 148 | 3,093 | 1,464 | 110 | 1,452 |

The 67 remaining pages are capability landing pages, which belong to no section.

## 3. The Foundry REST API

The v2 and v3 references describe **329 operations** on 22 area-version pairs, plus 120 explanatory pages. Methods: 160 GET, 136 POST, 21 PUT and 12 DELETE, with no PATCH.

| Version | Area | Resources | Operations | GET | POST | PUT | DELETE | Other pages |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| V2 | General | 0 | 0 | 0 | 0 | 0 | 0 | 8 |
| V2 | Admin | 19 | 62 | 30 | 23 | 7 | 2 | 19 |
| V2 | AIP Chatbot Studio | 5 | 15 | 8 | 4 | 2 | 1 | 5 |
| V2 | Audit | 1 | 2 | 2 | 0 | 0 | 0 | 1 |
| V2 | Checkpoints | 1 | 3 | 1 | 2 | 0 | 0 | 1 |
| V2 | Connectivity | 4 | 20 | 6 | 10 | 2 | 2 | 4 |
| V2 | Data Health | 2 | 6 | 3 | 1 | 1 | 1 | 2 |
| V2 | Datasets | 5 | 31 | 15 | 12 | 2 | 2 | 5 |
| V2 | Filesystem | 6 | 28 | 11 | 16 | 0 | 1 | 6 |
| V2 | Functions | 1 | 5 | 2 | 3 | 0 | 0 | 1 |
| V2 | Map Rendering | 2 | 2 | 1 | 0 | 1 | 0 | 2 |
| V2 | Media Sets | 1 | 17 | 9 | 6 | 1 | 1 | 1 |
| V2 | Models | 11 | 31 | 18 | 11 | 2 | 0 | 11 |
| V2 | Notepad | 4 | 6 | 3 | 3 | 0 | 0 | 4 |
| V2 | Observability | 1 | 1 | 0 | 1 | 0 | 0 | 1 |
| V2 | Ontologies | 18 | 49 | 31 | 18 | 0 | 0 | 18 |
| V2 | Orchestration | 4 | 19 | 7 | 10 | 1 | 1 | 4 |
| V2 | Sensitive Data Scanner | 1 | 1 | 1 | 0 | 0 | 0 | 1 |
| V2 | Sql Queries | 1 | 5 | 2 | 3 | 0 | 0 | 1 |
| V2 | Streams | 2 | 9 | 3 | 6 | 0 | 0 | 2 |
| V2 | Third Party Applications | 2 | 7 | 3 | 3 | 0 | 1 | 2 |
| V2 | Workbench | 1 | 2 | 0 | 0 | 2 | 0 | 1 |
| V2 | LLM APIs | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| V3 | General | 0 | 0 | 0 | 0 | 0 | 0 | 8 |
| V3 | Marketplace | 4 | 8 | 4 | 4 | 0 | 0 | 4 |
| V3 | LLM APIs | 0 | 0 | 0 | 0 | 0 | 0 | 4 |

- 244 operations list their error responses. 5 name no OAuth scope.
- 52 operations page with `pageToken`. 142 take a `preview` flag that opts into preview functionality. The docs describe it that way 117 times, and 25 times as enabling beta features.
- 52 distinct OAuth scopes are named. The most used are `api:ontologies-read` (50), `api:admin-read` (34), `api:admin-write` (27), `api:models-read` (19), `api:datasets-read` (16), `api:datasets-write` (14), `api:filesystem-write` (14), `api:orchestration-read` (12).

The full table, one row per operation with method, path, scopes, parameters and body fields, is in [PALANTIR_FOUNDRY_API_CATALOGUE_2026-10-24.csv](PALANTIR_FOUNDRY_API_CATALOGUE_2026-10-24.csv).

### The areas closest to this repo

**Ontologies** has 49 operations across 18 resources.

- *Ontologies*: List Ontologies `GET …/ontologies`, Get Ontology `GET …/ontologies/{ontology}`
- *Action Types*: List Action Types `GET …/ontologies/{ontology}/actionTypes`, Get Action Type `GET …/ontologies/{ontology}/actionTypes/{actionType}`, Get Action Type By Rid `GET …/ontologies/{ontology}/actionTypes/byRid/{actionTypeRid}`, Get Action Type By Rid Batch `POST …/ontologies/{ontology}/actionTypes/getByRidBatch`
- *Object Types*: List Object Types `GET …/ontologies/{ontology}/objectTypes`, Get Object Type `GET …/ontologies/{ontology}/objectTypes/{objectType}`, Get Object Type By Rid Batch `POST …/ontologies/{ontology}/objectTypes/getByRidBatch`, Get Object Type Full Metadata `GET …/ontologies/{ontology}/objectTypes/{objectType}/fullMetadata`, Get Object Type Edits History `POST …/ontologies/{ontology}/objectTypes/{objectType}/editsHistory`, List Outgoing Link Types `GET …/ontologies/{ontology}/objectTypes/{objectType}/outgoingLinkTypes`, Get Outgoing Link Type `GET …/ontologies/{ontology}/objectTypes/{objectType}/outgoingLinkTypes/{linkType}`, Get Outgoing Link Types By Object Type Rid Batch `POST …/ontologies/{ontology}/outgoingLinkTypes/getByRidBatch`
- *Ontology Objects*: List Objects `GET …/ontologies/{ontology}/objects/{objectType}`, Get Object `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}`, Search Objects `POST …/ontologies/{ontology}/objects/{objectType}/search`, Aggregate Objects `POST …/ontologies/{ontology}/objects/{objectType}/aggregate`
- *Linked Objects*: List Linked Objects `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/links/{linkType}`, Get Linked Object `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/links/{linkType}/{linkedObjectPrimaryKey}`
- *Attachment Properties*: List Property Attachments `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/attachments/{property}`, Get Attachment Property By Rid `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/attachments/{property}/{attachmentRid}`, Get Attachment Property Content `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/attachments/{property}/content`, Get Attachment Property Content By Rid `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/attachments/{property}/{attachmentRid}/content`
- *Media Reference Properties*: Read Media Content `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/media/{property}/content`
- *Time Series Properties*: Get First Point `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/timeseries/{property}/firstPoint`, Get Last Point `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/timeseries/{property}/lastPoint`, Stream Points `POST …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/timeseries/{property}/streamPoints`
- *Time Series Value Bank Properties*: Get Latest Value `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/timeseries/{propertyName}/latestValue`, Stream Values `POST …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/timeseries/{property}/streamValues`
- *Geotemporal Series Properties*: Load Geotemporal Series Entries `POST …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/geotemporalSeries/{property}/loadEntries`
- *Cipher Text Properties*: Decrypt `GET …/ontologies/{ontology}/objects/{objectType}/{primaryKey}/ciphertexts/{property}/decrypt`
- *Ontology Interfaces*: List Interface Types `GET …/ontologies/{ontology}/interfaceTypes`, Get Interface Type `GET …/ontologies/{ontology}/interfaceTypes/{interfaceType}`
- *Actions*: Apply Action `POST …/ontologies/{ontology}/actions/{action}/apply`, Apply Action Batch `POST …/ontologies/{ontology}/actions/{action}/applyBatch`
- *Query Types*: List Query Types `GET …/ontologies/{ontology}/queryTypes`, Get Query Type `GET …/ontologies/{ontology}/queryTypes/{queryApiName}`
- *Queries*: Execute Query `POST …/ontologies/{ontology}/queries/{queryApiName}/execute`
- *Ontology Object Sets*: Create Temporary Object Set `POST …/ontologies/{ontology}/objectSets/createTemporary`, Load Object Set `POST …/ontologies/{ontology}/objectSets/loadObjects`, Load Object Set Multiple Object Types `POST …/ontologies/{ontology}/objectSets/loadObjectsMultipleObjectTypes`, Load Object Set Objects Or Interfaces `POST …/ontologies/{ontology}/objectSets/loadObjectsOrInterfaces`, Aggregate Object Set `POST …/ontologies/{ontology}/objectSets/aggregate`
- *Attachments*: Upload Attachment `POST …/ontologies/attachments/upload`, Get Attachment Content `GET …/ontologies/attachments/{attachmentRid}/content`, Get Attachment `GET …/ontologies/attachments/{attachmentRid}`
- *Ontology Value Types*: Get Ontology Value Type `GET …/ontologies/{ontology}/valueTypes/{valueType}`, List Ontology Value Types `GET …/ontologies/{ontology}/valueTypes`

**AIP Chatbot Studio** has 15 operations across 5 resources.

- *Chatbot Studio Agents*: Get Chatbot Studio Agent `GET …/aipAgents/agents/{agentRid}`, List Sessions For Chatbot Studio Agents `GET …/aipAgents/agents/allSessions`
- *Chatbot Studio Agent Versions*: List Chatbot Studio Agent Versions `GET …/aipAgents/agents/{agentRid}/agentVersions`, Get Chatbot Studio Agent Version `GET …/aipAgents/agents/{agentRid}/agentVersions/{agentVersionString}`
- *Sessions*: Create Session `POST …/aipAgents/agents/{agentRid}/sessions`, Delete Session `DELETE …/aipAgents/agents/{agentRid}/sessions/{sessionRid}`, List Sessions `GET …/aipAgents/agents/{agentRid}/sessions`, Get Session `GET …/aipAgents/agents/{agentRid}/sessions/{sessionRid}`, Blocking Continue Session `POST …/aipAgents/agents/{agentRid}/sessions/{sessionRid}/blockingContinue`, Streaming Continue Session `POST …/aipAgents/agents/{agentRid}/sessions/{sessionRid}/streamingContinue`, Cancel Session `POST …/aipAgents/agents/{agentRid}/sessions/{sessionRid}/cancel`, Get Rag Context For Session `PUT …/aipAgents/agents/{agentRid}/sessions/{sessionRid}/ragContext`, Update Session Title `PUT …/aipAgents/agents/{agentRid}/sessions/{sessionRid}/updateTitle`
- *Contents*: Get Content `GET …/aipAgents/agents/{agentRid}/sessions/{sessionRid}/content`
- *Session Traces*: Get Session Trace `GET …/aipAgents/agents/{agentRid}/sessions/{sessionRid}/sessionTraces/{sessionTraceId}`

**Functions** has 5 operations across 1 resource.

- *Queries*: Get Query `GET …/functions/queries/{queryApiName}`, Get By Rid `GET …/functions/queries/getByRid`, Get By Rid Queries Batch `POST …/functions/queries/getByRidBatch`, Execute Query `POST …/functions/queries/{queryApiName}/execute`, Streaming Execute Query `POST …/functions/queries/{queryApiName}/streamingExecute`

**Data Health** has 6 operations across 2 resources.

- *Checks*: Create Check `POST …/dataHealth/checks`, Delete Check `DELETE …/dataHealth/checks/{checkRid}`, Get Check `GET …/dataHealth/checks/{checkRid}`, Replace Check `PUT …/dataHealth/checks/{checkRid}`
- *Check Reports*: Get Check Report `GET …/dataHealth/checks/{checkRid}/checkReports/{checkReportRid}`, Get Latest Check Reports `GET …/dataHealth/checks/{checkRid}/checkReports/getLatest`

**Checkpoints** has 3 operations across 1 resource.

- *Records*: Get Record `GET …/checkpoints/records/{recordRid}`, Get Records Batch `POST …/checkpoints/records/getBatch`, Search Records `POST …/checkpoints/records/search`

**Audit** has 2 operations across 1 resource.

- *Log Files*: List Log Files `GET …/audit/organizations/{organizationRid}/logFiles`, Get Log File Content `GET …/audit/organizations/{organizationRid}/logFiles/{logFileId}/content`

**Notepad** has 6 operations across 4 resources.

- *Templates*: Generate Template `POST …/notepad/templates/{templateRid}/generate`
- *Generation Jobs*: Get Generation Job `GET …/notepad/templates/{templateRid}/generationJobs/{generationJobRid}`, Save Document Generation Job `POST …/notepad/templates/{templateRid}/generationJobs/{generationJobRid}/saveDocument`
- *Export Jobs*: Get Export Job `GET …/notepad/exportJobs/{exportJobRid}`, Create Export Job `POST …/notepad/exportJobs/create`
- *Files*: Content File `GET …/notepad/files/{fileRid}/content`

**Orchestration** has 19 operations across 4 resources.

- *Schedules*: Create Schedule `POST …/orchestration/schedules`, Delete Schedule `DELETE …/orchestration/schedules/{scheduleRid}`, Get Schedule `GET …/orchestration/schedules/{scheduleRid}`, Get Schedules Batch `POST …/orchestration/schedules/getBatch`, Replace Schedule `PUT …/orchestration/schedules/{scheduleRid}`, Run Schedule `POST …/orchestration/schedules/{scheduleRid}/run`, Pause Schedule `POST …/orchestration/schedules/{scheduleRid}/pause`, Unpause Schedule `POST …/orchestration/schedules/{scheduleRid}/unpause`, Get Affected Resources Schedule `POST …/orchestration/schedules/{scheduleRid}/getAffectedResources`, List Runs Of Schedule `GET …/orchestration/schedules/{scheduleRid}/runs`
- *Schedule Versions*: Get Schedule Version `GET …/orchestration/scheduleVersions/{scheduleVersionRid}`, Get Schedule Of Schedule Version `GET …/orchestration/scheduleVersions/{scheduleVersionRid}/schedule`
- *Builds*: Get Build `GET …/orchestration/builds/{buildRid}`, Get Builds Batch `POST …/orchestration/builds/getBatch`, Create Build `POST …/orchestration/builds/create`, Cancel Build `POST …/orchestration/builds/{buildRid}/cancel`, List Jobs Of Build `GET …/orchestration/builds/{buildRid}/jobs`
- *Jobs*: Get Job `GET …/orchestration/jobs/{jobRid}`, Get Jobs Batch `POST …/orchestration/jobs/getBatch`

## 4. What the July study did not cover

The July study keeps no list of the pages it read, so page-level coverage cannot be measured. This section checks instead whether the study's text names each docs section. A section counts as named when its title, or a documented alias, appears as a whole word. Common words such as "map", "models" or "approvals" only count as a weak match, because the study uses them in other senses. Naming a section does not prove its pages were read.

- The study names 39 of 148 sections, holding 1,464 of 3,093 user-docs pages.
- It never mentions the REST API reference. The phrases "REST API", "API reference" and "OpenAPI" and any `/api/` path are absent. Its one use of "REST" is about a model's live endpoint. All 514 API pages are therefore outside what it shows it read.

The table below shows which API area and resource names appear in the study as whole words. A match on a common word such as "Versions" does not mean the area was discussed, and an area with no match can still be discussed in other words.

| API area | Names found in the study |
| --- | --- |
| Admin (v2) | Admin, Users, Groups, Markings, Enrollments … |
| AIP Chatbot Studio (v2) | AIP Chatbot Studio, Sessions |
| Audit (v2) | Audit |
| Checkpoints (v2) | Checkpoints, Records |
| Connectivity (v2) | Connectivity, Connections, Virtual Tables |
| Data Health (v2) | Data Health, Checks |
| Datasets (v2) | Datasets, Branches, Transactions, Files, Views |
| Filesystem (v2) | Resources, Projects |
| Functions (v2) | Functions, Queries |
| Map Rendering (v2) | none |
| Media Sets (v2) | none |
| Models (v2) | Models, Experiments |
| Notepad (v2) | Notepad, Templates, Files |
| Observability (v2) | Observability, Resources |
| Ontologies (v2) | Action Types, Object Types, Actions, Queries |
| Orchestration (v2) | Schedules, Builds |
| Sensitive Data Scanner (v2) | none |
| Sql Queries (v2) | none |
| Streams (v2) | Streams, Datasets |
| Third Party Applications (v2) | Versions |
| Workbench (v2) | none |
| LLM APIs (v2) | Models |
| Marketplace (v3) | Marketplace |
| LLM APIs (v3) | Models |

Uncovered sections, ranked by how closely they touch this repo. "Weak" means only a common word matched. The notes paraphrase each section's own first page.

| Rank | Section | Capability | Pages | Study match | What it is | Why it matters here |
| ---: | --- | --- | ---: | --- | --- | --- |
| 1 | Ontology MCP | Developer toolchain | 7 | none | Publishes one application's object types, actions and query functions as MCP tools for outside agents. | Compare with our MCP server in MCP_SERVER.md. This one is scoped to one application and can run actions. |
| 2 | Palantir MCP | Developer toolchain | 7 | none | An MCP server that lets coding agents build and edit pipelines, ontology and apps, and read docs and metadata. | The builder-side MCP: agents changing the platform itself, not only reading data. |
| 3 | Ontology Manager | Ontology building | 9 | none | The tool where object types, action types and their data bindings are created and maintained. | Compare with how people edit our ontology. |
| 4 | Object Explorer | Ontology building | 16 | none | Search and analysis over anything modelled in the ontology. | Compare with our catalog and explorer. |
| 5 | Insight | Analytics | 14 | none | Point-and-click paths over objects: filter, follow links, aggregate, chart, and save the result as a reusable object set. | Saved object sets feed other tools. Compare with what our Questions and dashboards consume. |
| 6 | Object permissioning | Ontology building | 7 | none | Security at two levels: on ontology definitions, and on the individual objects and links. | Object-level access as a second plane beside definition access. Compare with our workspace scoping. |
| 7 | Foundry Rules | Ontology building | 27 | none | Low-code rules over datasets, objects and time series that raise alerts or categorise records. | Compare with our monitors and metric conditions. |
| 8 | Object Monitors [Sunset] | Ontology building | 11 | none | Watched changes on objects that send notices or run actions. Now being retired. | A retired design worth reading before extending monitors. |
| 9 | Workflow Builder | Use case development | 2 | none | Build, test and watch an automated use case: a trigger, logic steps, and a live run. | Compare with our automations and question rhythms. |
| 10 | Workflow Lineage | Use case development | 7 | none | An interactive map of applications and the processes, functions and actions under them. | Compare with our lineage and graph views. |
| 11 | Ontology and AIP observability | Observability | 8 | none | Metrics, traces, logs and run history for ontology and AI executions, shown inside Workflow Lineage. | Compare with Agent Ops. |
| 12 | Autopilot | Use case development | 9 | none | A control centre for watching and tuning many ontology automations at once. | An operations view for automations at scale. |
| 13 | Pilot | Use case development | 14 | none | Generates ontology entities, React code and seed data from a prompt, then manages the app with agents. | A prompt-to-app builder. Compare with how our dashboards are built. |
| 14 | Custom widgets | Use case development | 16 | none | Custom frontend code embedded in Workshop apps. | An extension point. Compare with our dashboard pieces. |
| 15 | Cross-application interactivity | Developer toolchain | 11 | none | Apps share a selection by drag and drop, or pair up to share state live. | Selections flowing between apps, not only between pieces of one app. |
| 16 | OSDK React applications | Use case development | 17 | none | Fully custom React interfaces built on the ontology through the SDK. | The pro-code path beside the visual builder. |
| 17 | Pro-code agents | Developer toolchain | 9 | weak | Agents written with the Claude, OpenAI or Google agent SDKs, published as functions with ontology tools. | Palantir hosts third-party agent SDKs as platform functions. |
| 18 | Boardroom | AI Platform (AIP) | 5 | none | A team of agents, a director plus experts, over text or voice, that query data, run code and produce documents. | A multi-agent take on a standing report. Compare with our Briefing. |
| 19 | AIP Evolve | AI Platform (AIP) | 1 | none | Many AI FDE agents pursue a goal such as lower cost or a better eval score, within limits, and return a proposal for review. | A run-many-then-propose loop applied to whole AI systems, with a person reviewing. |
| 20 | AIP Document Intelligence | AI Platform (AIP) | 5 | none | Compares document-extraction strategies on quality, speed and token cost, then deploys the winner as a pipeline. | An evaluate-then-deploy loop that scores token cost beside quality. |
| 21 | Semantic search | Ontology building | 6 | none | Embedding-based search over ontology text. | Searching the ontology by meaning. |
| 22 | AIP Threads | AI Platform (AIP) | 2 | none | A general LLM workspace over uploaded documents and chatbots. | A free-form counterpart to an analyst chat. |
| 23 | HyperAuto (SDDI) | Data connectivity & integration | 15 | none | Packaged integration of business systems, SAP only today, that produces ready workflows. | Compare with our industry packs. |
| 24 | Vertex | Ontology building | 27 | none | Cause-and-effect graphs over a model of the organisation, used to monitor, simulate and optimise. | Compare with the diagnose question shape. |
| 25 | AIP Assist | AI Platform (AIP) | 9 | none | An LLM helper for using the platform itself. | Compare with our in-product help. |
| 26 | Compute modules | Developer toolchain | 17 | none | Run any containerised code inside the platform, scaled for app traffic. | A bring-your-own-code runtime. |
| 27 | Dynamic Scheduling | Ontology building | 19 | none | Scheduling and resource-allocation apps, such as a Gantt widget. | Low relevance today. |
| 28 | Solution Designer | Use case development | 7 | none | Architecture diagrams of a solution, linked to its platform resources. | Low relevance today. |

By page count the largest unnamed sections are pipeline and language reference rather than product ideas: Pipeline Builder Expressions (338 pages), Pipeline Builder Transforms (88 pages), Building pipelines (43 pages), FoundryTS (42 pages), Code Workbook [Legacy] (42 pages), Python (40 pages).

## 5. Unknowns and limits

- At least 135 indexed Foundry pages are not reachable from the walked sidebars. Their identity is unknown.
- The search-index opt-out flag was read on API pages only. User-docs pages may opt out without being counted here.
- REST API v1 was counted, not catalogued.
- Coverage is a text-match heuristic over the July study, not a record of pages read.
- The docs change continuously. The newest announcement page is October 2026, so these counts describe 2026-10-24 only.
- Section notes are paraphrases, written to avoid copying Palantir's text. The CSV holds names, paths and types, not descriptions.

## 6. How to reproduce

- User-docs page data: `/docs/_next/data/development/foundry/<section>/<page>.json?slug=foundry&slug=<section>&slug=<page>`.
- API page data: `/docs/_next/data/development/foundry/api/<v>/<area>/<resource>/<page>.json?productId=foundry&slug=<v>&slug=<area>&slug=<resource>&slug=<page>`.
- Sidebar items come in five kinds: `section` with `items`, `pageGroup` with `pages`, `pageLink`, `header` and `divider`. In the API sidebar a plain `header` is an area and a `header` marked `minimal` is a resource.
- `/docs/pagefind/pagefind-entry.json` names the metadata file. It is gzip-compressed CBOR after a `pagefind_dcd` signature. Its filter file for `product` maps each product to its page indices.
- The site's robots.txt allows all paths. Keep requests to two at a time with a delay.

