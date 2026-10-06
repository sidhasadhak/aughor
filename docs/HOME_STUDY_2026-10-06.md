# Home — the one page where a person and Aughor trade

**Status: DRAFTED 2026-10-06, NOT decided.** Written down at the user's *"lets write this down and push a
branch"*, after the user's ask on 2026-10-05: *"think of what Home page could deliver to improve its value.. make
sure that it has distinct value and doesnt just copy stuff from other pages/tabs.. how do we enrich that page..
think outside the box"*. Code read on `origin/main` at `cb682fde`; the live figures were read over HTTP from the
user's install on 2026-10-05. Nothing here is built. ROADMAP §3.54 is this study's pointer, and §6 item 45 lists
the calls it waits on.

---

## 1 · The survey — what Home is today

`HomeScreen` in `web/app/page.tsx` renders six blocks. Five of them are a copy of, or a link to, a page that
already exists:

| Block | What it shows | Where that already lives |
|---|---|---|
| Ask box (Quick · Agent) | a composer that hands the question to the chat | the chat itself, and the ⌘K palette |
| First-run steps | connect · load the demo · ask — until the first analysis | Home's own; only useful once |
| Get Started | four cards: Data Canvas, Catalog, Briefing, SQL Editor | four rows of the rail |
| Four stat tiles | tables in schema, entities mapped, findings, queries executed | Catalog, Ontology, Intelligence, Activity — each tile links there |
| Health scorecard | `ProcessHealthPanel` | the same component is the Health page |
| Recent activity | the last five analyses | Agent runs; its "View all" opens Recents |

**Now** sits beside Home on the rail and answers *"what needs me, this week?"* (`components/now/NowPanel.tsx`):
the week's slots, Waiting on you, Since you were here, Held this week, and the Briefing in one line. The 2027
study folded Home into Now (its §U); the rail was kept instead (§4.10), so Home stays and needs a job that Now
does not do.

## 2 · What the install showed (2026-10-05)

- **The Record is empty.** `GET /record/claims`, `/decisions`, `/inquiries` and `/missions` returned no rows,
  and `/record/corrections` counted 0 of every kind. The Brain map read 0 priorities and 0 of 1 named owners
  reachable on theLook.
- **Questions repeat, and nothing tells the person.** The last 50 analyses (`GET /investigations`, one page)
  are all on theLook, dated 2026-10-01 to 2026-10-05, and hold 11 distinct questions. One of them, *"Which 10
  product categories brought in the most revenue in the last 6 months…"*, ran 13 times in under two days. Most
  look like test runs from the accuracy work, but the product never said the question was already answered.
  The CI-0 measurement saw the same thing on real traffic: 46 questions asked three or more times, and *"where are
  we losing money?"* asked 52 times (the docstring of `db/history.find_prior_answers`).
- **Recall exists, but only for the model.** `find_prior_answers` finds earlier answers to the same question on
  the same connection, by normalised equality. Its one consumer, `build_prior_answers_section`, writes them into
  the model's prompt. No screen shows them to the person, and no route serves them.
- **Conclusions end where they are written.** The two newest analyses concluded *"August 2026 Revenue Increased
  by 13.2% Driven by Search Traffic and Men's Department Growth"* and *"Revenue decreased 15.0% on September 27,
  2026, alongside a 23.2% decline in average order value"*. No decision cites either, because none is on record.

## 3 · The idea

Every other page reports to the person. Home becomes the one page where the two trade:

- before a run is paid for, it gives back what it already holds;
- it asks for what only a person knows;
- it keeps a score of how that exchange has gone.

Each part has one item a day or a small fixed set. None of them lists a store.

```
┌ Ask ───────────────────────────────────────────────────────────────────┐
│ [ the question, as typed                                             ] │
│   Already on record: answered 13 times since 1 Oct, last on 3 Oct     │
│   "Outerwear & Coats led, with $229,793.89 …"  [Open it] [Run again]   │
└────────────────────────────────────────────────────────────────────────┘
┌ A question for you ───────────────┐ ┌ Worth another look ──────────────┐
│ August revenue rose 13.2%. The    │ │ Revenue decreased 15.0% on 27    │
│ analysis credits search and the   │ │ September … (5 Oct, nothing      │
│ men's department. Did the team do │ │ decided)                         │
│ anything that explains it?        │ │ [Decide] [Check again] [Not      │
│ [A campaign] [A price change] …   │ │  worth it]                       │
└───────────────────────────────────┘ └──────────────────────────────────┘
  Between you and Aughor:  told it 0 · the data agreed 0 · forecasts 0 · in range —
```

