# Olist live run — the product used as a customer would, 2026-10-22

**The ask (the user, 2026-10-22):** take the nine Olist CSVs (Brazilian e-commerce, 2016-09 → 2018-10,
99,441 orders, 126 MB, one file of a million rows) and run them through the platform exactly as a new
customer would — upload through the UI, then data ops, agent ops and questions, everything the product
says it is for — so that the gaps between what we say we offer and what a user gets are measured on a
dataset nobody tuned for.

**Method.** Driven through the UI at `localhost:3000` (main checkout `bb9f07c2`, API `ea6b7d18` +
web-only fix) with the built-in browser. Every figure the product states is checked against ground
truth computed locally with DuckDB over the raw files (`olist_truth.json`, figures below). Model spend
on this instance was approved for the run. The API is running WITHOUT the cockpit flags and
`AUGHOR_MODEL_PRICES` (the Mac rebooted at 22:18; the restart carried no env) — findings that depend on
either are marked so.

## Ground truth (DuckDB over the raw CSVs)

| Figure | Value |
|---|---|
| Orders | 99,441 (delivered 96,478 · shipped 1,107 · canceled 625 · unavailable 609) |
| Unique customers | 96,096 (repeat buyers 3.12%) |
| Sellers · products | 3,095 · 32,951 |
| Payments total | R$ 16,008,872.12 (items R$ 13,591,643.70 + freight R$ 2,251,909.54) |
| AOV (payments per order) | R$ 160.99 |
| Peak month | 2017-11 (7,544 orders · R$ 1,194,882.80) |
| Avg review score | 4.086 (5★ 57,328 · 1★ 11,424) |
| Avg delivery (delivered) | 12.5 days · late 8.11% |
| Top category by item price | health_beauty R$ 1,258,681 · watches_gifts · bed_bath_table |
| Top state | SP 41,746 orders · RJ 12,852 · MG 11,635 |
| Payment types | credit_card 76,795 · boleto 19,784 · voucher 5,775 · debit 1,529 |
| Data quirks | 814 duplicate review_ids · 775 orders without items · 1,000,163 geolocation rows for 19,015 zip prefixes · translation file has a BOM on its first header |

## The run — step by step

(appended as it happens; each step says what a user did, what the product did, and the gap if any)

## Gaps found

(numbered; each with the promise it falls short of, the evidence, and where in the code)

## Next

Start: Integrations → add a local-files connection → upload the nine files.

### 1. A new workspace (22:40)
Top-left switcher → "+ New workspace" → name → Create. Works in two clicks. The switcher then shows
"OLIST · CONNECTIONS" as a checklist of the install's EXISTING connections ("checked connections belong
to this workspace"). There is no "add a new connection to this workspace" door here; a new customer
with their own files has nothing to tick. Saved with none ticked → "Olist · 0 connections".

### 2. Upload (22:42)
Catalog in the empty workspace says "No connections yet. Add one to get started" → Add → FILES →
"Create or modify table — upload CSV, Parquet, Excel or JSON into your Workspace" → Bulk import →
"+ Add schema" `olist` → drop nine files. **9 added → olist in ~17 s for 126 MB** (POST
`/connections/workspace/files/bulk` 201), each file a table named after its filename; the explorer
auto-started on the connection the moment the upload returned (explore_on_connect) and logged
"Complete — 43q, 29 facts, 0 insights" four seconds later.

- **Gap 1 — uploads ignore the workspace you are in.** `AddDataPanel` hard-codes
  `WORKSPACE_ID = "workspace"` (web/components/AddDataPanel.tsx:45): every upload, from any workspace,
  lands in the one shared local-files connection. The copy says "into your Workspace" while the
  reader is standing in a workspace that does not contain it.
- **Gap 2 — the panel leaks the other workspace's data.** In the empty Olist workspace the upload
  panel lists "TABLES IN WORKSPACE · 24" — the Default workspace's airline and Uber tables, each with
  a Remove button.

### 3. Making the workspace see its data (22:45)
Switcher → Manage Olist → tick "Workspace" → Save. The Olist Catalog now shows one catalog, "Workspace ·
uploaded files · 3 schemas · 33 tables": `main` (23 airline tables), `olist` (9), `uber_ncr` (1). A new
customer's workspace cannot hold only its own data, because uploads share one connection with everyone.

- **Type inference is good.** Zip prefixes stayed VARCHAR with their leading zeros ('09790'), every
  date column is TIMESTAMP, prices DOUBLE, counts BIGINT, the BOM on the translation file's header was
  stripped, and the multi-line review comments parsed (99,224 reviews, the known figure).
- **Gap 3 — the Catalog and the schema disagree on row counts.** The Catalog says "Rows — no table carries
  a row count" and "not counted" for the upload, while the same connection's schema text already states
  `(99,441 rows)` per table. Two surfaces, one fact, one of them blank.
- **Gap 4 — "Needs you" leaks across workspaces and speaks in ids.** The Olist Catalog's NEEDS YOU says
  "2 baef6c3e documents can't be searched" — baef6c3e is the Superstore DuckDB connection, not in this
  workspace, and it is named by its id.
- **Explorer on upload:** a "structure" job, 0 model calls, 43 queries, 4.7 s, then "its questions wait
  for a person to set this dataset's layer" (proposed: Business). The Catalog bar reads "54% · exploring".
- **Gap 5 (seen in passing, Luxeperience) — a dead warehouse is a 500.** The Lux Postgres (localhost:5555)
  is down after the reboot; `GET /connections/dcc63d83/schema` answers `{"error":"internal_error"}` with a
  traceback in the log ("connection refused"), and the Catalog says "how far it is explored could not be
  read · Retry" and "Tables 0 in 0 schemas". The reader is not told the database is unreachable.

### 4. The schema page and its Settings (22:47)
Catalog › Workspace › olist. Overview says "9 tables · nothing to read · Rows not counted · Last explored —
not explored yet · Structure: none · Business objects 0 of 9", every table "not read". The API's
`/exploration/workspace/datasets` says the opposite for the same schema: structure share 1.0 "structure
learned", program last_run "structure · complete" at 17:13.

