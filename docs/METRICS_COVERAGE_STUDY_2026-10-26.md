# Metrics that cover the business — the framework (2026-10-26)

*Drafted 2026-10-26 at the user's word; the framework came first (the user: "Proceed with framework first"). Adopted
the same day as Arc MC with the six calls taken (§7; ROADMAP §3.62, §6 item 55; PENDING item 62). Nothing built yet.*

## 0. The ask

The user, on LuxExperience: *"for lux experience data, which is actually massive with a lot of data points, there are
only 12 proposed metrics.. for an e-commerce organisation that is probably not even 50% of the matrix that get tracked
and on which are based upon.. what are we missing?"* — then, sharpened: *"Missing in terms of approach or logic by which
we have only limited number of metrics suggested by explorer..."*

## 1. Measured first

**The data** (LuxExperience, Postgres, schema `luxexperience`, read 2026-10-26 over the API):

- 33 tables. The 12 metrics read 12 of them. 21 tables have no metric, among them eight with real volume:
  `web_events` 4.2M rows, `shipments` 140k, `payments` 146k, `marketing_attribution` 146k, `return_logistics` 86k,
  `email_engagement` 35k, `consent` 35k, `customer_service` 14k.
- theLook, for comparison: 15 metrics over 6 of its 7 tables. **The number of metrics does not follow the data** — a
  connection with five times the tables got fewer metrics.

**The 12 that exist** — 9 work:

| Metric | State |
|---|---|
| GMV, AOV, Gross Margin % (fixed to an inner join today), Item Return Rate, Session Conversion Rate, Repeat Purchase Rate | measured |
| Markdown Penetration, Average Inventory Weeks of Cover, Clienteling GMV per Interaction | measured where their data runs (it stops 2024–25) |
| **Return rate** | **reads 1 in every period** — `returned / all` inside `returns`, so every row counts |
| **Cart-to-order conversion rate** | **reads 1 in every period** — the same shape over `events`, the 66-row brand-events table |
| Marketing ROAS | a fiscal-year figure; no day, week or month exists in the data (refused by name since `6b22232b`) |

The two that read 1 are the retail pack's only two recipes. The pack's roles were bound in the Semantic Layer to the
wrong tables — `order_item` → `returns` (with `returned_at` → `return_date`, a column that is never empty there) and
`cart` → `events` (with `converted_order_id` → `event_date`, **a date bound to an id**) — and stored as `verified`. The
return-rate recipe declares a **sane range of 0–30%**; the metric reads 100%, and nothing compared them.

**Why the explorer proposes so few** — each read in the code (paths relative to the repo):

1. **The count is in the prompt.** One model call (`business_profile/infer.py:302-413`) asks for *"the 6-8 metrics … that
   matter MOST"* (`:322`; the schema field says "6-8 KPIs", `business_profile/models.py:56`). Thirty-three tables or
   three, it is asked for six to eight.
2. **It ranks; nothing checks coverage.** No map of what a business of this kind measures exists to check the proposals
   against, so nothing asks *which areas of this business have data and no metric*.
3. **It reads names, not the data.** It sees the schema text (capped at 60,000 characters, largest tables first,
   `infer.py:224-276`) and the ontology's domain labels — not the profiler's column statistics, not the ontology's
   processes and promises.
4. **The knowledge base of metrics is never asked.** The active packs ship about **100 curated metric patterns, each
   with a template statement** (`packs/*/kb/*.json`): retail 34 metric, ratio, funnel and cohort patterns across four
   areas (orders & revenue, funnel & conversion, customer lifecycle, inventory & merchandising), marketing 15, finance
   12, product 11, logistics 6, customer 5. Each carries its business definition, what it does and does not measure,
   the causes of a false high and a false low, diagnostic questions, related metrics and anti-patterns. They are read
   only when a question is answered — the two or three most similar help write its SQL (`semantic/kb_retriever.py`,
   `agent/grounding.py:173`, `agent/nodes.py:300`) — and never by the metric proposer, which reads
   `metric_kb.resolve_recipes` only to supply recipes for names the model already chose (`business_profile/infer.py:339`).
   *The user saw it first: "I think we already this list of metrics per industry as knowledge base or something else.."
   — the first draft of this study had counted retail's two typed recipes and its reading order, and missed it.*
   Retail's two typed recipes (`packs/retail/metrics/`), its 8 prose metrics and its 23-metric reading order
   (`packs/retail/industry.json`) likewise sort and cap the Briefing and never propose; the draft packs
   (`core-ecommerce`, `fashion-ecommerce`, `customer-analytics`) are not read.
