# Named statistical pitfalls — the shared vocabulary (AT-2)

Three readers need to name the same mistake: the **narrator**, which is told which pitfalls to
avoid; the **checks**, which refuse a report that commits one; and the **person reading the
report**, who sees a number in `confidence_justification` and wants to know what it means.
Before this file each of the three had its own words, so a check said *"these figures do not
appear anywhere in FULL EVIDENCE"* and a reader had no way to learn that this is a known,
named, recurring failure with a fix.

The numbering follows the taxonomy in `scientific-critical-thinking/references/statistical_pitfalls.md`
(K-Dense-AI/scientific-agent-skills, MIT), kept so the numbers stay comparable with the
literature. Only the rows aughor actually acts on appear here — a pitfall with no enforcement
and no prompt line would be decoration.

**Contract:** the enforced rows must match `report_checks.PITFALLS` exactly.
`tests/unit/test_pitfalls_contract.py` fails if they drift.

## Enforced

| # | Pitfall | What it looks like here | Enforced by |
|---|---|---|---|
| 2 | non-significant is not no effect | reporting "no difference" from an underpowered slice instead of "not distinguishable at this n" | `_ranking_noise_caveat` phrasing |
| 3 | statistically significant is not important | *"variations are not significant (p > 0.05)"* over a finding carrying **p = 2.4e-155**; or "does differ" over η² = 0.011 | `check_significance_claims`, `assess_group_means` 1–6% band |
| 11 | a mean from a handful of records is not a finding | `Ilam 3.2 days, n = 5` leading a chart of 1,089 order states | `_ranking_noise_caveat`, `check_noise_findings_not_cited` |
| 12 | an effect reported without its size | a p-value quoted with no η², r² or share of variation | `assess_correlation`, `assess_group_means` (both lead with the effect) |
| 15 | correlation asserted as causation | *"driven by localized state-level bottlenecks"* over a cross-sectional scan | `check_claim_type` + the claim licence |
| 17 | a whole-population claim from a truncated slice | *"city-level rates range from 73.21% to 81.32%"* — the top 15 of 563 | `_population_note`, `_hit_row_cap`, truncation note |
| 32 | a measured quantity replaced by a 0/1 flag | "shipping delay" resolved to `AVG(Late_delivery_risk)` instead of the delay in days | intake MAGNITUDE GUARD, `self_referential_segment` |
| 36 | a claim the run's own evidence does not contain | a figure in the headline that appears nowhere in the evidence log | `check_grounding`, `check_question_addressed` |

## Advisory — named in prompts, not mechanically checkable

| # | Pitfall | Why it is not enforced |
|---|---|---|
| 14 | explained variance is not importance | the counterweight to #3: a 1% effect can matter (height explains ~5% of NBA salary). A threshold cannot decide this; a domain pack could. |
| 16 | ecological fallacy | a group-level relationship read as an individual-level one. Detectable only with the unit of observation declared. |
| 17b | Simpson's paradox | a live risk for every dimension scan; needs the confounder named before it can be tested. |
| 33 | trying transformations until one works | aughor does not currently re-plan on a null result, so the exposure is low — revisit if it starts to. |

## Using a number

- **In a check:** `report_checks.pitfall(3)` returns `#3 (statistically significant is not important):`
  to lead the violation string with.
- **In a prompt:** cite the numbers the design puts at risk, not the whole list.
- **In a report:** the number reaches the reader inside `confidence_justification` when a
  violation ships, which is the only place a reader currently meets it.

## Adding one

Add the row here and the entry in `report_checks.PITFALLS`, in the same change. If it is
enforced, name the check; if it is advisory, say why it cannot be checked. A row that claims
enforcement without a check is worse than no row — it reads as covered.