- **Gap 6 — a schema page wears the connection's badge.** The Settings badge on Workspace › olist reads
  "Explored · 111 findings" — the WHOLE connection's count (the airline schema's findings), on a schema
  that has none. (The Overview's "not explored yet · Structure: none" seen at first was Gap 7's stale
  view: after a fresh load the Overview correctly said "exploring · 50% · Structure 9 of 9 · 1 dataset
  waits for its layer · Set it".)
- **Gap 7 — a failed read on one connection blanks another's Settings, silently.** Having passed through
  the Luxeperience workspace (its Postgres is down → `/exploration/dcc63d83/datasets` 503), the Catalog
  kept a null datasets view; back on Workspace › olist › Settings the "Layer and analysis" card rendered
  only its label — no layer picker, no "could not be read" line (`SchemaProgram` returns null when the
  view is null; `CatalogScope` only shows the Empty line when `view` is exactly null/undefined, and no
  datasets read was re-issued for the new connection). A full reload brought it back.
- **Gap 8 — the Catalog tree is org-wide, not workspace-wide.** In Olist (one connection) the tree lists
  Workspace, then Aughor Ops, DuckDB, BigQuery, theLook and PostgreSQL; only the header figures
  ("Catalogs 1") honour the membership. A workspace is a filter on the numbers, not on what is shown.

### 5. Setting the layer (22:49)
Settings tab: maturity bars (structure 100% learned · questions 0% "wait for its layer to be set"), a
"Layer of olist: Not set" picker with the explorer's proposal "Set as Business", and "On for analysis".
Clicked "Set as Business".
Result: `PUT /exploration/workspace/datasets/layer` 200 → "Business · Set by amitkamlapure · its questions
have started" and an exploration job started at once (`add093fa094f`, "domain_intel_only=True",
"Ontology not found before Phase 8 — building now…"). The header's LIVE counter went to "1 live".

### 6. Watching it run (22:50)
- **Gap 9 — "Now" does not show what is running now.** With one live run on the workspace's own data,
  the Now page says "Nothing waits on you" and lists slots, departures and corrections; the only trace of
  the run is the header's "1 live" (which links to Agent Ops). The schema's own Overview says "Last
  explored Thu 22 Oct · 0 new findings" with no "running" state either.
- Now's THE BRIEFING list is org-wide too (PostgreSQL, DuckDB, Aughor Ops, Workspace, theLook) inside the
  Olist workspace — Gap 8 again.
- **Gap 10 — "Agent runs" says "No runs yet" while one is live.** The header says "1 live"; the rail's
  Agent runs page in the same workspace says "No runs yet · Ask a question". The explorer's run (10 model
  calls, 20 queries at that moment) is not a run to this page.
- Meanwhile in the log: the ontology was built for olist in ~60 s (cardinality measured, 4 relationships
  relabelled, bindings proposed Customers→Orders→Order items…), then Phase 8 "17 baseline cells".
- **Gap 11 — the Ontology page opens on the wrong schema.** From the Olist workspace, Ontology lands on
  schema `main` (the airline data): "No ontology built for schema 'main'. Built for: olist, uber_ncr ·
  Build the ontology for main". The schema a user just set up is one picker away, unannounced.

### 7. The ontology the explorer built (22:52)
Ontology › schema olist (after switching the picker from `main`): **9 entities, 9 links, 0 processes, 0 rules,
no release yet, reads 9 of 9 tables.** Names are right — Customer, Customer Order, Order Line, Order Payment,
Order Review, Product, Product Category, Seller, Geolocation — with row counts, and it states its own doubts:
Order Line / Order Payment / Order Review / Geolocation "key not unique" (Order Line: order_id 98,666 distinct
over 112,650 rows), each with a NEEDS YOU "How is one order line named? Proposed: order_id · not checked yet ·
Check · Change". Links: paid through N:N, reviewed in N:N, belongs to N:1, is for N:1, sold by N:1.

**Follow-up named by the user here (not urgent):** rename internal names such as "Phase 8",
"domain_intel_only", "manifest-driven", "baseline cells" to words that say what the platform is doing, for the
user and for the developer. Listed as PENDING item 53.

### 8. "Draft the business" meets the approval gate (22:54)
Clicking the EXPLORER DRAFT's "Draft the business" (one model call, proposes processes/rules/sets) returned
`POST /ontology/explore … 428 Precondition Required` and a modal: "Approval required · HIGH-RISK ACTION — Edit
the ontology / semantic layer on workspace needs approval before it can run. Approving allowlists this action
for this scope; every attempt is recorded in Security & Audit." Approved for the scope (the whole `workspace`
connection — the scope is the connection, not the olist schema a user is drafting).
- Observation: the gate is right to exist, but a first-time user drafting their own brand-new schema is told
  their click is "high-risk" and must self-approve; the scope they approve is wider than what they asked for.
Result of the draft (one model call, ~20 s): **9 proposed · 0 confirmed · 1 refused** — 1 process "Order
fulfilment · olist_orders_dataset · 4 stages", 1 rule "Open orders · admits 1,729", a tenth link, 3 proposals
on Customer Order. Checked against the raw files: the open-order count 1,729 = shipped 1,107 + invoiced 314 +
processing 301 + created 5 + approved 2 — exactly the non-terminal statuses, with canceled and unavailable
left out. A correct business rule, measured before it landed.
Review of the nine: three "is a part of Customer Order" (lines, payments, review), Product categorised_as
Product Category on product_category_name, Customer places Order, Order Line contains_product Product,
Order Line sold_by Seller, the process purchased → approved → handed_to_carrier → delivered, and the rule
open_orders (status not in delivered/canceled/unavailable). All nine are right for this dataset.
- **Gap 12 — a repairable proposal is refused in validator-speak.** The tenth, `delivered_orders:
  order_status = ['delivered']`, was refused with "rule delivered_orders: filter 'order_status =' needs one
  value (is_null / not_null for NULL, in for a list)". The model wrote a one-element list for `=`; the door
  could have read it as `in` or as the scalar, or asked. Instead the most useful rule of all (delivered
  orders, 96,478 of them) is gone and the reader gets a parser's sentence.

### 9. Confirming the draft (22:56)
No "Confirm 9" the accessibility tree could name, so nine single Confirms. The map re-read itself: "6 types ·
3 parts" (Order Line, Order Payment, Order Review as parts of Customer Order), 1 process, 1 rule, "0 proposed ·
9 confirmed · 1 refused". The header's LIVE chip now says "exploring · 1 live".

