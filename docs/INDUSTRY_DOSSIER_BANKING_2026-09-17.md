# Banking and lending — the package dossier (IP-4, gate 1)

Written 2026-09-17 for `packs/banking` (ROADMAP §3.17, IP-4 tier 1). It records what the package claims, where each
claim comes from, and what gate 4 measured, so a person can review the draft (gate 6). The quoted figures live in
`packs/banking/sources.yaml`; the canon it starts from is `docs/INDUSTRY_CANON_REGULATED_STUDY_2026-09-14.md` §1–2.

## Scope

- **In.** FDIC-insured banks and savings institutions, measured the way the FDIC measures them:
  - the net interest margin, with the yield on earning assets and the cost of funding them;
  - return on assets and on equity, and the efficiency ratio;
  - credit quality: net charge-offs, noncurrent loans, past-due and nonaccrual loans, and reserve coverage;
  - liquidity (loans to deposits) and capital (the equity capital ratio).
- **Not yet.**
  - Loan-level lending: delinquency buckets, roll rates, vintage losses and approval rates (study §2). These need a
    loan-level public dataset or a synthetic generator — gate 4's other path — and come in their own slice.
  - Payments & fintech, and insurance: separate packages, next in tier 1.

## The regulator's data, and the figures it published

- **The published figures.** The FDIC's Quarterly Banking Profile aggregates every insured Call Report filer:
  4,421 institutions on June 30, 2025.
  - The second quarter of 2025 was chosen because it is more than a year old, so the institutions' amendments have
    largely landed.
  - The second quarter 2026 profile (published 2026-08-25) restates it — return on assets and net charge-offs for
    the quarter, and the equity capital ratio on June 30, 2025, for every group.
- **The per-institution data.** The FDIC's BankFind Suite API, `financials` endpoint.
  - One CSV of the profile's population: report date 20250630; charter classes N, NM, SM, SB, SI and SL, which
    leaves out insured branches of foreign banks and noninsured trust companies.
  - 4,421 rows, 87 columns, 2,938,692 bytes, SHA-256 `2e7f6707…564c`. Downloaded once on 2026-09-17, with the
    user's approval, into the dataset cache outside the repository.
  - Every asset concentration group and asset size group holds exactly the profile's count of institutions.
- **Why not the FFIEC's bulk Call Reports.** Their download page is a form postback with no stable URL, so gate 4
  could not name what to fetch.
- **A caveat the package carries.** The API serves the FDIC's current data, not a frozen file. A later download
  that differs from this snapshot is refused by its size and SHA-256, and re-pinning it means re-measuring.

## Definitions → recipes

The Notes to Users define every ratio, and each recipe follows them over one role, `financial_period`: an entity's
income over a period, its balances averaged over the period, and its balances at the period's end.

- **Weighted averages.** "the sum of the individual numerator values divided by the sum of individual denominator
  values". Every recipe sums its numerator and its denominator, then divides; none averages the entities' rates.
- **Averages.** "beginning-of-period amount plus end-of-period amount plus any interim periods, divided by the total
  number of periods". The dataset binds the API's two-point averages (ASSET2, ERNAST2, LNLSGR2, EQ2).
- **Annual rates.** A quarter's income times `periods_per_year` (4).
- **Net interest margin.** No tax-equivalent adjustment. **Efficiency ratio.** Noninterest expense less amortization
  of intangibles, over net interest income plus noninterest income.
- **Settled by the data, not by the notes.**
  - The equity capital ratio uses the bank's own equity (EQ). With total equity, which includes minority interests,
    5 of the 15 restated group ratios miss their published figure.
  - Not settled: the coverage ratio's allowance could be the reserve for losses with or without allocated transfer
    risk (LNATRES or LNATRESJ). On this quarter the two sum to the same amount, so the data cannot tell them apart.

## What gate 4 measured — no model

- **Recipes, on all institutions.** Each lies inside its sourced band:
  - net interest margin 3.2558%, yield on earning assets 5.5363%, cost of funding 2.2806%;
  - return on assets 1.1358%, return on equity 11.2403%, efficiency ratio 55.5136%;
  - net charge-off rate 0.6041%, noncurrent loan rate 0.9581%, past-due and nonaccrual rate 1.4975%;
  - reserve coverage 179.3955%, loans to deposits 65.2283%, equity capital ratio 10.1388%.
- **Goldens: 51 of 51 reproduce the FDIC's published figure** within its two-decimal rounding (±0.005 points):
  - 45 restated figures — return on assets, net charge-offs to loans and the equity capital ratio, for all
    institutions, the 9 asset concentration groups and the 5 asset size groups;
  - 6 all-institution figures as first published, which the amendments left inside their rounding: the margin, the
    yield, the cost of funding, the noncurrent rate, loans to deposits, and past-due and nonaccrual loans.
- **No golden for return on equity, the efficiency ratio or reserve coverage.** The amendments moved them past the
  rounding of their only publication — 11.24 against 11.22, 55.51 against 55.57, 179.40 against 179.41 — and the
  2026 profile does not restate them. Gate 4 holds them to their bands.
- **Detections** — a count is exposure, not a defect:
  - 1 institution earned interest with no average earning assets;
  - 0 report more noncurrent loans than loans;
  - 6 closed the quarter with assets more than a quarter away from their average;
  - 1,036 recovered more than they charged off in the quarter.
- **Claims: 2 measured true, 12 expected.**
  - Institution and CallReport are measured true.
  - The report-to-institution link stays expected: one quarter holds one report per institution, and a link measured
    1:1 would read its N:1 claim as false.
  - Customers, deposit accounts, loans, transactions, branches and the two lifecycles stay expected until a dataset
    carries them.

## The sane ranges

Each band runs from the lowest to the highest rate the FDIC published for its asset concentration groups and asset
size groups in the second quarters of 2025 and 2026, widened by the ±0.005 points of their rounding. The band's basis
says so, and says that a single institution can sit outside a group's rate — a custody bank's margin, a de novo bank's
return.

## Open

- **The runtime.** The agents read an industry through `industry.json` and `kb/`, and banking carries neither. The
  next slice reads a package's anatomy directly: its metrics, plays and questions.
- **Industry matching.** `metric_kb._UNCURATED_INDUSTRY_TERMS` lists banking's words ("bank", "banking", "lender",
  "credit union"), which keeps a bank from matching retail today. They come out when banking is activated, and a
  shipped industry that is not chosen has to keep blocking the generic match the same way.
- **Gate 5.** Not needed: gate 4 is unambiguous (§6 item 21, answer 8).
- **Gate 6.** A person's review, then `status: active`.
