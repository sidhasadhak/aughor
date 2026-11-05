# NVIDIA Auto-Ontology against Aughor's ontology — the finest-detail comparison (study, 2026-11-04)

**Status: ✅ ADOPTED 2026-11-04 as Arc NV (ROADMAP §3.68, §6 item 60; PENDING item 76) — NV-0 to NV-3 BUILT the same day
on `claude/nvidia-auto-ontology-study`.** Written at the user's ask: *"https://github.com/NVIDIA/auto-ontology — Dont we
do something similar or better? Lets compare first at the finest details."*, then built at *"make sure we have everything
well structured and start building based on the study"*. §5.1 → NV-3, §5.2 → NV-2, §5.3 → NV-1, §6 → NV-0; the live
receipts and what each wave still owes are in PENDING item 76. Two premises below were wrong when measured: the
candidate door "that already EXPLAIN-binds" (§5.1) had no caller at all, and the 200-value cap (§5.3) read as
eligibility would have kept the probe silent on Superstore's 1,237 distinct order dates — the probe reads up to 2,000.

**What was read.** `NVIDIA/auto-ontology` at `caced11e` (2026-11-03, "nemotron-3.5-defaults"), Apache-2.0: 78,836
non-test Python lines under `auto_ontology/` (122,491 with tests), a Next.js frontend, a FastMCP server, three agent
skills and seven Alembic migrations. Cloned read-only into the session scratchpad; nothing in it was executed. Aughor
read at `b19cf45` (main). Two mechanism-level surveys were made, one per repo, every claim with `file:line`; the
load-bearing ones were re-read by hand before this was written. External: the companion `auto-ontology-eval` README
and its PR #42 (the only accuracy numbers NVIDIA has published anywhere), re-read on GitHub. A press piece and a blog
critique were not readable from this session (hosts not allowed) and are not cited.

A path written `nv:…` is in the NVIDIA clone; a bare path is in this repo.

---

## 0 · The answer, on one page

1. **Yes — for what Auto-Ontology does, Aughor does the same thing, usually more strictly, and then a great deal
   that Auto-Ontology has no word for.** Auto-Ontology is a *context layer for text-to-SQL*: one LLM-proposed Term per
   table, one attribute per non-key column, inferred foreign keys, named SQL snippets mined from query history, all
   embedded in pgvector and consumed by a LangGraph text-to-SQL agent with live-database probes. Aughor's ontology is
   that same layer (entities, properties, links, verified formulas, trusted queries, vocabulary) **measured against the
   warehouse rather than proposed from names**, and then a second storey — processes, promises, rules, impacts,
   declared actions, row policies, releases with history, claims pinned to a release — that is not in NVIDIA's model at
   all.

2. **The three places NVIDIA is genuinely ahead are small and specific.** (a) It reads a warehouse's **own query
   history** (Snowflake `QUERY_HISTORY`, ClickHouse `system.query_log`, Postgres `pg_stat_activity`) and mines it into
   reusable SQL attributes; Aughor's sqlglot miner is as capable but reads only Aughor's own executed SQL, and reaches a
   prompt only behind a raw env var. (b) It detects **bridge tables** (every column a foreign key) and writes a join
   pattern for them; Aughor measures N:N per edge and refuses it in the compiler, but names no junction. (c) It infers
   a **date-format notation** per text date column by exhaustive `strptime` and refuses DD/MM-vs-MM/DD ambiguity;
   Aughor has no equivalent. Everything else NVIDIA does — live literal probing, join-path verification of the SQL the
   model wrote, scale-mismatch detection, deterministic answerability — Aughor has in a stronger or equivalent form.

3. **The two things NVIDIA's own repo admits are missing are exactly Aughor's invariants.** Its certification flags
   (five human-set booleans) are rendered in the UI and **never read by retrieval**: a certified and an uncertified
   Term reach the agent identically. It has **no versioning, supersession or audit log**; edits overwrite in place, and
   its own management skill says *"do not claim atomic certification, promotion, supersession, or rollback."* Its SQL
   attribute "validation" is a sqlglot parse, never an execution. Aughor's rules — *provenance required*, *supersede,
   do not delete*, *a formula is verified only when it bound against the live database*, *withheld is said* — are the
   answer to each of those.