5. **It happens once.** Proposals are made when the profile is built. The explorer later computes delivery days, CSAT,
   refund cycles in its findings and never offers one as a metric (`explorer/coverage_manifest.py` finds the "profiled
   measures the profile never named" — and feeds them to questions, not to metrics).
6. **The gates check the SQL, not the figure.** The audit refuses SQL that fails; nothing refuses a metric that reads the
   same value in every period, one outside its recipe's sane range, or a role bound to a column of the wrong type.

And one cap downstream: **the Briefing measures at most 12 approved metrics** (`briefing/ranges.py:65`, the Dashboard's
default view shares it). With 50 approved metrics, a Briefing shows the first 12 in reading order and names the rest.

On LuxExperience the ontology declares **no process, promise or segment** on its entities (theLook declares *Order
Fulfilment* with dispatch and delivery promises) — the code-derived proposals of §4.3 have nothing to read there until a
person declares one.

## 2. What "covering the business" means

A metric set covers a business when **every area the data describes has the metrics a person running that area reads**
— not when it holds the "most important" six. Coverage is measurable: areas with data, areas with metrics, the gap.

The map has two layers:

- **A generic layer**, true of any business: *volume* (how many), *value* (how much money), *rate* (a share of a
  population), *duration* (how long between two dates), *quality* (a score or a defect share), each over the entities the
  data holds. It proposes something sensible for a connection no pack fits.
- **An industry layer**, shipped with the pack — and **already written**: the knowledge base's metric patterns, grouped
  by area in their files (retail's four, and the function packs' customer, marketing, finance, product, logistics),
  each with a template, a definition and its traps. Retail's income-statement order (`gross_sales → deductions →
  net_sales → cogs → gross_profit → fulfilment → marketing → contribution → opex → profit`, then `volume · rate ·
  operations`) gives the areas their reading order.

For e-commerce the areas are these (the industry layer extends retail's statement with the operating areas it lacks):

| Area | The question it answers | Typical metrics |
|---|---|---|
| Traffic & conversion | Are visitors becoming buyers? | sessions, add-to-cart rate, checkout rate, checkout→order, conversion, bounce rate, revenue per session |
| Orders & sales | How much did we sell? | orders, GMV, net sales, units per order, average selling price, AOV |
| Margin & pricing | What did we keep? | gross profit, gross margin, markdown penetration, average markdown depth, full-price sell-through |
| Fulfilment | Did it arrive as promised? | days to ship, delivery days, on-time delivery, shipping cost per order, shipping-fee recovery |
| Returns | What came back, and what did it cost? | return rate, refund value, return-reason mix, restock rate, refund cycle time |
| Payments & risk | Did the money land safely? | payment success rate, fraud rate, instalment share, payment-method mix |
| Customers | Who buys, and do they come back? | active, new and returning customers, purchase frequency, revenue per customer, repeat purchase rate |
| Marketing | What did growth cost? | spend, ROAS, cost to acquire a customer, click-through rate, cost per click, attributed GMV by channel, days to conversion |
| CRM & consent | Can we reach them? | email open and click rates, subscribed share, marketing-consent rate |
| Service | Did we look after them? | contacts per 100 orders, CSAT, resolution days |
| Clienteling & events | Does the personal touch pay? | interactions per stylist, GMV per interaction, event spend uplift, event return on cost |
| Inventory | Is the stock right? | weeks of cover, sell-through, stock-out rate, share of stock on markdown |

Industry nouns live in the pack, never in core code (the industry-noun ratchet). A pack's area names are its own.

## 3. LuxExperience under the map

| Area | Data (rows) | Today | What its data supports |
|---|---|---|---|
| Traffic & conversion | web_sessions 4.8M, web_events 4.2M | session conversion ✓, cart-to-order ✗ | add-to-cart rate, checkout rate, checkout→order, bounce rate, pages per session, revenue per session |
| Orders & sales | orders 146k, order_items 274k | GMV, AOV | orders, units per order, average selling price, net sales (ex VAT and duty) |
| Margin & pricing | order_items, products, price_history | gross margin, markdown penetration | gross profit €, average markdown depth, full-price sell-through |
| Fulfilment | shipments 140k | — | days to ship, delivery days, on-time delivery, shipping cost per order, shipping-fee recovery |
| Returns | returns 86k, return_logistics 86k | item return rate ✓, return rate ✗ | refund value, return-reason mix, restock rate, refund cycle time |
| Payments & risk | payments 146k | — | payment success rate, fraud rate, instalment share |
| Customers | customers 35k | repeat purchase rate | active customers, new customers, purchase frequency, revenue per customer, top-customer share |
| Marketing | campaigns 453, attribution 146k | ROAS (yearly only) | click-through rate, cost per click, cost to acquire a customer, attributed GMV by channel, days and sessions to conversion |
| CRM & consent | email_engagement 35k, consent 35k | — | open rate, click rate, subscribed share, marketing-consent rate |
| Service | customer_service 14k | — | contacts per 100 orders, CSAT, resolution days |
| Clienteling & events | clienteling 7k, event_attendance 1.6k | GMV per interaction | interactions per stylist, event spend uplift, event return on cost |
| Inventory | inventory_snapshots 172k | weeks of cover | sell-through, stock-out rate, share of stock on markdown |

**12 today, 9 working; about 55 the data supports.** Several sources stop in 2024–25, so their metrics will say *data
ended* in a daily Briefing — correct, and said since 10-23.

## 4. The framework — six parts

### 4.1 The map
The knowledge base's metric patterns are the map: each file an area, each pattern a metric with its template,
definition and traps. What they lack is small — an explicit **area** where a file mixes two, a **direction** (up is
good or bad) and a **kind** (volume, value, rate, duration, quality) — and is added to the patterns, not kept beside
them. Retail's typed recipes (roles, `sane_range`) stay the strongest form and are proposed first. The generic layer
ships with the platform for a connection no pack fits; retail's statement orders the areas. Areas the knowledge base
does not cover yet are said as such (on LuxExperience: clienteling and events, consent, service beyond ticket volume,
returns logistics) — a pack can add them; nothing invents them.

### 4.2 Placement
Every table is placed in the areas it serves, from evidence the platform already holds — the ontology's entities and
domains, the profiler's row counts, dates and column types, the pack's role bindings, and the names — and each placement
says why. The result is a **coverage matrix**: area × (has data · has a metric · proposed · declined). It is a read, and
it is shown before anything is proposed.

### 4.3 Proposals, per uncovered area
Three sources, cheapest first:

1. **Recipes bound to roles — code, no model.** Where an area's recipe binds to the connection's roles, it is proposed.
   Binding is checked (§4.4); a role it cannot bind is said, never guessed.
2. **Derived from the ontology — code, no model.** Each promise a person declared gives its on-time rate; each process
   stage gives a stage conversion; each declared segment gives its share of the whole. Nothing on LuxExperience yet.
3. **The knowledge base's patterns, written for this schema — one scoped model call per area, spends.** A pattern's
   template is written against canonical names (`orders o`, `status = 'cancelled'`); this connection's tables and
   columns differ. One call per uncovered area is given that area's patterns (template, definition, anti-patterns) and
   only that area's tables with their profiler statistics, and asked which patterns the data supports and to write each
   for these tables — every proposal cites the pattern it came from, or says it came from none. The count follows the
   patterns the data supports, not a prompt. Its SQL goes through the same audit and recipe regeneration the explorer's
   does today, then the gates.
4. **Where no pattern covers an area**, the same call without patterns, asking for the metrics a person running that
   area reads — said as such, so a pack can later supply the pattern.

And a fourth, continuous: **a measure the explorer keeps computing without a metric** (the coverage manifest's blind
spots, or one recurring across findings) becomes a proposal in its area.

### 4.4 Gates — code, before a person sees a proposal
- **The SQL runs** (exists: `audit_value_sql`).
- **A window bounds it** (built 2026-10-26, `6b22232b`: outer-join optional side, date read only inside a filter).
- **It moves.** Measured over several periods, a metric that reads the same value in every one is refused with that
  sentence — the two LuxExperience metrics that read 1 would never have reached a person.
- **It sits in its sane range.** A recipe's declared `sane_range` is enforced at proposal and at approval, with the range
  and its basis said.
- **Its roles bind to the right things.** A role's columns are checked by type (an id is not a date, money is numeric),
  and a role is checked against the kind of table it names (sold lines are the table whose rows are sold lines).
- **It is not a twin** (exists: `metric_twins`, at approval).
- **Its data window is said** (exists: *data ended*).

### 4.5 Adoption — people only
Proposals land in the metric catalogue as a fourth source (`semantic/metric_catalogue.py`, beside defined · industry ·
explorer), grouped by area, with the gates' verdicts beside each. A person adopts per area through the adopt door that
exists (#624) and approves as today. A model never approves; a proposal never becomes a metric on its own.

### 4.6 Reading them
The Briefing's 12 becomes a setting, and the Briefing reads by the map's order — the income statement first, then the
operating areas — so a larger set reads as a business, not as a longer list. Dashboards can be drafted per area from the
adopted metrics (FA-6's templates are the door).

## 5. What it reuses — one store per concept

| Need | Already here |
|---|---|
| The map: ~100 metric patterns with templates, definitions and traps, grouped by area | `packs/*/kb/*.json`, read by `packs/knowledge.kb_files`, `semantic/kb_retriever.py` |
| Recipes with roles, sane ranges, anti-patterns | `packs/*/metrics/*.yaml`, `metric_kb.resolve_recipes` |
| An industry's order | `packs/retail/industry.json` (`statement`, `reading_order`), `briefing/reading_order.py` |
| Blind spots | `explorer/coverage_manifest.py` |
| Role bindings | `packs/bindings.py`, `/packs/{id}/propose-bindings` |
| Proposals, adoption, approval | `semantic/metric_catalogue.py`, `POST /metrics/catalogue/{conn}/adopt`, the transition door |
| SQL audit, window check, twins | `audit_value_sql`, `metric_statement.unbounded`, `metric_twins` |
| Promises and processes | the ontology's processes (`derived.py`'s `overdue_<noun>`), OC-4 |

New: area, kind and direction on the patterns that lack them, the generic layer, placement, the coverage matrix, the
per-area proposer that writes the patterns for a schema, and three gates (moves, sane range, binding types).

## 6. Arc MC — proposed waves (each behind its flag, off by default)

| Wave | Builds | Spends | Falsifier |
|---|---|---|---|
| **MC-0** | The defects: LuxExperience's two metrics that read 1 (the user's call, §7); the three new gates at approval — moves, sane range, binding types | no | a metric reading one value in every period is approved |
| **MC-1** | The knowledge base as the map: area, kind and direction on its metric patterns; the generic layer; areas ordered by retail's statement | no | a metric pattern in no area, or an area the knowledge base lacks unsaid |
| **MC-2** | Placement and the coverage matrix — read-only, shown on the Metrics tab: per area, the patterns, the data, the metrics | no | a table with a metric placed in no area, or an area said covered by a metric that reads 1 |
| **MC-3** | Typed recipe proposals per uncovered area (code), through the gates, into the catalogue grouped by area | no | a proposal that fails a gate shown as adoptable |
| **MC-4** | Ontology-derived proposals (promise → on-time rate, stage → conversion, segment → share) | no | a derived metric whose count differs from the ontology's own |
| **MC-5** | The knowledge base's patterns written for this schema, one scoped model call per uncovered area, each proposal citing its pattern | **yes** | a proposal naming a table outside its area, or citing a pattern it does not compute |
| **MC-6** | Blind spots → proposals; the Briefing's cap a setting, read by the map's order | no | a recurring measure left unproposed past N findings |

A receipt for each on LuxExperience, live: the matrix before and after, every proposal with its gate verdicts, and the
count of adoptable proposals per area.

## 7. Calls for the user

*Answered 2026-10-26 (ROADMAP §6 item 55): (1) deprecate — done the same day; (2) knowledge base + generic layer;
(3) **automatically when profiled** (not the recommended click); (4) all that pass, by area; (5) **raise the default** —
24; (6) refuse at approval.*

1. **The two LuxExperience metrics that read 1** — deprecate them now (*recommended*: the map proposes correct ones in
   MC-3), or rebind them by hand now (return rate over `order_items` with `returns`; cart-to-order over `web_sessions`'
   `added_to_cart` and `converted`)?
2. **The map** — the knowledge base's metric patterns, with area, kind and direction added to them, plus a generic layer
   in the platform for a connection no pack fits (*recommended*); or the knowledge base alone?
3. **The model proposer (MC-5) spends** — one call per uncovered area. On a person's click per area (*recommended*), or
   automatically when a connection is profiled?
4. **How many proposals a person sees** — every proposal that passes the gates, grouped by area (*recommended*), or the
   top three per area?
5. **The Briefing's cap** — a setting per workspace, default 12 (*recommended*), or a higher default?
6. **The new gates** — refuse at approval (*recommended*, as the window check does), or warn and let a person approve?

## 8. What was checked, and what was not

Checked live: LuxExperience's tables, row counts and columns; its 12 definitions and their SQL; the retail pack's
binding on it; its ontology's processes and segments (none); theLook's metric-to-table spread. Checked in code: every
proposal path and cap named in §1 (a survey, then the prompt and the cap read directly); the knowledge base's metric
patterns counted per pack and per type, one read in full, and where they are read (answers only). Missed in the first
draft and found at the user's prompt: the knowledge base itself — the survey had been asked about proposal paths, and
the knowledge base is not one; that is the finding. Not checked: whether the 60,000
character schema cap cuts LuxExperience's schema (its 33 tables are small enough that it probably does not — the
prompt's count is the binding limit either way); what a scoped model proposer actually proposes (MC-5 is a build, and it
spends).
