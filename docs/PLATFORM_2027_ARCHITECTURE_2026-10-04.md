# Aughor in 2027 — the architecture, drawn

*Drawn 2026-10-04 from the platform study of the same day
([`PLATFORM_2027_STUDY_2026-10-04.md`](PLATFORM_2027_STUDY_2026-10-04.md), sections F to O), adopted the same
day — `ROADMAP.md` §6 item 39, §3.53. Figure 1 is where everything sits, what is owned, and what crosses each
boundary. Figure 2 is the loop the ledger runs. The figures are the two SVG files under
[`assets/platform-2027/`](assets/platform-2027/); they carry their own light and dark palettes and need nothing
else to render.*

*The picture is the study's §F table made spatial: it adds nothing the study does not say, and where the two
disagree the study wins. First published as a page at
[claude.ai/artifact/6yUxAzPsKtc1R4GkfEHHiG](https://claude.ai/artifact/6yUxAzPsKtc1R4GkfEHHiG); this file is the
copy of record.*

---

## Figure 1 · The platform as a place

![Aughor in 2027: people and outside agents enter through one governance layer; agent duties, the action gateway and evaluation sit above a compiled intelligence layer; one append-only ledger with two clocks is the only state; data is queried in place and rows never move. Model vendors, systems of action, sources and packs sit outside the install.](assets/platform-2027/architecture.svg)

**The install is the tenant: one ledger, one gate map, one write path.** Centralise what must be *consistent* —
what is true, what is allowed, what happened, who was interrupted — and decentralise what must be *abundant* —
models, agents, compute, actions, packs. The three coloured flows are the ones the study says a competitor cannot
copy in a quarter: delivery through the gate under an attention budget; entries booked with their warrant; and
receipts that grant or withdraw authority.

Reading it top to bottom:

| Band | What it holds | Owned? |
|---|---|---|
| **People · outside agents** | the six destinations and the channels; the MCP server and the ledger API under a service principal. Both go through the same doors | necessary · outside |
| **Governance** | the gate map, policies as sentences, groups and clearances, the departure gate's ten laws, the attention budget, the exportable audit. Every arrow crosses it | **owned** |
| **Agent · Evaluation · Action** | seven duties with the runtime delegated and no memory of their own; scoring by code and never a judge; the one write path where authority is earned on receipts. The coloured arrow between evaluation and action is the graduation or demotion receipt | necessary · **owned** · **owned** |
| **Intelligence** | what people declare and code compiles: terms, definitions, the object door, the inquiry engine, the scenario ladder, triage | **owned** |
| **The ledger** | ten entry kinds, two clocks, one envelope, confidence as a counted hit rate. The indexes beside it — the graph, the embeddings — are projections rebuilt from it | **owned** |
| **Data** | queried in place. Statements go down, measured information comes up, rows never move. The settle tick is the clock that drives everything above it | necessary |
| **Outside the install** (dashed) | model vendors and sources on the left; systems of action and packs on the right. Many, replaceable, bought or someone else's | outside |

## Figure 2 · The loop the ledger runs

![The closed loop: a claim as recorded is relied on by a decision with a booked expectation, which authorises an action under a grant, which is reviewed on its date as an outcome against expectation and baseline, which is scored by code and written back to the claim's class and the action kind's grant. The settle tick drives every step on the calendar.](assets/platform-2027/loop.svg)

**The molecule that compounds.** A claim is relied on by a decision; the decision books its expectation at the
moment of choosing; the action runs under earned authority; the outcome is measured on settled days against both
the expectation and the metric's own history; and code writes the result back onto every claim the decision stood
on and onto the action kind's grant. Nothing in the loop is a model's opinion, and nothing in it can be backfilled —
which is why the study's phase 1 books decisions and expectations before they have a screen.

## Three rules the picture encodes

- **Rows never leave.** Statements run in the source; what crosses into the ledger is measured information with a
  receipt.
- **The scorer is code and is never the actor.** That is what lets one install grade its own agents, a vendor's agents
  and a system of action's agents in the same table.
- **Authority, confidence and delivery are all receipts.** A grant cites the executions that earned it; a confidence
  cites its hit rate and *n*; a delivery cites the laws it passed and the slot it used.

## What is new against the 2026 build

Marked *(new)* in figure 1: the attention budget; the Forecast and Operate duties; calibration by class, method and
author; authority L0–L5 earned on receipts. Everything else in the picture exists today in some form — the study's
reassessment table says which form, and section E says what is rebuilt rather than added.

---

*Sources: the study's §F (architecture and the own/buy/delegate table), §G (the object model and the two clocks),
§I (the loop), §M (action and authority), §O (trust and evaluation).*
