# Home — the one page that prepares for a person and trades with them

**Status: DRAFTED 2026-10-06, extended 2026-10-07; BUILT (first version) 2026-10-07** — what is and is not
built is in ROADMAP §3.54, and the defaults taken for the open calls in §6 item 45. It began with the user's ask on 2026-10-05:
*"think of what Home page could deliver to improve its value.. make sure that it has distinct value and doesnt just
copy stuff from other pages/tabs.. how do we enrich that page.. think outside the box"*. It was written down at
*"lets write this down and push a branch"*.

It was extended at the user's *"I'm looking for more enrichment and rather more proactive content on Home something
that would be super relevant to the user"* and *"now can you build the whole picture with the previous and the
current suggestions?"*. The user named two sections they liked: *"I actually like the sections called questions for
you as well as the section named worth another look"*.

Code was read on `origin/main` at `cb682fde`. Live figures were read over HTTP from the user's install on
2026-10-05 and 2026-10-07. Nothing here is built. ROADMAP §3.54 is this study's pointer, and §6 item 45 lists the
calls it waits on.

---

## 1 · The survey — what Home is today

`HomeScreen` in `web/app/page.tsx` renders six blocks. Five of them copy, or link to, a page that already exists:

| Block | What it shows | Where that already lives |
|---|---|---|
| Ask box (Quick · Agent) | a composer that hands the question to the chat | the chat itself, and the ⌘K palette |
| First-run steps | connect · load the demo · ask — until the first analysis | Home's own; useful only once |
| Get Started | four cards: Data Canvas, Catalog, Briefing, SQL Editor | four rows of the rail |
| Four stat tiles | tables in schema, entities mapped, findings, queries executed | Catalog, Ontology, Intelligence, Activity — each tile links there |
| Health scorecard | `ProcessHealthPanel` | the same component is the Health page |
| Recent activity | the last five analyses | Agent runs; its "View all" opens Recents |

**Now** sits beside Home on the rail and answers *"what needs me, this week?"* (`components/now/NowPanel.tsx`). It
shows the week's slots, Waiting on you, Since you were here, Held this week, and the Briefing in one line.

The 2027 study folded Home into Now (its §U). The rail was kept instead (§4.10), so Home stays — and it needs a job
that Now does not do.

## 2 · What the install showed

**The Record is empty (2026-10-05).** `GET /record/claims`, `/decisions`, `/inquiries` and `/missions` returned no
rows, and `/record/corrections` counted 0 of every kind. The Brain map read 0 priorities and 0 of 1 named owners
reachable on theLook.

**Questions repeat, and nothing tells the person.** The last 50 analyses (`GET /investigations`, one page) are all
on theLook, dated 2026-10-01 to 2026-10-05, and hold 11 distinct questions. One of them, *"Which 10 product
categories brought in the most revenue in the last 6 months…"*, ran 13 times in under two days. Most look like test
runs from the accuracy work. The CI-0 measurement saw the same on real traffic: 46 questions asked three or more
times, and *"where are we losing money?"* asked 52 times (the docstring of `db/history.find_prior_answers`).

**Recall exists, but only for the model.** `find_prior_answers` finds earlier answers to the same question on the
same connection, by normalised equality. Its one consumer, `build_prior_answers_section`, puts them in the model's
prompt. No screen shows them to the person, and no route serves them.

**Repeated questions got different figures (2026-10-07).**
- *"What was total revenue and how many units were sold in July 2026?"* was answered 12 times between 1 and 3 Oct.
  Those answers gave four revenue figures ($346,858.48, $359,224.30, $418,928.40, $338,523.13) and four unit counts
  (5,840, 6,012, 7,027, 6,835). The five answers from 07:46 on 3 Oct agree.
- The monthly-revenue question's August figure took four values ($120,063, $117,163.37, $113,573, $111,377.73). On
  3 Oct, an answer at 13:56 differed from the answers on either side of it.

Why the figures differed is not traced, and three causes can each move a figure: those were the days the accuracy
fixes landed; theLook restates recent days; and a model writes new SQL on every run. These counts were read from the
headline text of the stored answers.

**The daily runs disagree about the same day, because they measured different things (traced 2026-10-07).** The
scheduled daily run (`automations/temporal.py`) runs at 09:00 UTC, observing with an 8-day lag that was set by hand
for theLook on 2026-09-08.
- Its 4 Oct run read 26 Sep revenue as $5,762.95, counting only items marked Complete (90 orders).
- Its 5 Oct run read the same day as $17,316.12, over items not Cancelled or Returned (244 orders) — Net
  merchandise revenue's filter.
- The governed Revenue (`status <> 'Cancelled'`) was used by neither run.

Over those five runs, the headline series switched definition three times. The model authored the definition each
time, because the canonical pin cannot match the label "Revenue" (it reduces to no distinctive tokens), and the
declared-filter guard exempts a condition that excludes both Cancelled and Returned. The 4 Oct report then blamed
the difference on "the source has restated historical data". That was not the cause, and nothing booked either
figure on the Record.

