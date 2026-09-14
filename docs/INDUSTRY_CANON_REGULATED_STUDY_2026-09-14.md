# Industry canon for regulated sectors — KPI recipes, playbooks, ontologies, standards, validation data

Research date: 2026-09-14. Scope: 10 regulated industries. Every benchmark carries a source URL (listed per section). Figures are US unless stated. Where no authoritative public benchmark exists, the table says so rather than inventing one.

**How to read the benchmark column.** A benchmark is a *measurement with a date and a population*: e.g. "FDIC all insured institutions, Q2 2026". Aggregates hide segment spread; each table notes the driver of that spread.

**Research limits (be explicit).** Some primary pages refused automated fetch (403). Where a figure came from a search-result summary of a primary page instead of a direct read, it is marked *(search summary)*. Paywalled benchmarks (IQVIA audits, ZS AccessMonitor, CAQH chartbook, SOA-LIMRA detailed lapse tables, LIMRA persistency) are named but not quoted.

---

## 1. Retail & commercial banking

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| Net interest margin (NIM) | NIM | What the bank earns on its earning assets after paying for funding | (interest income − interest expense) ÷ average earning assets, annualized | bank × quarter (or product × month for FTP-based NIM) | 3.32% all FDIC-insured, Q2 2026; community-size banks higher (3.99% for <$100M, 4.02% for $100M–$1B) vs 2.94% for >$250B [S1] | Dividing by period-end instead of *average* earning assets; forgetting to annualize a quarter; mixing tax-equivalent and reported interest income |
| Cost of funds | cost of funding earning assets | Interest paid per dollar of earning assets | interest expense ÷ average earning assets | bank × quarter | 2.03% all institutions Q2 2026; yield on earning assets 5.35% [S1] | Using interest-bearing liabilities as denominator in one period and earning assets in another |
| Efficiency ratio | cost-to-income (EU) | Cents of expense per dollar of revenue (lower is better) | noninterest expense ÷ (net interest income + noninterest income) | bank × quarter | 55.38% all institutions Q2 2026; strongly size-driven: 76.47% (<$100M) → 53.74% (>$250B) [S1] | Including provision expense or securities gains; comparing a trading-heavy bank with a community bank |
| Return on assets / equity | ROA, ROE | Profitability per dollar of assets / equity | net income ÷ average assets (or equity), annualized | bank × quarter | ROA 1.37% (Q2 2026 quarter), 1.32% YTD; ROE 13.76% quarter [S1] | Annualizing a quarter with one-off securities gains (Q2 2026 had $5.5B one-time equity gains) |
| Loan-to-deposit ratio | LDR | Share of deposits lent out | net loans & leases ÷ total deposits | bank × period-end | 66.17% all institutions H1 2026; credit-card banks 89.53% [S1] | Gross vs net loans; domestic vs total deposits |
| Past-due & nonaccrual rate (PDNA) | delinquency rate | Share of loans ≥30 days past due or nonaccrual | (30–89 DPD + noncurrent) balances ÷ total loans | loan book × quarter-end | 1.44% Q2 2026; credit cards 2.81% [S1] | Counting accounts instead of balances; letting charge-offs silently cure delinquency |
| Net charge-off rate | NCO rate | Losses written off, net of recoveries | (gross charge-offs − recoveries) ÷ average loans, annualized | loan book × quarter | 0.57% all loans Q2 2026 [S1]; credit card 3.82% SA at commercial banks [S2] | Using period-end loans; mixing quarterly and annualized rates |
| Reserve coverage | allowance coverage | Reserves per dollar of noncurrent loans | allowance for credit losses ÷ noncurrent loans | bank × quarter-end | 172.7% Q2 2026 [S1] | Comparing pre- and post-CECL periods without a break flag |
| CET1 ratio | common equity tier 1 | Core loss-absorbing capital | CET1 capital ÷ risk-weighted assets | bank × quarter-end | Regulatory minimum 4.5% (+2.5% conservation buffer before payout limits) [S3][S4]; industry 13.70% H1 2026 [S1] | Treating the minimum as a target; comparing standardized vs advanced RWA |
| Liquidity coverage ratio (LCR) | LCR | Liquid assets vs 30-day stressed outflows | HQLA ÷ total net cash outflows over 30 days | bank × day/month | Minimum 100% (Basel) [S5] | Averaging daily LCRs across banks without weighting |
| Deposit beta | pass-through | Share of a policy-rate change passed to deposit rates | Δ deposit rate ÷ Δ fed funds rate (cumulative over a cycle) | product × cycle | Cumulative interest-bearing deposit beta ≈0.4 by 2022Q4 — reached in one year vs three in 2015–19 [S6] | Measuring beta on total deposits when noninterest-bearing mix is shifting; ignoring non-linearity (betas rise as rates rise) |

### Playbook

1. **NIM compresses** → check in order: (a) cost of funds rising faster than asset yield (deposit beta catch-up, CD mix shift); (b) noninterest-bearing deposit runoff (mix); (c) asset repricing lag (fixed-rate mortgages/securities); (d) earning-asset mix (cash build-up dilutes); (e) nonaccrual growth (interest reversals). Typical action: reprice exception deposits, shorten CD ladder, change FTP curve, hedge with swaps.
2. **Efficiency ratio worsens** → split numerator vs denominator first: revenue fall (NIM, fee income, trading) vs expense rise ("all other" noninterest expense: data processing, marketing, legal drove Q2 2026 [S1]); then one-offs. Action: expense program, branch rationalization, vendor renegotiation.
3. **Deposits decline** → segment by insured vs uninsured, operating vs rate-sensitive, retail vs commercial; check competitor rates, rate-sheet timing, large-depositor concentration. Action: targeted retention pricing, sweep products, relationship pricing.
4. **Delinquency (PDNA) rises** → product → vintage → geography/industry → underwriting cohort; distinguish flow into 30 DPD from slower cure. Action: tighten credit box, collections intensity, loss-mitigation programs.
5. **Unrealized securities losses grow** → duration × rate move; AFS vs HTM split (Q2 2026: AFS losses 2.9% of amortized cost, HTM 10.5% [S1]); liquidity implication if sale needed. Action: hedge, restructure portfolio, contingency funding plan.

### Ontology sketch

Objects: **Party** (customer; person or organisation) · **Account** (deposit account) · **Product** · **Loan/Facility** · **Collateral** · **Transaction** · **Statement** · **Branch** · **Channel** · **Rate/PriceSchedule** · **Fee** · **Limit** · **Case** (dispute/complaint) · **GLEntry** · **RegulatoryReport** (Call Report).

Links: Party N:M Account (via role — owner, signer, beneficiary; the Berka dataset models this as a `disposition` table [S9]) · Account N:1 Product · Transaction N:1 Account · Loan N:1 Party (borrower) and N:M Collateral · Account N:1 Branch · Statement N:1 Account · Case N:1 Transaction · GLEntry N:1 Account.

Lifecycles:
- Account: `applied → KYC_pending → open → dormant → frozen → closed` (terminal: closed; escheated).
- Loan: `application → underwriting → approved/declined → funded → current ⇄ delinquent(30/60/90) → nonaccrual → charged_off | paid_off | restructured` (terminal: paid_off, charged_off).
- Error dispute (Reg E): `notice_received → provisional_credit → investigated → resolved_error | resolved_no_error`.

Processes & promises:
- **Reg E error resolution**: consumer notice within 60 days of statement; bank determines within 10 business days, or up to 45 days if provisional credit given within 10 business days; 90 days for POS / foreign / new-account errors [S7].
- **Reg CC funds availability**: cash in person and electronic payments available next business day; next-day for Treasury and cashier's checks; first $275 of other check deposits [S8].
- Charge-off policy (loans): open-end 180 DPD, closed-end 120 DPD [L5 in §2].

### Systems & standards

