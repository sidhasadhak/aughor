# Making the decision loop turn honestly — a study (2026-10-24)

The user, 2026-10-24, shared an analysis of Roger Moser's article *Why Palantir Is Really a Decision Company*
(2026-04-28): an enterprise platform should not stop at answering questions about the business; it should carry
through to the decision, the authorised action, the observed outcome, and better decisions next time. Its own
caution: *recording decisions does not automatically produce learning* — it needs outcome attribution and honest
evaluation.

The finding that set this study's scope: **Aughor already has that decision record, nearly field for field** (the
2027 study §K, built 2026-10-05 in #568). What it does not have is a loop that turns. This study measures why, and
proposes the smallest changes that make it turn without crediting a decision with the business's own growth.
Nothing below is built. No model was called; every number was read over HTTP from the live install on 2026-10-24,
or from source.

**Status, 2026-10-24 — D-1 to D-3 BUILT** at the user's word (*"go with the recommended calls, build D-1 to D-3"*:
every call in §7 as recommended), behind the flag `record.decision_loop`, on live with it on. Two departures from §4,
both deliberate: the recommended option is marked as `extra.recommended` on the decision rather than as a field on
`Option`, so a record booked with the flag off is byte-identical; and the comparison group is not registered on the
scenario ladder — `METHODS` is what packs, the kit and the ledger contract publish — but is the review's baseline,
named on each outcome's effect. A comparison is drawn only for a metric that adds up (a SUM or a COUNT of rows at the
top of its formula); a part of a ratio is read against its own past under the drift guard.

**§5.1, the placebo, on live theLook data (2026-10-24, read-only, 18 statements through the query door, nothing
booked):** a do-nothing decision on each of the 26 product categories' units sold on each of nine first-of-month
dates (234 decisions), reviewed by the built functions. The comparison group credited a median **−0.25%** — 182
inside its 80% band, 26 above, 26 below; each category's own history credited **+19.83%**; the company total's own
history credited **+19.36%**, and the drift guard read the Record's calibration and said *cannot tell* ("units_sold's
own history band has missed above in 7 of 8 scored windows"). §5.1 passes. §5.2 — five decisions on live data
reaching a verdict within six weeks — is read on 2026-12-05.

## 1 · What exists

| The article asks for | Aughor's record (`aughor/record/decisions.py` unless named) |
|---|---|
| The decision and its context | `Decision.question`, `owner`, `approvers`, `objective` (a mission or metric), `source` (recommendation · approval · declared · autonomy), `connection_id` |
| The options weighed | `Decision.options[Option{id, description, predictions, cost, reversibility, actor}]`, `amend_decision` |
| The evidence | `relied_on` — claim ids as they stood when deciding; a restated claim reopens the decision (`reopen_for_claim`) |
| The choice, who approved, who disagreed | `chosen`, `decided_by`, `approvers`, `dissent[Dissent{who, why}]` |
| What was expected | `Expectation{metric, direction, low, mid, high, coverage, settles_on}`, booked as a prediction claim; `review_on` from `propose_review_on` (30 days plus the learned settling lag) |
| The outcome, tied to the decision | `Outcome{of, measured_on, actual, baseline, effect, verdict, against_expectation, writes_back}` |
| Was it a good decision | `Verdict`: as_expected · better · worse · cannot_tell, decided by code (`_verdict_against_history`, `aughor/record/byproducts.py`); a person's answer kept beside it |
| Better decisions next time | `update_playbook_success_rates` (`aughor/playbook/outcomes.py`); `autonomy.choose` takes the action with the largest measured past effect (`aughor/actions/autonomy.py`); the scenario ladder's `intervention` method (`aughor/record/scenario.py`) |

Decisions are booked as by-products where they happen (`aughor/record/byproducts.py`): accepting or declining a
recommendation, approving or rejecting a staged proposal, a decision declared in a person's words (Home's
**Decide**, `POST /record/decisions`), and an autonomous action. The full view is `web/components/decisions/
DecisionsPanel.tsx`; Home's "Between you and Aughor" reads `GET /record/you`.

## 2 · What is live

- **Decisions: 2, ever** (`GET /record/decisions`) — both approvals on 2026-10-10 on theLook (the OC-8 receipt's
  `open_case`, declined; a dashboard draft, approved). Neither has an objective, an expectation, a prediction on any
  option, dissent, a relied-on claim or an outcome. Their review dates are 2026-12-08.
- **The booking works.** Decision booking shipped on 2026-10-05; 11 staged proposals have ever been resolved, 9 of
  them before that date, and both resolved since were booked. The plumbing is not broken; it is barely walked.
- **Recommendations: none ever accepted or declined.** None of the 601 investigations has a recommendation outcome
  (`GET /investigations/{id}/outcomes`), and the outcome store has never been written on this install.
- **Home:** 236 findings behind "a finding to act on" (theLook 44, Olist 30, Superstore 72, LuxExperience 90); no
  decision has been declared from it.
