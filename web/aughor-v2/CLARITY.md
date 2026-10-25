# Clarity — what a screen says, and how it is laid out

The law for every screen redone in the interface overhaul. `INSTRUMENT.md` owns the tokens and the components;
this file owns what goes on a screen, in what order, and in how many words.

Adopted 2026-10-10. The user, on the first mockup in this style: *"Absolute perfection. I want exactly the same look
and feel"*, then *"I want this theme, this approach of clarity, design, layout and tokens"*. The brief behind it:
*"remove unnecessary junk and put forward only what is actionable, provides value in terms of knowledge or insights,
and avoid making the user read something that doesn't matter or help."*

**The reference screens**, each built from live theLook data (open them; they are the spec as much as this file):

| Mockup | Words a reader faced | After |
|---|---|---|
| `design-mockups/cockpit-from-object.html` — a cockpit started from an object, filtered | — (new screen) | — |
| `design-mockups/home.html` — Home | 1,076 | 256 |
| `design-mockups/spend.html` — Spend | 5,257 | 191 |
| `design-mockups/ontology-tab.html` — the Ontology tab | one panel that did not end | one panel, six tabs |
| Settings ▸ System, built (`components/SystemPanel.tsx`) | ~3,000 | 739 visible, 838 behind Details |

---

## 1. The test every element passes

An element stays on a screen only if it is one of four things:

1. **A figure someone acts on** — a number, its change, its comparison.
2. **Something that needs them** — a question, a decision, a broken promise, a missing price.
3. **A way to act** — a button on the row it acts on.
4. **Knowledge they came for** — an answer, a finding, a picture of how a thing moves.

Everything else is removed, folded into a count, or moved behind *Details*. If you cannot say which of the four an
element is, it goes.

## 2. Content

| Do | Don't |
|---|---|
| **Lead with the figure.** `$19,087.76` · `▲ $209.55 · +1.1%` · `within normal range` | Open with a sentence: *"TheLook generated $19,087.76 in revenue on October 2, 2026, representing a 1.1% increase…"* |
| **Say a thing once; fold repeats into a count.** "Query checks · 477" as one row; "Mon 12 Oct · 11 forecasts" | List 500 identical *"query.execution · query safe"* rows, or 33 *"A forecast settles: expected: …"* lines |
| **Put what needs a person first, together, under "Needs you"**, in amber, with its buttons on the row | Scatter questions and decisions among status cards |
| **One-line subtitles.** At most two sentences of 20 words anywhere always visible | A paragraph under any title |
| **Humanise numbers.** `$231.5K`, `60.0%`, `4.48M`, `1,904`; tabular numerals | `231521.3`, `0.599699`, `4476728` |
| **Facts as chips, not prose.** `Daily` · `Sends to Slack` · `1 model call per draft` · `no price` | *"Costs one model call per certified golden per agent per night."* |
| **Caveats as a chip, never hidden.** `8 days behind today` · `28% of calls priced` · `not checked yet` | A caveat buried in a paragraph — or dropped |
| **Short labels for long questions**; the full text on hover | The question printed in full beside its answer |
| **The reader's words** — `docs/GLOSSARY.md`; the business's names for objects | Routes, arc or wave ids, `§` references, function names, decision dates, internal probe names (`__trust_coltypes__`), *"exactly as before"* |
| **An empty section is one muted line** ("Nothing new since Sat 10 Oct"), or a single card that says so | A card per absence — five cards each saying there is nothing |
| **Withheld is said** — a trimmed list, a blocked action, an unpriced call, a row you may not see each says so, briefly | An empty result that means "you may not see this" |
| **Name noise as noise.** "112 flagged were the platform's own schema reads" | Alarm the reader with a count of "suspicious" that is the platform talking to itself |

## 3. Layout

**The order of a screen:** figures → *Needs you* → the picture (a chart, a flow) → the list. A reader who stops after
the first row still leaves with the answer.