Separately, the source does move. Under the same governed definition, 24 Sep went from $15,929.96 (8 days old) to
$19,057.53 (9 days old).

**Analyses record an organisation, not a person.** `GET /investigations/{id}` carries `org_id`, `agent_id` and
`session_id`, and `check_owner` checks the organisation. Nothing today says which questions belong to a given
person.

## 3 · The page, top to bottom

Every other page reports to the person. Home does two things no other page does:
- **it prepares** — work done before the person arrives, filtered to what they follow;
- **it trades** — it gives back what it already holds, and it asks for what only a person knows.

Seven sections, in page order. Each item is picked after the ones above it, so **no figure is stated twice on the
page** (the standing UI rule).

```
Wednesday 7 October · since your last visit on 3 Oct
┌ Ask ─────────────────────────────────────────────────────────────────────┐
│ [ Which 10 product categories brought in the most revenue …            ] │
│   Already on record: answered 13 times since 1 Oct, last on 3 Oct        │
│   [Open that answer] [Run it again and compare] [Answer it every morning]│
└──────────────────────────────────────────────────────────────────────────┘
┌ The one thing to know · the largest move in your numbers since 3 Oct ────┐
│ Revenue fell 15.0% on 27 September, to $14,724.                          │
│ Already looked into by the daily run on 5 Oct: more orders (270), smaller│
│ ones — average order value down 23.2% to $54.53.                         │
│ ⚠ Check the comparison: 26 Sep was $17,316 here (not Cancelled or       │
│   Returned) and $5,763 on 4 Oct (Complete only) — neither is Revenue.    │
└──────────────────────────────────────────────────────────────────────────┘
┌ A question for you ────────────────┐ ┌ Worth another look ───────────────┐
│ August revenue rose 13.2% … Did    │ │ Email drives the most unique user │
│ the team do anything that explains │ │ activity … 52,143 unique users …  │
│ it?  [A campaign] [A price change] │ │ [Decide] [Check again] [Not worth]│
└────────────────────────────────────┘ └───────────────────────────────────┘
Your standing questions · answered each morning
[ July revenue $338,523 ] [ Aug completed $113,573 ] [ Repeat 6.2→13.1% ] [ 1.5 + 2.5 days ]
┌ The week ahead ────────────────────┐ ┌ Between you and Aughor ───────────┐
│ Thu 8 Oct · September readable     │ │ told it 0 · agreed 0 · forecasts 0│
└────────────────────────────────────┘ └───────────────────────────────────┘
```

### 3.1 · Ask, with memory

While a question is typed, and before anything runs, Home says what is already on record for it: how many times it
was answered, when last, and the last headline. When the earlier answers disagree, it says that too.

There are three ways on:
- **Open that answer**;
- **Run it again and compare**;
- **Answer it every morning**, which makes the question a standing one (§3.5).

- **Matching is exact** (normalised equality, per connection), for the reason `find_prior_answers` gives: a looser
  match would hand one question's answer to another.
- **Agreement is read from the stored results**, not from headline text.
- **Doors.** `find_prior_answers` exists. It needs a read route, which it does not have. "Run again" is the existing
  ask path, which already compares against the earlier answers it is given.
- **Not this:** a search over history. Recents is that.

### 3.2 · The one thing to know

The largest move in a number the person follows since their last visit, **already looked into** by a run that
happened before they arrived. It carries a warning when the day it compares with was measured differently by an
earlier run.

- **Doors.**
  - The scheduled daily run exists. Its report carries the change label, the comparison basis and a summary.
  - "Last visit" is kept by Now per browser (`aughor_now_last_seen`); Home keeps its own the same way, or per person
    once there is one.
  - "Numbers you follow" needs a person (§3.8). Until then, it means the connection's daily runs.
- **The warning is new code.** For each run, take the figure it used for its comparison day, and compare it with the
  figure an earlier run measured for that same day. Compare the definition each run used (its pinned formula and
  filter) as well as the figure. Then the warning can say which happened: the source moved, or the platform measured
  something else. On theLook the 26 Sep case is the second kind (§2). This is code with no model, and nothing does
  it today.
- **Not this:** the Briefing's lead, which is connection-wide and narrated (Now repeats it in one line). This one is
  filtered to the person and arrives already analysed.

### 3.3 · A question for you

One question a day that only a person can answer: why something moved, what the team did, what they expect next.

- The answer is kept as **said** by that person, dated, and checked against the data where it can be.
- It blocks nothing. That is what separates it from Now's *Waiting on you*, which lists what is stuck on the person.
- **Doors.** The `said` tier exists (`hub/provenance.py`), and so does the claim kind `said` (`record/claims.py`).
  Today a `said` claim is booked only from a filed Slack reply (CB-8). No door books a statement typed into the web,
  so this section needs one. When the question hangs on an open inquiry, the existing
  `POST /record/inquiries/{id}/hypothesis` takes the answer instead.