### Part 1 · Ask, with memory

While a question is typed, and before anything runs, Home says what is already on record for it: how many times
it was answered, when last, and the last headline. It offers **Open it** and **Run again and compare**.

- **Matching is exact** (normalised equality, per connection), for the reason `find_prior_answers` gives: a looser
  match would hand one question's answer to another.
- **Doors.** `find_prior_answers` exists. It needs a read route, which it does not have. "Run again" is the
  existing ask path, which already compares against the earlier answers it is given.
- **Not this:** a search over history. Recents is that.

### Part 2 · A question for you

One question a day that only a person can answer: why something moved, what the team did, what they expect next.
The answer is kept as **said** by that person, dated, and checked against the data where it can be. It blocks
nothing. That is what separates it from Now's *Waiting on you*, which lists what is stuck on the person.

- **Doors.** The `said` tier exists (`hub/provenance.py`), and so does the claim kind `said`
  (`record/claims.py`). Today a `said` claim is booked only from a filed Slack reply (CB-8). No door books a
  statement typed into the web, so this part needs one. When the question hangs on an open inquiry, the existing
  `POST /record/inquiries/{id}/hypothesis` takes the answer instead.
- **Open (the user's):**
  - which question is asked on a given day — a ranking rule;
  - how it is worded — composed by code from records, since no model authors a fact here.

  Candidate sources, none decided: a finding that states a cause no person has spoken to; a decision booked
  without an expectation; a metric with no owner.

### Part 3 · Worth another look

One conclusion a day that nobody acted on, with three ways out:

| Way out | Door (all exist today) |
|---|---|
| **Decide something** | `POST /record/decisions`, a declared decision that names the finding it stands on |
| **Check it again** | `POST /exploration/{conn}/findings/{id}/revalidate` re-runs the finding's stored SQL with no model. For an analysis, `POST /investigations/{id}/recheck` does the same. |
| **Not worth it** | `POST /exploration/{conn}/findings/{id}/dismiss` with a reason: hidden, kept and reversible |

It differs from Now's *Since you were here*, which lists what changed. This lists what was concluded and left.

- **Open (the user's):** what counts as "acted on" — cited by a decision, dismissed, promoted, or any of them.

### Part 4 · Between you and Aughor

Four counts for the person looking at the page:

- what they told it;
- how often the data agreed;
- how many forecasts they booked;
- how many landed inside their range.

It starts at zero on this install, and says so.

- **Doors.** `GET /principals/{principal}/record` exists. It gives claims by kind, how many were restated, and
  predictions scored and inside their band. With identity off, "the person" is the name a form carried
  (`security/authz.acting_person`, kept as `person:<name>`), not a sign-in. The panel says which.

### What leaves Home

The Get Started cards, the four stat tiles, the health scorecard and the recent-activity table go: each is a page
that exists. The first-run steps stay, shown only before the first analysis. The ask box stays and gains Part 1.

## 4 · Order, if adopted

1. **Parts 1 and 3** read what already exists. Part 1 needs one read route; Part 3 needs none.
2. **Part 4** is a read over an existing door.
3. **Part 2** waits until its ranking rule and its wording are decided.

## 5 · Not taken: two Brain map redesigns (2026-10-05)

Before this, the same conversation asked what the Brain map should look like (Intelligence ▸ Brain map, §3.30).
Two shapes were shown in chat and neither was taken (*"Nah... not happy"*):

- the decision loop as five stations (knows → asked why → decided → did → learned);
- the business drawn as regions with measured links and decision trails.

The screen stays as built. One measured fact from that look is worth keeping. On theLook the map's link line
reads *"Findings → Dated facts: 114"*, while its Findings box reads 18. The first counts finding nodes in the
context graph; the second counts the explorer's store. That is two stores giving two numbers for one word, and it
is not traced.
