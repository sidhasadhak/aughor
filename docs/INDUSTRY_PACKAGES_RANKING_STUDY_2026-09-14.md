# Which industry packages to build next: an evidence-based vertical ranking for Aughor

Research date: 2026-09-14. Scope: web research only (market-research summaries, vendor industry catalogs, standards bodies, public datasets).
Already shipped by Aughor: e-commerce/retail, airline, food delivery, logistics, manufacturing, SaaS.

Citation convention: bracketed tags such as [M4], [V1], [T3], [D26] and [X2] refer to numbered URLs in the Sources section (M = market research, V = vendor catalogs, T = standards, D = datasets, X = metric definitions). A claim marked "(snippet)" comes from a search-index summary of a page that could not be fetched directly; such claims were not used for scoring.

---

## TL;DR: build tiers (unbuilt verticals only)

| Tier | Build | Why first |
|---|---|---|
| **1: build now** | **Banking & lending**; **Insurance (P&C + life)**; **Healthcare, payer/claims module first, providers second** | Largest and most consistent demand signal (BFSI is the largest vertical in 5 of 8 horizontal analytics reports; healthcare/life sciences is the fastest-growing in 3 of them and in 3 of 4 functional reports). Highest "generic analytics gets it wrong" premium: earned vs written premium, loss triangles, vintage curves, PMPM and claims lag. Mature open standards to seed from (BIAN/FIBO/ISO 20022, ACORD, FHIR/OMOP/X12, the Tuva dbt model). Public validation data exists (Berka, Freddie Mac, HMDA; freMTPL2, CAS Schedule P; Synthea, MIMIC-IV demo, CMS DE-SynPUF). |
| **2: next** | Pharma & life sciences; Energy & utilities; Telecommunications; CPG / consumer brands (extends retail); Payments & fintech (extends banking); Travel & hospitality: hotels, OTAs, car rental (extends airline) | Strong vendor investment or cheap adjacency to a shipped or Tier-1 package, each with a real standard and usable public validation data (CPG's is academic or terms-restricted). |
| **3: later** | Public sector; Education; Capital markets & wealth management; Media & streaming + Advertising/adtech (build as a pair); Oil, gas & mining; Automotive (extends manufacturing); Restaurants/QSR (extends food delivery and retail) | Real demand but heavy go-to-market friction (procurement, FERPA), weak public data (capital markets, automotive, media) or a narrow buyer base. |
| **4: on demand** | Real estate & property management; Construction & engineering; Agriculture; Gaming; Nonprofit & NGOs; Professional services & staffing; mobility and crypto as modules of existing packages | Little analytics-spend evidence, at most 3.5 of 10 vendor catalogs name them (agriculture 0.5; construction and professional services 1; real estate 2; gaming 3; nonprofit 3.5), and several lack standards or public data. |

---

## 0. Method

### 0.1 Scoring rubric (max 27)

**Score = 3×D + 2×V + 2×K + 1×S + 1×P**, each component scored 0–3.

| Component | 3 | 2 | 1 | 0 |
|---|---|---|---|---|
| **D: demand evidence** (weight 3) | The vertical is an IDC top-3 AI-spending industry; or it is named on its own as the largest or fastest-growing vertical in at least 2 analytics-market reports (horizontal or functional); or its combined bucket (e.g. BFSI, healthcare & life sciences) is largest or fastest in at least 2 reports *and* a vertical-specific analytics market of at least USD 15B is verified | Named segment in at least 2 horizontal reports (combined buckets count), or verified vertical analytics sizing of at least USD 5B plus named in at least 1 report | Verified sizing under USD 5B, or only unverified or stale sizing | No sizing found |
| **V: vendor investment** (weight 2) | 8.5–10 of 10 catalogs | 6–8 | 3–5.5 | under 3 |
| **K: knowledge premium** (weight 2; analyst judgement) | Core KPIs are industry- or regulator-defined, or need weighting, cohorting or maturation that a generic agent will get wrong | Several industry-specific definitions, but generic analytics is roughly right | — | Generic analytics is sufficient |
| **S: seedable standard** (weight 1) | Mature open or industry data model or messaging standard | Standard exists but is partial, paid, or adjacent to analytics | Only a mobility- or legal-niche standard | None found |
| **P: public validation data** (weight 1) | Realistic data, licence clear, multi-table | Realistic but restricted, old, or single-table | Fictional or partial | None found |

Vendor count (V) runs over 10 catalogs: Snowflake, Databricks, Microsoft, Google Cloud, AWS, Salesforce, Tableau Accelerators, ThoughtSpot, Sigma and the dbt Package Hub. A named industry, sub-industry or accelerator category scores 1; a mention inside a broader page, a preview/deprecated offering, or source-shaped dbt packages scores 0.5. Hex and Mode publish no vertical catalog ([V25], [V26]). Databricks' 40-industry data-model template list [V7] is shown as a separate column and not counted.

### 0.2 Merges and additions relative to the candidate list

- **Merged: retail & commercial banking + lending/credit → "Banking & lending".** Most lenders are banks, and the ontology (party, account, loan, collateral, delinquency) is shared; lending becomes a module (vintages, roll rates, loss curves).
- **Merged: health payers → "Healthcare providers & payers"** (two modules). They share code sets, the member/patient, encounter and claim ontology, and the Tuva/OMOP/FHIR models. P&C and life insurance stay in **Insurance**.
- **Merged: hotels & lodging + online travel + car rental → "Travel & hospitality".** Vendors catalog these as one vertical ([V1], [V19], [V20], [V23]), and all share the capacity × rate × occupancy and booking-curve analytics of the shipped airline package.
- **Merged: grocery → Retail & e-commerce** (shipped; grocery is a module).
- **Merged: ride-hailing/micromobility → "On-demand marketplaces & mobility"**, extending shipped food delivery.
- **Merged: crypto/web3 → "Payments, fintech & digital assets"** as a module. No vendor catalog names it as an analytics vertical.
- **Added: Capital markets & wealth/asset management.** Snowflake has an Asset & Wealth Management sub-industry [V1], Tableau has a Private Equity category [V21], and Microsoft ships a wealth-management data model ([V10], via search). This is a distinct analytics problem from retail banking.
- **Added: Oil, gas & mining** as separate from utilities, because the standards (OSDU/PPDM vs IEC CIM) and KPIs differ.
- **Folded in as sub-verticals, not separate rows:** sports (under media), semiconductors and chemicals (under manufacturing), defense (under public sector), water/waste (under utilities), legal and staffing (under professional services). Vendors list these, but they are not separate analytics problems.
- **Moved to the horizontal list:** supply chain & procurement, ESG/sustainability and cybersecurity/IT ops. Vendors present these as "industries" ([V2], [V19], [V21], [V22]), but they cut across verticals.

### 0.3 Caveats

1. **Market-research figures are not comparable.** They come from publisher summary pages and press releases for paywalled reports, and definitions differ widely. Example: insurance analytics 2025 is USD 19.3B per Fortune Business Insights [M16] but USD 43.18B per Mordor [M17]. Use them for order of magnitude and direction only.
2. **Vendor presence is marketing-page presence** as fetched on 2026-09-14, not product depth. Microsoft's Fabric industry data-solution list, for example, now shows only healthcare and nonprofit (preview) [V9].
3. **K is this report's own analytic judgement.** Metric definitions are cited where it depends on them ([X1]–[X9]).
4. **Research gaps.** The WebSearch quota ran out mid-research, and several standards-body sites returned HTTP 403 to automated fetches (ACORD, ISO 20022, TM Forum, OpenTravel, GS1 main site). Regulator, Wikipedia or alternate official pages were used instead and are flagged. **TM Forum SID could not be verified this session.** Kaggle competition pages are not machine-readable; dataset licences were verified through Kaggle's public dataset-metadata API where possible, and unverified competitions are listed separately [D62].

---

## 1. Market-research evidence: which verticals spend on analytics

### 1.1 Horizontal analytics markets: leading and fastest-growing vertical

All entries come from publisher summary pages or press releases for paywalled reports.

| Publisher (page type) | Market | Size (as stated) | Largest vertical (share, year) | Fastest-growing vertical | Src |
|---|---|---|---|---|---|
| Fortune Business Insights (summary) | Big data analytics | USD 394.70B (2025) → 1,176.57B (2034) | **BFSI 22.31% (2026)** | **Healthcare** (highest CAGR; % not given) | [M1] |
| Mordor Intelligence (summary) | Business intelligence | USD 41.16B (2026) → 62.38B (2031) | **BFSI 22.74% (2025)** | **Retail & e-commerce, 10.21% CAGR** to 2031 | [M4] |
| Precedence Research (summary) | Business intelligence | USD 43.48B (2025) → 134.94B (2035) | **IT & telecom >26% (2025)**; BFSI "anticipated to dominate" the forecast | not stated | [M3] |
| Fortune Business Insights (summary) | Business intelligence | USD 34.82B (2025) → 72.21B (2034) | **IT & telecom** (largest, % not given, 2025) | **BFSI** (highest growth) | [M2] |
| Precedence Research (summary) | Data analytics | USD 64.75B (2025) → 785.62B (2035) | **BFSI ~25% (2024)**; IT & telecom >20% (2025) | not given by vertical; fraud detection is the fastest application (14.70% CAGR) | [M5] |
| Mordor Intelligence (summary) | Data analytics | USD 108.79B (2026) → 438.47B (2031) | **IT & telecom 44.20% (2025)** | **Healthcare, 33.40% CAGR** | [M6] |
| Mordor Intelligence (summary) | Advanced analytics | USD 69.52B (2026) → 178.93B (2031) | **BFSI 21.55% (2025)** | **Healthcare & life sciences, 23.70% CAGR** | [M7] |
| MarketsandMarkets (press release, 23 Mar 2026) | Big data | USD 324.59B (2026) → 516.29B (2031) | **BFSI** "dominates" (no %) | (by vertical: not stated) | [M8] |

**Reading.** BFSI is the largest vertical in 5 of the 8 reports; the other 3 put "IT & telecom" first, a bucket dominated by software/IT companies. Healthcare / life sciences is the most frequently named fastest-growing vertical, with retail & e-commerce named once. Segment lists repeat the same core: BFSI, IT & telecom, retail & consumer goods, healthcare & life sciences, manufacturing, government, energy & utilities. Several reports add media & entertainment, transportation & logistics, education, hospitality & travel [M5], and automotive [M1].

### 1.2 IDC and Gartner

| Source | Evidence | Src |
|---|---|---|
| IDC blog, 21 Aug 2024 (AI spending by industry) | Top AI spenders in 2024: **Software & information services $33B, Banking $31.3B, Retail $25B**. Together $89.6B, 38% of global AI spend, rising to ~$222B by 2028. | [M9] |
| IDC press release, Aug 2021 (Big Data & Analytics Spending Guide) | Banking, discrete manufacturing and professional services ≈ one-third of 2021 BDA spending (total $215.7B). (snippet: direct fetch returned 403; dated) | [M10] |
| IDC Data & Analytics Spending Guide (product page) | Tracks spending by industry; counts and figures are not public on the page. | [M11] |
| Gartner, Forecast: Enterprise IT Spending by Vertical Industry Market (2023-2029) | Exists but is paywalled; no figures used. | [M12] |

### 1.3 Function-level reports naming a leading vertical (Mordor, 2025)

| Functional market | Size | Largest end-user vertical | Fastest-growing vertical | Src |
|---|---|---|---|---|
| Marketing analytics | USD 7.12B (2025) | **Retail 23.32%** | Banking & financial services, 13.24% CAGR | [M35] |
| Customer analytics | USD 17.58B (2026) | **Retail 20.70%** | Healthcare, 21.90% CAGR | [M36] |
| Supply chain analytics | USD 9.37B (2025) | **Retail & e-commerce 24.45%** | Healthcare & life sciences, 25.8% CAGR | [M24] |
| HR analytics | USD 4.89B (2025) | **IT & telecom 23.62%** | Healthcare & life sciences, 14.11% CAGR | [M37] |

**Reading.** Retail dominates functional analytics spend (the shipped retail package benefits). Healthcare is again the fastest grower.

### 1.4 Vertical-specific analytics markets (indicative only; publishers use incompatible definitions)

| Vertical | Figure (as stated) | Publisher | Src |
|---|---|---|---|
| Healthcare analytics | USD 55.52B (2025) → 166.65B (2030), 24.6% CAGR; providers hold "a significant share" | MarketsandMarkets PR, 23 Jan 2026 | [M13] |
| Big data analytics in healthcare | USD 67.32B (2025) → 374.70B (2035); **payers dominant in 2025**, providers fastest | Precedence Research | [M14] |
| Life science analytics | US$35.69B (2024) → 68.81B (2030), 11.4% CAGR | MarketsandMarkets PR, 2 May 2025 | [M15] |
| Insurance analytics | USD 19.3B (2025) → 54.54B (2034) / USD 43.18B (2025) → 132.04B (2031) | Fortune BI / Mordor | [M16], [M17] |
| Learning analytics (education) | USD 14.05B (2025) → 43.87B (2031) | Mordor | [M21] |
| Oil & gas analytics | USD 12.70B (2025) → 91.25B (2035) | Precedence | [M22] |
| Retail analytics | USD 11.31B (2026) → 20.65B (2031) / USD 6.60B (2025) → 8.44B (2031) | MarketsandMarkets / Mordor | [M19], [M20] |
| Big data analytics in banking | USD 10.56B (2025) → 29.87B (2030) | Mordor | [M18] |
| Big data analytics in construction | USD 10.3B (2025) → 28.9B (2035) (single source, broad definition) | GMI | [M23] |
| Supply chain analytics (functional) | USD 9.37B (2025) / USD 11.08B (2025) | Mordor / Fortune BI | [M24], [M25] |
| Telecom analytics | USD 8.09B (2025) → 14.69B (2031) | Mordor | [M26] |
| Sports analytics | USD 5.79B (2025) → 31.14B (2034) | Fortune BI | [M27] |
| Energy & utilities analytics | USD 5.36B (2025) → 10.10B (2031) | MarketsandMarkets | [M28] |
| Hospitality revenue-management & pricing analytics | USD 4.1B (2024) → 13.1B (2034) | GMI | [M29] |
| Aviation analytics | USD 3.58B (2025) → 13.42B (2035) | Precedence | [M30] |
| Restaurant management software (analytics/BI segment) | USD 6.54B total (2025); **analytics/BI USD 1.42B (2025), fastest segment at 17.25% CAGR** | Mordor | [M31] |
| Agriculture analytics | USD 1.4B (2023) → 2.5B (2028) | MarketsandMarkets | [M32] |
| Manufacturing analytics | 24% CAGR 2025-2030 (size not shown) | Mordor | [M33] |
| Transportation analytics | "USD 27.4B by 2024" (2019-vintage forecast, stale) | MarketsandMarkets | [M34] |
| Gaming, payments, crypto, real estate, public sector, nonprofit, professional services | No verified figure (see Appendix A for unverified snippets) | — | — |

---

## 2. Ranked verticals

Score = 3×D + 2×V + 2×K + S + P (max 27; see §0.1). **[SHIPPED]** marks verticals Aughor already packages. They are ranked for completeness, and the tiers in §5 cover only unbuilt verticals. Ranks 1–25 are the main table; 26–29 form the long tail (§2.2).

### 2.1 Main table (ranks 1–25)

| # | Vertical (sub-verticals covered) | D/V/K/S/P = score | Demand evidence | Standard data model(s) | Public validation dataset(s) | Why an industry package matters (what generic analytics gets wrong) |
|---|---|---|---|---|---|---|
| 1 | **Healthcare providers & payers** (hospitals/health systems, physician groups, health plans, TPAs) | 3/3/3/3/3 = **27** | Fastest-growing vertical in [M1], [M6] (33.40% CAGR), [M7] (23.70%); healthcare analytics USD 55.52B (2025) [M13]; big-data healthcare USD 67.32B (2025), **payers dominant** [M14]; vendors 10/10 | HL7 FHIR R5 [T1]; OMOP CDM [T2]; X12 837/835 v5010, HIPAA-mandated [T3] (licensed [T4]); Tuva Project, an open dbt claims/clinical model its site says is used by 100+ US healthcare organizations [V29] | Synthea: synthetic, Apache-2.0, FHIR/CSV [D35]; MIMIC-IV demo: 100 real de-identified patients, ODbL [D36]; CMS DE-SynPUF: synthetic Medicare claims 2008–10 [D37] | PMPM divides by member-months, not members; the latest months need claims-lag completion (IBNR) before trending; MLR is regulated (ACA floors of 80%/85%) [X7]; diagnoses and procedures roll up through ICD/CPT/DRG hierarchies. A naive "sum of paid claims by month" understates the most recent quarter. |
| 2 | **Banking & lending** (retail & commercial banking, credit unions, cards, consumer & mortgage lending) | 3/3/3/3/2 = **26** | BFSI largest: 22.31% (2026) [M1], 22.74% (2025) [M4], ~25% (2024) [M5], 21.55% (2025) [M7]; IDC: banking #2 AI spender, $31.3B (2024) [M9]; big data in banking USD 10.56B (2025) [M18]; vendors 9/10 | BIAN Service Landscape 14.0 [T6]; FIBO (OWL, OMG) [T7]; ISO 20022 [T8]; FDX API (114M customer connections) [T9]; MISMO v3 for mortgage (via ULDD) [T10], [T11] | PKDD'99 "Berka": real anonymized Czech bank, 8 tables [D23]; Freddie Mac single-family loan-level: ~56M loans 1999–2026, free for non-commercial use [D26]; HMDA loan-level [D27]; UCI Bank Marketing, CC BY 4.0 [D24]; Taiwan card default, CC0 [D25] | NIM = net interest income ÷ *average* earning assets [X8]; balances are snapshots and are never summed across months; credit quality is read by origination vintage and days-past-due bucket (roll rates), not as one pooled delinquency rate; charge-offs are net of recoveries. |
| 3 | **Retail & e-commerce** [SHIPPED] (incl. grocery, marketplaces) | 3/3/2/2/3 = **24** | IDC: retail #3 AI spender, $25B (2024) [M9]; fastest BI CAGR 10.21% [M4]; largest end-user of marketing (23.32%), customer (20.70%) and supply-chain (24.45%) analytics [M35], [M36], [M24]; retail analytics USD 11.31B (2026) [M19]; vendors 9.5/10 | GS1 GTIN / EPCIS 2.0 [T17]; ARTS relational data model (OMG/NRF) [T18] | Olist: ~100k orders 2016–18, CC BY-NC-SA 4.0 [D1]; UCI Online Retail II: 1.07M invoice lines, CC BY 4.0 [D2]; GA4 obfuscated sample [D3]; Instacart (Kaggle mirror, CC0 per mirror metadata) [D4] | Comparable-store growth excludes new and closed stores [X6]; GMV ≠ net revenue after cancellations and returns; basket metrics need order grain, not line grain. Grocery adds perishables and shrink. |
| 4 | **Pharma & life sciences** (pharma commercial, biotech, medtech, CROs) | 3/2/3/3/2 = **24** | Life science analytics US$35.69B (2024) → 68.81B (2030) [M15]; healthcare & life sciences fastest-growing in [M7], [M24], [M37]; vendors 7.5/10; Databricks templates for pharma, genomics and clinical trials [V7] | CDISC SDTM v2.1, required by FDA and PMDA [T5]; OMOP CDM [T2] | openFDA (FAERS, labels, NDC, recalls), CC0 [D38]; AACT, a daily relational copy of all ClinicalTrials.gov studies (account required from 15 Sep 2026) [D39]. No public prescription-level commercial data. | Commercial metrics (TRx/NRx, share, persistence by days' supply) come from licensed syndicated extracts with their own projection and calendar rules; trial data is SDTM-shaped (domain tables, visit-based). Counting prescription rows or joining raw panel files misstates share. |
| 5 | **Insurance** (P&C, life & annuity, specialty, reinsurance) | 3/2/3/3/2 = **24** | Inside BFSI (largest); insurance analytics USD 19.3B (2025) [M16] / USD 43.18B (2025) [M17]; ThoughtSpot launched an insurance Spotter agent (Mar 2026) [V23]; Microsoft P&C insurance data model (preview) [V11]; vendors 6/10 | ACORD: 1,200+ standardized transaction types, NGDS object model (2025), P&C/life/reinsurance [T12] | freMTPL2: 677,991 French motor policies with claim counts and amounts [D33] (licence not stated on doc page); CAS loss-reserving triangles from NAIC Schedule P, 6 lines, AY 1998–2007 [D34] | Loss ratio uses *earned*, not written, premium, by accident year; recent years are immature until developed through loss triangles (IBNR); combined ratio = (losses + expenses) ÷ premium [X3]; frequency is per exposure-year. A calendar-month "paid ÷ written" ratio is simply wrong. |
| 6 | **Manufacturing** [SHIPPED] (discrete, process, semiconductors, chemicals) | 2/3/3/3/2 = **23** | Named in every horizontal segmentation; manufacturing analytics 24% CAGR [M33]; IDC 2021: discrete manufacturing among top-3 BDA spenders (snippet) [M10]; vendors 9/10 | ISA-95 / IEC 62264 (paid) [T19] | AI4I 2020: synthetic, CC BY 4.0 [D19]; SECOM: real semiconductor line, 1,567 runs, CC BY 4.0 [D20] | OEE = availability × performance × quality [X5]; averaging OEE across lines without weighting by planned time overstates it; yield and scrap need lot genealogy. |
| 7 | **Energy & utilities** (electric, gas, water, retail energy, renewables) | 2/2/3/3/3 = **22** | Energy & utilities analytics USD 5.36B (2025) [M28]; named segment in [M1], [M5], [M6], [M7]; vendors 6/10 | IEC CIM (61970/61968/62325) [T20]; Green Button / NAESB REQ.21 ESPI (energy, gas, water usage) [T21] | Low Carbon London smart meters: 5,567 households, half-hourly, ~167M rows, CC BY [D45]; EIA Open Data, free API and bulk [D46] | Reliability is customer-weighted: SAIDI = Σ customer-interruption durations ÷ customers served (IEEE 1366) [X4]; load and revenue must be weather-normalized; 15/30-minute interval reads are not transactions. |
| 8 | **Telecommunications** (mobile, broadband, cable, wholesale) | 2/2/3/3/2 = **21** | Telecom analytics USD 8.09B (2025) [M26]; "IT & telecom" largest in [M2], [M3], [M6] (mostly IT); vendors 7.5/10 | TM Forum SID / Open Digital Architecture [T13] (**not verified this session**) | IBM Telco Customer Churn: IBM sample, repo Apache-2.0 [D40]; Telecom Italia Big Data Challenge, Milan/Trentino (19 datasets, 2015; licence per dataset not verified) [D41] | ARPU divides by the *average* subscriber base over the period [X9]; churn is a monthly rate on the opening base; prepaid "active" depends on an inactivity window; prepaid, postpaid and wholesale must not be pooled. |
| 9 | **CPG / consumer brands** (food & beverage, personal care, household, DTC brands) | 2/2/3/2/2 = **20** | "Retail and consumer goods" segment in [M2], [M3]; CPG pages at Google Cloud, Salesforce, Snowflake [V16], [V20], [V1]; vendors 7.5/10 | GS1 GTIN / EPCIS [T17] | dunnhumby: The Complete Journey (2,500 households, 2 years) and Breakfast at the Frat (promo, 156 weeks) [D5]; Kilts NielsenIQ scanner and panel data (academic subscription only) [D6] | Shipments (sell-in) ≠ consumption (sell-through); retailer POS and syndicated data run on retailer calendars; distribution is ACV-weighted; promo lift is incremental over a baseline, not the week's total sales. |
| 10 | **Public sector** (federal, state & local, defense, public-health agencies) | 2/2/2/3/3 = **20** | Government is a named segment in [M1], [M4], [M5], [M8]; vendors 6.5/10 | NIEMOpen (OASIS, 17 domains) [T31]; Open Contracting Data Standard 1.1.5, Apache-2.0 [T32] | USAspending API, free federal award data [D51]; NYC 311 service requests, updated daily [D52] | Fund accounting: appropriations, obligations and outlays are different measures on fiscal years; award modifications double-count if summed naively; service levels run from request open to close by agency. |
| 11 | **Education** (K-12, higher education, edtech) | 2/1/3/3/3 = **20** | Learning analytics USD 14.05B (2025) [M21]; education named in [M1], [M5]; vendors 5/10 | Ed-Fi (free; 26% of US states) [T24]; CEDS (early learning → workforce) [T25]; 1EdTech Caliper 1.2 [T26] | OULAD: 30k+ students with VLE interactions and assessments, CC BY 4.0 [D49]; IPEDS institution data, public [D50] | Retention and graduation are fixed-window cohort metrics; enrollment is counted on a census date and as FTE vs headcount; attendance is average daily attendance, not a count of "present" rows. |
| 12 | **Payments, fintech & digital assets** (acquiring, issuing, wallets, BNPL; crypto module) | 2/1/3/3/3 = **20** | Inside BFSI (largest); Snowflake Payments sub-industry [V1]; fraud detection is the fastest application (14.70% CAGR) [M5]; vendors 4.5/10; Databricks "Payments & Fintech" template [V7] | ISO 20022 (payments, cards, securities) [T8]; FDX [T9]. Crypto: no standard; the Ethereum-ETL schema is de facto [D32]. | PaySim: synthetic mobile money, CC BY-SA 4.0 (simulator GPL-3.0) [D28]; ULB card fraud, ODbL [D29]; IBM TabFormer: 24M synthetic card transactions, Apache-2.0 [D30]; BigQuery Ethereum [D32]; Elliptic bitcoin graph, CC BY-NC-ND 4.0 [D31] | Authorization rate must de-duplicate retries; chargeback ratios follow card-network counting rules; TPV ≠ net revenue (interchange and scheme fees); fraud is quoted in basis points of volume; on-chain volume double-counts internal wallet transfers. |
| 13 | **Logistics, freight & last-mile** [SHIPPED] (3PL, parcel, trucking, shipping/ports) | 2/1/3/3/3 = **20** | Supply-chain analytics USD 9.37B [M24] / 11.08B [M25] (2025); transportation & logistics named in [M5]; vendors 4/10 | GS1 EPCIS 2.0 [T17]; DCSA (track & trace, eBL, booking, schedules) [T37] | Amazon Last Mile Routing: 9,184 routes, CC BY-NC 4.0 [D11]; LaDe: 10.7M packages, Apache-2.0 [D10]; DataCo, CC BY 4.0 [D12]; FAF5 freight flows [D13] | OTIF needs a promised date per order line; multi-leg and multi-stop shipments are not independent observations; cost per stop and dwell depend on the stop grain. |
| 14 | **Oil, gas & mining** (upstream, midstream, mining) | 2/1/3/3/2 = **19** | Oil & gas analytics USD 12.70B (2025) [M22]; OSDU Forum has 190 member organizations [T22]; vendors 3/10 | OSDU standard and data platform [T22]; PPDM data model and "What is a Well" [T23] | Equinor Volve: ~40,000 files, Equinor Open Data Licence (research use) [D47]; Texas RRC production, well and permit data, free [D48] | Volumes are converted to BOE and allocated from facility to well; net volumes depend on working and net revenue interest; forecasts follow decline curves, not linear trends. |
| 15 | **SaaS / technology & software** [SHIPPED] | 3/1/3/0/1 = **18** | "IT & telecom" largest in [M2], [M3], [M6] (44.20%); IDC: software & information services #1 AI spender, $33B (2024) [M9]; vendors 5.5/10 | None found (no open SaaS-metrics standard) | No realistic public B2B SaaS dataset: Maven "CRM Sales Opportunities" and "MavenFlix subscriptions" are fictitious [D8]; KKBox churn is a B2C subscription competition, not verified [D62] | ARR/MRR is normalized from contracts, not invoices; NRR/GRR are cohort ratios on a fixed starting base; bookings ≠ billings ≠ revenue. |
| 16 | **Capital markets & wealth / asset management** (asset managers, wealth, brokerage, private equity) | 2/1/3/3/1 = **18** | Inside BFSI (largest); Snowflake Asset & Wealth Management [V1]; Tableau Private Equity category and "Client Assets & Liabilities" accelerator [V21]; Microsoft wealth-management data model (via search) [V10]; vendors 5.5/10 | FIBO [T7]; ISO 20022 securities messages [T8] | SEC Financial Statement Data Sets (XBRL-derived numbers from 10-K/10-Q, 2009–2026) [D61]. No public holdings or transaction data. | Performance is time-weighted (neutralizing flows); AUM change splits into net flows vs market movement; positions are as-of snapshots on trade vs settlement date, with FX. |
| 17 | **Media, streaming & publishing** (video/audio streaming, broadcasters, publishers, music, sports business) | 2/2/2/2/1 = **17** | Named in [M1] (telecom/media) and [M5] (media & entertainment); sports analytics USD 5.79B (2025) [M27]; vendors 7/10 | DDEX (ERN release notification, DSR sales/usage reporting) [T33]; EIDR content IDs [T34] | MovieLens (up to 32M ratings; no public redistribution without permission) [D42]; KKBox music-subscription churn (not verified) [D62] | Subscribers, accounts and profiles are different denominators; viewing is attributed by title and release window; royalties follow usage reports (DDEX DSR), not raw play counts. |
| 18 | **Travel & hospitality** (hotels & lodging, short-term rentals, OTAs/metasearch, car rental, cruise) | 1/1/3/2/3 = **16** | Hospitality revenue-management & pricing analytics USD 4.1B (2024) [M29]; hospitality & travel named in [M5]; ThoughtSpot Spotter for travel & hospitality (Mar 2026) [V23]; vendors 5/10 | OpenTravel (air, hotel, car, cruise, rail; XML/JSON) [T16] | Hotel booking demand: two hotels (city/resort) 2015–17 with ADR, cancellations and distribution channel, CC BY 4.0 [D15]; Inside Airbnb listings/calendar/reviews, CC BY 4.0 [D16] | RevPAR = rooms revenue ÷ available room-nights (= ADR × occupancy) [X2], so averaging property RevPARs is wrong; pace and pickup are read by stay date vs booking date; OTA revenue is net vs gross of commission; cancellations and no-shows distort occupancy. |
| 19 | **Advertising, adtech & martech** (agencies, publisher ad ops, DSP/SSP, retail media networks) | 1/1/3/3/2 = **16** | No verified vertical sizing; marketing analytics USD 7.12B (2025) [M35] is the functional proxy; Snowflake AdTech & MarTech and Agencies [V1]; AWS Advertising & Marketing [V19]; an IAB-related buy/sell accelerator repo in Databricks' org [V6]; vendors 3.5/10 | IAB Tech Lab OpenRTB 2.6 / 3.0 + AdCOM [T27] | Criteo Attribution Modeling: 16.5M impressions, 45k conversions, 700 campaigns, CC BY-NC-SA 4.0 [D44]; GA4 obfuscated sample [D3] | Reach is de-duplicated, not summed across campaigns; attribution depends on click and view windows; eCPM, fill rate, viewability and invalid traffic have industry definitions; platform-reported conversions overlap. |
| 20 | **Airlines** [SHIPPED] | 1/0/3/3/3 = **15** | Aviation analytics USD 3.58B (2025) [M30]; vendors 2/10 (appears only inside travel & hospitality pages) | IATA NDC (24.1) and ONE Order (replaces PNR, e-ticket and EMD) [T15], [T14]; OpenTravel [T16] | BTS On-Time Performance, Jan 1995–Jun 2026 [D14]; Maven "Airline Flight Delays", 5M+ flights (2015) [D8] | Load factor = RPK ÷ ASK [X1]: capacity-weighted, never an average of per-flight percentages; CASM/RASM need stage-length adjustment. |
| 21 | **Automotive** (OEMs, dealers, aftersales & warranty, connected vehicles) | 1/1/3/2/1 = **14** | Automotive named in [M1]; Mordor flags automotive as a fast-growing manufacturing-analytics end user [M33]; vendors 4/10 | COVESA Vehicle Signal Specification 6.0 [T38]; STAR dealer–OEM standards (dues-paying) [T39] | fueleconomy.gov vehicle data 1974–2026 [D21]; NHTSA vPIC VIN-decoding API [D22]. No dealer, sales or warranty data. | Warranty rates are claims per 1,000 vehicles by months-in-service and build month (immature cohorts look good); dealer stock is days' supply, not units; recall completion is tracked per VIN. |
| 22 | **Real estate & property management** (multifamily, commercial, REITs, brokerage/PropTech) | 1/0/3/2/2 = **13** | No verified sizing; real estate appears under "Others" in [M2]; only Salesforce Construction & Real Estate [V20] and Tableau Real Estate [V21]; vendors 2/10 | RESO Data Dictionary 2.0 (1,700+ fields; MLS/brokerage focus) [T28] | NYC rolling sales, public [D55]; Inside Airbnb, CC BY 4.0 [D16]; Redfin Data Center (terms unclear) [D56] | Occupancy (physical vs economic), effective rent net of concessions and NOI are as-of rent-roll snapshots; lease events are not transactions to sum; a cap rate must state trailing vs forward NOI. |
| 23 | **Construction & engineering** (general contractors, specialty trades, EPC) | 1/0/3/2/1 = **12** | Big data analytics in construction USD 10.3B (2025), single source, broad definition, not named in horizontal reports [M23]; Salesforce only [V20]; vendors 1/10 | IFC 4.3, ISO 16739-1:2024 (BIM, geometry-oriented) [T35] | NYC DOB permit issuance [D53]; Census construction spending (C30) [D54]. No project cost or schedule data. | Progress is earned value (CPI/SPI) against a baseline; revenue follows percent-complete with over/under billings; cost-to-date alone misleads; retainage and change orders move margin. |
| 24 | **Agriculture & agribusiness** (row crops, livestock, agri-inputs) | 1/0/2/2/2 = **11** | Agriculture analytics USD 1.4B (2023) → 2.5B (2028) [M32]; Microsoft Azure Data Manager for Agriculture (preview) [V12]; vendors 0.5/10 | AgGateway ADAPT, open source [T36] | USDA NASS Quick Stats, public, back to 1870 [D59] | Yield is per harvested acre, not planted, by crop or marketing year; prices depend on basis and grade; seasonality is agronomic, not calendar. |
| 25 | **On-demand marketplaces & mobility** [SHIPPED as food delivery] (food delivery, quick commerce, ride-hailing, micromobility) | 0/0/3/1/3 = **10** | No verified sizing (MarketsandMarkets transportation analytics is a 2019-vintage forecast [M34]); vendors 1/10 | Mobility Data Specification 2.1 (cities ↔ providers) [T30]; GTFS [T29]; GBFS bike-share feeds (via Citi Bike) [D18] | NYC TLC trip records incl. high-volume for-hire vehicle (HVFHV) trips since Feb 2019 [D17]; Meituan food-delivery dispatch data, CC BY-NC 4.0 [D9]; Citi Bike trips [D18] | Gross bookings ≠ net revenue (take rate); utilization is per supply-hour; liquidity is two-sided (fill rate, wait time); the definition of an "active" courier or driver changes every per-head ratio. |

### 2.2 Long tail (ranks 26–29)

| # | Vertical | D/V/K/S/P = score | Demand evidence | Standard | Public dataset(s) | Why an industry package matters |
|---|---|---|---|---|---|---|
| 26 | **Gaming** (mobile, PC/console, live-service) | 1/1/2/0/1 = **10** | No verified sizing (≈USD 2B snippets, Appendix A); Snowflake Gaming [V1], Google Cloud Games [V16], AWS Games [V19]; vendors 3/10 | None found | UCSD Steam datasets: 7.79M reviews across 15,474 games [D43]; 2019 Data Science Bowl game telemetry (not verified) [D62] | Retention is by install cohort (D1/D7/D30); monetization is ARPDAU/ARPPU with payer conversion; pooled averages mix cohorts, platforms and acquisition sources. |
| 27 | **Nonprofit & NGOs** (charities, foundations, international NGOs) | 0/1/2/2/2 = **10** | No sizing; Microsoft Fabric nonprofit data solutions (preview) [V9]; AWS [V19], Salesforce [V20], Tableau Non-for-Profit and Humanitarian [V21]; vendors 3.5/10 | IATI (1,846 publishers, 1M+ activities) [T41]; Microsoft nonprofit data model (vendor) [V9] | IRS Form 990 e-file XML, 2019–2026 [D57]; KDD Cup 1998 donor-mailing data (usage terms apply) [D58] | Restricted vs unrestricted funds; donor retention is cohort-based; program-expense ratios follow Form 990 functional-expense categories; pledges ≠ cash. |
| 28 | **Restaurants / QSR & foodservice** (chains, franchisors, cafés) | 1/0/2/0/1 = **8** | Restaurant-software analytics/BI segment USD 1.42B (2025), the fastest segment at 17.25% CAGR [M31]; no vendor catalog names restaurants (only Databricks' "Restaurants" data-model template [V7]); vendors 0/10 | None found | Yelp Open Dataset: 150k businesses, 6.99M reviews (educational use) [D7]; Maven restaurant/pizza/coffee orders (fictitious) [D8]; Recruit restaurant visitor forecasting (not verified) [D62] | System sales (incl. franchisees) ≠ company revenue (royalties); comps exclude immature units; labor and food cost are % of net sales by daypart; theoretical vs actual food cost. |
| 29 | **Professional services & staffing** (consulting, legal, accounting, agencies, staffing) | 1/0/2/1/0 = **8** | IDC 2021: professional services among top-3 BDA spenders (snippet) [M10]; Salesforce Professional Services only [V20]; Databricks Legal and Staffing & HR templates [V7]; vendors 1/10 | SALI LMSS (legal matters; open taxonomy) [T42] | None found (synthetic data required) | Utilization (billable ÷ available hours) ≠ realization (billed ÷ standard value); WIP and unbilled must be reconciled to avoid double-counting revenue; staffing margin = bill rate − (pay rate + burden). |

### 2.3 Reading the ranking

- **The top is regulated, standards-rich and definition-heavy:** healthcare (27), banking & lending (26), pharma & life sciences (24), insurance (24). All four combine the largest or fastest-growing spend with KPIs whose correct computation is defined by regulators or actuarial practice.
- **Two shipped packages sit in the top six** (retail 24, manufacturing 23). Logistics (20) and SaaS (18) are mid-table. Airline (15) and food delivery (10) rank low on spend evidence but high on knowledge premium and public data, so they are strongest as demonstration and validation packages.
- **Sensitivity.** With the knowledge weight cut to 1 (3D+2V+K+S+P), the top five are the same verticals. With the demand weight cut to 2 (2D+2V+2K+S+P), the top two are unchanged and retail, pharma, insurance and manufacturing tie for ranks 3–6. In both cases ranks 7–14 move by at most ±2 places and the Tier-1 set does not change.

---

## 3. Vertical × vendor matrix

Legend:
- **●** named industry or sub-industry page, industry solution, or accelerator category.
- **◐** only inside a broader industry page, preview or deprecated, or source-shaped packages (dbt).
- **–** not found in the catalog retrieved on 2026-09-14.

**Count** = ● + 0.5 × ◐ over the 10 vendor columns. **DBX tmpl** is Databricks' 40-industry data-model template list [V7], shown but not counted.

Column sources:
- Snowflake [V1]
- Databricks [V2]–[V6]
- Microsoft [V8]–[V13]
- Google Cloud [V15]–[V18]; the docs page plus the solutions listing, which was too large to fetch and was read via search summary. Its Energy entry appears in only one listing, hence ◐.
- AWS [V19]
- Salesforce [V20]
- Tableau Accelerators [V21]
- ThoughtSpot [V22], [V23]
- Sigma [V24]
- dbt Package Hub [V27]–[V29]

| # | Vertical | Snowflake | Databricks | Microsoft | Google Cloud | AWS | Salesforce | Tableau | ThoughtSpot | Sigma | dbt Hub | **Count** | DBX tmpl |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Healthcare providers & payers | ● | ● | ● | ● | ● | ● | ● | ● | ● | ● | **10** | ● |
| 2 | Banking & lending | ● | ● | ● | ● | ● | ● | ● | ● | ● | – | **9** | ● |
| 3 | Retail & e-commerce [SHIPPED] | ● | ● | ◐ | ● | ● | ● | ● | ● | ● | ● | **9.5** | ● |
| 4 | Pharma & life sciences | ● | ● | – | ● | ● | ● | ● | ● | ◐ | – | **7.5** | ● |
| 5 | Insurance (P&C, life) | ● | ◐ | ◐ | ◐ | ◐ | ◐ | ● | ● | ◐ | – | **6** | ◐ |
| 6 | Manufacturing [SHIPPED] | ● | ● | ● | ● | ● | ● | ● | ● | ● | – | **9** | ● |
| 7 | Energy & utilities | ● | ● | ◐ | ◐ | ● | ● | ● | – | – | – | **6** | ● |
| 8 | Telecommunications | ● | ● | ◐ | ● | ● | ● | ● | ● | – | – | **7.5** | ● |
| 9 | CPG / consumer brands | ● | ● | – | ● | ● | ● | – | ● | ● | ◐ | **7.5** | ● |
| 10 | Public sector | ● | ● | ◐ | ● | ● | ● | ● | – | – | – | **6.5** | ◐ |
| 11 | Education | ● | – | – | ● | ● | ● | ● | – | – | – | **5** | ● |
| 12 | Payments, fintech & digital assets | ● | ◐ | – | ◐ | ◐ | ◐ | – | ◐ | ◐ | ◐ | **4.5** | ● |
| 13 | Logistics, freight & last-mile [SHIPPED] | ● | – | – | ● | – | ● | ◐ | ◐ | – | – | **4** | ● |
| 14 | Oil, gas & mining | ◐ | ◐ | ◐ | – | ◐ | ◐ | ◐ | – | – | – | **3** | ● |
| 15 | SaaS / technology & software [SHIPPED] | ● | ● | – | – | – | ● | ● | ● | – | ◐ | **5.5** | – |
| 16 | Capital markets & wealth/asset mgmt | ● | ◐ | ◐ | ◐ | ◐ | ◐ | ● | ◐ | ◐ | – | **5.5** | – |
| 17 | Media, streaming & publishing | ● | ● | ◐ | ● | ● | ● | ◐ | ● | – | – | **7** | ● |
| 18 | Travel & hospitality | ● | – | – | – | ● | ● | ● | ● | – | – | **5** | ● |
| 19 | Advertising, adtech & martech | ● | ◐ | – | – | ● | – | ◐ | – | – | ◐ | **3.5** | ● |
| 20 | Airlines [SHIPPED] | ◐ | – | – | – | ◐ | ◐ | – | ◐ | – | – | **2** | ● |
| 21 | Automotive | ● | – | ◐ | ◐ | ● | ● | – | – | – | – | **4** | ● |
| 22 | Real estate & property management | – | – | – | – | – | ● | ● | – | – | – | **2** | ● |
| 23 | Construction & engineering | – | – | – | – | – | ● | – | – | – | – | **1** | ● |
| 24 | Agriculture & agribusiness | – | – | ◐ | – | – | – | – | – | – | – | **0.5** | ● |
| 25 | On-demand marketplaces & mobility [SHIPPED] | – | – | – | ◐ | – | ◐ | – | – | – | – | **1** | – |
| 26 | Gaming | ● | – | – | ● | ● | – | – | – | – | – | **3** | ● |
| 27 | Nonprofit & NGOs | – | – | ◐ | – | ● | ● | ● | – | – | – | **3.5** | ● |
| 28 | Restaurants / QSR | – | – | – | – | – | – | – | – | – | – | **0** | ● |
| 29 | Professional services & staffing | – | – | – | – | – | ● | – | – | – | – | **1** | ● |
| | **● named / ◐ partial (of 29)** | 20 / 2 | 11 / 5 | 3 / 11 | 12 / 6 | 16 / 5 | 19 / 6 | 15 / 4 | 11 / 4 | 5 / 4 | 2 / 4 | | 24 / 2 |

### 3.1 What the matrix says

- **Universal verticals (≥ 9 of 10 catalogs):** healthcare (10), retail (9.5), banking (9), manufacturing (9). **Next band (6–7.5):** pharma, telecom and CPG (7.5 each), media (7), public sector (6.5), insurance and energy (6 each).
- **Broadest catalogs:** Snowflake (20 named) and Salesforce (19 named). **Microsoft is contracting:** its Fabric industry data-solutions page now lists only healthcare, the DAX Copilot integration, and nonprofit (preview) [V9]. The Microsoft-for-Retail deprecations page on Learn now redirects to a marketing page [V13]; a search snippet said retail data solutions moved to a GitHub repository in Nov 2025 (not verified).
- **The BI tools are thin on verticals.** Sigma lists 4 industries [V24]. Hex [V25] and Mode (now ThoughtSpot) [V26] list none. Google's Cortex Framework currently documents SAP-only data foundations (SAP ECC, S/4HANA, Business Data Cloud) with two SAP solution samples [V17]. The dbt Hub is source-shaped (Shopify, ad platforms, Stripe/Zuora/Recurly billing, NetSuite/QuickBooks, Workday/Greenhouse); its only true vertical data models are healthcare (the Tuva Project, Google's FHIR packages) [V27], [V29].
- **The closest analogue to Aughor's packages is ThoughtSpot "Spotter for Industries"** (18 Mar 2026): industry agents for healthcare & life sciences, retail & CPG, financial services, technology & software, supply chain, media & telecom, insurance, travel & hospitality and manufacturing [V23]. Its choice of insurance and travel & hospitality as separate agents independently supports Tier 1 (insurance) and Tier 2 (travel & hospitality) below.
- **Long-tail verticals are covered by generation, not curation.** Databricks' data-model repository generates schemas for 40 industries, including restaurants, airlines, grocery, legal, staffing, water utilities and waste management [V7], none of which a BI catalog names. Aughor could do the same: a curated package for Tiers 1–2 plus an LLM-drafted "starter pack" for the long tail. Microsoft's Fabric IQ ontology (preview) is generic ontology tooling, not industry content [V14].

---

## 4. Horizontal / functional domains (cut across industries: build as importable "functional packs")

| Functional domain | Demand evidence | Vendor catalog evidence | Standard | Public dataset(s) | Why a functional pack matters |
|---|---|---|---|---|---|
| **Finance / FP&A & accounting** (close, P&L, AR/AP, spend) | Financial planning software USD 5.63B (2024) → 25.16B (2034) [M39] | Tableau "Corporate Finance" [V21]; Sigma "Finance" team solution [V24]; Databricks `financial-kpi-reporting` app [V6]; dbt NetSuite / QuickBooks / Sage Intacct / Xero packages [V27]; Google Cortex SAP samples [V17] | XBRL (the SEC data sets are XBRL-derived) [D61] | SEC Financial Statement Data Sets, 2009–2026 [D61] | Fiscal calendars and closed periods; credit-normal sign conventions; balances vs activity; accrual vs cash; FX translation and intercompany eliminations. |
| **Marketing analytics & attribution** | USD 7.12B (2025); retail is the largest end user (23.32%) [M35] | Databricks "Marketing" solution [V2] and `media-mix-modeling` repo [V6]; Snowflake AdTech & MarTech [V1]; Tableau Marketing, Digital & Social Media [V21]; dbt `ad_reporting` + 13 ad-platform packages [V27] | None on the advertiser side (IAB OpenRTB covers ad supply) [T27] | GA4 obfuscated sample (Google Merchandise Store, Nov 2020–Jan 2021) [D3]; Criteo attribution [D44] | Platform-reported conversions overlap and must be de-duplicated; attribution windows differ by platform; spend needs currency and time-zone normalization; attributed ≠ incremental. |
| **Sales / RevOps** | Sales intelligence USD 4.42B (2025) [M38] | ThoughtSpot "Sales Operations" [V22]; Sigma "Sales & Operations" [V24]; Tableau Sales, ERP & CRM [V21]; dbt Salesforce / HubSpot / Pipedrive / Dynamics 365 CRM [V27] | None (CRM object models are de facto) | Maven "CRM Sales Opportunities", fictitious B2B pipeline, 8,800 records [D8] | Pipeline is read from stage-history snapshots; win rate only over closed opportunities; bookings vs ACV vs TCV; quota attainment on effective-dated territories. |
| **Customer analytics & CX** (segmentation, CLV, churn, support) | USD 17.58B (2026); retail largest (20.70%), healthcare fastest (21.90% CAGR) [M36] | Tableau "Customer Service" [V21]; dbt Intercom, ServiceNow packages [V27] | None | UCI Online Retail II (RFM/CLV) [D2]; Maven "Bank Customer Churn", 10k customers [D8] | CLV needs margin and a discount rate; non-contractual churn needs an inactivity definition; retention is cohort-based, not pooled. |
| **Product analytics** (events, funnels, retention) | USD 9.6B (2021) → 25.3B (2026), 2021-vintage report [M40] | ThoughtSpot "Product Leader" role solution [V22]; Hex positions on functional use cases and lists no verticals [V25] | None (event schemas are vendor-specific, e.g. the GA4 export) | GA4 obfuscated sample [D3] | Sessionization and identity stitching; event de-duplication; DAU/MAU need a defined "active" event; funnels need ordering and time windows. |
| **HR / people analytics** | USD 4.89B (2025); IT & telecom largest (23.62%), healthcare & life sciences fastest (14.11% CAGR) [M37] | Tableau "Human Resources" [V21]; dbt Workday / Greenhouse / Lever / Personio [V27]; Databricks "Staffing & HR" template [V7] | HR Open Standards (free) [T40] | IBM HR Analytics Attrition (fictional, created by IBM; ODbL on Kaggle) [D60] | Headcount is point-in-time from effective-dated records; annualized turnover uses average headcount; FTE ≠ heads; small-group privacy thresholds. |
| **Supply chain & procurement** (planning, inventory, sourcing, spend) | USD 9.37B (2025; retail & e-commerce largest at 24.45%, HLS fastest at 25.8%) [M24]; USD 11.08B (2025) [M25] | ThoughtSpot "Supply Chain" and "Procurement" [V22]; Sigma "Supply Chain" [V24]; Tableau Supply Chain & Manufacturing, Procurement [V21]; Google Supply Chain & Logistics [V16] and Cortex "SAP Supplier Spend Analysis" [V17] | GS1 EPCIS 2.0 [T17] | DataCo Smart Supply Chain, CC BY 4.0 [D12] | Inventory is a snapshot and never summed over time; fill rate vs OTIF definitions; lead times are distributions, not means; unit-of-measure conversions. |
| **Risk, fraud & compliance** | Fraud detection & prevention is the fastest-growing data-analytics application (14.70% CAGR, 2025) [M5] | Google Cloud Anti Money Laundering AI [V15]; Databricks `anti-money-laundering` accelerator [V6]; Tableau "Fraudulent Claims" accelerator [V21] | ISO 20022 (payments data) [T8] | PaySim [D28]; ULB card fraud [D29]; Elliptic [D31] | Extreme class imbalance and label delay; precision at a fixed review capacity; alerts, cases and regulatory reports are different grains. |
| **ESG / sustainability** | No verified sizing | Microsoft for Sustainability [V8]; AWS Sustainability [V19]; Tableau ESG [V21]; Databricks `esg-scoring` repo [V6] | GHG Protocol Corporate Standard (Scopes 1–3) [T43] | No public corporate-emissions ledger verified; EIA energy data [D46] | Scope boundaries; location- vs market-based Scope 2; emission factors vary by region and year. |
| **IT operations & security** | Not assessed | Databricks "Cybersecurity" solution [V2] and `security-analysis-tool` [V6]; Tableau ITSM [V21]; dbt ServiceNow / Jira [V27] | Not assessed | Not assessed | Alert vs incident grain; MTTD vs MTTR definitions. |

**Implication.** Retail is the largest end user of three functional markets (marketing, customer, supply chain), and healthcare is the fastest grower in three (customer, supply chain, HR). Each vertical package should *import* functional packs rather than re-derive them. Insurance and banking import finance + risk/fraud + customer; healthcare imports finance + HR (clinical staffing); CPG imports marketing + supply chain. Build **finance** and **risk/fraud** alongside Tier 1, because all three Tier-1 verticals need them.

---

## 5. Build tiers and reasoning

### 5.1 Tiering principles

The score in §2 measures market pull and knowledge premium. The tiers also weigh four build and go-to-market factors:

1. **Adjacency to shipped packages**, which lowers cost: airline → hotels/travel; retail → CPG, grocery, restaurants; food delivery → mobility, restaurants; SaaS → telecom subscriptions, gaming; banking → payments, capital markets; healthcare → pharma.
2. **End-to-end validation feasibility**: a realistic, licence-clear dataset to run explorations, KPI recipes and diagnostic playbooks against before release.
3. **Deployment friction**: PHI/HIPAA (needs BAA-covered or local models), FERPA, public-sector procurement.
4. **Where the data lives**: warehouse-shaped business data the agent can query, as opposed to specialist engineering systems (subsurface, BIM) or licensed third-party panels.

### 5.2 Tier 1: build now

| Package | Rank / score | Reasoning | Seed from | Validate on | First KPI recipes and playbooks |
|---|---|---|---|---|---|
| **Banking & lending** | #2 / 26 | Largest analytics buyer (BFSI first in 5 of 8 reports) [M1], [M4], [M5], [M7], [M8]; IDC #2 AI spender [M9]; 9/10 catalogs; maximal knowledge premium; unlocks Payments and Capital markets (Tier 2–3) by reuse | BIAN service domains [T6] and FIBO concepts [T7] for the ontology; ISO 20022 [T8] / FDX [T9] for transaction semantics; MISMO [T10] for the mortgage module | Berka (relational accounts, transactions, loans, cards) [D23]; Freddie Mac loan-level (vintages, roll rates) [D26]; HMDA (application funnel) [D27] | NIM on average earning assets [X8]; deposit mix and cost of funds; delinquency roll rates by vintage; net charge-off rate; loan-to-deposit ratio. **Playbook:** "delinquency up → first separate vintage mix and seasoning from true deterioration." |
| **Insurance (P&C + life)** | #5 / 24 | BFSI demand plus a sizable standalone market (USD 19.3–43.2B, 2025) [M16], [M17]; ThoughtSpot made insurance a dedicated industry agent [V23]; Microsoft ships a P&C data model [V11]; the actuarial definitions are exactly where a generic agent fails | ACORD (transactions, NGDS object model) [T12] | freMTPL2 (frequency and severity per exposure) [D33]; CAS Schedule P triangles (reserving, development) [D34] | Earned premium; loss and combined ratio by accident year [X3]; frequency and severity per exposure-year; IBNR / development factors; retention and lapse; quote-to-bind. **Playbook:** "current accident-year loss ratio spikes → check development immaturity before concluding the rates are inadequate." |
| **Healthcare: payer/claims module first, provider module second** | #1 / 27 | 10/10 catalogs; fastest-growing vertical [M1], [M6], [M7]; payers held the dominant share of big-data healthcare analytics in 2025 [M14]; the strongest open seeds of any vertical. **Risk:** PHI, so ship with de-identified validation data and document BAA/local-model deployment. | X12 837/835 v5010 claim semantics [T3]; OMOP CDM [T2]; FHIR R5 [T1]; Tuva's open dbt data marts (PMPM, CMS-HCC, chronic conditions, readmissions) [V29] | CMS DE-SynPUF (claims) [D37]; Synthea (clinical, FHIR/CSV) [D35]; MIMIC-IV demo (hospital/ICU) [D36] | **Payer:** member-months, PMPM (paid and allowed), MLR [X7], utilization per 1,000, risk score, claims lag/completion, denial rate. **Provider:** ALOS by DRG, 30-day readmissions, occupancy, payer mix, days in A/R. **Playbook:** "latest month's PMPM drops → incomplete runout, not savings." |

**Why pharma is not Tier 1 despite ranking #4.** Its commercial data is licensed syndicated data that is often not in a customer's warehouse in raw form. There is no public commercial prescription dataset to validate against (only openFDA and ClinicalTrials.gov/AACT) [D38], [D39]. It reuses the healthcare code sets and OMOP ontology, so it is cheaper to build after healthcare. **Retail (#3) and manufacturing (#6) are already shipped.**

### 5.3 Tier 2: next

| Package | Rank / score | Reasoning (evidence + adjacency) |
|---|---|---|
| **Pharma & life sciences** | #4 / 24 | 7.5/10 catalogs; life-science analytics US$35.69B (2024) [M15]; SDTM is regulator-required [T5]. Build on the Tier-1 healthcare ontology. Modules: commercial (TRx/NRx, share, persistence), clinical operations (enrollment, site activation; AACT [D39]), pharmacovigilance (FAERS via openFDA [D38]). |
| **Energy & utilities** | #7 / 22 | 6/10 catalogs; USD 5.36B (2025) [M28]; two mature standards (IEC CIM [T20], Green Button [T21]); a large CC-BY smart-meter dataset [D45] plus EIA [D46]; high knowledge premium (SAIDI/SAIFI [X4], weather normalization, interval data). |
| **Telecommunications** | #8 / 21 | 7.5/10 catalogs; USD 8.09B (2025) [M26]; reuses the shipped SaaS subscription logic (churn, cohorts, ARPU [X9]). Validation is the weak point (IBM Telco sample [D40], Telecom Italia [D41]). **Verify TM Forum SID access terms before seeding [T13].** |
| **CPG / consumer brands** | #9 / 20 | 7.5/10 catalogs; reuses the shipped retail ontology (product, store, promotion, calendar). dunnhumby promo and household-panel data [D5]; Kilts NielsenIQ for academic validation [D6]. The sell-in vs sell-through and trade-promotion logic is where generic analytics fails. |
| **Payments, fintech & digital assets** | #12 / 20 | Reuses the Tier-1 banking party/account/transaction ontology plus shipped SaaS metrics. The best open validation data of any financial vertical: PaySim [D28], ULB [D29], TabFormer [D30], and for the crypto module the BigQuery Ethereum dataset [D32] and Elliptic [D31]. |
| **Travel & hospitality** (hotels, short-term rentals, OTAs, car rental) | #18 / 16 | Low spend evidence (USD 4.1B hospitality RM analytics [M29]) but the **cheapest build of any new vertical**: the shipped airline package already models capacity × rate × occupancy, booking curves and cancellations. Two CC-BY datasets [D15], [D16]; ThoughtSpot made travel & hospitality its own agent [V23]. |

### 5.4 Tier 3: later (pull-based; build when a design partner or usage asks)

- **Public sector (#10 / 20).** NIEM [T31] and OCDS [T32] plus USAspending [D51] and NYC 311 [D52] make strong demos, but procurement cycles are long.
- **Education (#11 / 20).** Ed-Fi [T24], CEDS [T25], OULAD [D49] and IPEDS [D50] are good seeds. FERPA and tight budgets slow adoption; start with higher-ed and IPEDS-style metrics.
- **Capital markets & wealth (#16 / 18).** High knowledge premium (time-weighted returns, flows vs markets), but no public holdings or transaction data, so it needs design-partner data.
- **Media & streaming (#17 / 17) together with Advertising/adtech (#19 / 16).** Build as one pair sharing an audience, impression and revenue ontology (DDEX/EIDR [T33], [T34]; OpenRTB [T27]). Open data is limited: Criteo is CC BY-NC-SA [D44], and MovieLens restricts redistribution [D42].
- **Oil, gas & mining (#14 / 19).** OSDU/PPDM [T22], [T23]; Volve [D47] and Texas RRC [D48]. Much of the data sits in specialist engineering systems; start with production accounting.
- **Automotive (#21 / 14).** Extends shipped manufacturing (quality, warranty) and retail (dealer stock). No public dealer or warranty data [D21], [D22].
- **Restaurants / QSR (#28 / 8), as a module.** Weakest vendor evidence, but a cheap extension of shipped food delivery and retail (orders, menu items, stores, dayparts). Its analytics/BI segment is the fastest-growing restaurant-software category (17.25% CAGR) [M31].

### 5.5 Tier 4: on demand (LLM-drafted "starter packs" from the standard, promoted to curated only on pull)

- Real estate & property management (#22): seed from RESO [T28].
- Construction & engineering (#23): seed from IFC [T35].
- Agriculture (#24): seed from ADAPT [T36].
- Gaming (#26): reuse the SaaS and product-analytics packs.
- Nonprofit & NGOs (#27): seed from IATI [T41].
- Professional services & staffing (#29): seed from SALI [T42].
- Mobility: an extension of the shipped on-demand marketplace package, validated on NYC TLC [D17] and Citi Bike [D18].

### 5.6 Suggested order

1. Banking & lending, together with the **finance** and **risk/fraud** functional packs.
2. Insurance.
3. Healthcare payer module.
4. Payments & fintech (reuses step 1).
5. Healthcare provider module, then pharma (reuse step 3).
6. CPG (reuses retail) and travel & hospitality (reuses airline).
7. Energy & utilities and telecommunications.
8. Tier 3, pull-based.

---

## 6. Sources

All pages were fetched or listed on 2026-09-14. "(search result)" means the URL and title came from a search listing; "(403)" means automated fetch was refused and a fallback source is used.

### M: Market research
- [M1] Fortune Business Insights, Big Data Analytics Market (summary): https://www.fortunebusinessinsights.com/big-data-analytics-market-106179
- [M2] Fortune Business Insights, Business Intelligence Market (summary): https://www.fortunebusinessinsights.com/business-intelligence-bi-market-103742
- [M3] Precedence Research, Business Intelligence Market (summary): https://www.precedenceresearch.com/business-intelligence-market
- [M4] Mordor Intelligence, Business Intelligence Market (summary): https://www.mordorintelligence.com/industry-reports/global-business-intelligence-bi-vendors-market-industry
- [M5] Precedence Research, Data Analytics Market (summary): https://www.precedenceresearch.com/data-analytics-market
- [M6] Mordor Intelligence, Data Analytics Market (summary): https://www.mordorintelligence.com/industry-reports/data-analytics-market
- [M7] Mordor Intelligence, Advanced Analytics Market (summary): https://www.mordorintelligence.com/industry-reports/advanced-analytics-market
- [M8] MarketsandMarkets press release, Big Data Market (23 Mar 2026): https://www.marketsandmarkets.com/PressReleases/big-data.asp
- [M9] IDC blog, Worldwide AI and Generative AI Spending: Industry Outlook (21 Aug 2024): https://www.idc.com/resource-center/blog/idcs-worldwide-ai-and-generative-ai-spending-industry-outlook/
- [M10] IDC press release via Business Wire, BDA spending 2021 (403; snippet only): https://www.businesswire.com/news/home/20210817005182/en/Global-Spending-on-Big-Data-and-Analytics-Solutions-Will-Reach-215.7-Billion-in-2021-According-to-a-New-IDC-Spending-Guide
- [M11] IDC Data & Analytics Spending Guide (product page): https://www.idc.com/data-analytics/spending-guide/
- [M12] Gartner, Forecast: Enterprise IT Spending by Vertical Industry Market 2023–2029, 2Q25 (paywalled; title only): https://www.gartner.com/en/documents/6706134
- [M13] MarketsandMarkets via PR Newswire, Healthcare Analytics Market (23 Jan 2026): https://www.prnewswire.com/news-releases/healthcare-analytics-market-worth-166-65-billion-by-2030--marketsandmarkets-302668799.html
- [M14] Precedence Research, Big Data Analytics in Healthcare Market: https://www.precedenceresearch.com/big-data-analytics-in-healthcare-market
- [M15] MarketsandMarkets via PR Newswire, Life Science Analytics Market (2 May 2025): https://www.prnewswire.com/news-releases/life-science-analytics-market-worth-68-81-billion-by-2030-11-4-cagr--marketsandmarkets-302444901.html
- [M16] Fortune Business Insights, Insurance Analytics Market: https://www.fortunebusinessinsights.com/insurance-analytics-market-108489
- [M17] Mordor Intelligence, Insurance Analytics Market: https://www.mordorintelligence.com/industry-reports/insurance-analytics-market
- [M18] Mordor Intelligence, Big Data Analytics in Banking Market: https://www.mordorintelligence.com/industry-reports/big-data-in-banking-industry
- [M19] MarketsandMarkets, Retail Analytics Market (research insight): https://www.marketsandmarkets.com/ResearchInsight/size-and-shares-of-retail-analytics-market.asp
- [M20] Mordor Intelligence, Retail Analytics Market: https://www.mordorintelligence.com/industry-reports/retail-analytics-market
- [M21] Mordor Intelligence, Learning Analytics Market: https://www.mordorintelligence.com/industry-reports/learning-analytics-market
- [M22] Precedence Research, Oil and Gas Analytics Market: https://www.precedenceresearch.com/oil-and-gas-analytics-market
- [M23] Global Market Insights, Big Data Analytics in Construction Market: https://www.gminsights.com/industry-analysis/big-data-analytics-in-construction-market
- [M24] Mordor Intelligence, Supply Chain Analytics Market: https://www.mordorintelligence.com/industry-reports/supply-chain-analytics-market
- [M25] Fortune Business Insights, Supply Chain Analytics Market: https://www.fortunebusinessinsights.com/supply-chain-analytics-market-108632
- [M26] Mordor Intelligence, Telecom Analytics Market: https://www.mordorintelligence.com/industry-reports/telecom-analytics-market
- [M27] Fortune Business Insights, Sports Analytics Market: https://www.fortunebusinessinsights.com/sports-analytics-market-102217
- [M28] MarketsandMarkets, Energy and Utilities Analytics Market: https://www.marketsandmarkets.com/Market-Reports/energy-analytics-utility-market-993.html
- [M29] Global Market Insights, Hospitality Revenue Management & Pricing Analytics Market: https://www.gminsights.com/industry-analysis/hospitality-revenue-management-and-pricing-analytics-market
- [M30] Precedence Research, Aviation Analytics Market: https://www.precedenceresearch.com/aviation-analytics-market
- [M31] Mordor Intelligence, Restaurant Management Software Market: https://www.mordorintelligence.com/industry-reports/restaurant-management-software-market
- [M32] MarketsandMarkets, Agriculture Analytics Market: https://www.marketsandmarkets.com/Market-Reports/agriculture-analytics-market-255757945.html
- [M33] Mordor Intelligence, Manufacturing Analytics Market: https://www.mordorintelligence.com/industry-reports/manufacturing-analytics-market
- [M34] MarketsandMarkets, Transportation Analytics Market (2019-vintage forecast): https://www.marketsandmarkets.com/Market-Reports/transportation-analytics-market-77033915.html
- [M35] Mordor Intelligence, Marketing Analytics Market: https://www.mordorintelligence.com/industry-reports/marketing-analytics-market
- [M36] Mordor Intelligence, Customer Analytics Market: https://www.mordorintelligence.com/industry-reports/customer-analytics-market
- [M37] Mordor Intelligence, HR Analytics Market: https://www.mordorintelligence.com/industry-reports/hr-analytics-market
- [M38] Mordor Intelligence, Sales Intelligence Market: https://www.mordorintelligence.com/industry-reports/sales-intelligence-market
- [M39] Polaris Market Research, Financial Planning Software Market: https://www.polarismarketresearch.com/industry-analysis/financial-planning-software-market
- [M40] MarketsandMarkets, Product Analytics Market (2021-vintage): https://www.marketsandmarkets.com/Market-Reports/product-analytics-market-194329984.html

### V: Vendor industry catalogs
- [V1] Snowflake, Industries: https://www.snowflake.com/en/solutions/industries/
- [V2] Databricks, Solutions (industries + cross-industry): https://www.databricks.com/solutions
- [V3] Databricks, Solution Accelerators: https://www.databricks.com/solutions/accelerators
- [V4] Databricks, Media & Entertainment: https://www.databricks.com/solutions/industries/media-and-entertainment
- [V5] Databricks, Manufacturing: https://www.databricks.com/solutions/industries/manufacturing-industry-solutions
- [V6] GitHub, databricks-industry-solutions organization (224 repositories): https://github.com/databricks-industry-solutions
- [V7] GitHub, databricks-industry-solutions/lakehouse-industry-data-models (40 industry templates): https://github.com/databricks-industry-solutions/lakehouse-industry-data-models
- [V8] Microsoft Learn, industry documentation hub: https://learn.microsoft.com/en-us/industry/
- [V9] Microsoft Learn, Industry Solutions in Microsoft Fabric: https://learn.microsoft.com/en-us/industry/industry-data-solutions-fabric
- [V10] Microsoft Learn, Financial services data model and entity reference (search result): https://learn.microsoft.com/en-us/dynamics365/industry/financial-services/overview-data-model
- [V11] Microsoft Learn, Deploy the property and casualty insurance data model (preview) (search result): https://learn.microsoft.com/en-us/dynamics365/industry/financial-services/deploy-insurance-data-model
- [V12] Microsoft Learn, Azure Data Manager for Agriculture (preview): https://learn.microsoft.com/en-us/azure/data-manager-for-agri/
- [V13] Microsoft Learn, Microsoft for Retail deprecations (now redirects to https://www.microsoft.com/en-in/ai/retail): https://learn.microsoft.com/en-us/industry/retail/whats-new-deprecations
- [V14] Microsoft Learn, Fabric IQ, What is Ontology (preview)? (search result): https://learn.microsoft.com/en-us/fabric/iq/ontology/overview
- [V15] Google Cloud, Industry solutions documentation: https://docs.cloud.google.com/docs/industry
- [V16] Google Cloud, Cloud solutions listing (read via search summary): https://cloud.google.com/solutions
- [V17] Google Cloud, Cortex Framework overview: https://docs.cloud.google.com/cortex/docs/overview
- [V18] Looker Marketplace, Retail Analytics Block (search result): https://marketplace.looker.com/marketplace/detail/retail-block-v2
- [V19] AWS, Industries: https://aws.amazon.com/industries/
- [V20] Salesforce, Industries: https://www.salesforce.com/industries/
- [V21] Tableau Exchange, Accelerators: https://exchange.tableau.com/en-us/accelerators
- [V22] ThoughtSpot, Solutions: https://www.thoughtspot.com/solutions
- [V23] ThoughtSpot press release, Spotter for Industries (18 Mar 2026): https://www.thoughtspot.com/press-releases/thoughtspot-launches-spotter-for-industries-purpose-built-agents-transform-complex-industry-content-into-trusted-actionable-insights
- [V24] Sigma Computing (solutions navigation): https://www.sigmacomputing.com/
- [V25] Hex: https://hex.tech/
- [V26] Mode (ThoughtSpot acquisition banner): https://mode.com/
- [V27] dbt Package Hub: https://hub.getdbt.com/
- [V28] dbt Package Hub, fivetran/stripe: https://hub.getdbt.com/fivetran/stripe/latest/
- [V29] The Tuva Project: https://thetuvaproject.com/

### T: Standards and data models
- [T1] HL7 FHIR (current published version R5, 5.0.0): https://hl7.org/fhir/
- [T2] OHDSI OMOP Common Data Model: https://ohdsi.github.io/CommonDataModel/
- [T3] CMS, HIPAA adopted standards and operating rules (X12 v5010 837/835/270/271/276/277/278; NCPDP D.0): https://www.cms.gov/priorities/key-initiatives/burden-reduction/administrative-simplification/hipaa/adopted-standards-operating-rules
- [T4] X12, transaction sets (licensed products): https://x12.org/products/transaction-sets
- [T5] CDISC, SDTM (v2.1, June 2024; required by FDA and PMDA): https://www.cdisc.org/standards/foundational/sdtm
- [T6] BIAN (Service Landscape 14.0): https://bian.org/
- [T7] EDM Council, FIBO: https://spec.edmcouncil.org/fibo/
- [T8] ISO 20022 (Wikipedia; iso20022.org 403): https://en.wikipedia.org/wiki/ISO_20022
- [T9] Financial Data Exchange (FDX): https://financialdataexchange.org/
- [T10] MISMO (Wikipedia; mismo.org 403): https://en.wikipedia.org/wiki/MISMO
- [T11] Freddie Mac, Uniform Loan Delivery Dataset (MISMO v3.0): https://sf.freddiemac.com/tools-learning/uniform-mortgage-data-program/uldd
- [T12] ACORD (Wikipedia; acord.org 403): https://en.wikipedia.org/wiki/ACORD
- [T13] TM Forum, Information Framework (SID) (403; NOT verified): https://www.tmforum.org/oda/information-systems/information-framework-sid/
- [T14] IATA, ONE Order: https://www.iata.org/en/programs/airline-distribution/retailing/one-order/
- [T15] IATA, NDC: https://www.iata.org/en/programs/airline-distribution/retailing/ndc/
- [T16] OpenTravel Alliance (Wikipedia; opentravel.org 403): https://en.wikipedia.org/wiki/OpenTravel_Alliance
- [T17] GS1, EPCIS 2.0 reference: https://ref.gs1.org/standards/epcis/
- [T18] ARTS, Association for Retail Technology Standards (Wikipedia): https://en.wikipedia.org/wiki/Association_for_Retail_Technology_Standards
- [T19] ISA, ISA-95 standard: https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard
- [T20] IEC Common Information Model (Wikipedia; cimug.ucaiug.org 403): https://en.wikipedia.org/wiki/Common_Information_Model_(electricity)
- [T21] Green Button Alliance: https://www.greenbuttonalliance.org/
- [T22] The Open Group, OSDU Forum: https://www.opengroup.org/osdu-forum/
- [T23] PPDM Association: https://ppdm.org/ppdm
- [T24] Ed-Fi Alliance: https://www.ed-fi.org/
- [T25] Common Education Data Standards (CEDS): https://ceds.ed.gov/
- [T26] 1EdTech, Caliper Analytics: https://www.1edtech.org/standards/caliper
- [T27] IAB Tech Lab, OpenRTB: https://iabtechlab.com/standards/openrtb/
- [T28] RESO, Data Dictionary: https://www.reso.org/data-dictionary/
- [T29] GTFS: https://gtfs.org/
- [T30] Open Mobility Foundation, Mobility Data Specification: https://www.openmobilityfoundation.org/about-mds/
- [T31] NIEMOpen (OASIS): https://niemopen.org/
- [T32] Open Contracting Data Standard: https://standard.open-contracting.org/
- [T33] DDEX: https://ddex.net/
- [T34] EIDR: https://www.eidr.org/
- [T35] Industry Foundation Classes (Wikipedia; buildingSMART technical site 403): https://en.wikipedia.org/wiki/Industry_Foundation_Classes
- [T36] AgGateway ADAPT: https://adaptframework.org/
- [T37] DCSA, Standards: https://dcsa.org/standards
- [T38] COVESA, Vehicle Signal Specification: https://covesa.github.io/vehicle_signal_specification/
- [T39] STAR, Standards for Technology in Automotive Retail: https://www.starstandard.org/
- [T40] HR Open Standards: https://hropenstandards.org/
- [T41] IATI Standard: https://iatistandard.org/en/
- [T42] SALI Alliance (LMSS): https://www.sali.org/
- [T43] GHG Protocol, Corporate Standard: https://ghgprotocol.org/corporate-standard

### D: Public datasets
Kaggle licences were read from Kaggle's public dataset-metadata API (`https://www.kaggle.com/api/v1/datasets/view/{owner}/{dataset}`).
- [D1] Olist Brazilian E-Commerce (CC BY-NC-SA 4.0): https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
- [D2] UCI, Online Retail II (CC BY 4.0): https://archive.ics.uci.edu/dataset/502/online+retail+ii
- [D3] Google, GA4 obfuscated sample ecommerce dataset: https://developers.google.com/analytics/bigquery/web-ecommerce-demo-dataset
- [D4] Instacart Market Basket Analysis (Kaggle mirror, CC0 per mirror metadata; original Instacart terms not verified): https://www.kaggle.com/datasets/psparks/instacart-market-basket-analysis
- [D5] dunnhumby, Source Files: https://www.dunnhumby.com/source-files/
- [D6] Kilts Center, Chicago Booth, NielsenIQ data (academic): https://www.chicagobooth.edu/research/kilts/research-data/nielseniq
- [D7] Yelp Open Dataset (educational use): https://business.yelp.com/data/resources/open-dataset/
- [D8] Maven Analytics, Data Playground: https://mavenanalytics.io/data-playground
- [D9] Meituan INFORMS TSL Research Challenge data (CC BY-NC 4.0): https://github.com/meituan/Meituan-INFORMS-TSL-Research-Challenge
- [D10] LaDe last-mile delivery dataset (Apache-2.0): https://huggingface.co/datasets/Cainiao-AI/LaDe
- [D11] Amazon Last Mile Routing Research Challenge (CC BY-NC 4.0): https://registry.opendata.aws/amazon-last-mile-challenges/
- [D12] DataCo Smart Supply Chain (CC BY 4.0): https://data.mendeley.com/datasets/8gx2fvg2k6/5
- [D13] Freight Analysis Framework v5: https://faf.ornl.gov/faf5/
- [D14] BTS, On-Time performance: https://www.transtats.bts.gov/ontime/
- [D15] Hotel booking demand (CC BY 4.0) and TidyTuesday readme: https://www.kaggle.com/datasets/jessemostipak/hotel-booking-demand and https://github.com/rfordatascience/tidytuesday/blob/main/data/2020/2020-02-11/readme.md
- [D16] Inside Airbnb (CC BY 4.0): https://insideairbnb.com/get-the-data/
- [D17] NYC TLC, Trip record data: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
- [D18] Citi Bike, System data (NYCBS Data Use Policy; GBFS): https://citibikenyc.com/system-data
- [D19] UCI, AI4I 2020 Predictive Maintenance (CC BY 4.0): https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset
- [D20] UCI, SECOM (CC BY 4.0): https://archive.ics.uci.edu/dataset/179/secom
- [D21] fueleconomy.gov, data downloads: https://www.fueleconomy.gov/feg/download.shtml
- [D22] NHTSA, vPIC API: https://vpic.nhtsa.dot.gov/api/
- [D23] CTU Relational Dataset Repository, Financial (PKDD'99 "Berka"): https://relational.fel.cvut.cz/dataset/Financial
- [D24] UCI, Bank Marketing (CC BY 4.0): https://archive.ics.uci.edu/dataset/222/bank+marketing
- [D25] Default of Credit Card Clients (CC0): https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset
- [D26] Freddie Mac, Single-Family Loan-Level Dataset: https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset
- [D27] CFPB, HMDA data: https://www.consumerfinance.gov/data-research/hmda/
- [D28] PaySim (CC BY-SA 4.0) and simulator repo (GPL-3.0): https://www.kaggle.com/datasets/ealaxi/paysim1 and https://github.com/EdgarLopezPhD/PaySim
- [D29] Credit Card Fraud Detection, ULB (ODbL): https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud
- [D30] IBM TabFormer (Apache-2.0): https://github.com/IBM/TabFormer
- [D31] Elliptic Data Set (CC BY-NC-ND 4.0): https://www.kaggle.com/datasets/ellipticco/elliptic-data-set
- [D32] Google Cloud blog, Ethereum in BigQuery public dataset: https://cloud.google.com/blog/products/data-analytics/ethereum-bigquery-public-dataset-smart-contract-analytics
- [D33] CASdatasets, freMTPL / freMTPL2: https://dutangc.github.io/CASdatasets/reference/freMTPL.html
- [D34] CAS, Loss reserving data pulled from NAIC Schedule P: https://www.casact.org/publications-research/research/research-resources/loss-reserving-data-pulled-naic-schedule-p
- [D35] Synthea (site; repository licensed Apache-2.0): https://synthetichealth.github.io/synthea/ and https://github.com/synthetichealth/synthea
- [D36] PhysioNet, MIMIC-IV Clinical Database Demo (ODbL v1.0): https://physionet.org/content/mimic-iv-demo/
- [D37] CMS, 2008–2010 DE-SynPUF: https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf
- [D38] openFDA, downloads and terms (CC0): https://open.fda.gov/data/downloads/ and https://open.fda.gov/terms/
- [D39] AACT (CTTI), ClinicalTrials.gov relational database: https://aact.ctti-clinicaltrials.org/
- [D40] Telco Customer Churn (Kaggle: "Data files © Original Authors") and IBM repository (Apache-2.0): https://www.kaggle.com/datasets/blastchar/telco-customer-churn and https://github.com/IBM/telco-customer-churn-on-icp4d
- [D41] Harvard Dataverse, Telecom Italia Big Data Challenge: https://dataverse.harvard.edu/dataverse/bigdatachallenge
- [D42] GroupLens, MovieLens: https://grouplens.org/datasets/movielens/
- [D43] UCSD McAuley lab, Steam datasets: https://cseweb.ucsd.edu/~jmcauley/datasets.html
- [D44] Criteo AI Lab, Attribution Modeling for Bidding (CC BY-NC-SA 4.0): https://ailab.criteo.com/criteo-attribution-modeling-bidding-dataset/
- [D45] London Datastore, SmartMeter energy use in London households (Creative Commons Attribution): https://data.london.gov.uk/dataset/smartmeter-energy-use-data-in-london-households
- [D46] EIA, Open Data: https://www.eia.gov/opendata/
- [D47] Equinor, Volve data sharing (Equinor Open Data Licence): https://www.equinor.com/energy/volve-data-sharing
- [D48] Railroad Commission of Texas, data sets for download: https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/
- [D49] UCI, Open University Learning Analytics Dataset (CC BY 4.0): https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset
- [D50] NCES, IPEDS, Use the data: https://nces.ed.gov/ipeds/use-the-data
- [D51] USAspending API: https://api.usaspending.gov/
- [D52] NYC Open Data, 311 Service Requests (metadata name: "311 Service Requests from 2020 to Present"): https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2010-to-Present/erm2-nwe9
- [D53] NYC Open Data, DOB Permit Issuance: https://data.cityofnewyork.us/Housing-Development/DOB-Permit-Issuance/ipu4-2q9a
- [D54] US Census Bureau, Construction Spending (C30): https://www.census.gov/construction/c30/data/index.html
- [D55] NYC Department of Finance, Rolling sales data: https://www.nyc.gov/site/finance/property/property-rolling-sales-data.page
- [D56] Redfin, Data Center: https://www.redfin.com/news/data-center/
- [D57] IRS, Form 990 series downloads: https://www.irs.gov/charities-non-profits/form-990-series-downloads
- [D58] UCI KDD Archive, KDD Cup 1998: https://kdd.ics.uci.edu/databases/kddcup98/kddcup98.html
- [D59] USDA NASS, Quick Stats: https://quickstats.nass.usda.gov/
- [D60] IBM HR Analytics Employee Attrition (fictional; ODbL): https://www.kaggle.com/datasets/pavansubhasht/ibm-hr-analytics-attrition-dataset
- [D61] SEC, Financial Statement Data Sets: https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets
- [D62] Kaggle competitions. Page titles were fetched; content and rules were **not verified**:
  - M5 Forecasting: https://www.kaggle.com/competitions/m5-forecasting-accuracy (see also https://github.com/Mcompetitions/M5-methods)
  - Recruit Restaurant Visitor Forecasting: https://www.kaggle.com/c/recruit-restaurant-visitor-forecasting
  - Personalize Expedia Hotel Searches (ICDM 2013): https://www.kaggle.com/c/expedia-personalized-sort
  - IEEE-CIS Fraud Detection: https://www.kaggle.com/c/ieee-fraud-detection
  - Home Credit Default Risk: https://www.kaggle.com/c/home-credit-default-risk
  - Porto Seguro Safe Driver Prediction: https://www.kaggle.com/c/porto-seguro-safe-driver-prediction
  - WSDM KKBox Churn Prediction: https://www.kaggle.com/c/kkbox-churn-prediction-challenge
  - 2019 Data Science Bowl: https://www.kaggle.com/c/data-science-bowl-2019
  - Avazu Click-Through Rate Prediction: https://www.kaggle.com/c/avazu-ctr-prediction
  - Bosch Production Line Performance: https://www.kaggle.com/c/bosch-production-line-performance

### X: Metric definitions
- [X1] Passenger load factor: https://en.wikipedia.org/wiki/Passenger_load_factor
- [X2] RevPAR: https://en.wikipedia.org/wiki/RevPAR
- [X3] Combined ratio: https://en.wikipedia.org/wiki/Combined_ratio
- [X4] SAIDI: https://en.wikipedia.org/wiki/SAIDI
- [X5] Overall equipment effectiveness: https://en.wikipedia.org/wiki/Overall_equipment_effectiveness
- [X6] Same-store sales: https://en.wikipedia.org/wiki/Same-store_sales
- [X7] Medical loss ratio: https://en.wikipedia.org/wiki/Medical_loss_ratio
- [X8] Net interest margin: https://en.wikipedia.org/wiki/Net_interest_margin
- [X9] Average revenue per user: https://en.wikipedia.org/wiki/Average_revenue_per_user

---

## Appendix A: Unverified search snippets (not used for scoring; verify before quoting)

- [U1] Grand View Research, BI software market: healthcare named the fastest-growing vertical (page 403). https://www.grandviewresearch.com/industry-analysis/business-intelligence-software-market
- [U2] Game analytics market ≈ USD 2.12B (2024). https://growthmarketreports.com/report/game-analytics-market
- [U3] Crypto compliance & blockchain analytics market USD 3.51B (2024) (GII listing). https://www.giiresearch.com/report/ires1809642-crypto-compliance-blockchain-analytics-market-by.html
- [U4] Payment analytics software ≈ USD 9.7B (2024). https://www.marketresearchfuture.com/reports/payment-analytics-software-market-33889
- [U5] U.S. healthcare payer analytics USD 5.90B (2024) (page 403). https://www.grandviewresearch.com/press-release/us-healthcare-payer-analytics-market-analysis
- [U6] Mordor, Big Data as a Service: BFSI 29.62% (2025); healthcare & life sciences fastest at 27.95% CAGR. https://www.mordorintelligence.com/industry-reports/big-data-as-a-service-market
- [U7] Microsoft: "Retail data solutions in Microsoft Fabric transitioned to a GitHub repository on November 14, 2025". Search snippet of [V13]; the page now redirects.
- [U8] Gartner: banking & investment services enterprise IT spending ≈ $760B in 2025. Search snippet of [M12]; paywalled.
- [U9] Vehicle analytics ≈ USD 4.3–5.7B (2024), multiple publishers. https://www.datamintelligence.com/research-report/vehicle-analytics-market

## Appendix B: Reproducibility notes

- The research ran on 2026-09-14 and hit the session's 200-call WebSearch limit. The remaining evidence was gathered with direct page fetches, which is why some standards cite Wikipedia or regulator pages (flagged "403").
- Every rank can be recomputed from the D/V/K/S/P columns in §2 (score = 3D + 2V + 2K + S + P). V is derived from the §3 matrix: ● = 1, ◐ = 0.5; 8.5–10 → 3, 6–8 → 2, 3–5.5 → 1, under 3 → 0.
- K ("knowledge premium") is the one judgement-based component. Every K = 3 vertical has at least one industry-defined KPI named in its row, cited to a definition where one was fetched ([X1]–[X9]).
- Recommended re-checks before committing engineering time: TM Forum SID access terms [T13]; licences of the Kaggle competitions [D62]; the original Instacart terms [D4]; Telecom Italia dataset licences [D41].