- **Open (the user's):**
  - which question is asked on a given day — a ranking rule;
  - how it is worded — composed by code from records, since no model authors a fact here.

  Candidate sources, none decided: a finding that states a cause no person has spoken to; a decision booked without
  an expectation; a metric with no owner.

### 3.4 · Worth another look

One conclusion a day that nobody acted on, and that is not already on the page. On 7 Oct the 27 Sep fall is the
lead, so this card takes an explorer finding instead. There are three ways out:

| Way out | Door (all exist today) |
|---|---|
| **Decide something** | `POST /record/decisions`, a declared decision that names the finding it stands on |
| **Check it again** | `POST /exploration/{conn}/findings/{id}/revalidate` re-runs the finding's stored SQL with no model. For an analysis, `POST /investigations/{id}/recheck` does the same (behind `answers.recheck`). |
| **Not worth it** | `POST /exploration/{conn}/findings/{id}/dismiss` with a reason: hidden, kept and reversible |

- **Not this:** Now's *Since you were here*, which lists what changed. This lists what was concluded and left.
- **Open (the user's):** what counts as "acted on" — cited by a decision, dismissed, promoted, or any of them.

### 3.5 · Your standing questions

The questions a person asked three or more times, or opted into from Ask, re-answered each morning on settled days.
Each one shows as one figure, with how many answers it has had and whether they agreed.

- **Why "your numbers" merged into this.** On this install, the numbers a person's questions touch are exactly these
  questions' answers. Two sections would show the same figures.
- **How it re-answers.** It re-runs the answer's own stored SQL, with no model, as `recheck` and `revalidate` already
  do. A figure that changes is then the data's change, not a new SQL's. §2 shows why this matters: fresh model runs
  gave a question four different figures in three days. A model run happens only on an opt-in, with its budget shown
  on the page.
- **Doors.** The re-run exists for one answer (`recheck`, flag-gated), and so do schedules (automations). It needs a
  standing mark per person, and the morning job.

### 3.6 · The week ahead

Only what lands in the coming days:
- when a number becomes readable whole, from the connection's lag;
- decisions' review dates;
- forecasts' settle dates;
- missions' report dates.

What is due today stays on Now (*Waiting on you*).

- **Doors.** All of these are reads: the lag, `decisions.due_for_review`'s dates, prediction claims' `settles_on`,
  and missions' reviews.
- **One truth per number.** A lag is read in two places: the daily run's (`automations/temporal.resolve_lag`, 8 days
  for theLook) and the Briefing's ranges (`briefing/ranges`). The week ahead must use the one the Briefing uses for
  the same number, or say which one it used.

### 3.7 · Between you and Aughor

Four counts for the person looking at the page:
- what they told it;
- how often the data agreed;
- how many forecasts they booked;
- how many landed inside their range.

It starts at zero on this install, and it says so: *"Answer today's question and this starts counting."*

- **Doors.** `GET /principals/{principal}/record` exists. It gives claims by kind, how many were restated, and
  predictions scored and inside their band.

### 3.8 · What it costs, said plainly

- **Who "you" is.** Analyses record an organisation, not a person (§2). Sections 3.2, 3.5 and 3.7 need one. On an
  install with identity off, "you" is the name a form carries (`security/authz.acting_person`, kept as
  `person:<name>`), and the page says so.
- **Spend.**
  - 3.2 reads runs that already happen; the daily run is already paid for.
  - 3.5 re-runs stored SQL, which costs warehouse time but no model calls.
  - A model run happens only on an opt-in, with a per-person budget shown on the page.

### 3.9 · What leaves Home

The Get Started cards, the four stat tiles, the health scorecard and the recent-activity table go: each is a page
that exists. The first-run steps stay, shown only before the first analysis.

## 4 · Order, if adopted

1. **Drop the copies; add 3.1 Ask with memory** (one read route), **3.4 Worth another look** (doors exist) and
   **3.7 Between you and Aughor** (a read).
2. **3.2 The one thing to know** reads the daily runs; its warning is the one piece of new code. **3.6 The week
   ahead** is all reads.
3. **3.5 Your standing questions** needs the standing mark, the morning job, and who "you" is.
4. **3.3 A question for you** comes once its rule and wording are decided. It needs a door to book a statement.

## 5 · Not taken: two Brain map redesigns (2026-10-05)

Before this, the same conversation asked what the Brain map should look like (Intelligence ▸ Brain map, §3.30).
Two shapes were shown in chat and neither was taken (*"Nah... not happy"*):
- the decision loop as five stations (knows → asked why → decided → did → learned);
- the business drawn as regions with measured links and decision trails.

The screen stays as built. One measured fact from that look is worth keeping. On theLook the map's link line reads
*"Findings → Dated facts: 114"*, while its Findings box reads 18. The first counts finding nodes in the context
graph; the second counts the explorer's store. That is two stores giving two numbers for one word, and it is not
traced.