Meanwhile the explorer's baseline pass (21 model calls, 62 queries, 114k tokens by 22:54) is self-policing:
it skipped a GMV headline for "SQL grain bug: SUM(oi.price) over a …" (grain-confused ratio), kept "overall
average order value including freight" and "on-time delivery rate", and DROPPED "Average Review Score:headline —
one value, two labels: 4.09 is asserted as both …". The guard is right that one number should not carry two
labels, but the cost is that the dataset's most-asked KPI (average review score 4.09, correct) has no finding.
Worth checking later whether it comes back under one label.

### 10. Fixing Order Line's key (22:58)
NEEDS YOU › "How is one order line named? · Change" opens the Properties tab: "KEY measured over 112,650 rows ·
order_id · not unique per row", "NAMED BY proposed from the profile · order_id · not yet measured", and a
"Declare [column ▾] · Measure" door. The picker offers ONE column.
- **Gap 13 — a key is one column.** Three of this dataset's nine tables are keyed by a pair — order lines by
  (order_id, order_item_id), payments by (order_id, payment_sequential), reviews by (review_id, order_id)
  because 814 review_ids repeat — and the door cannot say so. The ontology will carry "key not unique" on all
  three parts forever, and every count over them stays a warning.
- The explorer's grain guard kept firing on the review questions ("COUNT(*) over a chasm join",
  "grain-confused ratio") — right each time, but the simple AVG(review_score) never got written.

### 11. The business profile (23:00)
Profile tab: "Brazilian Multi-Category E-commerce Marketplace (Olist) · ✓ held · 97% · inferred 2m ago" with a
correct paragraph (small sellers, order lifecycle, installments, delivery vs estimate, review scores; levers
GMV, delivery reliability, satisfaction, repeat purchase, freight cost) and a "why" naming the tables. Status
column found (order_status, 6 values, "no order claimed"); blanks named (review title/message = a data-quality
gap). This is the product at its best.
- **Gap 14 — the inferred currency loses to the org default, silently.** "Currency: USD · org setting ·
  inferred BRL". The profile knew it was Brazil; the Olist workspace has no currency of its own, so every
  figure will read in dollars. No door here to adopt the inference for this workspace.
- **Gap 15 — "Governed metrics · 5" on the olist profile are other schemas' metrics** (Ride Completion Rate,
  ABV, VTAT from uber_ncr; Average Order Value from main.sales_transactions). Connection-scoped on a
  schema-scoped page.
- **Gap 16 — "No table profile yet — tables are profiled when the connection is first read, and after its
  schema changes."** The schema changed by nine tables 18 minutes earlier; the profile did not follow.

### 12. Key Questions — four findings, checked (23:02)
Profile › Key Questions: "4 findings · 0 angles · explored 0%", three mid-novelty, one low.
1. Category satisfaction vs GMV: office_furniture 3.62 on ~$273.6K, bed_bath_table 3.97 on ~$1.04M,
   watches_gifts 4.07 on ~$1.20M, computers_accessories 4.03, furniture_decor 4.01, telephony 4.00 — every
   figure matches DuckDB over the raw files (3.62 / 273,961 · 3.97 / 1,036,989 · 4.07 / 1,205,006 · 4.03 ·
   4.01 · 4.00). **But "watches_gifts leads GMV" is false: health_beauty leads at R$1,258,681 with a 4.18
   score and is absent from "the list".** The finding never shows the list it ranks.
2. Late delivery cuts review scores by ~2 points per state × freight band — consistent with the raw data
   (on time 4.29 vs late 2.57 over 96,359 delivered-and-reviewed orders); it even names the cells too
   small to read (AC, AM, AP).
3. Repeat purchase by first-order category (home_appliances 9.0%, bed_bath_table 4.5%…) — plausible, not
   re-checked.
4. "The first 20 rows cover only Sept–Oct 2016, so they can't show a growth trend" — a row-capped query
   produced a non-answer that was still published as a finding.
- **Gap 17 — findings rank over a list they do not show, and state figures in "$" for a BRL business.**
  (The currency is Gap 14's consequence; the missing leader is a correctness defect a reader cannot see.)
- **Gap 17b — a finding that says it cannot answer is still a finding** (the 20-row growth one).

### 13. The Briefing (23:03)
Briefing tab, Day: "This edition hasn't been written yet — Nothing to brief on for 2026-10-20 (Tuesday) —
Gross Merchandise Value: no approved definition; approve one in the Semantic Layer to measure it; Average
Order Value: no approved definition; … (×8)". "In brief: No finding could be measured for 2026-10-20. All 13
are about all history: 6 — its data has no rows in this range or the previous one · 6 — its statement names
none of the rows its query returns · 1 for other reasons."
- **Gap 18 — the Briefing anchors to today, not to the data's last day.** Olist ends 2018-10-17; Day, Week,
  Month, Year and both to-date editions can only ever be empty. The page knows the data's range (the
  explorer logged "2016-01-01→2020-01-01") and does not use it, nor say "your data ends in 2018".
- **Gap 19 — the lead repeats one sentence eight times.** "no approved definition; approve one in the
  Semantic Layer to measure it" per metric, instead of "8 metrics are proposed and none approved yet".

### 14. The Semantic Layer (23:05)
"Workspace › All schemas": Approved 3 (all uber_ncr), Waiting for review 2 (uber_ncr, main), Suggested 16 of
which **8 are olist, all "suggested · explorer", undated**: Gross Merchandise Value (item price) BRL, Average
Order Value (price + freight) BRL, On-Time Delivery Rate, Average Review Score, Repeat Customer Rate, Freight
Share of Order Value, Order Cancellation / Unavailable Rate, Credit Card Share of Payment Value. The right
eight for this business, in BRL (the Semantic Layer kept the inferred currency the Profile lost).
- NEEDS YOU names 2 uber_ncr metrics waiting for review and "2 industry metrics are not bound: cart,
  order_item (retail package)" — inside the Olist workspace, the needs-you list is the whole connection's.
- The exploration job `add093fa094f` ended **CANCELLED** at 22:56:52 ("Cancelled, progress saved") after
  506 s, 40 model calls, 72 queries, 202k tokens, during Phase 9 synthesis. No one pressed cancel. See the
  next step for the cause.