4. **On accuracy, neither side can claim a comparable number, and the shapes of the evidence differ.** NVIDIA's one
   published figure (PR #42 of the eval repo, 2026-10-13): BIRD dev 1,533 questions, schema-in-prompt **70.4%** against
   the ontology agent **76.5%**, model unnamed, after fixing two harness defects that had shown a *loss*. Aughor's
   ablations are smaller and on its own sets: prose ontology blocks lifted nothing (R4 injected 58% against raw 92%;
   ON-0 13/14 = 13/14), the object query language regressed (3/12 against 12/12), and **framing a question against
   declared definitions lifted 4→12 of 16 and 6→11 of 15.** The NVIDIA result is consistent with Aughor's reading: the
   lift comes from resolving terms and joins deterministically before the model writes SQL, not from prose.

5. **What is worth taking** (§5): the warehouse query-history reader for the three engines that have one, feeding the
   miner Aughor already has, through the candidate door that already EXPLAIN-binds; the bridge-table mark as a measured
   fact on an entity whose columns are all keys; the date-format probe as a property fact. Each is a day or two, each
   goes through the measured tier, none needs a model. What is **not** worth taking: the one-Term-per-table LLM pass
   (Aughor's builder does it deterministically), the lenient LLM intent validator, and feature flags.

6. **Found on our side on the way** (§6): `AUGHOR_QUERY_LOG_MINING` is a raw `os.environ` switch outside
   `kernel/flags.py` and outside `orgsettings/allows.py` — a feature flag that survived the 2026-10-28 retirement by
   not being registered. `candidates.py` declares `query_log`, `saved_sql` and `dbt` origins that `mine()` never wires.

---

## 1 · What Auto-Ontology is, mechanically

Three tiers in one Postgres (`nv:CLAUDE.md:28` "The store is Postgres … SQLAlchemy Core (no ORM)"); a graph-database
vocabulary of nodes, edges and labels survives only in constant names (`nv:auto_ontology/catalog/constants.py:13-56`).

| Tier | Tables | Written by |
|---|---|---|
| Catalog | `catalog_database/schema/table/column`, `column__foreign_key`, `column__join`, `column__union`, `sql_query`, `sql_query__table/column` | ingestion: `information_schema`-style connector queries plus parsed query history (`nv:catalog/extract.py:89-94`) |
| Semantic | `term`, `column_attribute`, `sql_attribute`, `custom_analysis`, `pql_analysis`, and the links `table__term`, `column__has_attribute`, `column__semantic_fk`, `column_attribute__term`, `sql_attribute__term`, `sql_attribute__sql` | "semantic compilation": one LLM call chain per table (`nv:semantic/compile.py:33-127`) |
| Retrieval | pgvector `vdb.data_objects_layer`, `vdb.semantic_layer`, HNSW over `halfvec(2048)` (`nv:vdb/postgres.py:280-324`) | embedder; read by a LangGraph text-to-SQL agent |

The ontology proper is **a Term per table** — the extraction prompt: *"Strongly prefer ONE Term per table"*
(`nv:semantic/term_extractor.py:38`) and *"Do not propose IS_A, PART_OF, or ROLE relationships"* (`:47`) — with one
**ColumnAttribute** per non-foreign-key column, **SEMANTIC_FK** edges from a foreign-key-looking column to the attribute
it references, and **SqlAttributes**, named SQL snippets with `source ∈ {manual, sql, table, bridgeTable}`
(`nv:dal/schema.py:618-622`). There is no hierarchy, no instance, no process, no action. Terms are created only by
compilation or import: there is no `POST /terms` (`nv:server/terms/router.py`).

### 1.1 Vocabulary crosswalk

| Auto-Ontology | Aughor | Note |
|---|---|---|
| Term | **Entity** (`OntologyEntity`) | both one-per-table by default; Aughor's a person merges, absorbs (Part), or declares over a keyed SELECT; NVIDIA's merges only by name collision |
| ColumnAttribute | **Property** (`EntityProperty`) | NVIDIA's carries an LLM one-sentence description and a `certified` bit; Aughor's carries measured null rate, distinct, top values, percentiles, `measure_grain` probed on data |
| SEMANTIC_FK edge | **Link** (`OntologyRelationship`) | NVIDIA: column→attribute, pruned on zero overlap; Aughor: entity→entity, containment ≥ 0.15 measured, both sides' cardinality counted |
| SqlAttribute | **Expression property / verified computed property / trusted query** | NVIDIA validates by parse; Aughor executes before `verified=True` |
| CustomAnalysis | **Trusted query** | both named, reusable SQL retrieved into the prompt; Aughor's runs the full guard battery before `proposed` |
| Acronym (frontend `Acronym` table) | **Vocabulary / glossary** | Aughor ranks sources `human > mined > pack > llm_candidate`; NVIDIA has one table, no rank |
| `is_junction_table` | — | absent in Aughor (§5.2) |
| `format` (date notation) | — | absent in Aughor (§5.3) |
| Tag, Rule (saved search → tags), Zone | tags on trusted queries only; **Layer** (`dataset_layers.py`) and declared exclusions; row policies | NVIDIA's zones "stopped being an authorization boundary" (`nv:frontend/auth/proxy-backend.ts:12-14`) |
| `name_certified`, `description_certified`, `certified` | `verified` (bound against the database) and `source: human` | NVIDIA's flags are never read downstream (§3.6) |
| `check_answerable` coverage | **Frame** (`framing.py`) and `framing_misses.py` | both deterministic; NVIDIA's is an embedding distance, Aughor's is stem matching against declared names |
| PqlAnalysis / KumoRFM | — | no predictive engine in Aughor (`tools/stats.py` STL only) |
| — | Process, Stage, Promise, Rule, Impact, declared Action, Binding, Part, Row policy, Sensitive property, Release, Draft, Retiring, Put back, Dependents, Contract, Pack, Claim/Record | no equivalent in NVIDIA's model |

---

## 2 · The crosswalk, layer by layer

Legend: **DET** deterministic · **LLM** a model call · **DATA** measured on the warehouse · **NAME** inferred from
identifiers or text only · **STORE** persisted.

### 2.1 Catalog ingestion and column profiling

| Mechanism | Auto-Ontology | Aughor | Verdict |
|---|---|---|---|
| Schema source | `information_schema` queries per connector; fails closed if any relation has zero columns (`nv:catalog/extract.py:43-77`) | connector metadata plus engine-declared FKs (`db/metadata.declared_join_candidates`); profiler (`tools/profiler.py`) | even |
| Incremental re-ingest | diff on natural keys refreshes `table_type`, `pk`, `data_type`, `is_nullable`, never curated descriptions (`nv:catalog/diff.py:128-133`); docstring admits the column diff "was already silently broken for every re-ingest once" (`:11-12`) | fingerprint of table names + row counts + grain columns (`ontology/store.py:380-396`); overrides tree keyed outside the cache so rebuilds never wipe declarations (`overrides.py:1-20`) | Aughor |
| Row sample | `SELECT * LIMIT 1000` per table (`nv:semantic/visit_enter.py:53,463`) | profiler: catalog approx-distinct, exact `COUNT(DISTINCT)` on tables under a size threshold, DuckDB HLL above (`profiler.py:1180-1216`) | Aughor measures whole columns; NVIDIA samples the first 1,000 rows |
| Uniqueness | `is_unique` = all non-null *sampled* values distinct (`nv:visit_enter.py:495`) | grain verified on the full table ±1%; composite grain probed pairwise (`profiler.py:1227-1232`); re-measured on the backing (`backing.py`) | Aughor: a sample of 1,000 cannot prove a key |
| Top values | top 5, strings ≤30 chars, dates/uuids excluded (`nv:visit_enter.py:62-66`); full enum via `SELECT DISTINCT LIMIT 26` when ≤25 distinct (`:72,362-404`) | `top_values` per column from the profiler; value dictionaries curated per column (`vocabulary.py:395-430`); trigram value index for high cardinality (`sql/value_index.py`) | Aughor |
| Date format | **23 `strptime` candidates, a winner must parse every one of ≤200 distinct values, DD/MM vs MM/DD ambiguity returns None** — "saying nothing beats a coin flip the model would take as fact" (`nv:semantic/date_format.py:39-63,65-80,181-184`); stored on `catalog_column.format`, rendered in the prompt | none | **NVIDIA** (§5.3) |
| JSONB | nested-key sampling with unit-marker annotation (`nv:visit_enter.py:76-86`); a Postgres-only JSONB key-path pre-check at query time (`nv:db_probe/jsonb_path_check.py`) | none specific to JSON | NVIDIA, narrow |
| PII | regex rules first, LLM fallback, propagated column→attribute as a protected `PII` tag; removing an auto tag is a respected override (`nv:pii_detection/detector.py:5`, `dal/schema.py:291-294`) | `Sensitivity` declared by a person per property, masked and refused in queries (`security.py`); clearance tags (`govern/tags.py`) | different: NVIDIA detects, Aughor enforces |
| Nullability coercion | `YES/TRUE/T/Y/1` and `NO/FALSE/F/N/0`, raises on anything else — "silently guessing is what the bug was" (`nv:catalog/normalize.py:79-111`) | measured `null_rate` | even in spirit |

### 2.2 Entity formation

| Mechanism | Auto-Ontology | Aughor | Verdict |
|---|---|---|---|
| Entity per table | **LLM**: one structured call per table — name, description, every column assigned (`nv:term_extractor.py:220-262`); label regex sanitised; fallback `to_term_name(table)`; unassigned columns fall to the first Term (`:186-196`) | **DET**: `_table_to_entity_name` strips DWH prefixes and singularises (`builder.py:56-111`); `# table = entity: every profiled table becomes an entity` (`:846`) | Aughor's is free and reproducible; NVIDIA's names read better out of the box. Aughor's enricher then overwrites `display_name` in one temp-0 call (`enricher.py:245-328`) |
| Name collisions | commits serialised in canonical `(database, schema, table)` order so an unqualified Term name goes to the first table; later ones are qualified (`nv:semantic/pipeline.py:116-137`, `dal/terms.py:417-429`) | ids are PascalCase of the table leaf; `api_name` never overwritten (`models.py:372`) | NVIDIA's is a nice determinism under parallel LLM work; Aughor has no parallel LLM pass to need it |
| Beyond one table | SEMANTIC_FK only; the prompt forbids IS_A/PART_OF (`:47`); `text_attribute`, `analysis` tables "never written" (`nv:dal/schema.py:704-706`) | declared entity over a keyed SELECT; merge = two tables one binding (`dedup.py:11-14`); Part (`parts.py`); static/timeseries/detail bindings across connections (`models.py:269-325`); organisation ontology keyed `org/domain` (`domains.py`) | **Aughor**, by a storey |
| Entity type | none | `reference_data | business_object | event | standalone` by name heuristic (`builder.py:114-136`), enricher may correct | Aughor, minor |
| Lifecycle | none | status-named low-cardinality column → states; terminal by keyword; **`active_filter` deliberately None** (`builder.py:152-155,228-233`); `lifecycle.py` then measures rows that left a claimed terminal state and flips `lifecycle_verified` | Aughor |
| Instances | none; Terms only | objects read live by key, never copied (`semantic/object_instances.py`); object pages | Aughor |
| Synonyms | second LLM call extracting only aliases **explicitly written** in the table description (`nv:term_extractor.py:66-78,203-217`) | vocabulary with source rank and tombstoned declines (`vocabulary.py:12-24`); pack terms reach a prompt only once a person promotes them | Aughor |
| Descriptions | LLM, batches of 15 columns, "ONE concise sentence … Use the column name, data type, and sample values as evidence" (`nv:semantic/deterministic.py:29-40`); existing descriptions get " — samples: …" appended | glossary precedence `manual > dbt > auto-seed > DDL` (`semantic/dbt.py:12-13`); enricher fills blanks only, never overwrites a glossary or human text (`enricher.py:275-280`) | even on quality, Aughor on governance. Note: `entity.description` reaches no answer prompt in Aughor (prompt-reach audit) — nor does NVIDIA's Term description reach SQL generation except through the attribute's embedding text |

### 2.3 Joins and foreign keys — the closest contest

| Mechanism | Auto-Ontology | Aughor | Verdict |
|---|---|---|---|
| Declared FKs | read into `column__foreign_key`, `last_seen` stamped, stale swept (`nv:catalog/write.py:146-155`) | seated first in the join map with `match="declared"` (`tools/schema.py:204-215`) | even |
| FK candidates | **LLM + NAME**: one structured call per table returns `fk_suggestions`, `pk_column_names`, `is_junction_table` (`nv:semantic/fk_suggester.py:117-233`); guards: an LLM "PK" rejected when profiling says non-unique; a non-unique uuid column is always an FK (`:191-227`). **Suggestions are not persisted** — they only remove columns from attribute candidacy (`nv:visit_enter.py:813`) | **DET + NAME**: `fk_root` on id/key-suffixed columns, a plain root must name a table and not be in `_NON_KEY_ROOTS` (`tools/schema.py:216-235`); star routing to the dimension that owns the root, facts never join facts (`:255-283`) | even on recall; Aughor needs no model |
| Resolving the target | declared FK fast path; else two pgvector queries over ColumnAttributes with `is_unique=True` (full text top-3 + name-only top-3), LLM pick with "Do NOT guess. If unsure, return null" (`nv:semantic_fk.py:466-529,67-78`); if the LLM abstains, a **sample-value membership probe** on same-named candidates keeps hits where every FK sample appears (`:531-597`) | the owner dimension's PK by name (`_dimension_pk`, `tools/schema.py:135-160`); `reconcile_join_keys` tries type/format respellings when overlap is low (`join_guard.py:567`, 0.60) | NVIDIA finds targets across unlike names via embeddings; Aughor would miss `cust_ref → customers.id` unless declared |
| Value verification | **existence only**: delete an edge with zero overlap or an all-NULL source — "No overlap at all is the only test applied … a low share is no proof" (`nv:semantic_fk.py:103-157`) | **containment ≥ 0.15** over a 100 × 1,000 sample or HLL inclusion–exclusion above a row threshold (`join_guard.py:34,38-39,437-472`); disjoint name coincidences dropped, a contradicted catalog FK kept with its measured overlap so "a reader sees both claims" (`builder.py:1009-1019`) | **Aughor** |
| Cardinality | not measured; `is_unique` from the 1,000-row sample is the only hint | `SELECT COUNT(*), COUNT(col), COUNT(DISTINCT col)` per side on the whole table (`cardinality.py:66-82`); measured label replaces an authored one, the authored survives in `cardinality_note` | **Aughor** |
| Bridge / junction tables | **a table whose columns are all FKs is marked junction** ("Structural qualification is sufficient evidence", `nv:semantic/bridge_tables.py:232-236`); an LLM writes one join-pattern SqlAttribute using only the listed FK pairs; the owning Term is chosen by the RERANK model (`:100-148`); `is_junction_table` is never cleared by compilation (`nv:dal/schema.py:244-247`) | N:N measured per edge and **refused by the object compiler**; a `detail` binding or Part models a line table; no junction concept (grep: only linker comments) | **NVIDIA** (§5.2) |
| Join default among several FKs to one target | LLM picks, fallback alphabetical, persisted `use_in_join_paths` (`nv:semantic_fk.py:286-345,405-416`) | `use_instead` routing overrides, person-declared (`routing.py`) | even |
| Join-path search | shortest path over SEMANTIC_FK; **reverse edge only when the owner column is the declared PK**, so two FKs into a shared non-identity column never read as joinable (`nv:dal/attributes.py:792-813`); same-table or cross-database → `[]` | `framing._to_one_paths` walks measured to-one links N hops (`:563`); compiler traverses measured links only, ≤3 hops, N:N refused (`object_query.py`) | even; different jobs (NVIDIA hands the path to the model as text; Aughor compiles it) |

### 2.4 Measures, SQL snippets and query-history mining

| Mechanism | Auto-Ontology | Aughor | Verdict |
|---|---|---|---|
| Query-log source | **Snowflake `INFORMATION_SCHEMA.QUERY_HISTORY`** (`nv:connectors/snowflake.py:352-360`), **ClickHouse `system.query_log`** (`clickhouse.py:773-774`), **Postgres `pg_stat_activity`** — recent activity, not a durable log, system queries not excluded (`postgres.py:220-243`); Databricks deliberately off (`databricks.py:863-871`); MySQL, Trino, Kyuubi, HeavyDB, SQLite return empty | the `aughor_sql_examples` collection of **SQL Aughor itself ran** (`sql/query_log_miner.py:209-232`); the docstring says a QUERY_HISTORY reader "can feed the same `mine_query_log` once credentials land" — not built | **NVIDIA** (§5.1) |
| Parsing | sqlglot with `qualify` through CTEs and subqueries, alias pre-pass, catalog-assisted fallback (`nv:catalog/parsers/sqlglot_extractor.py:5-25`); emits table, column, join-pair and union-pair edges | sqlglot: join equalities ranked by frequency, filter literals, named formulas, column roles (`query_log_miner.py:46-54,117`); roles feed the profiler unconditionally (`profiler.py:1760-1765`) | even |
| Dedup | exact text → structural pre-filter (table set, column set, AST node count, join and union counts) → literal-blind canonical comparison (`nv:catalog/query_stats.py:36-62`, `query_comparator.py:35-67`) | `answer_divergence.py` finds the same question answered by different SQL and makes a person pick (measured: 92% of 793 receipts were repeats) | different aims; NVIDIA's dedup is the more thorough parser-level one |
| Usage ranking | **pinned broken**: `_usage_score` returns 0.0 for every statement because the writer emits `count_8_2026` and the reader expected `count_monthly_2026_08`; tests assert the bug (`nv:semantic/sql_attribute_suggester.py:69-123`, `semantic/tests/test_usage_score.py:1-16`) | `use_count` on `DefinitionSource` from executed SQL (`harvest.py:104`); `popularity.py` per table and column | Aughor, by default |
| Expression extraction | WHERE/HAVING/ON predicates with a literal, aggregates, CASE, set-operation branches; excludes bare columns and `col = col` (`nv:sql_attribute_suggester.py:125-233`); top 10 to an LLM judge with hard-coded rules; approved ones wrapped as SELECTs, **validated by sqlglot against the catalog, not executed**, persisted `source='sql'` (`:584-624`) | `candidates.py` mines typed candidates (`join|measure|filter|synonym|object_set`) from trusted queries and accepted verdicts; **every candidate must EXPLAIN-bind before it is offered** (`:11-15`); `harvest.py`: "`verified` means the formula BOUND against the live database, and nothing else may set it" (`:18-25`) | Aughor on verification; NVIDIA on breadth of extraction |
| Reusable measure | SqlAttribute: `expression`, one owning Term, `certified`, `description_suggestion`; validation = parse + table resolution (`nv:server/sql_utils.py:68-85`) | `MetricDefinition` with owner, caveats, additivity, tests, "NEVER rules", approval; save refuses a formula that will not bind (`metric_checks.py`); figure gates at approval (`metric_gates.py`); twins by figure agreement over 6 months (`metric_twins.py`) | **Aughor** |
| Additivity / grain | none | `measure_grain` probed on data; semiadditive declarations; fan-out and ratio-of-sums guards; promise-derived `late_<name>` segments and `<name>_breach_rate` metrics by construction | **Aughor** |

### 2.5 Storage, versioning, provenance, governance

| Mechanism | Auto-Ontology | Aughor | Verdict |
|---|---|---|---|
| Store | ~30 Postgres tables, Alembic, server refuses a non-current schema and never migrates itself (`nv:dal/schema_version.py:5-20`) | YAML overrides tree per `{conn}/{schema}/{kind}/{id}` plus `system.db`; shipped declarations under `data/shipped/` | even |
| History | **none**: `update_term`, `update_column_attribute`, `update_sql_attribute` overwrite; `created/modified/modified_by` only (`nv:dal/schema.py:128-152`) | every save and withdrawal a version with stable id `ontology:<conn>/<schema>/<kind>/<id>` (`history.py`); a rename is a new version, a measurement is not | **Aughor** |
| Release | none; `POST /semantic-compilation/reset` is "an asynchronous, destructive rebuild" | draft → release; ERR · MEANING · WARN · SAFE per change (`compatibility.py:24`); publish refused while an ERR stands; release hash; claims pin `<conn>/<schema>@<n>`; MEANING changes restate the claims computed under the old meaning (`release.py:1-22`) | **Aughor** |
| Rollback | export YAML with SHA-256 as "the rollback artifact"; the maintainers' skill calls this non-atomic and lists open import defects #250, #265, #267 (`nv:skills/nvidia-ontology-management/references/publication.md`) | put back an earlier version through the normal save path, re-measured, into the draft (`put_back.py`); retiring with successor and day (`retiring.py`) | **Aughor** |
| Dependents | none; a Term can be renamed with nothing checking who relies on it | withdrawal refused where automations, processes, rules, actions, links, parts or metrics name it (`dependents.py`) | **Aughor** |
| Provenance | structural: `sql_attribute.source`, `sql_attribute__sql`, `tagged_by` vs `rule_id`, `created_by` where "Compilation … does not count" (`nv:dal/schema.py:134-137`). **No provenance on a Term's name or description; no model or prompt version recorded; FK rationales discarded** (`nv:visit_enter.py:813`) | `Provenance` required on every context-graph node and edge, allow-list with "deliberately no `llm_inferred`" (`context_graph.py:44-60`); explorer proposals `origin: model`, `model:<id>@<version>` (`explorer.py:610`); `DefinitionSource` with author, asset, use count, bind verdict | **Aughor** |
| Human sign-off | five booleans — `term.name_certified`, `term.description_certified`, `column_attribute.certified`, `sql_attribute.certified`, catalog `description_certified` — rendered as a badge and **never read by retrieval; no `certified` in VDB metadata** (`nv:semantic/embed.py:256-280`; grep `certif` in `retrieval/` and `semantic/` hits one unrelated comment) | `verified` is earned by execution; `source: human` outranks everything; only verified items are injected (`semantic_block.py:12-14`); a pack term reaches a prompt only once a person promotes it | **Aughor** — and this is NVIDIA's single largest gap |
| Model proposals | written straight into the served tables by compilation | wait in the draft; the organisation ontology refuses model declarations outright (`domains.py:20-25`) | Aughor |
| Audit | none beyond `modified_by`; a write without the gateway header records "Auto Generated" (`nv:dal/schema.py:829-834`) | `govern.audit` on every verdict; ledger events; Trust Receipt per answer | Aughor |
| Feature flags | pervasive: `distinct_value_probing_enabled`, `pii_detection_enabled`, `semantic_compilation_enabled`, `visualization_enabled` in a settings table plus ~10 env toggles (`nv:infra/feature_flags.py:28-45`, `db_probe/config.py:33-70`) | none registered since 2026-10-28 (AGENTS.md) — with the one exception found in §6 | Aughor, by policy |

### 2.6 Query time — retrieval and what reaches the prompt

| Mechanism | Auto-Ontology | Aughor | Verdict |
|---|---|---|---|
| Question decomposition | LLM intent (`information | prediction | calculation` + subtype) and LLM entity extraction of noun phrases (`nv:agents/question_intent.py`, `prompts.py:1037-1099`) | deterministic **frame**: stems matched against declared entity names, properties, process stages, promises, rules, keyed metrics (`framing.py:841`); one model call only to choose among ties | Aughor: the measured lift lives here |
| Candidate retrieval | per entity: pgvector top-10 ColumnAttributes, top-3 CustomAnalyses, top-3 SqlAttributes (`nv:data_access/semantic_search.py:51-56`); LLM intent filter; a database chosen by hit counts | linker over schema embeddings with BM25 floor (`semantic/lexical.py`); metric retrieval BM25 ⊕ vector; trusted-query token match; `fk_neighbor_expand` 1 hop | even |
| Anchor and paths | LLM picks an **anchor** attribute (`nv:candidates_preparation.py:1207-1226`); `find_join_path` anchor→each destination; junction and bridge expansion; LLM table-relevance filter "When in doubt, do NOT remove" (`prompts.py:1119-1153`) | frame resolves the entity; compiler builds to-one paths; the planner sees verified joins with cardinality | even |
| Prompt content | per table a pipe table `table | label | description | pk`, per column `column | type | nullable | semantic_fk | description | samples | format`; "SEMANTIC HINT — likely starting table"; "JOIN PATHS (VERIFIED OPTIONS)" hop by hop with "Once you choose a path, every intermediate/bridge table and every listed hop is mandatory. Never shorten the path" (`nv:formatters_util.py:154-222,302-402`; `prompts.py:433-489`); custom analyses; SQL attributes; acronyms; other-database exemplars; ≤5 turns / 12,000 chars history | ENTITY MODEL block (`builder.py:1053-1132`), relationship block with measured cardinality, question-scoped verified semantic layer, metrics catalog, synonyms, trusted block, frame block; **prompt reach measured and ratcheted**: a field reaches a block iff changing it changes the block (`prompt_reach.py`; 59 of 142 on 2026-09-10, 156 walked now) | Aughor on discipline (NVIDIA has no reach audit); NVIDIA's "verified options" wording is good |
| Certified vs not at query time | identical treatment | only verified reaches the model | Aughor |
| SQL generation | one LLM call; "You MUST always produce a SQL query" (`nv:prompts.py:433`) | planner → SQL under the guard battery; a question the frame cannot ground is said so | Aughor on honesty; NVIDIA's `check_answerable` is the mitigation |
| Compiled path | none — the model writes all SQL | `semantic/compiler.py` single-table intents; `object_query.py` object algebra with the join law by construction (to-one LEFT JOIN with repetition-safe aggregates only, to-many pre-aggregated, N:N refused); the model-facing object tool was **deleted 2026-10-04 after measuring 3/12** | Aughor has the door; measured that the model should not drive it |
| Predictive questions | KumoRFM: uploads up to 20 tables / 2 GiB to a hosted service, LLM writes PQL, budget refuses rather than truncates (`nv:kumo/budget.py:84-86`) | none | NVIDIA, if wanted; data leaves the install (README) |

### 2.7 Between the model and the answer

| Check | Auto-Ontology | Aughor |
|---|---|---|
| Static SQL checks | sqlglot: degenerate SQL, vacuous GROUP BY, missing aggregation, mixed-case identifier quoting (`nv:sql_parse_validation.py:206-770`) | `readonly.py` AST mutation and CTE-masked write denylist (fail-closed); `lint`, `engine_fit`, `capability_check`, `composite_key`, `numeric_text`, `order_measure` |
| LLM intent check | yes, **deliberately lenient**: "Be LENIENT - only mark as invalid if there are serious…" (`nv:prompts.py:545,590`); stops blocking after 5 failed attempts | none; guards are deterministic and name what they could not check (`validation.py:46-51`) |
| Literal / value probe | opt-in `validate_sql_values` (agentic) and `precheck_combined` behind `DB_PROBE_*` env flags: DISTINCT ≤20 categorical discovery, `difflib` 0.6 near-miss, 100× scale and integer-division detection (`nv:db_probe/literal_check.py:74,389`); on empty result `check_value_repair` | always on: `grounded_literals.py` pre-generation; `filter_domain_check` probes the column's real domain (≤50 enumerated, trigram index above, cutoff 0.82), sibling-column and `novel` verdicts, `repair_filter_literals` via sqlglot (`join_guard.py:890-1000`, `value_index.py`) |
| Join verification of the written SQL | `join_path_check` verifies the actual `ON` predicates against the SEMANTIC_FK graph, falls back to a live overlap probe ≥ 0.2, normalises case-dirty joins (`nv:db_probe/join_path_check.py:77`) | `join_domain_check` (containment 0.15), `check_join_coverage` (0.90), `fanout.py` chasm-trap detector, `grain_guard`, `ratio_grain`, `semiadditive` |
| Probe sandbox | `ProbeExecutor`: single SELECT/WITH, auto-LIMIT, 40 calls, 50 rows, 5 s, ≤8 tables × 8 columns (`nv:db_probe/executor.py:5-22`) | `execute_guarded`; `internal=True` probes; `cost` guard |
| Time and type traps | none found | `time_order_guard`, `day_window`, `trust_checks.py` (timestamp-vs-date boundary, lexicographic text sort, text-vs-numeric compare), `lifecycle_guard`, `metric_filter_guard` |
| Semantics of operations | none | `operations.yaml`: 24 concepts with `aggregate / never / numeric` (SUM of a latitude never) |
| Retry discipline | reconstruct ≤7, soft checks unblock after 5, full pipeline ≤2, then last deterministic SQL (`nv:text_to_sql_graph.py:82`, `main.py:72,304`) | guards fail-open per guard and say so; a flagged answer is shown flagged, never silently |
| Answer receipt | `sql_code`, rows, `thoughts` step trace; MCP rows capped at 100 | HMAC-signed Trust Receipt: artifact, lineage, guards and their outcomes (`trust/receipt.py`); `recheck.py` re-runs later and says late-rows vs restatement; `factcheck/` checks every number in a document |

Reading: Auto-Ontology's probes are good and specific — the scale-mismatch and integer-division checks are worth
noting — but they are **opt-in behind env flags**, and the one check that runs on every answer is an LLM told to be
lenient. Aughor's battery is always on, deterministic, and its own evaluation (R4) is what retired "more context" as
a strategy. The two systems agree on the posture; one of them enforces it by default.

### 2.8 Answerability and clarification

| | Auto-Ontology | Aughor |
|---|---|---|
| Before SQL | `check_answerable`: coverage = entities with a ColumnAttribute hit at vector distance ≤ 0.75 over entities (`nv:entity_coverage/agents/coverage.py:60-66`, `state.py:17`); deterministic given embeddings; the README's "coverage 0.5; no term covers 'ad spend'" | frame: declared or not, per term; `framing_misses.py` records every question that reached no definition (no question text); `near_match.py` proposes the declaration that would have caught it (IDF stem matcher, threshold 1.0, top 3) |
| Clarifying turns | `retrieval/interactive/`: clarify, entity resolution (`_KB_VDB_DISAMBIG_THRESHOLD = 0.62`), KB coverage, completeness, follow-up merge — **a BIRD-Interact eval harness reachable only from `main.py` under `INTERACTIVE`, not from UI or MCP** | ambiguity ledger (`semantic/ambiguity_ledger.py`), intake with shown-list picks (99.9% of 1,833 picks from the list) |

### 2.9 Security, identity, tenancy

| | Auto-Ontology | Aughor |
|---|---|---|
| Roles | `admin`, `viewer` from `access.json`; groups carry one role; a row's owner (account or group) may edit that row (`nv:server/owners.py:5-12`) | viewer ⊂ analyst ⊂ owner; securables include metric, promise, process, rule, domain, automation (`metastore/models.py:143-172`); enforced once `AUGHOR_REQUIRE_IDENTITY` is set |
| Enforcement point | Next.js gateway `withPermission`; **FastAPI trusts `x-auto-ontology-user-id`**; ingestion endpoints have no auth (`nv:README.md:259-262`) | router dependencies (`rbac/deps.py`) |
| Row and column security | none on the ontology; zones "stopped being an authorization boundary" (`nv:frontend/auth/proxy-backend.ts:12-14`), every router passes `zone_ids=None` | `RowPolicy` and `Sensitivity` per entity compiled into every object door and into the connection's SQL door via sqlglot (`security.py`, `security_sql.py`); masked is said, never guessed |
| Agent identity | MCP: Auto-Ontology is the OAuth server, tokens checked via UserInfo each call, "a session can do exactly what the person behind it can do" (`nv:docs/mcp.md`); a skill benchmark notes the `aud` claim is not checked on SSO bearer tokens | service principals with `read | run | act` per tool, hidden from `tools/list` when denied (`mcp/policy.py`); a grant is permission to propose, never execute |
| Warehouse auth | SSO-federated per caller, fail-closed (`nv:connectors/registry.py:189-199`); optional Vault | per-connection credentials in the secret vault (`secretvault.py`) |

NVIDIA's SSO-to-warehouse federation is a real feature Aughor lacks; its ontology-level security is absent.

### 2.10 Interchange, MCP, skills, connectors, models

| | Auto-Ontology | Aughor |
|---|---|---|
| Interchange | native YAML (`data_layer` / `semantic_layer`; import is one transaction, `replace=true` default deletes what the payload omits) and **Apache Ossie** via `ossie_nvidia_auto_ontology` (`nv:server/model_interchange/service.py:17-21,83-94`); an Ossie dataset is one table, so a multi-table Term is projected | YAML bundle round-trip (`interchange.py`), graph pack export, JSON Schema + TypeScript contract per release (`builder_doors.py`), dbt import only (`semantic/dbt.py`); Ossie: `ontology/ossie.py` exists — its depth was not re-read for this study |
| MCP | 9 read-only tools; "deliberately no tool for browsing databases, schemas, or raw columns"; handshake advertises the order readiness → search_terms → check_answerable → ask_question | 23 static tools plus one `propose_<action>` per declared action; `search_graph`, `describe_entity`, `list_objects`, `read_contract`, `post_claim` |
| Agent skills | three, with CI-generated BENCHMARK.md; **the benchmarks measure the skill documents** (Claude Code and Codex uplift on 10–13 tasks, 1 attempt each), not SQL accuracy | `SKILL.md`, `llms.txt`, exported offline `skills/*.md` per graph pack |
| Connectors | 10: Postgres, MySQL, Databricks, Snowflake, ClickHouse, Trino, Kyuubi, HeavyDB, DuckDB, SQLite | 40 in `connectors/catalog.json`, including API (HubSpot, Salesforce, Stripe, Sheets), file and knowledge sources |
| Models | four roles; `nvapi-` → Nemotron 3.5 Lightning 30B / embed-1b / rerank-8b; NVIDIA-internal `sk-` → **`azure/anthropic/claude-opus-5-5`** for both reasoning roles (`nv:utils/model_config.py:29-54`); the eval repo's maintainers test both arms on Claude Opus 5.5 | seven backends with a fallback chain (`llm/provider.py:60-61,346`); temp-0 structured enrichment; `test_ontology_llm_boundary.py` forbids `ontology/*` importing `llm/*` |
| Tests | 159 files, 2,203 test functions; frontend 0; no accuracy data in the repo | 13,616 test functions; 347 in `test_ontology*.py`; 90 eval artifacts under `evals/` with results committed |

### 2.11 What Aughor has that Auto-Ontology has no word for

Each of these is measured on the data and has a store, a door and at least one consumer. None appears anywhere in the
NVIDIA model or roadmap text read for this study.

- **Processes and promises** (`processes.py`, 1,009 lines): stages anchored to timestamps or states, per-pair skip and
  reversal counts, p50/p90/p95 lags, promises measured kept/broken/open/overdue as of the data's own latest moment,
  deriving a segment, a lag property and a breach-rate metric by construction.
- **Rules** (`business_rules.py`): value sets and conditions the business holds and the data does not, counted.
- **Impacts** (`impacts.py`): one promise's effect on another, `influence | validated | formula`, worded by mechanism.
- **Declared actions** (`KineticAction`): typed parameters, criteria with authored messages, risk tiers, verification,
  undo, earned authority, an outbox; edits to an overlay, never to the source.
- **Bindings and parts**: one entity over several tables and connections; an organisation ontology across sources.
- **Releases, drafts, history, dependents, retiring, put-back** (§2.5).
- **The Record**: claims with warrants pinned to a release, decisions, outcomes, restatements.
- **Packs**: 18 industry priors evaluated as claims tiered `expected | measured-true | measured-false | human`.
- **Row policies and sensitive properties** compiled into every door.
- **A prompt-reach ratchet** that measures what the ontology changes in a prompt, and a vocabulary ratchet.

---

## 3 · Evidence: what each side has measured

| | Auto-Ontology | Aughor |
|---|---|---|
| Benchmarks | external repo `auto-ontology-eval`: BIRD dev 1,534, BEAVER `dw` 100, FDABench-Lite 169, WWI 41, BIRD-Interact; control = schema in prompt, treatment = the agent over the compiled ontology; deterministic execution-match verifier, no LLM judge; headline withheld when >5% of questions got no output | own sets on own warehouses: `evals/ablation_*` (missimi, samples/ecommerce, LuxExperience hard and business, Olist business, rate units); Spider2-Lite SQLite slice 135 instances 18.5% → 56.3% (2026-06-28; harness since removed) |
| Published numbers | **PR #42 (merged 2026-10-13)**: BIRD dev 1,533 — schema-only 70.4% (1,079), ontology 76.5% (1,172), **+6.1**; by difficulty simple +5.6, moderate +8.4, challenging +1.4; model not named in the PR. The repo README publishes none; the eval README publishes none. The first run showed 64.3% against ~70% — a loss — until two harness defects were fixed (payload mismatch between arms; an unpinned retriever dependency that made `get_relevant_tables` return an empty list silently) | R4 (2026-06-21, n=12): raw 92%, guarded 92%, injected 58% with 5 silent-wrong. ON-0 (n=12, n=14): ontology prose = raw on all arms. ON-0a: 13/14 vs 14/14. ON-2 object language: 3/12 vs 12/12. **ON-10 framing: LuxExperience 4→12 of 16, Olist 6→11 of 15** (`evals/ablation_on10_*`). Frame matcher 5/16 → 16/16 on declared wording, 0/3 on paraphrases |
| Reading | the lift is real on BIRD at +6 points and comes from resolved terms and verified join paths handed to the model; the two defects that hid it are the kind Aughor's "run the thing" rule exists for | the same conclusion from the other side: declared definitions and deterministic guards lift; prose and a new query language do not |

The numbers are not comparable — different sets, models, scales — and neither side should quote the other's.
What is comparable is the mechanism each side found load-bearing, and they agree.

---

## 4 · Where NVIDIA is ahead, and where Aughor is

**NVIDIA ahead (specific, small):**
1. Warehouse query-history ingestion for Snowflake and ClickHouse, and a parser-level dedup of statements.
2. Bridge-table detection and a written join pattern per junction.
3. Date-format inference with an honest refusal on ambiguity.
4. Embedding-based FK target resolution across unlike column names (then pruned on data).
5. SSO-federated warehouse authentication per caller.
6. Scale-mismatch (100×) and integer-division detection as explicit pre-execution checks.
7. JSONB nested-key profiling and key-path checks (Postgres).
8. KumoRFM predictive questions, if an install accepts the data leaving.
9. Apache Ossie import/export is wired end to end and documented.

**Aughor ahead (structural):**
1. Everything is measured on the whole table, not a 1,000-row sample: keys, cardinality, containment, lifecycle.
2. A formula is verified only by executing; NVIDIA's is validated by parsing.
3. Human sign-off changes what the agent sees; NVIDIA's certification bits change only a badge.
4. History, draft, release, change classes, dependents, retiring, put-back, claim pinning: NVIDIA has none.
5. Provenance on every fact with no `llm_inferred`; NVIDIA records no model or prompt version anywhere.
6. Row and property security on the ontology, compiled into every door; NVIDIA's zones enforce nothing.
7. Always-on deterministic guard battery with a signed receipt; NVIDIA's probes are opt-in and its one always-on
   check is a lenient LLM.
8. A prompt-reach audit; NVIDIA cannot say which fields reach its prompt.
9. The second storey: processes, promises, rules, impacts, actions, record, packs.
10. No feature flags; NVIDIA has a settings table of them.

---

## 5 · What is worth taking — each with its premise check

Ordered by value over cost. Each goes through the measured tier and needs no model; each is a candidate for the
plan of record, not a decision made here.

### 5.1 A warehouse query-history reader for the miner that exists

**Premise, checked.** `sql/query_log_miner.py` already extracts join equalities, filter literals, named formulas and
column roles with sqlglot (`:46-54,117`), and `candidates.py` already EXPLAIN-binds every candidate before it is
offered (`:11-15`). What is missing is the source: `collect_logged_sql` reads only Aughor's own executed SQL
(`:209-232`). NVIDIA's three readers are small: Snowflake `INFORMATION_SCHEMA.QUERY_HISTORY` (`nv:snowflake.py:352-360`),
ClickHouse `system.query_log` (`nv:clickhouse.py:773-774`); its Postgres `pg_stat_activity` reader is recent activity,
not history, and is not worth copying (BigQuery's `INFORMATION_SCHEMA.JOBS` and Databricks `system.query.history`
are the equivalents Aughor would add; NVIDIA turned Databricks off for cost). **Shape:** a connector method
`query_history(hours)` returning `(end_time, sql)`, off by default as an organisation's setting (data leaving nowhere,
but a whole-workspace read a connection's admin should choose), feeding `mine_query_log` → `candidates.mine()`
through the `query_log` origin that is already declared and unwired (`candidates.py:46,185-199`). Nothing reaches a
prompt except a candidate a person confirmed and that bound. **Receipt:** on a connection with history, the count of
join candidates the miner proposed that the name-based join map had not, and how many bound. **Falsifier:** if on
two connections the miner adds no join the map lacked and no formula a person confirms, the reader stays a connector
method and goes no further.

### 5.2 The junction mark as a measured fact

**Premise, checked.** No `bridge|junction|associative` concept exists outside linker comments
(`tools/context_manifest.py:79`); N:N links are measured and refused by the compiler. NVIDIA's rule is structural —
every column is a foreign key (`nv:bridge_tables.py:7-8`) — and then an LLM writes the join. Aughor's version would be
a builder fact: an entity whose every non-key property is a measured FK (containment ≥ 0.15 on each) with no
measures of its own is marked `junction`; the two links it carries are then declared as **one N:N link between the
far entities through it**, with both containments on record, and the compiler may traverse an N:N *only* through a
marked junction with pre-aggregation on the far side. The ENTITY MODEL block says "junction between X and Y". No model
call. **Receipt:** on theLook, Lux, Olist — which tables are marked, and whether `order_items → products` reads as
a junction (it should not: it has measures). **Falsifier:** if no live connection has a table that qualifies, the
mark ships as a fact with no compiler change.

### 5.3 Date-format as a property fact

**Premise, checked.** `EntityProperty` has `data_type`, `value_interpretation`, `unit` and no format; the vocabulary
has `set_format` for *display* formats (`vocabulary.py:155`), not storage notation. Text columns holding dates
(`'20260131'`, `'31/01/2026'`) are a known text-to-SQL trap and Aughor's `trust_checks` catches the comparison, not the
parse. NVIDIA's method transfers whole: ≤200 distinct values, 23 candidates in specificity order, a winner must parse
every value with year ∈ [1900, 2099], ambiguity returns None (`nv:date_format.py:39-115`). **Shape:** a profiler
probe for `VARCHAR` columns whose name or values look like dates, writing `EntityProperty.format`; rendered in the
ENTITY MODEL block only when set (reach grows, the ratchet records it); `numeric_text`/`trust_checks` gain the format
to say "compare as a date, not as text". **Receipt:** count of text-date columns found across live connections and how
many were ambiguous. **Falsifier:** none found on any live connection → the probe ships, the renderer change waits.

### 5.4 Smaller, also worth it

- **Scale and integer-division pre-checks** (`nv:literal_check.py:389`): a filter literal 100× off the column's range,
  and `a / b` over two integer columns, each a deterministic guard in the existing battery.
- **Embedding-assisted FK target proposals** for columns whose root names no table (`cust_ref`, `acct`): propose, then
  value-verify with the existing containment probe; the explorer's catalogue is where it belongs.
- **"VERIFIED OPTIONS … never shorten the path"** wording for the relationship block when a path is multi-hop.
- **SSO-federated warehouse auth** is a connector feature, not an ontology one; filed as a note, not a wave.

### 5.5 Not worth taking

- The LLM term-extraction pass: the builder already names entities deterministically and the enricher corrects
  display names in one call; NVIDIA's pass is per table and persists no rationale.
- The lenient LLM intent validator: R4 is the reason.
- The settings-table of feature flags.
- KumoRFM: a hosted service the data is uploaded to; against the posture that rows never move.

---

## 6 · Found on our side on the way

Not fixed — the ask was a comparison.

- **A feature flag outside the flag machinery.** `aughor/tools/schema.py:822` gates the query-log block on
  `os.environ.get("AUGHOR_QUERY_LOG_MINING") == "1"`. It is not registered in `kernel/flags.py`, not an organisation
  setting in `orgsettings/allows.py`, and not retired in `RETIRED_ENV`; it survived the 2026-10-28 "no feature flags"
  retirement by being invisible to it. Under the invariant it should become either always-on (the block is pure
  rendering of mined facts) or an organisation's setting if §5.1 lands.
- **Declared, unwired origins.** `candidates.py:46` lists `query_log`, `saved_sql`, `dbt`; `mine()` (`:185-199`) wires
  only trusted queries and verdicts. Either wire them (§5.1) or drop the names so a reader is not told they exist.
- **Ossie depth unread.** `ontology/ossie.py` exists; whether it round-trips a release the way NVIDIA's converter does
  was not re-measured for this study and should be before any claim either way.

---

## 7 · Appendix — the NVIDIA repo's own admissions, quoted

Collected because they are the most reliable evidence about what the system is, and each is the kind of sentence
this repo's own ratchets exist to make unnecessary.

- *"Strongly prefer ONE Term per table."* — `nv:auto_ontology/semantic/term_extractor.py:38`
- *"No overlap at all is the only test applied: real references in loaded data can still miss most of their target,
  so a low share is no proof."* — `nv:auto_ontology/semantic/semantic_fk.py:108-110`
- *"These tests pin a known bug rather than the behaviour anyone wants. `_usage_score` returns 0.0 for everything, so
  candidate expressions are never ranked."* — `nv:auto_ontology/semantic/tests/test_usage_score.py:7-9`
- *"Zone membership stopped being an authorization boundary."* — `nv:frontend/auth/proxy-backend.ts:12-13`
- *"Be LENIENT - only mark as invalid if there are serious…"* — `nv:auto_ontology/retrieval/text_to_sql/prompts.py:545`
- *"Current Auto Ontology certification fields are not an atomic review/promotion system. … do not claim atomic
  certification, promotion, supersession, or rollback."* — `nv:skills/nvidia-ontology-management/references/publication.md`
- *"FastAPI trusts the user identity the frontend forwards in the `x-auto-ontology-user-id` header, and the ingestion
  service's endpoints … have no authentication of their own."* — `nv:README.md:259-262`
- *"The Auto-Ontology team maintains the code and doesn't accept external pull requests."* — `nv:README.md`