| Do | Don't |
|---|---|
| **A row of 3–4 figures** at the top: label (11.5px, muted) · value (22–30px) · one muted line ("of 125,080", "614 in the last 7 days") | A header bar of mixed links, counts and sentences |
| **Surfaces on a ground** (2026-10-25): a card `--bg-2` on the page `--bg-0` — a step lighter in dark, white on grey in light — with a hairline edge `--card-edge` in both skins, radius `--r3`, no shadow; a control `--bg-3` a step under the card it sits in; a 1px line wherever two surfaces meet; 14px gaps | Borders drawn twice (a boxed card inside a boxed card); shadows; a surface the same colour as its ground |
| **Pairs side by side** — two related cards on one row (Tokens by model · Where tokens go) | One long column the reader scrolls past |
| **Filters in a left column**: value · count · a 6px bar; the chosen row tinted; the set's size as "37,838 of 125,080" | Dropdown filters that hide the distribution |
| **List rows: name · figure · one muted meta line**, with marks (`✓ key`, `● 1 proposed`) instead of words | A sentence per row |
| **Read first, edit behind *Edit*.** Forms appear only when a person asks for them | Authoring forms open in a reading view |
| **Detail behind tabs or *Details*** (Overview · Properties · Links · Actions · Sources · History) | One panel of twelve sections that never ends |
| **Tools in one menu** (*Tools ▾*) | A row of five tool buttons |
| **Small uppercase section labels** (11px, letter-spaced, muted), the meta at their right end | Page title bars; a title that repeats the rail or tab |
| **One skin across the shell and the page** — the rail, the top strip and the content share the skin the toggle set | A dark rail or strip on a light page, or the reverse: *"I cannot have half dark and half light theme"* (the user, 2026-10-25) |
| **Graph connectors straight**, bending only at 90° or 45° (step edges, zero radius) | Curves (bezier edges) |
| **A process as a funnel** — stage · bar · count — with each promise on one line and its overdue count as a button | A process described in prose |

**Count it.** The design study of 2026-10-25 (in `docs/`, §2.3) measured the numbers a published guide to
operational screens holds a screen to; they agree with the test in §1 and make it countable. Hold a screen to them before
it ships:

| Count | At most |
|---|---|
| Primary actions in a screen's top row (buttons a reader is meant to press first) | **5** |
| Components visible at once — buttons, panels, cards, charts, tables | **10** |
| Air — the share of the screen that is not ink | **30–40 %**, as a floor |
| Regions with a shaded or raised style (a tinted panel, a shadow) | **1** per screen |
| Header and tab rows that scroll away | **0** — the header and its tabs stay; only content scrolls |
| A control's hit target where a section scrolls | **≥ 30 px** |
| A dense table's row at 100 % (the ledger's too) — the compact row of an operations console, one variable in `app/globals.css` | **30 px** |

Filters stand in the left column, the figures above the list, the detail to the right of it (§3's order and
`cockpit-from-object.html`); a sideways scroll is a column to fit, never a scrollbar.

## 4. Colour and type — what each one means

Values are the app's tokens (`theme/tokens-v2.css`); the mockups use their computed dark values.

| Token / use | Means | Never |
|---|---|---|
| `--bg-0` ground · `--bg-1` chrome (rail, strips, table heads) · `--bg-2` card, panel · `--bg-3` control, inset | Structure: dark steps gray 1 · 2 · 3 · 1, light gray 3 · 2 · white · 3 | — |
| `--t1` · `--t2` · `--t3` | Value · supporting · meta | Colouring text with a series colour |
| Accent (indigo) + its soft fill | Selected, primary action, the chosen row | Decoration |
| Amber + soft fill | Needs a person: a broken promise, no price, no cap | "Series 4" |
| Green | Up, checked, passed | Decoration |
| Violet | Proposed by a model or a pack, not yet confirmed; "via" a link | Anything a person decided |
| Hatched de-emphasis grey | Unknown — not zero (no price, not counted) | Any other meaning |
| Inter 13px base; figures Inter with tabular numerals; mono only for ids, code, column names | — | Mono for figures |

## 5. Charts

Follow the dataviz method and `components/charts/palette.ts`: one axis, never two; categorical hues in the palette's
fixed order, colour following the entity; a single series carries no legend; ≥ 2 series a legend; selective direct
labels (the last point, not every point); recessive grid; bars with a rounded data end; the de-emphasis grey for
"all" behind a filtered series; a tooltip on every mark. A distribution beats a table: counts by category as bars,
change over time as bars, a comparison as two bars.

## 6. Before a screen ships

1. **Mockup first**, in this style, on live data (theLook), and the user's reaction before building.
2. **Count the words** a reader faces before and after; say both numbers.
3. **Run the four-part test** (§1) on every element; list what was removed and why.
4. **Read the whole screen as the reader sees it** after the change — the blocks you did not touch included.
5. **Nothing true is lost**: every caveat, withheld row and refusal still says so.
6. **Screenshot it** and show it.
7. Copy that ships in code obeys the same rules — and where a test can hold them (`tests/unit/test_flag_copy.py`
   holds the flag cards to two short sentences and no engineering names), add one.

## 7. Where this departs from `INSTRUMENT.md`

- **Cards, not one plane.** INSTRUMENT §0 says *"one plane, not a stack of cards"*; the approved screens set content
  in cards on the ground. Superseded there, 2026-10-10.
- **Figures in Inter.** INSTRUMENT §2 still says JetBrains Mono for every figure; its own §10 self-check already says
  tabular Inter, mono for ids and code only. This file agrees with §10; §2's line is marked stale.

Everything else in INSTRUMENT — the token names, the focus ring, motion, the states, the trust system — stands.