- **Gap 20 — a budget stop is reported as a cancel.** The log says "job add093fa094f exceeded token budget
  (200,000 tokens) in-context — cancelling (agent scout)". The job record says `state: CANCELLED`, the same
  word a person's Stop gets. Twelve minutes earlier the explorer had written "budget 83% spent — reserving
  the rest for synthesis" and still overran during Phase 9. A new dataset's first exploration ends on a
  budget it never shows the user, and nothing on screen says "stopped at its budget; N findings saved".

### 15. Adopting a suggested metric (23:07)
A suggested metric has no Approve: its doors are "Customise for this connection — a copy for olist of this
connection, as a draft; the original is untouched" and "Remove". Customise made "Drafts 1 · Gross
Merchandise Value (item price) · BRL · olist · draft · dated by olist_order_items_dataset.shipping_limit_date ·
month" and opened the full editor inline (Overview · Approval · Dates · Measures · Edit, with name, label,
SQL, unit, dimensions, filters, caveats, additivity, health scorecard, ownership, freshness, lineage,
anti-patterns, quality tests).
- **Gap 21 — the draft dated itself by the wrong column.** GMV got `shipping_limit_date` (the first
  timestamp of the first table in its SQL) instead of the order's purchase date; a user who approves without
  opening Dates gets monthly GMV by shipping deadline. The explorer's own SQL names the orders table, whose
  `order_purchase_timestamp` is the business date.
- **Gap 22 — eight metrics, eight times this.** Adopting the explorer's own suggestions is Customise → Dates →
  Approval per metric; nothing adopts a set.

Ground truth for the eight (DuckDB over the raw files, the metrics' own definitions): GMV not canceled /
unavailable R$ 13,494,400.74 (2018-08: R$ 848,860.10) · AOV price+freight per order R$ 160.24 · on-time
delivery 91.89% · average review 4.086 · repeat customers 3.12% · freight share 14.21% · cancel/unavailable
1.24% · credit-card share of payment value 78.34%.

### 16. Dates, then propose, then approve (23:09)
Dates tab: "set automatically · by month · Flow — a row counts on the day of
olist_order_items_dataset.shipping_limit_date … shipping_limit_date is the main date of olist_order_items_dataset
— the one the platform reads to learn when the table's numbers settle · Confirm · Correct…". Correct… offers
"6 dates on order_items, orders — choose one"; chose olist_orders_dataset.order_purchase_timestamp → "confirmed
by you · by month · set by amitkamlapure in the metric editor" (PUT /metrics/gross_merchandise_value_item_price
200). Approval tab: "BEFORE YOU DECIDE — What it changes: not applicable (first approval) · Whether it runs:
the definition executes and currently reads … · What it declares · What could be compared: not applicable ·
Population fingerprint" and a single door: **Propose**. So the adoption path is Customise → Dates (Correct) →
Propose → Approve: four decisions per metric, eight metrics.
- **Gap 23 — a money figure in scientific notation.** "Whether it runs · clean · The definition executes and
  currently reads 1.34944e+07." The value is right (R$ 13,494,400.74 in DuckDB) and unreadable; the row's own
  unit (BRL) is not applied where the decision is taken.
- **Gap 24 — Approve asks for approval.** Clicking Approve on the proposed GMV returned 428 and a second
  HIGH-RISK modal: "Publish a governed metric on gross_merchandise_value_item_price needs approval before it
  can run. Approving allowlists this action for this scope". The scope is the single metric, so adopting the
  explorer's eight suggestions means eight self-granted allowlists by the same person who is approving. For
  a one-person install the gate is a ninth click per metric; for a team it is the right place for a second
  pair of eyes, but the copy never says which.
Approved: "Gross Merchandise Value (item price) · BRL · olist · ✓ measured · order_purchase_timestamp · month ·
approved v1 · approved by you · today". Approved and measured 3 → 4. The remaining seven stay suggested for now
(the path is known; the questions matter more for this run).

### 17. A canvas for Olist (23:12)
Data Canvas in the Olist workspace lists "Airline And Sales Operations · Workspace · 24 tables" (the Default
workspace's canvas on the shared connection) — Gap 8's shape again. "+ New" → "Connect your data: pick a
connection, scope it to the tables that matter, and start asking questions — we'll name it for you" → Workspace
→ 33 tables with "All tables (auto-includes new tables)" ticked by default. No schema-level tick: scoping to
olist is untick-all, search "olist", tick nine. The chips under "Selected" read "olist.olist_geoloca… ×
olist.olist_order_i… × +5 more".
- **Gap 25 — scoping a canvas has no schema level**, on a connection whose schemas are three unrelated
  customers' worth of data; the search box is the only way to find nine tables among 33.

### 18. First question (23:14) — "How much revenue did we collect in payments in 2018, month by month?"
Typed into the new canvas's composer and sent. It ran as **Agent · "investigating, as you asked"** with a
thinking row "Analyzing adhoc_3…".
- **Gap 26 — the default mode on a fresh canvas is Agent, and the copy says the reader asked for it.** A
  month-by-month lookup — the plainest quick question there is — became a deep analysis (the ~100-call
  kind) because the composer's default was the deep one, and the answer header claims "as you asked".
- "adhoc_3" is an internal step name in the reader's face (the user's rename item, PENDING 53).
Ground truth for the answer: 2018 payments by month — Jan 1,115,004.18 · Feb 992,463.34 · Mar 1,159,652.12 ·
Apr 1,160,785.48 · May 1,153,982.15 · Jun 1,023,880.50 · Jul 1,066,540.75 · Aug 1,022,425.32 · Sep 4,439.54 ·
Oct 589.67 · total 8,699,763.05.
**Answer (23.2 s, 3 steps):** "We collected 8,699,763.05 in payments from 1 January to 17 October 2018 · 54,011
orders" + a month table + prose that explains it summed payments per order first after its own
double-counting flag, and that September (16 orders) and October (4) are a data gap, not a collapse. **Every
figure matches the raw files to the cent** (total 8,699,763.05; all ten months). It also says what it withheld
("Some figures … could not be traced to the query results, so the sentence stating them was withheld").
- **Gap 27 — "month by month" came back sorted by value** (March, April, May, January, July…), with no
  currency on any figure.