- **The Record:** 556 claims — 407 findings, 130 predictions (all by the system), 10 observations, 7 hypotheses, 2
  said by a person. No person has made a prediction (`GET /record/you`).
- **The playbook:** 886 entries, all `active`, none with a measured outcome.
- **Autonomy:** theLook at level 0, manual (1 of 24 runs clean).

The analytical half is rich; the decision half has the structure and almost no use.

## 3 · Why the loop has not turned

**3.1 · The doors book bare decisions.** Home's Decide sends `{question, chosen, connection_id, note}` — the finding
travels only as text in the note (`web/components/home/HomeDesk.tsx`, `LookCard`). The route already accepts
`options`, `relied_on`, `expectation` and `review_on` (`declare_decision`); nothing sends them. A decision with no
expectation records *"none declared — nothing to score"*, and its review can only ever say cannot tell. Approvals
never carry one either (*"a staged proposal carries no expectation line"*).

**3.2 · Deciding not to act is lost, and so is what was recommended.** "Not worth it" flags the finding invalid
(`dismiss_connection_finding`, `aughor/routers/exploration.py`) and books no decision. A recommendation is booked as
its own accept-or-decline pair (`_ACCEPT_OPTIONS`), and an approval as approve-or-reject (`_APPROVE_OPTIONS`): the
same report's other recommended actions are never kept as alternatives, and no option is marked as the one the
platform recommended — so overrides can be read off a recommendation's decline, but not counted across kinds.

**3.3 · Only recommendations are reviewed.** The hourly tick runs `run_due_reviews` over recommendation outcomes
(`run_due_reviews_hourly`, `aughor/automations/scheduler.py`). `decisions.due_for_review()` exists but feeds only a
list filter (`GET /record/decisions?due=true`). A Home, approval or autonomy decision with an expectation would reach
its review date and nothing would measure it.

**3.4 · The score credits growth.** The verdict is the actual against what the metric's own history predicted — the
mean of the six prior windows with an 80% band (`scenario.history`). The Record already scores those predictions
against what happened (`GET /record/calibration`, read per metric name — all eight below are approved on theLook,
and average order value and return rate on LuxExperience too), and where a metric trends the band is missed one way:

| Metric | What it is | Inside the 80% band | Missed above | Missed below |
|---|---|---|---|---|
| revenue | a total | 3 of 8 | 5 | 0 |
| units_sold | a total | 1 of 8 | 7 | 0 |
| daily_active_users_dau | a total | 0 of 5 | 5 | 0 |
| session_to_purchase_conversion_rate | a ratio that trends | 1 of 8 | 7 | 0 |
| inventory_sell_through_rate | a ratio (cohort) that trends | 0 of 7 | 7 | 0 |
| gross_margin_percentage | a ratio that holds level | 8 of 8 | 0 | 0 |
| average_order_value_aov | a ratio that holds level | 5 of 8 | 1 | 2 |
| return_rate | a ratio (cohort) that holds level | 6 of 8 | 1 | 1 |