- Systems: core banking (Fiserv, FIS, Jack Henry, Temenos, Finastra, Oracle FLEXCUBE, Thought Machine, Mambu), loan origination (nCino), CRM (Salesforce Financial Services Cloud), GL/ERP, treasury/ALM (QRM, Moody's), regulatory reporting (Call Report / FR Y-9C; EU FINREP/COREP).
- Standards to quarry for names: **BIAN** Service Landscape 14.0 — 322 service domains, event-driven design [S10]; **FIBO** (EDM Council / OMG) — OWL ontology with loans, securities, derivatives modules [S11]; **ISO 20022** financial messaging (pacs/camt/pain message families) [S12]; FFIEC Call Report schedules (RC, RI, RC-N) as the de facto US field dictionary [S13].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| FFIEC CDR bulk Call Reports + UBPR | https://cdr.ffiec.gov/public/PWS/DownloadBulkData.aspx | US public data | Every insured commercial bank, quarterly; tab-delimited or XBRL [S13] | NIM, efficiency, ROA/ROE, LDR, PDNA, NCO, reserve coverage, capital ratios — directly comparable to FDIC QBP aggregates (a strong falsifier) |
| FDIC BankFind Suite API | https://api.fdic.gov/banks/docs | Public; no key required [S14] | Institutions, financials, SOD branch deposits, failures | Same as above plus branch-level deposit share |
| PKDD'99 "Berka" Czech bank | https://sorry.vse.cz/~berka/challenge/pkdd1999/berka.htm | Research use; no explicit licence stated | 8 tables: 4,500 accounts, 5,369 clients, 1,056,320 transactions, 682 loans, ~900 cards (1993–1999) [S9] | Transaction-grain ontology test (party–account roles), balances, loan status; *not* NIM or capital |
| UCI Bank Marketing | https://archive.ics.uci.edu/dataset/222/bank+marketing | CC BY 4.0 | 45,211 calls, Portuguese bank, 2008–2010 [S16] | Campaign conversion, contact-frequency effects; not financial KPIs |

### What generic analytics gets wrong here

- Averages ratios across banks (mean of NIMs) instead of recomputing from summed numerators and denominators; the FDIC industry figure is aggregate-weighted.
- Uses period-end balances as denominators for flow metrics (NIM, NCO, ROA) — must be *average* balances, annualized.
- Treats delinquency as monotone: accounts cure, re-age and charge off; a falling delinquency rate can mean faster charge-offs, not better credit.
- Compares institutions across size and business model (credit-card banks: NIM 9.41%, efficiency 57.42% [S1]) without peer grouping.
- Ignores regime breaks (CECL adoption, ASC 810/860 consolidations, merger restatements) in trend lines.

### Sources

- [S1] FDIC Quarterly Banking Profile, Q2 2026 (text, Tables I-A, II-A, III-A, IV-A): https://www.fdic.gov/quarterly-banking-profile/quarterly-banking-profile-second-quarter-2026.pdf
- [S2] Federal Reserve, Charge-off and delinquency rates, seasonally adjusted: https://www.federalreserve.gov/releases/chargeoff/chgallsa.htm
- [S3] 12 CFR 324.10 minimum capital (CET1 4.5%, Tier 1 6%, total 8%, leverage 4%): https://www.law.cornell.edu/cfr/text/12/324.10
- [S4] 12 CFR 324.11 capital conservation buffer (>2.5% RWA before payout limits): https://www.law.cornell.edu/cfr/text/12/324.11
- [S5] BCBS, Basel III: The Liquidity Coverage Ratio (Jan 2013): https://www.bis.org/publ/bcbs238.htm ; NSFR ≥100%: https://www.bis.org/bcbs/publ/d295.pdf
- [S6] NY Fed Liberty Street Economics, "Deposit Betas: Up, Up, and Away?" (Apr 2023): https://libertystreeteconomics.newyorkfed.org/2023/04/deposit-betas-up-up-and-away/
- [S7] Regulation E §1005.11: https://www.consumerfinance.gov/rules-policy/regulations/1005/11/
- [S8] Regulation CC 12 CFR 229.10: https://www.law.cornell.edu/cfr/text/12/229.10
- [S9] Berka dataset description: https://sorry.vse.cz/~berka/challenge/pkdd1999/berka.htm
- [S10] BIAN Service Landscape 14.0 announcement: https://bian.org/news-room/bian-unveils-new-service-landscape-14-0-to-accelerate-ai-ready-banking-architecture/ ; landscape: https://bian.org/deliverables/service-landscape/
- [S11] FIBO: https://spec.edmcouncil.org/fibo/ ; https://github.com/edmcouncil/fibo
- [S12] ISO 20022 (official site; blocks automated fetch): https://www.iso20022.org/
- [S13] FFIEC CDR bulk data: https://cdr.ffiec.gov/public/PWS/DownloadBulkData.aspx
- [S14] FDIC BankFind Suite API: https://api.fdic.gov/banks/docs
- [S16] UCI Bank Marketing: https://archive.ics.uci.edu/dataset/222/bank+marketing

---

## 2. Lending / credit (consumer loans, cards, BNPL, mortgage)

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| Denial rate / approval rate | decline rate | Share of decided applications turned down | denied ÷ (applications − withdrawn − closed-incomplete) | application × decision month | HMDA 2023: home purchase 9.4%, refinance 32.7%; conventional conforming purchase 7.9%, FHA purchase 13.6% [L1] | Putting withdrawn/incomplete files in the denominator (HMDA excludes them [L1]); pooling purchase and refinance |
| Pull-through rate | fallout (inverse) | Share of applications (or locks) that fund | funded ÷ applications (or locks) in the cohort | application cohort | No authoritative free benchmark (MBA performance reports are paid) | Measuring on calendar month instead of application cohort; lock expiries counted twice |
| Cost to originate | production expense per loan | All-in cost of producing one closed loan | total production expense ÷ loans closed | lender × quarter | Independent mortgage banks $10,936/loan (308 bps) Q2 2026, down from $11,898 Q1 2026; 2008–2025 average ≈$7,945 [L2] *(search summary)* | Excluding corporate allocations; mixing units and bps |
| Delinquency rate (30+/60+/90+) | past-due rate | Share of balances past due | past-due balance in bucket ÷ total balance | portfolio × month-end | Cards 2.62% SA, all commercial banks Q2 2026 [S2]; mortgages (1–4 unit) 4.37% SA Q2 2026 — 30d 2.21%, 60d 0.73%, 90d+ 1.43%; foreclosure inventory 0.67% [L3] *(search summary)* | Account counts vs balances; delinquency and foreclosure inventory are separate series — adding them double counts nothing only if definitions are checked |
| Transition (roll/flow) rate | roll rate | Share of balances moving to a worse bucket | balance entering bucket k+1 ÷ balance in bucket k (or total) | portfolio × month/quarter | Annualized share of balances transitioning into serious (90+) delinquency, Q2 2026: cards 6.97%, auto 3.00%, mortgages 1.52%, student loans 7.83%, HELOC 1.15% [L4] | Treating a stock (delinquency rate) as a flow; ignoring cures and re-aging |
| Net charge-off (NCO) rate | loss rate | Annualized net losses | (charge-offs − recoveries) ÷ average balances × annualization | portfolio × quarter | Commercial banks Q2 2026 SA: cards 3.82%, consumer total 2.66%, residential RE 0.07%, C&I 0.41% [S2]. Timing policy: open-end at 180 DPD, closed-end at 120 DPD [L5] | Loss recognition lags delinquency by ~6 months for cards — a same-quarter correlation between the two is misleading |
| Vintage cumulative loss | static-pool loss | Losses of one origination cohort as it ages | cumulative net losses ÷ original balance, by months-on-book | origination cohort × MOB | No cross-lender public benchmark; compute from Freddie Mac SFLLD or LendingClub | Dividing by *current* balance; comparing vintages at different ages |
| Expected loss | EL | Loss the book should anticipate on average | PD × LGD × EAD [L6] | exposure × horizon | Framework definition (Basel IRB) [L6]; parameters are lender-specific | Multiplying segment-average PD, LGD and EAD instead of summing exposure-level products (correlated parameters) |
| BNPL late-fee incidence & charge-off | — | Share of pay-in-four loans hit by a late fee / written off | loans with ≥1 late fee ÷ loans originated; loans charged off ÷ loans originated | lender × year | 2023: 4.1% of loans assessed a late fee (5.2% in 2022); late fees 0.18% of origination volume; 1.83% of loans charged off (2.63% in 2022); 335.8M loans, $45.2B, average $135 — six large firms [L7] | Measuring BNPL losses per *loan count* vs per dollar interchangeably; users counted per lender overstate unique users [L7] |

### Playbook

1. **Charge-offs rise** → (a) which vintages (months-on-book curves vs prior cohorts); (b) roll rates 30→60→90 — did inflow worsen or cures slow?; (c) product/channel/score band/geography; (d) policy changes 6–12 months earlier (cutoffs, line increases, new partners); (e) macro (unemployment, rates). Action: tighten credit box, stop line increases, collections capacity, hardship/forbearance programs, reserve build.
2. **Approval rate falls** → application mix (score, DTI, loan-to-value, channel) → rule/strategy changes → fraud-rule declines → bureau/data outages → pricing moves. For mortgages, check the DTI and collateral denial reasons, which track house prices [L1]. Action: rule review, champion/challenger tests, counteroffers.
3. **Pull-through falls (mortgage)** → rate move since lock (re-shopping), lock expirations, appraisal gaps, condition turnaround, share withdrawn vs denied. Action: lock-extension policy, condition SLAs, float-down offers.
4. **First-payment defaults spike** → synthetic/first-party fraud, onboarding changes, autopay enrollment, servicing transfers, billing-address errors. Action: fraud rules, verification step-up, payment reminders.
5. **Prepayment speeds change** → rate incentive (note rate vs market), burnout, seasonality, housing turnover. Action: retention/refinance offers, hedge adjustment, MSR valuation.

### Ontology sketch

Objects: **Applicant** (Party) · **Application** · **CreditReport** · **Decision** · **Offer** · **RateLock** (mortgage) · **LoanAccount** (term loan, card account, BNPL plan) · **Collateral/Property** · **PaymentSchedule** · **Payment** · **DelinquencySnapshot** · **CollectionsCase** · **Modification/Forbearance** · **ChargeOff** · **Recovery** · **Servicer** · **Pool/Investor**.

Links: Application N:M Applicant (co-borrowers) · Decision 1:1 Application · LoanAccount 0..1:1 Application · RateLock N:1 Application · Payment N:1 LoanAccount · Collateral N:M LoanAccount · DelinquencySnapshot N:1 LoanAccount (one per month) · CollectionsCase N:1 LoanAccount · LoanAccount N:1 Servicer (time-varying; keep history) · LoanAccount N:1 Pool.

Lifecycles:
- Application: `started → submitted → underwriting → approved | counteroffered | denied | withdrawn | closed_incomplete` (all but approved are terminal; approved → funded or expired).
- LoanAccount: `funded → current ⇄ dpd30 → dpd60 → dpd90+ → charged_off → (recovery)`; also `paid_off`, `modified`; mortgage adds `foreclosure → REO → liquidated`. Terminal: paid_off, charged_off (after recovery), liquidated.

Processes & promises:
- **TRID**: Loan Estimate within 3 business days of receiving the application; Closing Disclosure received at least 3 business days before consummation [L8].
- **Reg B**: notify the applicant of action within 30 days of a completed application; 90 days after an unaccepted counteroffer [L9].
- **Charge-off**: closed-end at 120 DPD, open-end at 180 DPD [L5].

### Systems & standards

- Systems: loan origination (ICE Mortgage Technology Encompass, nCino, Blend, MeridianLink); servicing (ICE/Black Knight MSP); card processing (TSYS TS2, Fiserv Optis, FIS); decisioning (FICO, Experian PowerCurve, Provenir); credit bureaus (Equifax, Experian, TransUnion); collections (FICO Debt Manager). BNPL providers run in-house platforms.
- Standards (quarry): **MISMO** Reference Model; the GSEs' ULDD loan-delivery dataset builds on MISMO v3 [L10]; **HMDA/Reg C** filing field definitions (action taken, denial reasons) [L12]; **Basel IRB** risk components (PD, LGD, EAD) [L6]; **FIBO** loan ontology [S11].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| Freddie Mac Single-Family Loan-Level Dataset | https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset | Free with registration; internal/research use only; no redistribution without a licence [L11] | ≈55M fully amortizing mortgages originated 1999 – Q3 2025; origination and monthly performance files [L11] | Delinquency buckets, roll rates, vintage default/loss curves, prepayment, loss severity |
| HMDA Snapshot National Loan-Level Dataset | https://ffiec.cfpb.gov/data-publication/snapshot-national-loan-level-dataset/2023 | US public data, with privacy modifications [L1] | Every reportable US mortgage application (millions per year) | Denial rates by purpose/type/lender, pricing, origination mix — reconciles to [L1] |
| LendingClub accepted + rejected loans 2007–2018 (Kaggle mirror) | https://www.kaggle.com/datasets/wordsforthewise/lending-club | As stated on the Kaggle page (not verified here) | Millions of accepted loans plus a rejected-applications file | Approval rate (accepted vs rejects), grade-level default, vintage loss, recoveries — note rejects have no outcomes |
| Fannie Mae Single-Family Loan Performance Data | https://capitalmarkets.fanniemae.com/credit-risk-transfer/single-family-credit-risk-transfer/fannie-mae-single-family-loan-performance-data | Registration; terms on site (page blocks automated fetch) | Acquisition + monthly performance | Same as Freddie Mac; cross-check |

### What generic analytics gets wrong here

- Divides losses by *current* balances in a growing book: new, unseasoned loans inflate the denominator and hide deterioration. Use vintage (static-pool) curves.
- Correlates delinquency and charge-offs in the same period, although charge-off policy imposes a 120/180-day lag [L5].
- Counts accounts where the business manages dollars (or vice versa); weights by balance for loss and delinquency.
- Builds approval models on accepted loans only: survivorship/reject-inference bias.
- Mixes seasonally adjusted and unadjusted series, or monthly and annualized rates.

### Sources

- [L1] CFPB, 2023 Mortgage Market Activity and Trends (Dec 2024), §3.3 and footnote 24: https://files.consumerfinance.gov/f/documents/cfpb_2023-mortgage-market-activity-and-trends_2024-12.pdf
- [L2] MBA, IMB production profits Q2 2026 *(search summary)*: https://www.mba.org/news-and-research/newsroom/news/2026/08/18/imbs-production-profits-increase-in-second-quarter-of-2026 ; Q1 2026: https://www.mba.org/news-and-research/newsroom/news/2026/05/15/imbs-production-profits-remain-flat-in-first-quarter-of-2026
- [L3] MBA National Delinquency Survey Q2 2026 *(search summary)*: https://www.mba.org/news-and-research/newsroom/news/2026/08/13/mortgage-delinquencies-decrease-slightly-in-the-second-quarter-of-2026
- [L4] NY Fed, Household Debt and Credit Q2 2026: https://www.newyorkfed.org/newsevents/news/research/2026/20260811
- [L5] FFIEC Uniform Retail Credit Classification and Account Management Policy: https://www.federalregister.gov/documents/2000/06/12/00-14704/uniform-retail-credit-classification-and-account-management-policy
- [L6] Basel Framework CRE31 (risk-weight functions): https://www.bis.org/committees/bcbs/basel-framework/standard/cre/31/inforce/2022-01-01/published/2019-12-15 ; CRE32 (risk components): https://www.bis.org/committees/bcbs/basel-framework/standard/cre/32/inforce/2023-01-01/published/2020-03-27
- [L7] CFPB BNPL market report (Dec 2025): https://files.consumerfinance.gov/f/documents/cfpb_bnpl-market-report_2025-12.pdf
- [L8] Regulation Z §1026.19: https://www.consumerfinance.gov/rules-policy/regulations/1026/19/
- [L9] Regulation B §1002.9: https://www.consumerfinance.gov/rules-policy/regulations/1002/9/
- [L10] MISMO Reference Model: https://www.mismo.org/standards-resources/residential-specifications/reference-model ; MISMO v3 / ULDD user guide: https://sf.freddiemac.com/docs/pdf/other/mismo_user_guide.pdf
- [L11] Freddie Mac SFLLD terms: https://freddiemac.embs.com/FLoan/HistoricalDataTerms.html ; summary: https://capitalmarkets.freddiemac.com/crt/docs/docs/sflld_nsd_summary.pdf
- [L12] HMDA Filing Instructions Guide: https://s3.amazonaws.com/cfpb-hmda-public/prod/help/2022-hmda-fig.pdf
- [S2] Federal Reserve charge-off/delinquency release (see §1).

---

## 3. Payments & fintech (acquiring, issuing, wallets, fraud & chargebacks)

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| Authorization (approval) rate | acceptance rate | Share of authorization attempts approved by the issuer | approved auths ÷ auth attempts (after de-duplicating retries) | auth attempt, rolled to merchant × BIN country × day | **No authoritative public benchmark.** Varies with card-present vs not-present, cross-border share, issuer mix, MCC, retry policy | Counting retries or card-testing bursts as independent attempts; Visa now monitors enumeration separately (ratio ≥20% of auths and ≥300,000 enumerated auths) [P1] |
| Visa VAMP ratio | dispute/fraud ratio | Fraud reports + disputes per settled card-not-present transaction | count(TC40 fraud + TC15 disputes) ÷ count(TC05 settled CNP transactions), monthly | merchant or acquirer × month | Acquirer: Above Standard ≥50 bps, Excessive ≥70 bps. Merchant Excessive (AP, Canada, EU, US): ≥220 bps, lowered to ≥150 bps on 1 Apr 2026, with ≥1,500 monthly fraud+disputes [P1] | Using value instead of count; including disputes resolved pre-dispute (excluded) [P1] |
| Mastercard chargeback ratio | ECM ratio | Chargebacks per sale, lagged | chargebacks in month M ÷ sales transactions in month M−1 | merchant (MID) × month | Excessive (ECM): 100–299 chargebacks and 1.50–2.99%; High Excessive (HECM): ≥300 and ≥3.00%; both conditions must hold [P2] | Using same-month sales (Mastercard uses the prior month) — misfires during seasonal peaks |
| Fraud loss rate | fraud bps | Fraud losses per unit of volume | fraud losses ÷ transaction value (bps or ¢ per $100) | issuer/acquirer × period | Global cards 6.43¢ per $100 in 2024 ($33.41B); US = 26.31% of volume but 41.87% of losses [P3]. US covered debit issuers 2023: 17.6 bps to all parties [P4]. EEA 2024: card payments 0.033% of value, credit transfers 0.001% [P5]. US card-present debit 2023: 14.2 bps (dual-message), 5.1 bps (single-message); EEA card-present 0.7 bps [P6] | Comparing count-based ratios (VAMP) with value-based loss rates; mixing issuer and acquirer perspectives (EBA figures are issuing-side [P5]) |
| Fraud-loss burden split | liability share | Who absorbs the loss | losses borne by party ÷ total fraud losses | payment type × year | US covered debit 2023: merchants 49.9%, issuers 28.3%, cardholders 21.8% [P4]; EEA 2024: users bore 38% of card fraud losses and ≈85% of credit-transfer fraud losses [P5] | Reporting "fraud losses" as issuer write-offs only, which omits the merchant chargeback share |
| Regulated debit interchange | Durbin cap | Max interchange for issuers ≥$10B assets | 21¢ + 0.05% of value + 1¢ fraud-prevention adjustment | transaction | Cap per Regulation II; 2023 proposal to 14.4¢ + 4.0 bps + 1.3¢ still pending; a 2025 district-court vacatur is stayed pending appeal [P7]. Actual 2023 average: $0.22 (dual-message), $0.24 (single-message) [P4] | Applying the cap to exempt (<$10B) issuers or to credit cards |
| Take rate | net revenue yield | Revenue kept per dollar processed | net revenue (after interchange and scheme fees) ÷ total payment volume | merchant or company × quarter | Company-specific; no neutral public benchmark | Mixing gross revenue (including pass-through interchange) with net revenue; blended vs interchange++ pricing cohorts |
| Dispute win rate | representment success | Share of contested disputes won | disputes won ÷ disputes contested (not all disputes) | merchant × reason-code category × month | No authoritative public benchmark | Denominator of all disputes (including accepted ones); ignoring late reversals [P8] |
| SCA effect on fraud | — | Fraud where strong customer authentication is not required | fraud rate (payee outside EEA) ÷ fraud rate (domestic) | corridor × year | EEA card fraud about 17× higher when the counterpart is outside the EEA; SCA applied to 40% of electronically initiated card payments by count in 2024 [P5] | Reading SCA-authenticated credit transfers' higher fraud rate as SCA failing — SCA is targeted at riskier payments [P5] |

### Playbook

1. **Approval rate drops** → decline-code mix (do-not-honor, insufficient funds, suspected fraud, invalid card) → issuer/BIN concentration → cross-border share → acquirer/gateway routing or outage → retry storms / card testing → credential-on-file and network-token coverage → 3-D Secure changes. Action: smart retries, network tokens and account updater, routing changes, issuer outreach.
2. **Chargeback/VAMP ratio rises** → reason-code category (fraud vs consumer dispute vs processing error) → MID concentration → product and billing descriptor → fulfilment/delivery delays → refund policy; check denominator seasonality (Mastercard's prior-month base). Action: pre-dispute alerts (Verifi/Ethoca), refund-before-dispute, clearer descriptors, 3DS for liability shift, Compelling Evidence 3.0 submissions [P1].
3. **Fraud losses rise** → channel (CNP vs CP) → attack type (card testing, account takeover, stolen credentials — EBA: fraudsters directly issuing the payment order dominate card fraud [P5]) → BIN ranges/geography → merchant onboarding cohort → model/rule releases. Action: velocity rules, model retraining, step-up authentication, merchant offboarding.
4. **Take rate declines** → merchant mix (large merchants on interchange++), debit/credit mix (regulated debit), cross-border share, pricing concessions, scheme-fee pass-through changes. Action: repricing, value-added services, surcharging where legal.
5. **Settlement/payout breaks** → auth vs capture vs settlement reconciliation gaps, partial captures, reserve holds on risky merchants, cut-off/holiday calendars. Action: reconciliation automation, reserve policy review.

### Ontology sketch

Objects: **Merchant** · **MerchantAccount (MID)** · **Acquirer** · **Issuer** · **CardNetwork** · **Cardholder** · **PaymentInstrument** (PAN, network token, wallet) · **Order/PaymentIntent** · **Authorization** · **Capture/Clearing** · **Settlement/Payout** · **Refund** · **Dispute** · **FraudReport** (TC40 / SAFE) · **FeeLine** (interchange, scheme, markup) · **RiskDecision** · **Device/Session**.

Links: Authorization N:1 PaymentInstrument · Authorization N:1 MerchantAccount · Capture N:1 Authorization (partial captures make this N) · Settlement 1:N Capture (batch) · Refund N:1 Capture · Dispute N:1 Capture (several disputes per payment are possible [P8]) · FraudReport N:1 Capture · FeeLine N:1 Capture · MerchantAccount N:1 Merchant and N:1 Acquirer · PaymentInstrument N:1 Issuer and N:1 Cardholder.

Lifecycles:
- Payment: `created → authorized | declined`; `authorized → captured (partial/full) → settled → refunded (partial/full)`; `authorized → voided | expired`.
- Inquiry (pre-dispute): `warning_needs_response → warning_under_review → warning_closed` (closed after 120 days without escalation) [P8].
- Dispute: `needs_response → under_review → won | lost` (terminal; rare late reversals) [P8].
- Merchant: `applied → KYB → approved → active → monitored (VAMP/ECM) → remediated | terminated`.

Processes & promises:
- **Dispute clock**: cardholders typically may dispute within 120 days of payment (event date for future services); merchants typically have 7–21 days to respond; issuers typically decide within 60–75 days; end to end 2–3 months [P8].
- **Scheme monitoring**: monthly VAMP and ECM identification; exit ECM after 3 consecutive months below threshold [P1][P2].
- **EFT error resolution** (debit, P2P): Regulation E timelines [S7 in §1].

### Systems & standards

- Systems: PSPs/gateways (Stripe, Adyen, Checkout.com, Braintree); acquirer processors (Fiserv, Worldpay, Global Payments, Elavon); issuer processors (TSYS, Fiserv, Marqeta, Galileo); fraud (Visa and Mastercard network scores, Sift, Forter, Riskified, Featurespace); dispute tooling (Verifi, Ethoca, Chargebacks911); ledgers (in-house, Modern Treasury).
- Standards (quarry): **ISO 8583** card messages — message classes 01xx authorization, 02xx financial, 04xx reversal/chargeback, 05xx reconciliation, 08xx network management [P9]; **ISO 20022** for account-to-account payments [S12 in §1]; **EMV 3-D Secure** (v2.3.1.1; v2.4.0.0 draft) [P10]; Visa record types TC05 (settled), TC15 (dispute), TC40 (fraud) as named in VAMP [P1].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| IEEE-CIS Fraud Detection (Vesta e-commerce) | https://www.kaggle.com/c/ieee-fraud-detection (described in https://github.com/amazon-science/fraud-dataset-benchmark) | Kaggle competition rules (not an open licence) | 590,540 transactions, 3.5% fraud, 431 features; transaction + identity tables joined on TransactionID [P11] | Fraud rate by count and value, by product/card/device/email domain; no disputes, fees or merchant dimension |
| Credit Card Fraud Detection (Worldline × ULB) | https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud | Database Contents License (DbCL) v1.0 [P12] | 284,807 transactions over two days (Sept 2013), 492 frauds (0.172%); PCA-transformed features [P12] | Fraud rate by count/amount, precision/recall of rules; nothing else |
| PaySim synthetic mobile-money log | https://www.kaggle.com/datasets/ealaxi/paysim1 | See Kaggle page (not verified) | Simulated transaction log with fraud labels | Fraud rate by transaction type; flagged-vs-actual fraud |
| Federal Reserve Regulation II data (aggregates) | https://www.federalreserve.gov/paymentsystems/regii-data-collections.htm | US public data | Biennial issuer/network survey tables since 2009 | Reconciliation targets: interchange per transaction, fraud bps, loss-burden shares |

No public dataset carries the full authorization → capture → settlement → dispute → fee chain. This is one of the hardest packages to validate (see cross-industry note).

### What generic analytics gets wrong here

- Mis-aligns chargeback ratios: Visa VAMP is a same-month *count* over settled CNP transactions; Mastercard divides this month's chargebacks by *last* month's sales [P1][P2].
- Mixes count-based and value-based fraud measures (VAMP counts vs Nilson/Fed/EBA value bps).
- Double counts payments when joining authorizations, captures, refunds and disputes (all 1:N).
- Treats retries and card-testing bursts as organic authorization attempts, depressing approval rates.
- Computes take rate on gross revenue that includes pass-through interchange.

### Sources

- [P1] Visa Acquirer Monitoring Program fact sheet (2025): https://corporate.visa.com/content/dam/VCOM/corporate/visa-perspectives/security-and-trust/documents/visa-acquirer-monitoring-program-fact-sheet-2025.pdf
- [P2] Braintree, Mastercard Excessive Chargeback Program: https://developer.paypal.com/braintree/articles/risk-and-security/card-brand-monitoring-programs/mastercard-programs/excessive-chargeback-program
- [P3] Nilson Report, "Global Card Fraud Losses at $33 Billion" (Jan 2026): https://www.globenewswire.com/news-release/2026/01/07/3214821/0/en/global-card-fraud-losses-at-33-billion.html
- [P4] Federal Reserve, 2023 Interchange Fee Revenue, Covered Issuer Costs, and Fraud Losses: https://www.federalreserve.gov/paymentsystems/2023-interchange-fee.htm
- [P5] EBA & ECB, 2025 Report on Payment Fraud (Dec 2025): https://www.eba.europa.eu/sites/default/files/2025-12/1709846a-84d9-47cf-86a0-b155efb34d66/EBA%20and%20ECB%20Report%20on%20Payment%20Fraud.pdf ; press release: https://www.ecb.europa.eu/press/pr/date/2025/html/ecb.pr251215~e133d9d683.en.html
- [P6] Federal Reserve Bank of Kansas City, "New Data on Card-Present and Card-Not-Present Fraud Rates in the United States" (Feb 2026): https://www.kansascityfed.org/research/payments-system-research-briefings/new-data-on-card-present-and-card-not-present-fraud-rates-in-the-united-states/
- [P7] Federal Reserve, Regulation II: https://www.federalreserve.gov/supervisionreg/regiicg.htm ; 2023 proposal: https://www.federalregister.gov/documents/2023/11/14/2023-24034/debit-card-interchange-fees-and-routing ; vacatur note (Cooley, Aug 2025): https://www.cooley.com/news/insight/2025/2025-08-15-district-court-vacates-regulation-iis-debit-card-interchange-fee-standard
- [P8] Stripe Docs, How disputes work: https://docs.stripe.com/disputes/how-disputes-work
- [P9] ISO 8583 overview (secondary; ISO page blocks fetch): https://en.wikipedia.org/wiki/ISO_8583
- [P10] EMVCo, EMV 3-D Secure: https://www.emvco.com/emv-technologies/3-d-secure/
- [P11] Amazon Science Fraud Dataset Benchmark (IEEE-CIS description): https://github.com/amazon-science/fraud-dataset-benchmark
- [P12] ULB/Worldline Credit Card Fraud Detection: https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud

---

## 4. Insurance — property & casualty and life

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| Loss ratio (incl. LAE) | loss & LAE ratio | Claims cost per dollar of premium earned | (losses incurred + loss adjustment expenses incurred) ÷ net premiums **earned** | line × accident or calendar year | US P&C 2025: 66.5% (2024 71.2%, 2023 76.3%) [I1] | Dividing by written premium; excluding LAE; comparing a catastrophe year with a quiet one (2025 was a low-cat year) |
| Expense ratio | underwriting expense ratio | Acquisition and overhead cost per premium dollar | other underwriting expenses ÷ net premiums **written** (trade basis) | company/line × year | US P&C 2025: 25.8% [I1] | Silently switching between written- and earned-premium denominators |
| Combined ratio | CR, NCR | Underwriting result (<100 = underwriting profit) | loss ratio + expense ratio + policyholder dividend ratio | line × year | US P&C 2025: 92.9% (2024 96.9%, 2023 101.7%, 2022 102.5%) [I1]. By line, 2025: personal auto 91.8, homeowners 88.1, workers' comp ≈91; general liability and commercial auto above 100 [I2] | Averaging company CRs instead of premium-weighting; ignoring reserve development and line mix |
| Claim frequency | frequency | Claims per unit of exposure | claim count ÷ earned exposure (e.g. vehicle-years) | coverage × exposure period | US private passenger auto 2024: bodily injury 0.80%, property damage 2.50%, collision 4.16%, comprehensive 3.95% of insured with the coverage [I3] | Dividing by policies in force instead of earned exposure; counting claims closed without payment inconsistently |
| Claim severity | average claim cost | Cost per claim | incurred (or paid) losses ÷ claim count | coverage × accident period | US private passenger auto 2024: bodily injury $28,278; property damage $6,770; collision $5,489; comprehensive $2,306 [I3] | Using paid losses on immature, open claims; mixing gross and net of deductible/salvage |
| IBNR / loss development | development factor, LDF | Losses not yet reported or fully valued | ultimate losses − reported losses; age-to-age factors from accident-year × development-age triangles | line × accident year × development age | No single benchmark — long-tail liability develops for years, short-tail property within months; validate on Schedule P triangles [I4] | Reading the latest accident year's loss ratio as final; chain-ladder when claim-closure speed has changed |
| Auto repair cycle time | claim cycle time | Days to repair a repairable vehicle | mean(repair completion − first notice or vehicle drop-off) | claim | 19.3 days in 2025, down from 22.3 days [I5] *(search summary)* | Mixing total losses with repairable claims; means dominated by long-tail outliers |
| Policy retention | renewal rate | Share of policies up for renewal that renew | renewed ÷ eligible-to-renew (by expiring term) | policy term cohort | No authoritative free benchmark | Denominator of all policies in force; counting rewrites as churn |
| RBC ratio | capital adequacy | Capital vs required risk-based capital | total adjusted capital ÷ authorized control level RBC | legal entity × year | ≥300%: no action; 200–300%: trend test; <200%: escalating intervention; <70%: regulator must take control [I7] | Comparing group-level and legal-entity ratios |
| Life lapse rate | persistency (inverse) | Policies terminating (lapse or surrender) | lapses and surrenders ÷ exposure, by count **or** face amount | product × policy year | SOA–LIMRA UL study 2015–2021: 33.5M policy exposures, 1.3M lapse terminations; lifetime-secondary-guarantee policies lapse ≈45% less than non-lifetime ones; detailed rates are paid [I8] | Mixing count and amount bases; ignoring shock lapse at the end of level periods; crude exposure instead of an actuarial exposure method [I8] |
| Mortality A/E | actual-to-expected | Observed deaths vs table-expected | actual deaths (or amounts) ÷ expected under a table (e.g. VBT) | product × duration × underwriting class | Intercompany studies published by SOA ILEC [I9]; no single number | Count vs amount basis; unmatched table vintage |

Life & annuity industry context 2025: ROE 5.7%, ROA 0.5% [I1].

### Playbook

1. **Combined ratio rises** → split loss vs expense ratio → within losses: catastrophe vs non-cat; current accident year vs prior-year reserve development; frequency vs severity by line/coverage; rate adequacy (earned rate change vs loss trend); mix (new vs renewal, geography). Action: rate filings, underwriting tightening, reinsurance, exposure management in cat zones.
2. **Auto severity spikes** → parts/labour inflation, total-loss share, repair cycle time and rental days, attorney representation (bodily injury), large-loss concentration. Action: repair-network steering, subrogation, litigation management, case-reserve review.
3. **Frequency rises** → exposure shifts (miles driven, new territories), weather events, new-business cohort quality, fraud rings. Action: pricing variables, underwriting rules, special investigations unit.
4. **Retention drops** → renewal rate-change size, competitor pricing, post-claim experience, agent/channel changes, billing failures. Action: rate capping, retention offers, service recovery.
5. **Adverse reserve development** → line × accident year; claim-closure speed changes (distort chain-ladder); case-reserving practice changes; litigation trends. Action: reserve strengthening, claims-practice audit.
6. **Life lapses rise** → product (UL/IUL crediting vs market rates), policy duration (end of level term), payment mode, orphaned policies after agent churn. Action: conservation campaigns, repricing, persistency incentives.

### Ontology sketch

Objects: **Party** (insured, claimant, beneficiary) · **Producer/Agent** · **Account** · **Submission/Quote** · **Policy** · **PolicyTerm/Version** (endorsements) · **Coverage** · **InsuredRisk** (vehicle, location, life) · **PremiumTransaction** · **Invoice** · **Claim** · **Exposure** (claim feature per coverage × claimant) · **Reserve** · **ClaimPayment** · **Recovery** (salvage/subrogation) · **CatastropheEvent** · **ReinsuranceTreaty**; life adds **Contract**, **Rider**, **CashValue**.

Links: Policy N:1 Account · Policy 1:N PolicyTerm · PolicyTerm 1:N Coverage · Coverage N:1 InsuredRisk · Claim N:1 PolicyTerm (the term in force on the loss date) · Claim 1:N Exposure · Exposure N:1 Coverage · Reserve and ClaimPayment N:1 Exposure · Claim N:0..1 CatastropheEvent · Policy N:1 Producer · ReinsuranceTreaty N:M Policy.

Lifecycles:
- Submission: `received → quoted → bound | declined | lost`.
- Policy: `bound → in_force → (endorsed)* → renewed | non_renewed | cancelled | expired`.
- Claim: `reported (FNOL) → open → accepted | denied → paying → closed | closed_without_payment`, with `closed → reopened` allowed.
- Life contract: `applied → underwritten → issued → in_force → lapsed | surrendered | death_claim_paid | matured` (`lapsed → reinstated` allowed).

Processes & promises (NAIC Model Regulation 902, adopted variably by states; "days" are calendar days) [I6]:
- Acknowledge a claim notice within 15 days.
- Answer an insurance-department inquiry within 21 days.
- Accept or deny a first-party claim within 21 days of proof of loss, or say more time is needed; then re-notify every 45 days.
- Tender payment within 30 days of affirming liability when the amount is not in dispute.

### Systems & standards

- Systems: P&C core suites (Guidewire PolicyCenter/ClaimCenter/BillingCenter, Duck Creek, Majesco, Sapiens, Insurity, EIS); rating content (Verisk ISO); estimating (CCC, Mitchell); life/annuity administration (FAST, EXL LifePRO, Sapiens, DXC, Equisoft, Oracle OIPA); actuarial tools (Moody's AXIS, WTW Radar, Milliman Arius).
- Standards (quarry): **ACORD** — P&C AL3 (batch) and XML (real-time), Life & Annuity XML, plus a reference architecture of capability, process and information models [I10]; **NAIC Annual Statement Blank** (Schedule P loss triangles) [I11].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| freMTPL2freq / freMTPL2sev (French motor TPL) | https://www.openml.org/d/41214 | CC0 on OpenML [I12] | 677,991 policies, mostly one year, with exposure fraction and claim counts; severity file keyed by policy ID [I12] | Frequency per exposure-year, severity, pure premium, rating relativities (driver age, BonusMalus, region) |
| CAS Loss Reserving Database (NAIC Schedule P) | https://www.casact.org/publications-research/research/research-resources/loss-reserving-data-pulled-naic-schedule-p | Public research data (CAS) | Paid and incurred triangles with upper and lower (future) parts for six lines: PP auto liability, commercial auto, workers' comp, medical malpractice, other liability, product liability [I4] | Development factors, IBNR, ultimate loss ratios, back-testing reserve methods |
| SOA ILEC mortality experience data | https://www.soa.org/research/topics/indiv-mort-exp-study-list/ | SOA terms (verify) | Intercompany exposure and claims by duration, face band, underwriting class; CSV and pivot files [I9] | Mortality A/E by segment |
| NAIC industry snapshots | https://content.naic.org/sites/default/files/2025-ye-snapshot.pdf | Public | Industry aggregates, 2021–2025 | Reconciliation target for loss/expense/combined ratios |

### What generic analytics gets wrong here

- Mixes denominators: the loss ratio uses earned premium, the trade-basis expense ratio uses written premium [I1].
- Reads recent accident years as final; they are under-developed (IBNR). Compare years at equal development age.
- Computes frequency per policy rather than per earned exposure-year (freMTPL2's `Exposure` is a year fraction).
- Joins claims to policies without effective dating, so claims fan out across endorsements and renewals and are double counted.
- Averages combined ratios across lines or companies instead of premium-weighting, and ignores catastrophe-year volatility.

### Sources

- [I1] NAIC Industry Snapshots, period ended 31 Dec 2025 (P&C, Title, Life/A&H): https://content.naic.org/sites/default/files/2025-ye-snapshot.pdf
- [I2] Triple-I blog (14 May 2026), "U.S. P/C Market Records Hard-Earned Decade-Low Combined Ratio": https://www.iii.org/blog/u-s-p-c-market-records-hard-earned-decade-low-combined-ratio/
- [I3] Insurance Information Institute, Facts + Statistics: Auto insurance (ISO/Verisk data, 2024): https://www.iii.org/fact-statistic/facts-statistics-auto-insurance
- [I4] CAS, Loss Reserving Data Pulled from NAIC Schedule P: https://www.casact.org/publications-research/research/research-resources/loss-reserving-data-pulled-naic-schedule-p
- [I5] J.D. Power 2025 U.S. Auto Claims Satisfaction Study *(search summary)*: https://www.jdpower.com/business/press-releases/2025-us-auto-claims-satisfaction-study/
- [I6] NAIC Unfair Property/Casualty Claims Settlement Practices Model Regulation (Model 902), §§6–7: https://content.naic.org/sites/default/files/model-law-902.pdf
- [I7] NAIC, Risk-Based Capital: https://content.naic.org/insurance-topics/risk-based-capital
- [I8] SOA Research Institute & LIMRA, 2015–2021 UL Lapse Rate Experience Study (Nov 2023): https://content.naic.org/sites/default/files/call_materials/SOA-LIMRA%20Research%20-%202015-2021%20UL%20Lapse%20Study%20(1).pdf
- [I9] SOA Individual Life Mortality Experience Studies: https://www.soa.org/research/topics/indiv-mort-exp-study-list/
- [I10] ACORD Data Standards: https://www.acord.org/standards-architecture/acord-data-standards ; Reference Architecture: https://www.acord.org/standards-architecture/reference-architecture
- [I11] NAIC 2025 Annual Statement Blank – Property/Casualty: https://content.naic.org/sites/default/files/publication-asb-prop.pdf
- [I12] OpenML freMTPL2freq metadata (CC0; source CASdatasets): https://www.openml.org/api/v1/json/data/41214

---

## 5. Healthcare providers (hospitals, health systems, clinics)

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| Operating margin | operating margin index | Share of operating revenue left after operating expense | (operating revenue − operating expense) ÷ operating revenue | hospital × month (or year-to-date) | Kaufman Hall national **median**, Apr 2026 calendar-year-to-date: 2.5% including corporate allocations, 8.3% without; April month alone 3.4% / 9.2% [H1] | Comparing with-allocation and without-allocation figures; comparing a median index with a mean; hospital vs system level |
| Average length of stay (ALOS) | LOS | Mean inpatient days per stay | inpatient days ÷ discharges (or admissions) | hospital × period; case-mix adjust against DRG geometric mean LOS | ≈5.7 days, **derived** from AHA 2024 community hospitals: 562 inpatient days per 1,000 population ÷ 99 admissions per 1,000 [H2]. Condition-specific example: sepsis stays averaged 9.0 days in 2022 [H3] | Averaging hospital ALOS values; mixing observation stays with inpatient stays; no case-mix adjustment; long-stay outliers |
| Bed occupancy | census rate | Share of staffed beds occupied | occupied staffed beds ÷ staffed beds (midnight census or average daily census) | unit/hospital × day | US post-pandemic average 75% vs ≈64% in the pre-pandemic decade; 85% is treated as the shortage threshold [H4] | Using licensed instead of staffed beds; midnight census hides midday peaks |
| 30-day all-cause readmission rate | readmit rate | Share of discharges followed by a readmission within 30 days | readmissions ≤30 days ÷ index admissions (exclude in-hospital deaths, transfers, discharges without 30-day follow-up) | index discharge | 13.9 per 100 index admissions nationally, 2016–2020; 2020 by payer: Medicare 17.0, Medicaid 13.6, self-pay 11.9, private 8.5; Medicare ages 21–64: 21.4 [H5]. CMS HRRP covers six conditions/procedures, payment cut capped at 3%, hospitals peer-grouped by dual-eligible share [H6] | Counting planned readmissions and transfers; single-hospital data misses readmissions elsewhere; December discharges without follow-up window |
| ED left before treatment complete | LWBS, LBTC, walkaway rate | Share of ED arrivals who leave before care is complete | patients leaving before completion ÷ ED arrivals | ED × month | 2.6% in 2024 (4.9% in 2022, 2.7% in 2019); 2023 cohort range ≈1.2% (small EDs) to 4.5% (large EDs) [H7] | Pooling EDs of very different volume; excluding patients who leave after triage |
| ED median length of stay / door-to-provider | throughput | Time from arrival to departure / to first provider | median(departure − arrival); median(provider − arrival) | ED visit | 2024: median ED LOS 187 min; door-to-doctor ≈13 min; average boarding ≈108 min [H7] | Means instead of medians; mixing admitted and discharged patients |
| Initial denial rate | first-pass denial rate | Share of claims denied on first submission | denied claims ÷ submitted claims (by count **and** by dollars) | claim × payer × month | Nearly 15% of claims to private payers initially denied (2022 data, 516 hospitals); 54% of denials later overturned; $43.84 average cost to fight one denial [H8]. HFMA MAP Key AR-5 defines the remittance denial rate [H9] | Treating resubmissions as new claims; count vs dollar basis |
| Net days in A/R | DAR | Days of revenue sitting in receivables | net patient A/R (in-house + discharged-not-final-billed, net of allowances) ÷ average daily net patient service revenue [H9][H10] | hospital × month-end | No authoritative public benchmark verified | Gross charges instead of net; excluding DNFB; month-end timing effects |
| Clean claim rate | first-pass yield | Claims passing edits with no manual touch | claims passing edits without intervention ÷ claims accepted (MAP CL-1) [H9] | claim batch | No authoritative public benchmark | Counting clearinghouse-rejected claims inconsistently |
| Cost to collect | — | Revenue-cycle cost per dollar collected | total revenue-cycle cost ÷ total patient service cash collected (MAP FM-6) [H9] | hospital × year | No authoritative public benchmark | Leaving out outsourced vendor fees |

### Playbook

1. **Operating margin falls** → revenue per adjusted discharge (payer mix, case mix, denials, bad debt and charity — up 22% per calendar day year-on-year in April 2026 [H1]) → volume (adjusted discharges, surgical minutes, ED visits) → expense (labor per adjusted discharge: contract labor, overtime; supplies; drugs) → allocation changes. Action: labor productivity and contract-labor reduction, payer contracting, denial prevention, service-line mix.
2. **ALOS rises** → case-mix index shift vs throughput: discharge delays (post-acute placement — Premier found nearly 20% of discharges to post-acute care initially denied [H8]), weekend discharges, observation-status policy, occupancy above 85%. Action: discharge planning, care management, post-acute network agreements.
3. **Readmissions rise** → HRRP condition cohort → payer/age → discharge disposition (home vs skilled nursing) → follow-up visit within 7 days → medication reconciliation → coding or measure-definition changes. Action: transitional care, post-discharge calls, SNF partnerships.
4. **LWBS rises** → boarding time (tracks walkaway rates closely [H7]) → arrival surges by hour → staffing gaps → triage-to-provider interval → inpatient occupancy. Action: provider-in-triage, flex staffing, inpatient capacity management.
5. **Denials rise** → payer → denial reason (eligibility/prior authorization vs medical necessity vs coding) → service line → registration errors → payer policy changes. Action: eligibility verification, prior-authorization automation, clinical documentation improvement, appeals.
6. **Days in A/R rises** → discharged-not-final-billed days (coding backlog) → final-billed-not-submitted (claim edits) → denial backlog → payer slow-pay → self-pay growth. Action: coding capacity, edit fixes, payer escalation under prompt-pay rules.

### Ontology sketch

Objects: **Patient** · **Encounter** (inpatient, outpatient, ED, observation) · **BedAssignment** · **Location/Unit** · **Practitioner** · **ServiceLine/Department** · **Diagnosis** · **Procedure** · **Order** · **Observation/Result** · **MedicationAdministration** · **Appointment** · **Charge** · **HospitalAccount/Guarantor** · **Coverage** · **Payer** · **Claim** · **Remittance** · **Denial**.

Links: Encounter N:1 Patient · BedAssignment N:1 Encounter (transfers make it 1:N) · BedAssignment N:1 Location · Diagnosis and Procedure N:1 Encounter · Encounter N:M Practitioner (attending, consulting) · Charge N:1 Encounter · Claim N:1 HospitalAccount (interim bills make Claim N:M Encounter) · Remittance N:1 Claim (several remits per claim possible) · Denial N:1 Remittance line · Coverage N:1 Patient, N:1 Payer · derived readmission link Encounter 0..1 → index Encounter.

Lifecycles:
- Inpatient encounter: `pre_admit → arrived → admitted → in_bed ⇄ transferred → discharged` (terminal: discharged, died, left against medical advice); a new encounter within 30 days is flagged as readmission.
- ED visit: `arrived → triaged → seen_by_provider → dispositioned: admitted | discharged | transferred | left_before_complete`.
- Claim: `charges_captured → coded → billed → submitted → accepted | rejected → adjudicated → paid | denied → appealed → paid | written_off`.

Processes & promises:
- Medicare claims must be filed no later than one calendar year after the date of service [H11].
- HRRP: 30-day risk-standardized unplanned readmission measures; payment reduction capped at 3% [H6].
- Payer prior-authorization decisions: 72 hours expedited / 7 calendar days standard for impacted payers from 2026 (see §6).
- ED boarding time is part of CMS hospital reporting [H7].

### Systems & standards

- Systems: EHR (Epic, Oracle Health/Cerner, MEDITECH, athenahealth, eClinicalWorks); revenue cycle (Epic Resolute, R1, Waystar clearinghouse); ERP/HR (Workday, Oracle, UKG); decision support/cost accounting (Strata — the data behind the Kaufman Hall report [H1]); bed management (TeleTracking). HL7 v2 ADT feeds are the usual source of encounter events.
- Standards (quarry): **HL7 FHIR** — R5 (v5.0.0) is the current published version; resources include Patient, Encounter, Condition, Procedure, Observation, MedicationRequest, Claim, ExplanationOfBenefit, Coverage [H12]; **OMOP CDM** v5.5 (VISIT_OCCURRENCE, CONDITION_OCCURRENCE, COST, PAYER_PLAN_PERIOD, etc.) [H13]; **X12 837 (institutional/professional) and 835** HIPAA transactions [H14]; **HFMA MAP Keys** for revenue-cycle KPI definitions [H9].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| MIMIC-IV v3.1 (Beth Israel Deaconess, 2008–2022) | https://physionet.org/content/mimiciv/3.1/ | PhysioNet Credentialed Health Data License 1.5.0; CITI training + DUA required [H15] | 364,627 patients; 546,028 hospitalizations; 94,458 ICU stays; hosp, icu, ED and note modules [H15] | ALOS, ICU LOS, in-hospital mortality, same-hospital readmissions, ED LOS/boarding; no costs or denials |
| CMS HCRIS hospital cost reports (form 2552-10) | https://www.cms.gov/data-research/statistics-trends-and-reports/cost-reports | US public data | Every Medicare-certified hospital, annual [H17] | Operating margin, payer-mix days, beds and bed-days (occupancy), cost-to-charge ratios |
| CMS Provider Data Catalog — "Unplanned Hospital Visits" and "Timely and Effective Care" | https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/632h-zaca | Public [H18] | Hospital-level measures; updated July 2026 [H18] | Readmission and excess-days measures; ED throughput measures — a hospital-level falsifier |
| Synthea / SyntheticMass | https://github.com/synthetichealth/synthea | Apache-2.0 [H16] | Generator; SyntheticMass ships 1M synthetic patients in FHIR, C-CDA and CSV [H16] | Pipeline/schema tests for encounters, claims, costs — rates are simulated, not real-world benchmarks |
| HCUP Nationwide Readmissions Database | https://hcup-us.ahrq.gov/nrdoverview.jsp | Paid; HCUP Data Use Agreement [H19] | 2010–2022; 30 states; ≈16.5M unweighted discharges in 2022 [H19] | National readmission rates (not hospital-specific) |

### What generic analytics gets wrong here

- Averages hospital-level rates (ALOS, readmission, margin) instead of pooling numerators and denominators; and compares medians (Kaufman Hall) with means.
- Counts transfers and planned readmissions as readmissions, or uses single-hospital data (e.g. MIMIC-IV) and misses readmissions to other facilities.
- Treats observation patients as inpatients (or ignores them), distorting ALOS and occupancy; uses licensed rather than staffed beds.
- Double counts revenue when joining claims to encounters (interim bills, late charges, multiple remittances per claim).
- Reports denial rates by count when the business manages dollars, and counts resubmissions as new claims.

### Sources

- [H1] Kaufman Hall, National Hospital Flash Report, April 2026 metrics: https://www.kaufmanhall.com/sites/default/files/2026-06/KH-NHFR_Report-April-2026-Metrics.pdf
- [H2] KFF State Health Facts (AHA Annual Survey 2024): inpatient days per 1,000 https://www.kff.org/other/state-indicator/inpatient-days-by-ownership/ ; admissions per 1,000 https://www.kff.org/other/state-indicator/admissions-by-ownership/
- [H3] AHRQ HCUP Statistical Brief #306 addendum (June 2025): https://hcup-us.ahrq.gov/reports/statbriefs/sb306-overview-sepsis-2016-2022-addendum.pdf
- [H4] UCLA Health release on Leuchter et al., JAMA Network Open (Feb 2025): https://www.uclahealth.org/news/release/us-facing-critical-hospital-bed-shortage-2032-ucla-research
- [H5] AHRQ HCUP Statistical Brief #304, 30-day all-cause readmissions 2016–2020: https://hcup-us.ahrq.gov/reports/statbriefs/sb304-readmissions-2016-2020.jsp
- [H6] CMS Hospital Readmissions Reduction Program: https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/hospital-readmissions-reduction-program-hrrp
- [H7] Emergency Department Benchmarking Alliance, 2024 ED Performance Measures Report (July 2025): https://iepc.org/wp-content/uploads/2025/09/2024-EDBA-Data-Report-v8-002.pdf
- [H8] Premier Inc., claims denial survey: https://premierinc.com/newsroom/blog/trend-alert-private-payers-retain-profits-by-refusing-or-delaying-legitimate-medical-claims
- [H9] HFMA MAP Keys: https://www.hfma.org/data-and-insights/map-initiative/map-keys/
- [H10] HFMA, Ask the Experts: Net Days in A/R: https://www.hfma.org/accounting-and-financial-reporting/52117/
- [H11] 42 CFR 424.44 (claim filing time limits): https://www.law.cornell.edu/cfr/text/42/424.44
- [H12] HL7 FHIR specification home: https://hl7.org/fhir/
- [H13] OHDSI OMOP Common Data Model: https://ohdsi.github.io/CommonDataModel/
- [H14] CMS, HIPAA adopted standards and operating rules: https://www.cms.gov/priorities/key-initiatives/burden-reduction/administrative-simplification/hipaa/adopted-standards-operating-rules ; X12 transaction sets: https://x12.org/products/transaction-sets
- [H15] MIMIC-IV v3.1 on PhysioNet: https://physionet.org/content/mimiciv/3.1/
- [H16] Synthea: https://github.com/synthetichealth/synthea ; downloads: https://synthea.mitre.org/downloads
- [H17] CMS Cost Reports: https://www.cms.gov/data-research/statistics-trends-and-reports/cost-reports ; NBER HCRIS files: https://www.nber.org/research/data/hcris-hosp
- [H18] CMS Provider Data Catalog metadata: https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/632h-zaca ; https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/yv7e-xc69
- [H19] AHRQ HCUP Nationwide Readmissions Database overview: https://hcup-us.ahrq.gov/nrdoverview.jsp

---

## 6. Health payers / health insurance

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| ACA medical loss ratio (regulatory) | MLR, 80/20 rule | Share of premium spent on care and quality improvement | (incurred claims + quality-improvement expense) ÷ (premium − taxes and fees), 3-year average with credibility adjustment | issuer × state × market × year | Minimum 85% large group, 80% small group and individual; below that the issuer rebates enrollees [Y1]. Rebates paid in 2025 exceeded $1.6B (based on 2022–2024) [Y1] *(search summary)* | Treating the regulatory MLR as the same thing as a statutory loss ratio or a 10-K medical cost ratio |
| Statutory loss ratio | medical cost ratio (approx.) | Claims cost per premium dollar | total hospital & medical expenses ÷ net earned premium | line of business × year | US health entities 2025: 90.3% aggregate; comprehensive 90.7%; Medicare 90.5%; Medicaid 90.7%; Medicare supplement 86.8%; FEHBP 93.8%; dental 81.1%; vision 73.1% [Y2] | Pooling lines with very different ratios (vision vs Medicare) without mix analysis |
| Administrative expense ratio | admin ratio | Non-claims cost per premium dollar | (claims adjustment + general administrative expenses) ÷ net earned premium | line × year | 2025: 10.3% aggregate; comprehensive 13.8%; Medicare 10.1%; Medicaid 9.6% [Y2] | Classifying care-management or quality spend inconsistently between admin and medical |
| Combined ratio / profit margin | underwriting result | Claims + admin vs premium; net income vs revenue | loss ratio + admin ratio; net income ÷ revenue | company/line × year | 2025: combined 100.6%, profit margin 0.4%, net income $6.0B across 1,156 health filers [Y2] | Ignoring investment income, which offset an $8.1B underwriting loss in 2025 [Y2] |
| Premium and claims PMPM | per member per month | Dollars per member for each month of coverage | Σ amount ÷ Σ member-months | line × month | 2025: premium $372 / claims $337 aggregate; comprehensive $558 / $506; Medicare $1,458 / $1,321; Medicaid $578 / $526 [Y2] | Dividing by period-end enrollment rather than member-months; comparing lines with different acuity |
| Utilization per 1,000 | admits/1000, days/1000 | Service use normalized to population size | events × 12,000 ÷ member-months | category of service × period | Population reference (all payers, community hospitals, 2024): 99 admissions and 562 inpatient days per 1,000 population [H2 in §5] | Incurred-date counts for immature months (claims lag); population vs insured-population mix |
| Claim denial rate (payer side) | denial rate | Share of claims denied | denied claims ÷ claims received | issuer × plan year | HealthCare.gov insurers 2023: ≈19–20% of in-network claims and 36–37% of out-of-network claims denied; insurer range 1%–54%; fewer than 1% of denials appealed; 56% of appealed denials upheld [Y3] | Counting administrative rejections and duplicate submissions as denials; 34% of denials carry an unspecified "other" reason [Y3] |
| Prior-authorization turnaround | PA decision time | Time from PA request to decision | decision timestamp − receipt timestamp, measured against the applicable clock | PA request | Rule, not benchmark: 72 hours expedited, 7 calendar days standard for Medicare Advantage, Medicaid and CHIP payers from 1 Jan 2026; public PA metrics from 31 Mar 2026 [Y4]. Part D coverage determinations: 72 hours; payment requests 14 calendar days [Y5] | Measuring from when the request was complete instead of when it was received; business days vs calendar days |
| Clean-claim prompt payment | prompt pay | Share of clean claims paid within the statutory window | clean claims paid ≤30 days ÷ clean claims received | payer × month | Rule: Medicare Advantage organizations must pay 95% of clean claims from non-contracted providers within 30 days; other non-contracted claims paid or denied within 60 days [Y6] *(search summary)* | Not separating clean from unclean claims; state prompt-pay laws differ |
| Electronic transaction adoption | CAQH Index | Share of admin transactions done fully electronically | electronic transactions ÷ all transactions, by type | industry × year | CAQH Index 2025 sizes the remaining savings opportunity at $21B [Y7]; only ≈35% of medical prior authorizations were fully electronic (X12 278) in the 2024 Index [Y7] *(search summary)* | Mixing portal-based (partially manual) with fully electronic transactions |

### Playbook

1. **Loss ratio / PMPM rises** → decompose claims PMPM into utilization per 1,000 × unit cost × service mix (inpatient, outpatient, professional, pharmacy — GLP-1 drugs added $14B of US drug-spend growth in 2025, per §7) → large claimants → membership mix and risk-score drift → premium side (rate adequacy, risk-adjustment revenue) → claims-lag completion (IBNR). Action: rate filings, utilization management, network contracting, formulary changes, high-cost-member care management.
2. **Denials or appeals rise** → denial reason (administrative vs medical necessity vs missing prior authorization) → provider cohort → newly deployed payment-policy edits → eligibility-file (834) errors. Action: roll back or tune edits, provider education, PA "gold-carding".
3. **PA turnaround breaches the clock** → request volume by service type → pended-for-information share → staffing → electronic PA adoption (X12 278 / FHIR PAS) → auto-approval rules. Action: automation, criteria updates, staffing.
4. **Membership churn rises** → enrollment events (open vs special enrollment, Medicaid eligibility checks) → premium changes (ACA marketplace median premiums rose ≈20% after enhanced tax credits expired at end-2025 [Y2]) → broker/channel → Star Ratings changes (Medicare Advantage). Action: retention outreach, pricing, broker programs.
5. **Admin PMPM rises** → claims per member → manual-touch (pend) rate → call volumes → provider-data errors → mandated projects (CMS APIs due 2027 [Y4]). Action: auto-adjudication fixes, provider-directory clean-up.
6. **Star Rating / HEDIS measure drops** → which measure domain (screenings, medication adherence PDC measures — see §7, member experience surveys) → member cohort → provider group. Action: gap-closure campaigns, pharmacy adherence outreach.

### Ontology sketch

Objects: **Member** · **Subscriber** · **Employer/Group** · **Plan/Product** · **BenefitPackage** · **EnrollmentSpan** · **PremiumInvoice** · **Provider** (NPI) · **NetworkContract** · **FeeSchedule** · **Claim** · **ClaimLine** · **Adjudication** (versioned) · **Payment/Remittance** · **AdjustmentReason** · **PriorAuthorization** · **Appeal/Grievance** · **CareManagementCase** · **RiskScore** · **QualityGap** (HEDIS) · **Accumulator** (deductible, out-of-pocket).

Links: Member N:1 Subscriber · EnrollmentSpan N:1 Member and N:1 Plan · Plan N:1 Group (commercial) · Claim N:1 Member and N:1 billing Provider · ClaimLine N:1 Claim and N:1 rendering Provider · Adjudication N:1 ClaimLine (adjustments and reversals create new versions) · Payment N:M Claim (835 batches) · PriorAuthorization N:1 Member, linked 0..N to Claims by authorization number · Appeal N:1 Claim or PriorAuthorization · RiskScore N:1 Member × year · Accumulator N:1 Member × plan year.

Lifecycles:
- Claim: `received → pended → adjudicated → paid | denied | partially_paid → adjusted | reversed → appealed → overturned | upheld → external_review`.
- PriorAuthorization: `requested → pended_for_info → approved | partially_approved | denied → appealed` with 72-hour / 7-day clocks [Y4].
- EnrollmentSpan: `applied → effectuated → active → grace_period → terminated` (reinstatement possible).

Processes & promises: PA decision clocks [Y4]; Part D coverage determination clock [Y5]; Medicare Advantage prompt pay [Y6]; annual MLR reporting and rebates [Y1]; HIPAA transactions carry the process: 834 enrollment, 820 premium payment, 270/271 eligibility, 278 prior authorization, 837 claim, 276/277 claim status, 835 payment/remittance [H14 in §5].

### Systems & standards

- Systems: core administration (Cognizant TriZetto Facets and QNXT, HealthEdge HealthRules Payer, Epic Tapestry; Gainwell for Medicaid), payment integrity and claim editing (Optum, Cotiviti), care management (ZeOmega Jiva, Salesforce Health Cloud), PBMs (CVS Caremark, Express Scripts, Optum Rx), risk adjustment and quality (Inovalon, Cotiviti), clearinghouses (Availity).
- Standards (quarry): **X12 HIPAA transactions** [H14]; **HL7 Da Vinci Prior Authorization Support** FHIR IG v2.2.1 (STU 2) [Y9]; **CARIN Blue Button** FHIR IG v2.2.0 (STU 2, FHIR R4) for consumer-facing claims/EOB data [Y10]; **NCQA HEDIS** measure specifications [Y11]; **CMS Part C & D Star Ratings** technical notes [Y8]; OMOP `PAYER_PLAN_PERIOD` and `COST` tables [H13].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| CMS 2008–2010 DE-SynPUF | https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf/de10-sample-1 | Free public use file | Built from a 5% sample of 2008 Medicare beneficiaries; beneficiary summary, inpatient, outpatient, carrier and prescription-drug-event files; synthetic with limited inferential value [Y12] | PMPM, utilization per 1,000, claim header/line structure, member-month construction; no denials or PA |
| AHRQ MEPS Household Component public use files | https://meps.ahrq.gov/survey_comp/household.jsp | US public data | Nationally representative person-, event- and condition-level files with expenditures by source of payment [Y13] | Spend per person by payer, utilization rates, out-of-pocket share |
| NAIC health industry tables (aggregate) | https://content.naic.org/sites/default/files/2025-annual-health-industry-commentary.pdf | Public | Ten-year aggregates by line [Y2] | Reconciliation target for loss ratio, admin ratio, PMPM |
| Synthea (synthetic claims and costs) | https://github.com/synthetichealth/synthea | Apache-2.0 | Generator [H16 in §5] | Schema and pipeline tests only |

### What generic analytics gets wrong here

- Divides by period-end enrollment instead of member-months when computing PMPM and utilization per 1,000.
- Trends claims on incurred date without completion factors: recent months look cheap because claims have not arrived yet.
- Sums paid amounts across claim versions (original, adjustment, reversal) and double counts.
- Conflates three different ratios: ACA regulatory MLR, statutory loss ratio, and the medical cost ratio in earnings releases.
- Compares PMPM across years or groups without risk adjustment (risk-score drift).

### Sources

- [Y1] 45 CFR 158.210 (minimum MLR): https://www.law.cornell.edu/cfr/text/45/158.210 ; CMS MLR data resources: https://www.cms.gov/marketplace/resources/data/medical-loss-ratio-data-systems-resources ; rebate totals *(search summary)*: https://www.healthinsurance.org/obamacare/billions-in-aca-rebates-show-80-20-rules-impact/
- [Y2] NAIC, U.S. Health Insurance Industry Analysis Report, 2025 annual results: https://content.naic.org/sites/default/files/2025-annual-health-industry-commentary.pdf
- [Y3] KFF, Claims Denials and Appeals in ACA Marketplace Plans in 2023: https://www.kff.org/private-insurance/claims-denials-and-appeals-in-aca-marketplace-plans-in-2023/ ; companion analysis: https://www.kff.org/private-insurance/healthcare-gov-insurers-denied-nearly-1-in-5-in-network-claims-in-2023-but-information-about-reasons-is-limited-in-public-data/
- [Y4] CMS fact sheet, Interoperability and Prior Authorization Final Rule (CMS-0057-F): https://www.cms.gov/newsroom/fact-sheets/cms-interoperability-prior-authorization-final-rule-cms-0057-f
- [Y5] 42 CFR 423.568: https://www.law.cornell.edu/cfr/text/42/423.568
- [Y6] 42 CFR 422.520 *(search summary)*: https://www.ecfr.gov/current/title-42/chapter-IV/subchapter-B/part-422/subpart-K/section-422.520
- [Y7] CAQH Index (now DataSpring): https://dataspring.com/advisory-services/index-report ; 2024 Index coverage *(search summary)*: https://www.ajmc.com/view/2024-caqh-index-foresees-major-opportunity-for-health-care-savings
- [Y8] CMS Part C and D Performance Data (Star Ratings): https://www.cms.gov/medicare/health-drug-plans/part-c-d-performance-data
- [Y9] HL7 Da Vinci Prior Authorization Support IG: https://hl7.org/fhir/us/davinci-pas/
- [Y10] HL7 CARIN Blue Button IG: https://hl7.org/fhir/us/carin-bb/
- [Y11] NCQA HEDIS (site blocks automated fetch): https://www.ncqa.org/hedis/
- [Y12] CMS DE-SynPUF FAQ: https://www.cms.gov/files/document/de-10-frequently-asked-questions.pdf
- [Y13] AHRQ MEPS: https://www.ahrq.gov/data/meps.html

---

## 7. Pharma & life sciences — commercial analytics

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| TRx | total prescriptions | All dispensed prescriptions for a product, new and refills | count(dispensed prescriptions); compare also standardized 30-day fills | prescriber × product × week/month | No free national product-level benchmark (IQVIA/Symphony audits are paid). Public Medicare-only proxy: Part D claims (original + refills) and standardized 30-day fills by prescriber × drug [R1] | Treating a 90-day fill as equal to a 30-day fill; reading Medicare Part D as the whole market |
| NRx vs NBRx | new Rx; new-to-brand Rx | NRx = new prescription numbers (continuing patients can generate them); NBRx = patients new to the brand (naïve starts, switches, add-ons) | NRx: count(new Rx numbers). NBRx: count(patients whose first claim for the brand falls in period, after a lookback with no brand claims) | prescriber × product × week; NBRx needs patient-level longitudinal data | Vendor-defined (lookback windows differ); no public benchmark | Calling NRx "new patients"; comparing NBRx across vendors with different lookbacks |
| Market share | TRx share, NBRx share | Product's portion of a defined therapeutic market | product units (or days of therapy) ÷ market units | market × geography × period | No public benchmark; NBRx share typically leads TRx share | Changing the market definition mid-trend (a new entrant mechanically lowers share); mixing units and days of therapy |
| Gross-to-net (GTN) discount | GTN, net sales adjustment | Share of list-price sales given back as rebates, discounts, chargebacks and other concessions | (gross sales at WAC − net sales) ÷ gross sales at WAC | product × channel × quarter | US market 2024: $1,216B at list (WAC) vs $544B at net manufacturer prices — a $672B gap, ≈55% of WAC [R2] | Reporting growth on list prices; ignoring accrual true-ups; applying a market-average GTN to one product |
| Net spending & volume | net medicine spending; days of therapy | Dollars actually realized and units consumed | Σ net spend; Σ days of therapy | market × year | US 2025: $606B net spending (+10.6%); 210B days of therapy (+1.5%); patient out-of-pocket $110B; GIP/GLP-1 drugs added $14B of growth. Forecast to 2030: list +6–9%/yr vs net +4.5–7.5%/yr [R3] | Comparing invoice-level and net-level figures from different methodologies (IQVIA revised its net method in 2026 [R2]) |
| Unfilled new prescriptions | abandonment, payer rejection | Share of new prescriptions never dispensed | (rejected + abandoned) ÷ new prescriptions written | product × first year on market | Novel medicines 2020–2024: of 7M first-year new prescriptions, 65% went unfilled — 49% rejected by payers, 17% abandoned by patients after approval [R3] | Counting a rejected claim that is later resubmitted and paid as abandoned |
| Adherence — proportion of days covered (PDC) | PDC ≥80% rate | Share of patients whose supply covers most days in the measurement period | days covered ÷ days in period (overlaps shifted, capped at 100%); report % of patients with PDC ≥ threshold | patient × measurement year, rolled to plan/brand | Threshold, not rate: 80% standard; 90% for antiretrovirals. PQA measures for diabetes drugs, RAS antagonists and statins feed Medicare Part D Star Ratings [R4] | Double counting overlapping fills; not capping at 100%; inconsistent period start (index fill vs calendar) |
| Persistence | time on therapy | How long patients stay on therapy | days from first fill to discontinuation (gap in supply > grace period) | patient | No public benchmark — varies by class and by the grace period chosen | Changing the grace period silently changes the answer; censoring patients who switch plans as discontinued |
| Reach & frequency | call reach, coverage | Share of target prescribers contacted and how often | targets with ≥1 interaction ÷ target list; interactions ÷ reached targets | territory × product × month | No free authoritative benchmark (industry access benchmarks are proprietary) | Counting emails and live calls as equivalent; stale target lists |
| HCP transfers of value | Open Payments spend | Payments and transfers of value to physicians and teaching hospitals | Σ reported payments | manufacturer × recipient × program year | Program Year 2025: 17.07M published records totaling $14.67B [R5] | Inferring prescribing causality from payment–prescribing correlation |

### Playbook

1. **TRx share declines** → NBRx share (leading) vs continuing-patient persistence (lagging) → payer access (formulary tier, prior authorization, step edits, rejections) → competitor launch or loss of exclusivity → channel shift (specialty, mail) → territory → data-vendor restatement. Action: rebate contracting, hub/patient support, field targeting.
2. **NBRx drops** → prescriber segments (decile, specialty) → access changes at top plans → competitor activity → field coverage gaps (vacant territories) → supply shortages → guideline changes. Action: re-targeting, peer programs, copay support.
3. **GTN widens** → payer/channel mix (Medicaid, 340B, Medicare Part D redesign) → new rebate contracts → copay program utilization → chargeback and returns accruals → list-price change timing. Action: contract renegotiation, copay program caps, pricing strategy.
4. **Adherence / persistence falls** → out-of-pocket exposure (Part D redesign capped enrollee costs at $2,000 in 2025 [Y2 in §6]) → side-effect signals → pharmacy channel and 90-day conversion → support-program enrollment → shortages. Action: adherence outreach, 90-day conversion, affordability support.
5. **Field effectiveness drops** → reach/frequency on targets → access restrictions → channel mix (remote, digital) → vacancies → target-list quality. Action: territory realignment, omnichannel orchestration, vacancy fills.

### Ontology sketch

Objects: **Product** (brand) · **Package** (NDC) · **Substance/Molecule** · **TherapeuticMarket** · **HCP** (NPI) · **HCO/Account** (hospital, IDN, clinic) · **Territory** · **SalesRep** · **Interaction** (call, email, event) · **Sample** · **TransferOfValue** · **Prescription** · **PharmacyClaim** (paid, rejected, reversed) · **Patient** (de-identified token) · **Pharmacy** · **Payer/Plan** · **FormularyStatus** · **RebateContract** · **GTNAccrual** · **HubEnrollment**.

Links: Package N:1 Product · Product N:M Substance · Product N:M TherapeuticMarket · Prescription N:1 HCP, N:1 Patient, N:1 Package, N:1 Pharmacy, N:1 Plan · PharmacyClaim N:1 Prescription (reversals and rebills make it 1:N) · HCP N:M HCO (affiliations) · HCP N:1 Territory (alignment changes over time) · Territory N:1 SalesRep (time-varying) · Interaction N:1 HCP, N:1 SalesRep, N:M Product · TransferOfValue N:1 HCP or teaching hospital and N:1 manufacturer · FormularyStatus N:1 Plan × Product × effective period · RebateContract N:1 Payer.

Lifecycles:
- Pharmacy claim: `submitted → paid | rejected → (resubmitted → paid) → dispensed → picked_up | reversed/abandoned`.
- Patient on therapy: `naive → new_to_brand (start | switch | add_on) → persistent ⇄ gap → discontinued | switched_out`.
- Product: `approved → launch → growth → mature → loss_of_exclusivity → generic/biosimilar erosion → discontinued`.
- Open Payments record: collected Jan–Dec; manufacturer submission 1 Feb–31 Mar; recipient review and dispute 1 Apr–15 May; CMS publishes by 30 Jun [R5].

Processes & promises: Open Payments annual cycle [R5]; Part D coverage determinations within 72 hours [Y5 in §6]; PDC measurement-year conventions [R4].

### Systems & standards

- Systems: prescription and sales data (IQVIA Xponent/NPA/DDD, Symphony Health, Komodo Health); CRM (Veeva, Salesforce Life Sciences Cloud); HCP/HCO master data (Veeva OpenData, IQVIA OneKey, Reltio); incentive compensation (Varicent, Xactly); contracting and GTN (Model N, IntegriChain); specialty pharmacy/hub data aggregators; ERP (SAP).
- Standards (quarry): **FDA NDC** — three-segment labeler/product/package identifier; directory updated daily [R6]; **ISO IDMP** — ISO 11615 (medicinal products), 11616 (pharmaceutical products), 11238 (substances), 11239 (dose forms, routes, units of presentation), 11240 (units of measurement), implemented by EMA through SPOR master data [R7]; **PQA** adherence measures [R4]; **OMOP CDM** `DRUG_EXPOSURE` [H13 in §5]; **CMS cell-size suppression policy** — cells with values 1–10 may not be reported [R8].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| Medicare Part D Prescribers by Provider and Drug | https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/medicare-part-d-prescribers-by-provider-and-drug | US government work, public [R1] | Annual 2013–2024; one row per prescriber NPI × drug; total claims (original + refills), standardized 30-day fills, drug cost, beneficiaries [R1]; small counts suppressed [R8] | TRx and 30-day-fill proxies, prescriber deciles, Part D market share, cost per claim. Cannot compute NBRx or persistence (no patient history) |
| CMS Open Payments | https://openpaymentsdata.cms.gov/ | Public | PY2025: 17.07M records, $14.67B [R5] | HCP engagement spend by category and manufacturer; NPI joins to Part D prescribing (association only) |
| Medicaid State Drug Utilization Data | https://www.medicaid.gov/medicaid/prescription-drugs/state-drug-utilization-data | Public | NDC-level Medicaid outpatient drug utilization by state and quarter, reported since the start of the Medicaid Drug Rebate Program [R9] | Units, prescriptions, reimbursement by product and state |
| FDA NDC Directory | https://www.fda.gov/drugs/drug-approvals-and-databases/national-drug-code-directory | Public | Daily-updated product/package listing [R6] | Reference joins: NDC → product → labeler |
| CMS DE-SynPUF prescription drug events | https://www.cms.gov/files/document/de-10-frequently-asked-questions.pdf | Public, synthetic | 2008–2010 synthetic PDE file [Y12 in §6] | Mechanical tests of PDC and persistence logic only |

No public, real, patient-level longitudinal prescription dataset exists; NBRx, persistence and switching can only be tested on synthetic data.

### What generic analytics gets wrong here

- Adds prescriptions of different lengths; a 90-day fill is one prescription but three standardized 30-day fills [R1].
- Treats NRx as new patients; NBRx needs patient-level lookback.
- Reports growth at list price; the US list-to-net gap was ≈55% of WAC in 2024 [R2], and product-level GTN varies widely.
- Double counts overlapping fills in PDC and forgets the 100% cap.
- Treats suppressed small cells as zeros [R8], biasing low-volume prescribers and rare drugs; and changes the market definition mid-trend.

### Sources

- [R1] CMS, Medicare Part D Prescribers by Provider and Drug: https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/medicare-part-d-prescribers-by-provider-and-drug ; data.gov record (2013–2024, public): https://catalog.data.gov/dataset/medicare-part-d-prescribers-by-provider
- [R2] IQVIA Institute, Measuring the Estimated Size of the U.S. Pharmaceutical Market on a Net Manufacturer Price Basis (technical note, Mar 2026), Exhibits 2, 3, 6: https://www.iqvia.com/-/media/iqvia/pdfs/institute-reports/measuring-the-estimated-size-of-the-us-pharmaceutical-market-on-a-net-manufacturer-price-basis/iqvia-measuring-the-us-pharma-market---tech-note-03-26-forweb.pdf
- [R3] IQVIA Institute, U.S. Medicine Use Trends 2026: https://www.iqvia.com/insights/the-iqvia-institute/reports-and-publications/reports/us-medicine-use-trends-2026
- [R4] Pharmacy Quality Alliance, Measures & Resources: https://www.pqa.org/measures/measures-resources/
- [R5] CMS Open Payments: https://www.cms.gov/priorities/key-initiatives/open-payments
- [R6] FDA National Drug Code Directory: https://www.fda.gov/drugs/drug-approvals-and-databases/national-drug-code-directory
- [R7] EMA, Data on medicines (ISO IDMP standards): https://www.ema.europa.eu/en/human-regulatory-overview/research-development/data-medicines-iso-idmp-standards-overview
- [R8] ResDAC, CMS Cell Size Suppression Policy: https://resdac.org/articles/cms-cell-size-suppression-policy
- [R9] Medicaid.gov, State Drug Utilization Data: https://www.medicaid.gov/medicaid/prescription-drugs/state-drug-utilization-data

---

## 8. Telecommunications (mobile & broadband)

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| Postpaid phone churn | churn rate | Share of subscribers who leave in a month | disconnects in month ÷ average subscribers in month | carrier/segment × month (reported as quarterly average of monthly) | Q2 2026: AT&T 0.86% [T1]; Verizon 0.92% [T2]. T-Mobile now reports only postpaid **account** churn: 0.99% [T2] | Mixing lines and accounts (carriers retired comparable metrics at end-2025 [T2]); average vs opening subscribers; voluntary and involuntary (non-pay) pooled; annualizing as 12× monthly |
| ARPU / ARPA | average revenue per user / account | Service revenue per subscriber (or account) per month | service revenue ÷ average subscribers (or accounts) ÷ months | segment × quarter | Q2 2026: Verizon ARPA $168.35 (from $170.79); T-Mobile $152.91 per postpaid account [T2] | Including equipment/device-installment revenue; IoT connections diluting "per user" figures |
| Net additions | net adds | Subscriber growth after losses | gross adds − disconnects | product × quarter | Q2 2026: AT&T 432K postpaid phone, 367K fiber [T1]; Verizon 184K postpaid phone, 348K broadband (193K fixed wireless + 155K fiber) [T3] | Comparing units that are not the same product (FWA vs fiber; lines vs accounts) |
| Unique-subscriber penetration | mobile penetration | Share of population with a mobile subscription | unique subscribers ÷ population | country/region × year | 5.8B unique mobile subscribers worldwide, about 70% of the global population [T4] *(search summary of GSMA post)* | Counting SIMs/connections (multi-SIM, IoT) as people |
| 5G adoption | 5G share | Subscriptions on 5G | 5G subscriptions ÷ mobile subscriptions | region × quarter | Close to 3.3B 5G subscriptions worldwide (June 2026) [T5] | Counting 5G-capable devices rather than 5G subscriptions |
| RAN accessibility & retainability | setup success rate, drop rate | Can a session start, and does it stay up | successful setups ÷ attempts; abnormal releases ÷ established sessions | cell × 15-min/hour, rolled to cluster/market | KPI definitions standardized in 3GPP TS 32.450 [T6]; no public cross-operator benchmark | Averaging cell-level rates without weighting by attempts; excluding outage windows |
| Delivered broadband speed / latency | throughput | Speeds users actually get | median download, upload, latency across tests | geographic tile × quarter | Ookla open data: fixed and mobile tiles quarterly Q1 2019 – Q1 2026 [T7]; no single benchmark | Crowdsourced tests over-sample problem moments; mean speeds skewed by fast outliers |
| Simple port completion | porting interval | Time to move a number to a new carrier | port completion timestamp − valid request timestamp (business days) | port request | Rule: simple wireline and intermodal ports within one business day [T8] | Clock start before a complete, valid request; calendar vs business days |

### Playbook

1. **Postpaid churn rises** → voluntary vs involuntary → tenure cohort (promotion or device-plan end) → price-increase events → competitor promotions (cable MVNOs, convergence bundles) → local network quality (drop rate, speed) → billing errors and care contacts → port-out destination. Action: targeted retention offers, upgrade offers, price locks, fix specific network clusters.
2. **ARPU/ARPA declines** → plan mix (downgrades) → promotional discount amortization → lines per account (multi-line discounts) → prepaid migration → roaming/overage decline → bundle revenue allocation changes. Action: premium-plan upsell, discount-expiry management.
3. **Net adds fall** → gross adds (store traffic, switching pool, promotions) vs disconnects → segment (consumer, business, FWA, fiber) → capacity limits on fixed wireless. Action: promotional response, channel incentives, capacity-aware selling.
4. **Network KPIs degrade** → site/cluster outages → capacity (resource utilization) → interference → software or parameter changes → backhaul faults → weather; then check complaint and churn uplift in the same areas. Action: roll back changes, add capacity, repair sites.
5. **Bad debt / involuntary churn rises** → credit mix of new device-financing customers → macro stress → collections changes → billing-cycle changes. Action: deposits/credit tightening, payment arrangements.

### Ontology sketch

Objects: **Customer** (party) · **BillingAccount** · **Line/Subscription** (MSISDN) · **SIM/eSIM** (ICCID/IMSI) · **Device** (IMEI) · **ProductOffering** (plan) · **ProductInstance** · **Service** (customer-facing / resource-facing) · **Resource** (cell, site, port, number) · **ProductOrder** · **UsageRecord** (CDR/xDR) · **Bill** · **Payment** · **DeviceInstallmentPlan** · **TroubleTicket** · **NetworkAlarm** · **PortRequest** · **CareInteraction**.

Links: BillingAccount N:1 Customer · Line N:1 BillingAccount · Line 1:1 SIM at a time (history N) · Line N:1 Device (time-varying) · ProductInstance N:1 ProductOffering and N:1 Line/Account · ProductInstance 1:N Service · Service N:M Resource · UsageRecord N:1 Line and N:1 Cell · Bill N:1 BillingAccount · TroubleTicket N:1 Customer or Service · PortRequest N:1 Line · DeviceInstallmentPlan N:1 Line.

Lifecycles:
- Line: `ordered → activated → active ⇄ suspended (non-pay) → ported_out | disconnected_voluntary | disconnected_involuntary`.
- Product order: `acknowledged → in_progress → pending (appointment) → completed | cancelled | failed`.
- Trouble ticket: `submitted → acknowledged → in_progress → resolved → closed` (reopen allowed).
- Port request: `requested → validated → scheduled → completed | rejected` (one-business-day rule for simple ports [T8]).

Processes & promises: FCC simple-port interval [T8]; network KPI definitions per 3GPP [T6].

### Systems & standards

- Systems: BSS/OSS suites (Amdocs, Netcracker, Oracle Communications BRM, CSG, Ericsson and Nokia charging/OSS), CRM (Salesforce Communications Cloud), network performance management (Ericsson ENM, Nokia NetAct), probes and xDR mediation (NETSCOUT), inventory and billing platforms.
- Standards (quarry): **TM Forum Information Framework (SID, GB922)** — domains Market/Sales, Product, Customer, Service, Resource, Supplier/Partner and a common domain (Party, Location, Agreement) [T9]; **TM Forum Open APIs** — e.g. TMF620 Product Catalog, TMF622 Product Order, TMF629 Customer Management, TMF637 Product Inventory, TMF641 Service Order (published repositories, Apache-2.0) [T10]; **3GPP TS 32.450** KPI definitions [T6].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| IBM Telco Customer Churn (fictional California operator) | https://github.com/IBM/telco-customer-churn-on-icp4d | Repository Apache-2.0 [T11] | 7,043 customers × 21 columns [T11] *(search summary)* | Churn rate, churn by tenure/contract/payment method, monthly charges as ARPU proxy — synthetic |
| KDD Cup 2009 (Orange) | https://www.kdd.org/kdd-cup/view/kdd-cup-2009 | Competition data (terms on site) | Large, noisy, anonymized marketing database; churn, appetency, up-selling targets [T12] | Churn/propensity model validation only (features anonymized) |
| Ookla Open Data speed-test tiles | https://github.com/teamookla/ookla-open-data | CC BY-NC-SA 4.0 (non-commercial) [T7] | Fixed and mobile; ~610 m tiles; quarterly 2019–2026; Parquet/Shapefile on AWS [T7] | Delivered speed and latency distributions by geography |
| Telecom Italia Big Data Challenge (Milan, Trentino) | https://dataverse.harvard.edu/dataverse/bigdatachallenge | Per dataset record (verify) | 20 datasets published 2015 [T13] | Traffic by grid cell over time (network load) — no revenue or churn |
| Carrier SEC filings | https://www.sec.gov/Archives/edgar/data/0000732717/000073271726000294/t-2q2026exhibit991.htm | Public | Quarterly | Reconciliation of churn and net adds [T1] |

No public dataset links subscribers, usage, billing and network events; subscriber-level validation relies on fictional data.

### What generic analytics gets wrong here

- Compares churn across carriers whose units differ (lines vs accounts) and whose definitions changed in 2026 [T2].
- Annualizes monthly churn as 12× (should compound) and uses opening rather than average subscribers.
- Counts connections (SIMs, IoT) as subscribers [T4], and includes equipment revenue in ARPU.
- Averages network success rates across cells without weighting by attempts.
- Treats crowdsourced speed tests as a random sample.

### Sources

- [T1] AT&T 2Q 2026 earnings, Form 8-K exhibit 99.1: https://www.sec.gov/Archives/edgar/data/0000732717/000073271726000294/t-2q2026exhibit991.htm
- [T2] Recon Analytics, "What the Carriers Stopped Telling You About Q2 2026": https://www.reconanalytics.com/what-the-carriers-stopped-telling-you-about-q2-2026/
- [T3] Verizon, 2Q26 results: https://www.verizon.com/about/news/verizon-delivers-record-2q26-results
- [T4] GSMA, The Mobile Economy 2026: https://www.gsma.com/solutions-and-impact/connectivity-for-good/mobile-economy/ ; GSMA announcement *(search summary)*: https://x.com/GSMA/status/2042180732576268294
- [T5] Ericsson Mobility Report (June 2026): https://www.ericsson.com/en/reports-and-papers/mobility-report
- [T6] 3GPP TS 32.450, KPIs for E-UTRAN: Definitions (spec page blocks automated fetch): https://www.3gpp.org/DynaReport/32450.htm
- [T7] Ookla Open Data: https://github.com/teamookla/ookla-open-data
- [T8] 47 CFR 52.35 (porting intervals): https://www.law.cornell.edu/cfr/text/47/52.35
- [T9] TM Forum Information Framework (SID): https://www.tmforum.org/open-digital-architecture/information-framework-sid/
- [T10] TM Forum Open API repositories: https://github.com/tmforum-apis
- [T11] IBM telco churn repository: https://github.com/IBM/telco-customer-churn-on-icp4d ; Kaggle mirror: https://www.kaggle.com/datasets/blastchar/telco-customer-churn
- [T12] KDD Cup 2009: https://www.kdd.org/kdd-cup/view/kdd-cup-2009
- [T13] Harvard Dataverse, Big Data Challenge collection: https://dataverse.harvard.edu/dataverse/bigdatachallenge

---

## 9. Energy & utilities (electricity, gas and water distribution; retail energy)

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| SAIDI | minutes/hours without power | Total sustained-outage time for the average customer in a year | Σ(customer interruption durations) ÷ total customers served | utility × year (daily values for MED classification) | US 2024: about 11 hours per customer in total — nearly 9 hours from major events, about 2 hours otherwise; major events averaged nearly 4 hours/yr in 2014–2023. Worst state 2024: South Carolina, nearly 53 hours [E1] | Reporting only the all-in figure: major events made up 80% of 2024 outage hours [E1]; averaging utilities instead of customer-weighting |
| SAIFI | interruption frequency | Sustained interruptions per average customer per year | Σ(customers interrupted) ÷ total customers served | utility × year | US 2024 average ≈1.5 interruptions; Hawaii highest at 4.4 [E1] | Counting momentary interruptions (those belong in MAIFI) |
| CAIDI | restoration time | Average outage length for customers who had one | SAIDI ÷ SAIFI | utility × year | Derived; no separate benchmark | Averaging CAIDI across utilities rather than recomputing from pooled SAIDI and SAIFI |
| Major event day (MED) threshold | IEEE 1366 2.5β | Statistical cut-off separating major-event days from normal days | T_MED = exp(α + 2.5β), with α and β the mean and standard deviation of ln(daily SAIDI) over ~5 years; days above T_MED are MEDs [E2] | utility × day | Method, not a number; the originating paper notes it should give ≈2.3 MEDs every two years in theory, 2–8 per year in practice [E2] | Using a fixed "storm" list instead of the rule; zero-SAIDI days break the log (the method needs an explicit rule for them [E2]) |
| T&D losses | line losses | Energy lost between generation and customer meters | (energy into the network − energy delivered/billed) ÷ energy into the network | system × year | US ≈5% of electricity transmitted and distributed, 2018–2022 [E3] | Comparing billing-cycle sales with calendar-month input (calendarization) |
| Non-revenue water (NRW) | water loss | Water produced but not billed | (system input volume − billed authorized consumption) ÷ system input volume; split into real (leakage) and apparent (metering/billing/theft) losses [E6] | utility or district metered area × year | IBNET-reporting utilities ≈35%; developing-world level likely 40–50%; ≈32 bcm/yr leaked and 16 bcm/yr delivered unbilled [E4]; later global estimate 126 bcm/yr [E5] *(search summary)* | Percent-of-input comparisons across utilities with very different consumption and density; unvalidated audit inputs (AWWA stresses data validity [E6]) |
| Smart-meter (AMI) penetration | AMI share | Share of meters with two-way communication | AMI meters ÷ total meters | utility × year | US 2022: ≈119M AMI installations, ≈72% of electric meters; ≈73% of residential meters [E7] | Counting AMR (drive-by) meters as AMI |
| Customers in arrears | arrears rate | Share of customers with long-unpaid bills and no plan | customers with a bill unpaid >91 days (13 weeks) and no repayment arrangement ÷ customers [E8] | supplier × fuel × quarter | Great Britain Q1 2026: 3.8% of electricity and 3.7% of gas customers; average arrears £1,876 (electricity); total debt and arrears £4.79bn [E8] | Mixing customers on repayment plans (2.9% of accounts [E8]) with those in arrears |
| Supply-restoration standard | guaranteed standard | Restore supply within a regulated time or pay compensation | restoration time vs prescribed period | interruption × customer | Great Britain: 12 hours in normal conditions, else £75 (domestic) / £150 (non-domestic), plus further payments for each additional 12 hours; longer periods in severe weather [E9] | Measuring from crew arrival instead of loss of supply |

### Playbook

1. **SAIDI worsens** → split MED vs non-MED days (IEEE 1366) → cause codes (vegetation, equipment, weather, animals, third-party damage) → worst-performing feeders → frequency (SAIFI: exposure, protection coordination) vs duration (CAIDI: crew availability, switching automation) → asset age. Action: vegetation management, feeder automation (FLISR), targeted hardening, storm crew staging.
2. **T&D losses rise** → metering data gaps (estimated reads, AMI communication failures) → non-technical losses (tamper flags, theft) → overloaded feeders (technical losses) → calendarization mismatch between input and billed sales. Action: meter audits, revenue protection, reconductoring.
3. **NRW rises** → apparent losses (meter under-registration, billing errors, unauthorized use) vs real losses (main breaks, background leakage, pressure) → district-metered-area night-flow analysis → audit data validity. Action: leak detection, pressure management, meter replacement, validated audit [E6].
4. **Arrears / bad debt rise** → tariff or price-cap changes → weather-driven winter bills → payment-method mix (prepay, direct debit, pay-on-receipt) → vulnerable-customer segments → collections pauses → back-billing after meter fixes. Action: repayment plans, hardship support, prepay options, write-off schemes.
5. **Estimated bills and complaints rise** → AMI read success rate → meter-exchange backlog → billing-system releases → move-in/move-out handling. Action: fix head-end/communications faults, targeted manual reads.

### Ontology sketch

Objects: **Customer** · **ServiceAgreement** · **Premise** · **ServicePoint** · **Meter** · **IntervalReading/RegisterRead** · **Tariff/RatePlan** · **Bill** · **Payment** · **RepaymentArrangement** · **NetworkAsset** (substation, feeder, transformer, line section; water main, valve, DMA) · **Topology connection** · **Outage/Interruption** · **WorkOrder** · **Crew** · **Complaint/Case** · **DER** (rooftop solar, battery, EV charger) · **ProgramEnrollment** (demand response).

Links: ServiceAgreement N:1 Customer and N:1 ServicePoint · ServicePoint N:1 Premise · Meter N:1 ServicePoint (exchanges over time) · Reading N:1 Meter · Bill N:1 ServiceAgreement · Payment N:M Bill · ServicePoint N:1 Transformer N:1 Feeder N:1 Substation (topology, time-varying after switching) · Outage N:M ServicePoint (customers interrupted) · WorkOrder N:1 Asset or N:1 Outage · DER N:1 ServicePoint · ServicePoint N:1 DMA (water).

Lifecycles:
- Outage: `detected (AMI last-gasp, call, SCADA) → verified → crew_dispatched → isolated → partially_restored → restored → closed`; carries a MED flag and a momentary/sustained class.
- Meter: `installed → commissioned → active → exchanged | failed → removed`.
- ServiceAgreement: `pending_start → active → pending_stop → final_billed → closed`.
- Arrears: `current → overdue → in_arrears (>13 weeks, no plan) → repayment_plan | prepayment_meter | written_off` [E8].
- WorkOrder: `created → scheduled → dispatched → in_progress → completed | cancelled`.

Processes & promises: GB guaranteed standards of performance for restoration and compensation [E9]; IEEE 1366 major-event classification for reliability reporting [E2]; US utilities report SAIDI/SAIFI annually to EIA on Form 861 [E10].

### Systems & standards

- Systems: customer information and billing (SAP S/4HANA Utilities / IS-U, Oracle Utilities CC&B), meter data management (Itron, Oracle MDM, Siemens EnergyIP), AMI head-ends (Itron, Landis+Gyr, Aclara, Honeywell), outage and distribution management (GE Vernova, Schneider Electric, Oracle NMS, Hitachi Energy), GIS (Esri ArcGIS Utility Network), asset/work management (IBM Maximo, SAP PM), SCADA; water utilities add hydraulic models and AWWA audit software.
- Standards (quarry): **IEC CIM** — IEC 61970 (transmission/EMS network model), IEC 61968 (distribution business functions: assets, work, metering, customers), IEC 62325 (market processes) [E11]; **NAESB REQ.21 ESPI** behind Green Button Download My Data / Connect My Data [E12]; **IEEE 1366** reliability indices [E2]; **AWWA M36 / IWA water balance** [E6].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| EIA Form 861 (annual electric power industry report) | https://www.eia.gov/electricity/data/eia861/ | US public data | Census of US utilities; more than 20 spreadsheets per year including reliability, sales, customers, revenue [E10] | SAIDI/SAIFI with and without MEDs by utility, revenue per kWh, customers — reconciles to [E1]. Cleaned version: PUDL [E13] |
| SmartMeter Energy Consumption Data in London Households (UK Power Networks, Low Carbon London) | https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d | Creative Commons Attribution [E14] | 5,567 households; half-hourly; Nov 2011 – Feb 2014; ≈167M rows (~10 GB); ≈1,100 on dynamic time-of-use tariff in 2013 [E14] | Load profiles, peak demand, time-of-use response, read completeness |
| UCI ElectricityLoadDiagrams20112014 | https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014 | CC BY 4.0 [E15] | 370 Portuguese clients; 15-minute kW; 2011–2014 [E15] | Load factor, peak, consumption trend |
| Ofgem debt and arrears indicators | https://www.ofgem.gov.uk/data/debt-and-arrears-indicators | Public (aggregate) | Quarterly by fuel [E8] | Reconciliation target for arrears metrics |

No realistic public customer-level dataset combines outages, topology, billing and payments; water utilities lack any verified open transaction-level NRW data.

### What generic analytics gets wrong here

- Trends reliability including major events, so one hurricane season dominates; report with and without MEDs per IEEE 1366 [E1][E2].
- Averages SAIDI/CAIDI across utilities or feeders instead of customer-weighting pooled numerators.
- Compares billing-cycle sales with calendar-month supply, manufacturing swings in losses or NRW.
- Treats estimated reads as actuals, and double counts interval reads at daylight-saving transitions or head-end retries.
- Confuses customers, accounts and service points (multi-premise accounts; premises with several meters).

### Sources

- [E1] EIA Today in Energy (1 Dec 2025), hours without power in 2024: https://www.eia.gov/todayinEnergy/detail.php?id=66744
- [E2] IEEE PES Working Group on System Design, Major Event Normalization (2.5 Beta method): https://cmte.ieee.org/pes-drwg/wp-content/uploads/sites/61/2002-08-WhitePaperMajorEvent.pdf
- [E3] EIA FAQ, transmission and distribution losses: https://www.eia.gov/tools/faqs/faq.php?id=105&t=3
- [E4] World Bank, The Challenge of Reducing Non-Revenue Water in Developing Countries: https://documents1.worldbank.org/curated/en/385761468330326484/pdf/394050Reducing1e0water0WSS81PUBLIC1.pdf
- [E5] Liemberger & Wyatt, Quantifying the global non-revenue water problem (2018) *(search summary)*: https://www.researchgate.net/publication/326238463_Quantifying_the_global_non-revenue_water_problem
- [E6] AWWA, Water Loss Control (M36, Free Water Audit Software): https://www.awwa.org/Resources-Tools/Resource-Topics/Water-Loss-Control
- [E7] EIA FAQ, smart meters: https://www.eia.gov/tools/faqs/faq.php?id=108&t=3
- [E8] Ofgem, Debt and arrears indicators: https://www.ofgem.gov.uk/data/debt-and-arrears-indicators
- [E9] The Electricity (Standards of Performance) Regulations 2015, Schedule 2: https://www.legislation.gov.uk/uksi/2015/699/schedule/2/made ; regulation 5: https://www.legislation.gov.uk/uksi/2015/699/regulation/5/made
- [E10] EIA Form 861 data: https://www.eia.gov/electricity/data/eia861/
- [E11] PNNL-32679, Enabling data exchange and integration with the CIM: https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-32679.pdf
- [E12] Green Button Alliance: https://www.greenbuttonalliance.org/green-button
- [E13] Catalyst Cooperative PUDL, EIA-861 documentation: https://docs.catalyst.coop/pudl/en/latest/data_sources/eia861.html
- [E14] London Datastore, SmartMeter Energy Consumption Data: https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d
- [E15] UCI ElectricityLoadDiagrams20112014: https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014

---

## 10. Public sector (tax, benefits, permits) — brief

### KPIs

| KPI | Aliases | Plain definition | Formula | Grain | Benchmark (source) | Anti-patterns |
|---|---|---|---|---|---|---|
| Voluntary compliance rate | VCR | Share of true tax liability paid voluntarily and on time | tax paid voluntarily and timely ÷ total true tax | tax year (estimate) | Tax year 2022 projection: VCR 85.0%; net compliance rate 86.9%; gross tax gap $696B; net tax gap $606B after $90B of enforced and late payments [G1] | Reading a change in the projected gap as a change in behavior — the IRS attributes the rise to economic growth and income mix [G1] |
| Payment error rate | improper payment rate | Share of benefit dollars paid in the wrong amount (over or under) | (overpayments + underpayments) ÷ benefits issued, from a statistical quality-control sample | program × state × fiscal year | SNAP FY2025: 10.62% nationally vs a 6% threshold; $10.1B improper; 41 states plus DC above 6% [G2] *(search summary)* | Treating a sample estimate as exact; netting under- against overpayments |
| Government-wide improper payments | — | Payments that should not have been made or were made in the wrong amount | Σ agency-reported improper payment estimates | government × fiscal year | FY2025: ≈$186B across 64 programs in 15 agencies (+$24B); ≈$3 trillion cumulatively since FY2003 [G3] | Equating improper payments with fraud — not all improper payments are fraud [G3] |
| Benefit application timeliness | processing timeliness | Share of applications decided within the legal clock | applications processed within standard ÷ applications processed | office/state × month | Rule (SNAP): eligible households must get benefits within 30 calendar days of filing; expedited cases by the 7th calendar day [G4] | Starting the clock at "complete application" instead of filing date |
| UI first-payment promptness | time lapse | Share of first payments made quickly | first payments within 14 days (waiting-week states) or 21 days (others) of the first compensable week ÷ all first payments | state × month | Acceptable level of performance: ≥87% [G5] *(search summary)*; source data is DOL report ETA 9050 [G6] | Mixing intrastate and interstate claims; using the claim date instead of the first compensable week |
| Tax refund turnaround | refund cycle time | Time from filing to refund | refund issue date − return received date | return | IRS guide: about 3 weeks for e-filed returns; refunds claiming EITC are held until mid-February by law; 6+ weeks for paper returns [G7] | Pooling paper and electronic returns |
| Permit processing time | days to permit | Days from application to issuance | issue date − application start date | permit | No national benchmark; Chicago publishes `PROCESSING_TIME` per permit [G8] | Mixing permit types (express vs new construction); voided/revoked permits dropped from the data [G8] |
| 311 time to close | service-request resolution time | Time from request to closure | closed − created | service request | No benchmark; NYC publishes request-level data daily [G9] | Closure ≠ resolution; duplicates for one issue inflate volume |

### Playbook

1. **Payment error rate rises** → overpayment vs underpayment → error element (income, household composition, deductions) → caseload growth vs staffing → policy or waiver changes → local office/caseworker cohorts → system conversions; check sampling confidence intervals before acting. Action: targeted verification, training, system fixes (SNAP states above 6% now face cost-sharing [G2]).
2. **Timeliness falls (SNAP/UI)** → application surge (economic shock) → staffing and backlog age → identity-verification or fraud holds → missing documents → interstate claims; look at the time-lapse distribution, not just the percentage. Action: surge staffing, automation, identity-proofing redesign.
3. **Permit backlog grows** → volume by permit type → incomplete submissions → review stage (zoning, building, fire) → inspector capacity → fee or code changes. Action: express permits, electronic plan review, staffing.
4. **311 closure time grows** → complaint type and agency → duplicates → seasonal surges (heat, snow) → crew capacity. Action: triage and deduplication, crew rebalancing.

### Ontology sketch

Objects: **Person** (taxpayer, claimant) · **Household** · **Business/Entity** · **Application** · **Case** · **EligibilityDetermination** · **BenefitIssuance/Payment** · **Overpayment/Recovery** · **Appeal/Hearing** · **TaxReturn** · **Assessment** · **Examination** · **Refund** · **PermitApplication** · **Permit** · **Inspection** · **Violation** · **ServiceRequest** · **Agency/Office** · **Program**.

Links: Household 1:N Person · Application N:1 Household · Case 1:N EligibilityDetermination · Payment N:1 Case · Overpayment N:1 Payment · Appeal N:1 Determination · TaxReturn N:1 Taxpayer × tax year · Assessment and Examination N:1 TaxReturn · Refund N:1 TaxReturn · Permit N:1 PermitApplication · Inspection N:1 Permit · ServiceRequest N:1 Agency.

Lifecycles:
- Benefit application: `filed → interviewed → verified → approved | denied | withdrawn → certified → recertification_due → closed`.
- UI claim: `initial_claim → monetary_determination → first_payment → continued_weeks → exhausted | ended`.
- Tax return: `filed → processed → refund_issued | balance_due → (examined) → assessed → closed`.
- Permit: `applied → in_review → approved → issued → inspected → finaled | expired | revoked`.
- 311 request: `open → closed`, with `expected_datetime` as the promise (Open311 GeoReport v2) [G10].

Processes & promises: SNAP 30-day / 7-day clocks [G4]; UI 87% within 14/21 days [G5]; IRS refund guidance [G7].

### Systems & standards

- Systems: tax administration (FAST Enterprises GenTax, SAP Tax and Revenue Management), benefits eligibility (Merative Cúram, Salesforce Public Sector, integrator-built state systems), permitting and land management (Accela, Tyler EnerGov), 311/CRM (Salesforce, Microsoft Dynamics), ERP (Tyler Munis, Oracle, Workday).
- Standards (quarry): **NIEM** — common vocabulary with model content for 17 domains, now an OASIS Open Project (NIEMOpen) [G11]; **Open311 GeoReport v2** — services, service requests, status, requested/updated/expected datetimes [G10]; **BLDS** building-permit data specification (no longer actively maintained) [G12]; **DOL ETA reports** (ETA 539 weekly claims, ETA 5159 claims and payments, ETA 9050 first-payment time lapse) [G6].

### Validation datasets

| Dataset | URL | Licence | Size | KPIs it can compute |
|---|---|---|---|---|
| NYC 311 Service Requests (2020 to present) | https://data.cityofnewyork.us/api/views/erm2-nwe9 | Public NYC Open Data (terms on portal) | Millions of requests; updated daily [G9] | Volume by type/agency, time to close, backlog |
| Chicago Building Permits (2006 onward) | https://data.cityofchicago.org/api/views/ydr8-5enu | City of Chicago terms of use [G8] | All issued permits except voided/revoked; includes processing time and fees [G8] | Days to permit by type, fee totals |
| DOL UI data downloads (ETA 9050, 5159, 539) | https://oui.doleta.gov/unemploy/DataDownloads.asp | US public data | Monthly/weekly state reports in CSV, updated daily [G6] | First-payment promptness, claims volumes, payment activity |
| IRS tax gap estimates (aggregate) | https://www.irs.gov/pub/irs-pdf/p5869.pdf | US public data | Tax-year component tables [G1] | VCR, gap components (reconciliation only) |

### What generic analytics gets wrong here

- Treats sample-based error rates as exact and over-reads small state or year differences.
- Uses the wrong clock start (complete application vs filing date; claim date vs first compensable week) or business vs calendar days.
- Reports timeliness as one percentage and hides the long tail.
- Equates closure with resolution, and counts duplicate 311 requests as separate problems.
- Equates improper payments with fraud [G3].

### Sources

- [G1] IRS, 2022 tax gap projections (news release): https://irs.gov/newsroom/irs-releases-2022-tax-gap-projections-voluntary-compliance-rate-among-taxpayers-remains-steady ; Publication 5869: https://www.irs.gov/pub/irs-pdf/p5869.pdf
- [G2] USDA, FY 2025 SNAP payment error rates *(search summary)*: https://www.usda.gov/about-usda/news/press-releases/2026/06/24/usda-announces-fy-2025-state-payment-error-rates-snap
- [G3] GAO, Improper Payments: https://www.gao.gov/improper-payments
- [G4] 7 CFR 273.2(g)(1) and (i)(3): https://www.law.cornell.edu/cfr/text/7/273.2
- [G5] DOL, UI PERFORMS Core Measures *(search summary)*: https://oui.doleta.gov/unemploy/pdf/Core_Measures.pdf
- [G6] DOL, UI data downloads: https://oui.doleta.gov/unemploy/DataDownloads.asp
- [G7] IRS, Refunds: https://www.irs.gov/refunds
- [G8] City of Chicago, Building Permits (metadata): https://data.cityofchicago.org/api/views/ydr8-5enu
- [G9] NYC Open Data, 311 Service Requests (metadata): https://data.cityofnewyork.us/api/views/erm2-nwe9
- [G10] Open311 GeoReport v2: http://wiki.open311.org/GeoReport_v2/
- [G11] NIEMOpen: https://niemopen.org/
- [G12] BLDS repository: https://github.com/open-data-standards/permitdata.org

---

## Cross-industry note — a shared base package, and where validation is hardest

### Shared objects (candidates for a base ontology)

| Base object | Banking | Lending | Payments | Insurance | Hospitals | Payers | Pharma | Telecom | Utilities | Public sector |
|---|---|---|---|---|---|---|---|---|---|---|
| Party with roles | customer, signer | borrower, co-borrower | merchant, cardholder | insured, claimant, beneficiary | patient, guarantor | member, subscriber | HCP, patient | customer | customer | person, household |
| Agreement / Account | deposit account | loan account | merchant account | policy term | hospital account | enrollment span | rebate contract | billing account | service agreement | case |
| Product / Plan | product | loan product | pricing plan | coverage | service line | plan, benefit | product, NDC | plan offering | tariff | program |
| Event / Transaction | transaction | payment | authorization, capture | premium transaction | encounter, charge | claim line | prescription | usage record | interval reading | payment, filing |
| Bill / Invoice / Payment | statement | payment schedule | settlement | invoice | claim, remittance | premium, 835 | chargeback | bill | bill | refund |
| Case: claim, dispute, appeal, ticket | Reg E dispute | collections case | dispute | claim | denial, appeal | PA, appeal | coverage determination | trouble ticket | outage, complaint | appeal, 311 request |
| Location / Asset | branch | collateral property | device | insured risk | bed, unit | provider site | territory | cell, site | premise, feeder | parcel |

### Shared KPI templates (implement once, parameterize per industry)

1. **Ratio of sums** — efficiency ratio, loss/combined ratio, MLR, operating margin, GTN. Always sum numerator and denominator, then divide; never average ratios.
2. **Exposure-normalized rates** — PMPM and per-1,000 (member-months), claim frequency (exposure-years), SAIDI/SAIFI (customers served), ARPU and churn (average subscribers), NIM/NCO (average balances). The denominator must be time-weighted exposure, not a period-end count.
3. **Aging buckets and roll rates** — loan delinquency, hospital A/R aging, utility arrears (>13 weeks), involuntary telecom churn. Stocks and flows are different metrics.
4. **Churn / retention / lapse / persistence** — deposits, telecom, P&C retention, life lapse, pharma persistence, payer membership. Declare the unit (line vs account, count vs amount) and the grace or gap rule.
5. **Decision rates** — loan approval, card authorization, claim denial (payer and provider views), PA decisions, benefit eligibility. Denominator hygiene: withdrawn/incomplete files, retries, duplicates, resubmissions, reversals.
6. **Clock / SLA compliance** — a promise is a start event, a stop event, a unit (calendar vs business days) and a threshold. Report median and tail as well as percent-within-SLA. The rules gathered here: Reg E and Reg CC (§1), TRID and Reg B (§2), card dispute windows (§3), NAIC Model 902 (§4), Medicare timely filing and HRRP (§5), CMS-0057-F prior authorization and MA prompt pay (§6), Part D coverage determinations and the Open Payments cycle (§7), FCC porting (§8), GB supply-restoration standards (§9), SNAP and UI clocks (§10).
7. **Maturity / lag completion** — P&C IBNR, health claims lag, charge-off lag, chargeback windows (≈120 days), readmission follow-up windows. Recent periods are incomplete by construction; flag them.
8. **Event normalization** — catastrophe years (P&C), major event days (utilities, IEEE 1366), network outages (telecom), pandemic years (hospitals, payers). Show metrics with and without.
9. **Loss/error rates by count vs value** — fraud (VAMP counts vs bps of value), improper payments (dollars), denials (claims vs dollars). Declare the basis.

### Shared anti-patterns (the base package's guardrails)

- Averaging ratios across entities instead of pooling.
- Period-end or opening denominators for flow metrics.
- Reading immature periods as final (IBNR, claims lag, charge-off lag, dispute windows).
- Double counting through versioned or 1:N records: claim adjustments and remits, policy endorsements, authorization→capture→refund→dispute, meter exchanges, pharmacy claim reversals, interim hospital bills.
- Unit mismatches: lines vs accounts, SIMs vs people, count vs value, 30- vs 90-day fills, licensed vs staffed beds, service points vs customers.
- Unrecorded regime breaks: CECL, IQVIA's 2026 net-price method revision, carriers' 2026 metric changes, scheme threshold changes (VAMP April 2026).

### Shared standards families

- **Health** (hospitals, payers, pharma): HL7 FHIR, X12 HIPAA transactions, OMOP CDM, NDC/IDMP.
- **Finance** (banking, lending, payments; insurance partly): ISO 20022, ISO 8583, FIBO, BIAN, MISMO, ACORD.
- **Networks** (telecom, utilities): both separate a customer-facing service layer from a physical resource/asset topology (TM Forum SID Service/Resource; IEC CIM assets and connectivity). One "network topology + customer impact" pattern serves both.

### Hardest to validate (no realistic public data)

1. **Payments** — no public dataset carries authorization → capture → settlement → dispute → fees; fraud datasets are PCA-anonymized or competition-licensed.
2. **Pharma commercial** — no public, real, patient-level longitudinal prescription data; the audits (IQVIA, Symphony, Komodo) are paid; Part D is Medicare-only with small-cell suppression.
3. **Telecom subscriber/BSS** — only fictional (IBM) or anonymized (KDD Cup 2009) subscriber data; network data is aggregated.
4. **Insurance transactions** — freMTPL2 is policy-level frequency/severity; Schedule P is aggregate triangles; no public policy-admin + claim-lifecycle data.
5. **Health payers** — DE-SynPUF is synthetic 2008–2010 with limited inferential value; no public claim-denial or PA-level microdata.
6. **Water utilities** — no verified open transaction-level NRW data.

**Best validated**: banking (FFIEC Call Reports reconcile exactly to FDIC QBP aggregates), mortgage lending (Freddie Mac SFLLD + HMDA), hospitals (HCRIS + CMS Provider Data + credentialed MIMIC-IV), electricity reliability (EIA-861), public sector (NYC 311, Chicago permits, DOL ETA 9050).

**Practical recommendation**: in the hard-to-validate industries, test packages two ways — (a) reconcile computed aggregates to the published benchmarks cited above (a falsifier: the recipe must reproduce the regulator's number from the regulator's own data where it exists), and (b) test lifecycle, join and SLA logic on synthetic generators (Synthea; generators seeded with the public rates here), never quoting synthetic rates as benchmarks.