- **Gap 28 — a "+1475261.3% MoM" badge** on the revenue chart: an impossible delta (the total against
  October's 589.67, or similar), shown as if it were a reading.
- **Gap 29 — chart titles are SQL aliases:** "Rev by m — 1 Jan – 17 Oct 2018", "Rev, orders and pay rows by
  m, mn and mx", "Rev and orders by m". The y-axis runs to 8.0M for monthly values that never exceed 1.2M.
- The footer of this Agent answer shows "Why this number → · Regenerate" and no thumbs at all (the
  control needs a receipt id, which this run did not carry) — checked next on a Quick answer.

### 19. Second question (23:07, Quick) — "Which 10 product categories had the highest revenue, and what was the average review score for each?"
Answered as "Quick answer · answering directly, as you asked · 2 steps taken" with a table (Cat · Revenue ·
Orders · Avg Review · Reviewed Orders, Copy + CSV, "Σ Totals off") and its sources. **All ten rows match the raw
files: health_beauty 1,258,681.34 / 4.18 · watches_gifts 1,205,005.68 / 4.07 · bed_bath_table 1,036,988.68 /
3.97 · sports_leisure 988,048.97 / 4.17 · computers_accessories 911,954.32 / 4.03 · furniture_decor 729,762.49 /
4.01 · cool_stuff 635,290.85 / 4.17 · housewares 632,248.66 / 4.14 · auto 592,720.11 / 4.09 · garden_tools
485,256.46 / 4.14.** Revenue is shown as "$1,258,681.34" — Brazilian reais in dollars (Gap 14).
- **Gap 30 — History is blind to the canvas's own runs.** The canvas's History tab ("this canvas · finished
  runs") says "Nothing asked on this canvas yet" while `/investigations` holds run 858b1b26, status
  complete, canvas_id dd30a7d4, the first question's text.
- **Gap 31 — Enter emptied the composer and no question was asked.** Typing the question and pressing
  Return cleared the box; the API log shows no `/ask`; nothing appeared on screen, nothing in History. The
  same text through the composer's Send button worked. Seen once; needs a retest before it is called a
  defect (done below with the third question).
- **The feedback fix, live:** the finished Quick answer's foot reads "Methodology & details › · Export ▾ ·
  👍 👎 · Why this number → · ↺ Regenerate" — one thumbs pair (the accessibility tree holds exactly one
  "Helpful" and one "Not helpful" button), where the morning's screenshot had two.
- **Gap 32 — the answer states every figure twice.** The prose lists all ten categories with revenue and
  score ("health_beauty: 1,258,681 revenue, 4.18 average review …"), then the table below repeats the same
  ten rows. The user's rule (2026-10-02): nothing below an answer repeats a figure it states.

### 20. Third question (23:11, Quick, sent with Enter) — late delivery by state
"What share of delivered orders arrived after the estimated date, by customer state? Show the worst five
states with at least 500 orders." → 1 step: MA 19.67% (141 of 717) · CE 15.32% (196 of 1,279) · BA 14.04%
(457 of 3,256) · RJ 13.47% (1,664 of 12,350) · PA 12.37% (117 of 946), a bar chart, its definition ("status
delivered, both dates recorded"), and a scale note (RJ's 1,664 late orders exceed the other four combined).
**Matches DuckDB** (MA 19.67 · CE 15.32 · BA 14.04 · RJ 13.47 · PA 12.37; RJ 12,350 vs 12,353 is the
status filter, stated). Enter sent it this time → Gap 31 stays "seen once, not reproduced".

### 21. Fourth question (23:13, Agent) — "What drives low review scores, and what should we fix first?"
Sent in Agent mode; "Classifying question…" then the run. Read in step 23.

### 22. Home, after an hour (23:14)
Home in the Olist workspace: "ONE THING TO KNOW — No daily run has reported a move here yet" · "NEEDS YOU ·
A FINDING TO ACT ON · Thu 22 Oct: Late delivery does not explain office_furniture's weak reviews. Its late
rate is 0.0646, only slightly above the other categories (0.0501–0.0591). When late, it scores 1.969 …
The gap shows up among on-time orders: office_furniture averages 3.75 against 4.139–4.276 … driven mainly by a
product or experience problem … Fixing logistics would help only marginally." with Decide · Check again · Not
worth it. This is the promise kept: the exploration's synthesis reached the front door with a decision
attached, and the reasoning is sound (office_furniture 3.62–3.64 overall in the raw data).
- Figures in the finding are raw ratios ("late rate 0.0646") where a reader expects "6.5%".

### 23. The operations pages (23:16, second tab)
- **SQL Editor** (`?tab=query`): "Configure your query in the panel, then Run or press ⌘↵" — a builder panel;
  tried below.
- **Monitors:** "No monitors yet — A monitor alerts you when a metric crosses a line, drifts, or goes stale ·
  Create first monitor". Tried below.
- **Agent Ops › Overview (Workspace, 24h):** Runs 8 · typical 7.2 s · slow 8 min · Failed 0 · Running now 1 ·
  9 of 10 agents on, Curator paused · **"Model spend · at least $0.02 · 2% of calls priced · 436.6K tokens · 82
  calls · 2% fell back"** · agents with token totals (Explorer 202.5K · Analyst 234.1K · The Look Analyst 1
  failed, 1 unmetered) · tokens by model (claude-sonnet-5-5 484.6K over 76 calls, haiku 50.0K with 25%
  failed, deepseek 23.6K) · by role · by where in the code · DEEP RUNS listing both Olist questions with
  Open, the running one with Kill.
- **Gap 33 — the install is unpriced and only this page says so, in small print.** "2% of calls priced" is the
  consequence of the API restart without `AUGHOR_MODEL_PRICES` (section 0). Spend of a whole dataset's
  exploration reads "$0.02". A reader of Home, Now or the Briefing never learns it.
- **Gap 34 — three surfaces, three answers to "what ran?"** Agent Ops lists both deep runs; the rail's Agent
  runs page said "No runs yet" during the exploration; the canvas History says "Nothing asked on this canvas
  yet" after two finished runs on it.
- Nit: "claude-haiku-5-5 · 4 calls · 25% failed" and "2% fell back" are stated with no door to the failure.

### 24. A monitor (23:19)
Monitors › Create first monitor: name · metric "From catalog" (a picker of every metric on the connection,
suggested ones included) or Custom SQL · condition (Threshold, Anomaly, Trend reversal, Segment drift, Data
freshness, Any change) · warning/critical · direction · schedule (cron shown: `0 9 * * *`) · grace hours ·
notification (In-app, Slack, Email). Created "Monthly GMV floor · Threshold · below 900K, critical below 800K ·
daily · in-app · Gross Merchandise Value (item price)" (POST /monitors 201). The Overview then says "Proven to
fire 0 of 1 · none delivered end to end" and NEEDS YOU "1 monitor has never been proven to fire — Checking
feeds each rule a made-up outlier; no query runs and nothing is sent · Check its rule". Good door.
- Overview figures in the Olist workspace: "Open alerts 0 · 5 acknowledged · last 24 Aug", "ALERTS · LAST 12
  WEEKS · 4 alerts" — other connections' alerts, the workspace filter again (Gap 8's shape).
- The form never says WHICH value a threshold reads for a monthly metric (the latest month? the whole
  history?). For a dataset whose last month holds four orders, that decides whether it fires at once.

### 25. The deep answer (23:20) — "What drives low review scores, and what should we fix first?"
2m 35s, 6 steps. Headline: "Low scores concentrate in late and never-delivered orders, not in a recent trend".
Body: 14.7% of 99,224 reviews score ≤2; >7 days late → 78.3% low (2,563 of 3,272) vs 9.2% on time; 0–7 days
late 36.1%; canceled/unavailable/invoiced/processing/shipped 69.3%–92.6% low; on-time multi-seller orders
average 2.77–3.03 with 42.7–48.7% low vs 4.33–4.37 and 7.2–7.7% for single-item single-seller; "associations
in observational data; the design cannot establish causation". Bottom line + five recommended actions
(late deliveries first; stuck statuses; 39 sellers with ≥25% low share = 1,298 of 13,250 low reviews; multi-
seller fulfilment; pull review text and carrier logs before spending).
**Checked:** 14.7% ✓ exact · on-time 9.2% = 8,186 / 88,653 ✓ exact · status shares shipped 69.3 / canceled
76.5 / invoiced 81.8 / unavailable 84.8 / processing 92.6 ✓ all exact · multi-seller on-time avg 2.87, 47.0%
low in DuckDB (inside the report's ranges) · single-item 4.36 / 7.5% ✓. The lateness buckets differ only by
boundary (DuckDB: >7 d 79.2% of 2,797, 0–7 d 39.7% of 4,903; same 7,700 late in total).
- **Gap 35 — a third of the report refutes a claim nobody made.** Two exhibits and ~300 words argue that
  "the headline 'decline' is a volume effect rather than a quality deterioration" (weekly average of LOW
  scores 1.24 → 1.21, "Within noise · z = −1.9", "+3.0% WoW"), with a chart whose y-axis is 0–1.4 titled
  "late vs on-time delivery · average review score". The question asked what drives low scores; the agent
  tested a trend hypothesis of its own and published the refutation at full length.
- Gap 29 again: exhibit titles "Avg s and low by mn and mx", "Avg s and low by grp", "Records by k where
  order status = delivered".
"Run now" (POST /monitors/{id}/trigger 200) → the row says "No condition met".
- **Gap 36 — a monitor's reading is never shown.** The metric is monthly; its last full month (Aug 2018) is
  R$ 848,860, below the 900K warning line, and the two months after it hold 20 orders — yet "No condition
  met". The record exposes no run history (`/runs`, `/history` 404) and the proof endpoint only says "never
  proven — no drill". Whether the threshold read the all-time total (R$ 13.49M) or something else is not
  knowable from the product.

### 26. Record, Documents, Spend (23:22)
- **Record › Inquiries:** "What drives low review scores…" waiting · 1 run · next check Sat 24 Oct · 7 still
  open; "How much revenue…" closed as answered · 1 run. The ledger works per question. Nit: "7 still open —
  none says what settles it" is a count with no door.
- **Documents:** 10 (2 uploaded · 8 compiled from your schemas · last added 22 Oct · Workspace · olist) — the
  olist schema documents were compiled on upload. NEEDS YOU "the index and this list disagree on 2
  documents" (pre-existing, another connection).
- **Spend:** "Spent · at least $0.91 · 14% of calls priced · 1,734 calls have no price, so the real spend is
  unknown · Spend cap: None · nothing stops a runaway run · Set a cap". Honest, and the only page that is.
  Governance feed (last 50 min, 500 events): "Budget exceeded · job cancelled for scout: token budget
  (200,000 tokens)" (so Gap 20's stop IS said — here), "Metric enforcement · governed formula improvised —
  drift on revenue · 7", approvals granted 19, query checks 383.
- **Gap 37 — metric drift is reported to Spend, not to the answer that drifted.** Seven "governed formula
  improvised — drift on revenue" events: the quick answers computed "revenue" their own way (payments; item
  price without the status filter) while the governed GMV says otherwise, and the reader of those answers
  was never told. The governance feed is the wrong reader.

### 27. Security & Audit, Health, Evals (23:24)
- **Security & Audit › Queries (Workspace):** 51.1K checked · 3 blocked · 1.2K flagged · 14.6K values masked;
  NEEDS YOU "2 flagged queries from people or agents · profile-finding-sql · Review"; who ran them (Briefer,
  Scout, Automations, ontology validate); limits (10,000 rows · warns 15 s · stops 60 s). Two of the
  platform's own Olist queries failed and are shown with their errors: "Briefer · metric move check ·
  Binder Error: Referenced column 'freight_share' not found" (22 Oct 22:56) and a period comparison against a
  schema that no longer exists. The audit is the most complete surface in the product.
- **Health:** "No metric has a target yet, so nothing is scored · Set a target · Semantic Layer › a metric ›
  Edit" — right, and a door.
- **Evals:** 10 suites, 173 cases, org-level; "a run replays SQL · no model calls". Nothing of Olist's yet;
  the "from a real answer" suite shape exists.

### 28. Inbox and Notifications (23:25)
- **Inbox:** "Open 5 · from 1 deep analysis" — the five recommended actions of the review-score analysis, each
  with its source finding, "Execute →" and "Mark"; a lifecycle (Proposed → Accepted → Implemented → Verified)
  and "Who they are for · no owner named · 5". The closed loop from question to tracked action exists and
  was fed by the run. Nit: every recommendation says "no owner named" and nothing proposes one.
- **Notifications:** Triggers 0 · Delivered 0 of latest 50 · Failed 50 "all from 2 triggers since removed"
  (DS-7 blackhole, slack-ops). A new customer's first look at Notifications is 50 failures that are not
  theirs — Gap 8's shape at the org level.

### 29. The Briefing on a month the data has (23:27)
Briefing › Custom › 2018-08-01 to 2018-08-31 › Show. The page started writing the edition by itself
("Writing this edition… · Measuring this edition…", a narrator model call on a click that only said "Show")
and placed four findings under "In brief — measured for this range": the office_furniture finding, "Freight
accounts for 0.142134 of total order value … roughly 14.2 cents of every currency unit", "average order value
(price plus freight) is 160.578 BRL", and the late-delivery penalty. DuckDB: freight share 0.1421 ✓; AOV
price+freight per distinct order 160.58 over all orders ✓ (160.24 without canceled/unavailable). "Gaps · Still
open: What drives low review scores… parked until 2026-10-24" — the open inquiry rides along ✓.
- The range radios are labelled "The newest day whose numbers have settled", "The last complete month whose
  numbers have settled" — and still resolved to October 2026, not to the data's settled days in 2018. Gap 18
  in the copy's own words.
- "0.142134 of total order value" and "every currency unit": a raw ratio and a currency the platform knows
  (BRL) but will not say (Gap 14).
Written edition (≈40 s later): **"August GMV Dips 3% Against July — Gross merchandise value for 2018-08-01 to
2018-08-31 fell 3%, to BRL 848,860 from BRL 878,044 in the 31 days before. … The only finding recorded for
this range is the GMV movement … Average order value, delivery timeliness, review scores, repeat customers,
freight share and cancellations were not measured for this range"** (they are not approved — true, and said).
"The range in numbers": GMV BRL 848,860 −3%, the other seven "not measured". The currency is BRL here, from
the metric's own unit. GMV August matches DuckDB to the real (848,860.10); July checked below.
- **Gap 38 — boilerplate that is false for the range shown.** "The range ends 2 days before today
  (2026-10-22) because the platform measures a 2-day settling lag while late rows arrive" and "Attention
  should go first to confirming the August figure once the settling window closes" — on a range the reader
  typed, ending 2018-08-31, eight years settled. The narrator's lag sentence is unconditional.
July 2018 GMV in DuckDB: 878,044.27 — the Briefing's "from BRL 878,044" ✓, "−3%" ✓.

### 30. A custom agent (23:29)
Agent Ops › "+ Create agent" → a six-step wizard: 1 Describe (connection + plain words: "name the decisions it
should support, not the tables"), 2 Start (pack or scratch), 3 Scope, 4 Define (stance), 5 Prove ("how you'll
know it works"), 6 Reach (optional). Described an Olist logistics agent (on-time delivery by state and month,
late deliveries vs review scores, late sellers and categories, "always say which month the data ends in") and
pressed "Draft it" (one model call).
Drafted in ~15 s: **"Olist Delivery Performance"** — "Why this scope: olist.olist_orders_dataset (purchase,
delivered and estimated dates, status); customers (state); reviews (score); order items (links to sellers and
products); sellers; products with product_category_name_translation. Nothing outside the olist schema is
needed." Scope "olist · 0 documents · 0 packs". The stance defines "late", counts only delivered orders with a
date and says how many were excluded, assigns months by purchase date, reports by the customer's state,
reports counts next to rates, flags small samples, warns about multi-seller double counting and repeated
reviews, calls the review effect an association, uses English category names, refuses revenue/pricing/
segmentation questions and will not guess at carriers or weather. Six "questions worth being right about",
the first two of which name the data's last month. This is the product's promise met in one call: the
scope landed on the right schema when every other surface struggled to.