The bias follows the trend, not the formula's shape: totals miss above, and so does a ratio that keeps rising
(conversion, sell-through). A do-nothing decision on revenue would be scored *better than expected* most months. The placebo of
2026-10-10 measured the same thing directly: over 49 theLook series × 12 thirty-day windows where nothing was done,
this baseline credited a do-nothing decision a median **+18%**; a comparison-group baseline (the rest of the
segment's group × its prior share) credited **+0.0%** and read an injected +5% as +5.0%; a trend-and-season forecast
(statsforecast, ~210 MB of packages) still credited +7%. The two ratios it tested (average order value, return
rate) were unbiased under the current method — ratios that hold level, as the table shows. And two
decisions on the same metric in the same window would each take the whole effect: nothing handles overlap.

## 4 · The plan — smallest first

**D-1 · Book decisions in full where they are made.**
- Home's Decide cites the finding — its claim key, `claim:finding:explorer:<connection>:<schema>:<finding>` —
  as `relied_on`, offers *act as written* and *not act* as the options, and asks for an optional expectation (a
  metric from the approved list and a direction; a range when the person has one), the review date proposed by
  `propose_review_on`. Server: `declare_decision` resolves a claim key to the claim as it stands then
  (`claims.latest(key)`), so `relied_on` keeps the version that was read.
- "Not worth it" books the decision not to act, with its reason, citing the finding; the finding is set aside as
  today.
- An `Option.recommended` flag (additive; records written before read as unmarked). A recommendation's decision
  keeps the same report's other recommended actions as alternatives, the accepted one marked recommended; an
  approval marks *approve* as what the proposer recommended. An override is then a decision whose chosen option is
  not the recommended one — countable across every kind.
- Files: `web/components/home/HomeDesk.tsx`, `web/lib/record.ts`, `aughor/record/decisions.py`,
  `aughor/record/byproducts.py` (`declare_decision`, `decision_from_recommendation`, `decision_from_proposal`),
  `aughor/routers/exploration.py`.

**D-2 · Review every decision that expected something.** The hourly tick also sweeps `due_for_review()`: the
expectation's metric is measured for the review window by the metric's own compiler (`metric_time.measure_sql`,
the same path a monitor now reads its period by), and an `Outcome` is booked through the existing
`book_outcome`. A decision that expected nothing gets one outcome, *cannot tell — nothing was expected*, said once.
Data that has ended (Olist stops on 2018-10-17) has no review window after the decision: *cannot tell — the data
ended before the decision*. Files: `aughor/automations/scheduler.py`, `aughor/record/byproducts.py`.

**D-3 · Score against what would have happened anyway.** Register a `comparison` method on the scenario ladder
(`scenario.project` already takes registered methods): for a decision that names a segment, the baseline is the rest
of its group × the segment's prior share — measured unbiased on theLook. For a company-wide figure, of any shape,
the Record's own calibration is the guard: where that metric's history band is missed one-sidedly (above, as
revenue's and conversion's are), the verdict is *cannot tell — the metric's history band has missed above in N of M
windows, so its trend cannot be told from the decision* rather than *better*; a metric whose band holds (gross
margin, average order value) keeps the history verdict. Two
decisions on one metric with overlapping review windows each say so — *shared with decision X* — and the effect is
not split by guesswork. Files: `aughor/record/scenario.py`, `aughor/record/byproducts.py`
(`_verdict_against_history`).

**D-4 · Decision quality, beyond the outcome.** Read off the record, by code: did the decision cite evidence, state
an expectation, weigh more than one option, record dissent, and was the recommended option overridden. Shown on the
Decisions view and on `/record/you` as a count, never a score. No money value until the metric's unit is money in a
person-confirmed currency (the currency rule of 2026-10-23).

**D-5 · Feed back, and say what is unproven.** A playbook entry with no measured outcome reads *unproven* rather than
*active* (886 do today). Autonomy levels and grants stay a person's to raise; an outcome may only propose one.

D-1 to D-3 are one change: booking and reviewing without D-3 would start crediting growth on the first review.

## 5 · The falsifier

Written before the readings it judges:

1. **The placebo, re-run on the built method:** a do-nothing decision declared on theLook's revenue and on one
   category's revenue, reviewed by D-2 and D-3. Passes if the segment reads within ±2% of zero and the company total
   reads *cannot tell*; fails if either is credited the growth.
2. **Use:** within six weeks of shipping, at least five decisions on live data reach their review with an
   expectation and a verdict other than *cannot tell*. If none do, the scoring was not the bottleneck — the doors
   were: people do not decide inside Aughor, and the next step is to book decisions where they are made (a ✅ on a
   Slack recommendation, a dashboard Question's answer), not more scoring.

## 6 · What not to do

- No new decision store: the Record holds decisions (AGENTS.md, one store per concept).
- No model judges a decision. Verdicts are code over measured numbers; a model may propose an expectation's wording.
- No causal claim on a company-wide total without a holdout or a comparison group; *cannot tell* is said instead.
- No money value without a confirmed currency.
- The learning-from-runs study (PENDING 56) stays parked; this is not it.

## 7 · The calls that are the user's

1. **Scope of the first branch:** D-1 to D-3 together *(recommended — reviewing without honest scoring credits
   growth from day one)* · D-1 and D-2 first, D-3 after.
2. **Home's expectation:** optional, and a decision without one says it cannot be scored *(recommended)* · required.
3. **"Not worth it":** books a decision not to act *(recommended)* · stays a set-aside only.
4. **Company-wide figures:** *cannot tell* while the metric's own history band misses one way *(recommended)* ·
   the history verdict with its measured bias said beside it.
5. **Alternatives on recommendations:** each recommendation stays its own decision and keeps the report's others as
   alternatives *(recommended, additive)* · one decision per report with every recommendation as an option (a model
   change; older records read both ways).
6. **The next door after the falsifier's second reading, if use stays near zero:** Slack *(recommended — where the
   Briefing already lands each morning)* · a dashboard Question's answer.

## Sources

- The shared analysis of R. Moser, *Why Palantir Is Really a Decision Company* (2026-04-28), read 2026-10-24.
- Live install over HTTP, 2026-10-24: `GET /record/decisions`, `GET /record/claims`, `GET /record/calibration`,
  `GET /record/you`, `GET /investigations` and each `GET /investigations/{id}/outcomes`,
  `GET /kinetic-actions/inbox?connection_id=…`, `GET /exploration/{connection}/findings`, `GET /playbook`,
  `GET /ontology/autonomy`.
- Code: `aughor/record/decisions.py`, `aughor/record/byproducts.py`, `aughor/record/scenario.py`,
  `aughor/record/claims.py`, `aughor/record/writers.py`, `aughor/playbook/outcomes.py`,
  `aughor/automations/scheduler.py`, `aughor/routers/record.py`, `aughor/routers/exploration.py`,
  `web/components/home/HomeDesk.tsx`.
- The placebo of 2026-10-10 on theLook (49 series × 12 windows, no model calls), recorded in the session memory
  `record-baseline-credits-growth`; its scripts were scratch and are not in the repo.