### 31. SQL Editor (23:30)
`?tab=query`: a workbench with Visual and SQL modes, a schema tree (Workspace › main · olist · uber_ncr), a
"(all schemas)" resolver, guards ("Guards clean"), saved queries, tabs, a history rail. `SELECT order_status,
COUNT(*) … GROUP BY 1 ORDER BY 2 DESC` → 8 rows in 7 ms: delivered 96,478 · shipped 1,107 · canceled 625 ·
unavailable 609 · invoiced 314 · processing 301 · created 5 · approved 2 — identical to the raw files — with
"receipt · Copy · CSV · Transpose · Columns · Find" on the result. The user's table rules (Copy + CSV) hold.
- The history rail lists a `DROP SCHEMA reorm_single CASCADE` run among "recent runs" with no sign of who or
  when beyond a relative time — worth a look at how it got through the guards (not Olist's).
"Use this draft" → step 3 Scope prefilled: Name "Olist Delivery Performance", Connection Workspace, Schema
olist ("picked from this connection's real catalogue"), "In scope: 9 tables". "What it is for" (the one line
other agents read when routing) was left empty by the draft — filled by hand.
Define step: the stance as drafted, plus Documents — a list of EVERY document in the org (Lux, Superstore,
theLook, the airline schemas…) with "Attaching none is not neutral: an agent with no documents sees NO
documents at all — fewer than asking with no agent" — ticked "Schema documentation — workspace/olist · 9
chunks" — and Packs (Retail and e-commerce, Logistics… "inert until active AND pinned"). Prove step: the six
drafted questions each wait for reference SQL ("a suite the model writes for itself measures nothing");
certified the sixth with `SELECT COUNT(*) … WHERE order_status <> 'delivered' OR order_delivered_customer_date
IS NULL` (DuckDB: 2,971) → "ground truth". Create agent → Reach (optional Slack door) → "Skip — the agent is
already created". Honest copy throughout; the whole wizard took about four minutes.
- Nit: the document picker is org-wide (Gap 8's shape); the olist schema documentation was not pre-attached
  although the scope is the olist schema.

## Gaps found — the list, grouped

**A. One connection, one workspace, one upload bucket (the structural one).** Gaps 1, 2, 3, 8, 15, 25, 34 and
every "org-wide" nit. A new customer's files land in the shared `workspace` connection whatever workspace they
stand in (`AddDataPanel` hard-codes it); a workspace is a filter on the numbers, not on what is shown (Catalog
tree, Now's briefing list, Needs-you items by connection id, metrics on a schema's profile, documents in the
agent wizard, alerts and failed notifications on Monitors and Notifications); scoping a canvas has no schema
level. This is the gap a second customer would hit on day one.

**B. The product does not know when its own data ends.** Gaps 18, 38 (and 9 in spirit). The Briefing's
Day/Week/Month/Year editions anchor to today and are empty forever on a 2016–2018 dataset; the narrator's
settling-lag boilerplate runs on a 2018 range; the explorer logs the data's range and nothing reads it.

**C. Money without a currency, numbers without a unit.** Gaps 14, 17, 23 and the "$" / "0.142134" / "late rate
0.0646" readings. The Profile inferred BRL at 97% and the org default USD won silently; quick answers print
"$1,258,681.34" for reais; the approval panel prints 1.34944e+07; findings print raw ratios.

**D. Adopting what the explorer proposes costs too many clicks and two self-approvals.** Gaps 12, 21, 22, 24
(and 13 for keys). Customise → correct the auto-picked date → Propose → Approve → approve the approval, per
metric; a one-element list refuses a correct rule; a composite key cannot be declared.

**E. What ran, what it cost, what it read — said in the wrong place or not at all.** Gaps 9, 10, 20, 30, 33,
36, 37. Now ignores the live run; Agent runs says "No runs yet"; History says "Nothing asked"; a budget stop is
"Cancelled"; the monitor's reading is invisible; metric drift goes to Spend's governance feed; the unpriced
install is a footnote on Agent Ops.

**F. Answer presentation.** Gaps 27, 28, 29, 32, 35. Month tables sorted by value; a "+1475261.3% MoM" badge;
SQL aliases as chart titles; every figure said twice; a deep report that refutes a claim nobody made.

**G. Defects proper.** Gap 5 (dead warehouse = 500 + "could not be read"), Gap 7 (a failed datasets read on
one connection blanks another's Settings), Gap 11 (Ontology opens on the wrong schema), Gap 16 (no table
profile after a schema change), Gap 26 (a fresh canvas defaults to Agent and says "as you asked"), Gap 31
(seen once), Gap 19 (one sentence eight times).

**What held.** Upload (126 MB in 17 s, right types, BOM and multi-line fields handled); the business profile
(97%, the right levers); the ontology's names and its self-doubt; the explorer's rule "open orders admits
1,729" exact; every checked figure in five answers and the Briefing exact to the cent or the real; the audit;
Record, Inbox and the closed loop; the agent wizard's draft, scope and honesty about proof.

## Next

1. Decide A: either uploads create a connection per workspace, or a workspace scopes by schema everywhere a
   page says "Workspace". **Done 2026-10-23 (#623):** an uploads connection per workspace; Catalog, Now's
   Briefing fold, Needs-you docs and profile metrics scoped. Still org-wide: agent-wizard documents,
   Monitors' and Notifications' lists.
2. Teach the Briefing (and Now) the data's last settled day (B). **Built 2026-10-23** on the user's decision
   (mockup `design-mockups/briefing-data-ended.html`): data whose newest row is more than a month old has
   ENDED; every edition reads as if today were the day after its last row (Olist: 17 Oct 2018), is final,
   says so in one line, and lists where each edition landed; a comparison whose earlier range starts before
   the data does is withheld and says why; nothing is predicted after the end; a scheduled send pauses
   while the edge does not move; Now names the days and the end.
3. A workspace currency that adopts the Profile's inference; one number formatter for money and ratios (C).
   **Built 2026-10-23**, per DATASET on the user's choice (one connection held Olist in BRL and `main` in EUR):
   the profile's currency is a suggestion; a person confirms it on the Profile page; only a confirmed currency
   labels a figure, server and web, and an unconfirmed one prints plain amounts and says so. Percentages carry
   one decimal; findings are asked to write ratios as percentages; the definition check reads 13,494,400.74,
   not 1.34944e+07. Olist confirmed BRL live.
4. "Adopt the explorer's eight" as one door with the right dates (D); composite keys (Gap 13).
5. One answer to "what ran" across Now, Agent runs, History, Agent Ops; a monitor shows what it read (E).
6. The user's own item: rename "Phase 8"-style names (PENDING 53). **Done 2026-10-23 (#623).**
Not done in this run: the other seven Olist metrics, Health targets, a document upload, Slack reach, the
Default workspace's `data/metrics.json` drift from this run.

### 32. Asking the new agent its own golden question (23:35)
Agent Ops › the agent's page reads "custom agent · active · answers on Workspace · schema olist · 1 document ·
Packs none · May propose: nothing — no grants". In the canvas composer, "Answer as a saved agent" lists it;
picked it, Quick mode, asked "How many orders were excluded from the on-time calculation because they were
undelivered or canceled?" (the certified golden; DuckDB 2,971).
Answer (Quick, "Answering as Olist Delivery Performance · 1 bound document · 2 steps taken · 1 guard
intervened"): it kept its stance — "The data ends in August 2018, by purchase date. The latest delivered order
was purchased on 2018-08-29, so treat August as possibly partial. An order counts as late if it was delivered
after its estimated delivery date." — and broke the exclusions down: shipped 1,107 · canceled 625 ·
unavailable 609 · invoiced 314 · processing 301 · created 5 · approved 2 · delivered with no delivery date 8
(= 2,971, the certified figure; 96,470 left in the calculation), with the note that 6 canceled orders carry a
delivery date and were still excluded.
- **Gap 39 — the certified number is never said.** The headline reads "Orders were excluded from the on-time
  calculation, leaving 96,470 orders…": the reader must add eight rows to get 2,971. The guard that withholds
  figures not traced to a query result ("1 guard intervened") appears to have withheld the sum of the rows
  it shows. A golden question's own answer should be the first number on the page.
- The exhibit's range chip reads "4 Sept, 21:15 – 6 Nov, 13:12" with no years, on a status breakdown titled
  "Daily N by Order Status" (Gap 29's family).

*Run closed 23:36. Everything above is on the live instance: workspace Olist (206c6618), canvas dd30a7d4,
monitor a1c46186, agent "Olist Delivery Performance", two allowlists granted by the run (ontology edits on
`workspace`; publishing gross_merchandise_value_item_price) — revoke in Security & Audit › Approvals if unwanted.*
