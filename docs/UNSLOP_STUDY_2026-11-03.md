# What unslop teaches, measured on Aughor's own screens (2026-11-03)

The user, 2026-11-03: *"lets study this https://github.com/heydamir/unslop and try to make our platform more appealing
and top UI/UX quality."*

Source: [heydamir/unslop](https://github.com/heydamir/unslop) by Damir Sokolovsky ([@heydamir](https://x.com/heydamir)),
CC BY 4.0, read whole at `a6f121e`: the skill, its five references, both example screens. Anything adapted from it keeps
this credit. Mockup: `design-mockups/unslop-proposal.html` (Home and Record, now vs proposed, live theLook).

## 0. The verdict

1. **Aughor is not slop.** Purple gradients, gradient text, glows, greeting headlines, hype words, exclamation marks and
   `transition-all` are all at zero. By unslop's own triage this is *light slop*: polish it, keep the system, do not
   redesign it.
2. **It fails unslop's second test, the one that matters here.** *"A screen that is clean but could belong to any product
   is the next template."* 15 of 23 screens open on the same row of equal figure cards. Nothing on any screen is larger
   than 22px. Two thirds of all text is 12px or smaller. The loudest thing on 9 screens is an amber warning box.
3. **That is why it reads as flat, not as ugly.** Every element is at the same volume, so nothing is memorable and nothing
   leads. The fix is not more decoration. It is one lead per screen, drawn from what only Aughor knows.
4. **The user already asked for this once.** 2026-10-13: *"make sure everything does not look like a dashboard at the
   end."* The rollout drifted back. A shared kit made that easy, and makes the fix cheap: `Figures` is used in 28 files and
   `NeedsYou` in 26, both from `components/clarity/kit.tsx`.
5. **The most serious findings are about copy, not paint.** Raw 404 errors, UUIDs and a prompt preamble are printed to
   readers, and Home's lead figure is six times what the warehouse now says for that day (§3).

## 1. How this was measured

Headless Chrome at 1600×1000 against the live `:3000`/`:8000`, theLook, in the user's own look (teal · gray · small · 95% ·
edges on · Source Sans 3). Every API write and the known spending GETs (`needs-human`, `findings/reask`, the Briefing build)
were blocked at the browser, so no screen could spend or write. Each screen was screenshotted and measured from the DOM.
The source was counted separately: 500 files, 160,926 lines.

Spend: no model calls (the one `openrouter` log line is `GET /models`, a price list). Two BigQuery statements through
`POST /query/run`: one refused at planning, one daily revenue read of `order_items`.

**Not judged:** the Briefing and Dashboards (the guard stopped their reads, so what was captured is not what a reader
sees), the light skin (the capture came back dark) and small screens. The failure states on Now and Agent Ops are also
the guard's and are not counted below.

## 2. The audit against unslop's signs

| Sign | Measured | Reading |
|---|---|---|
| Gradient text, `bg-gradient`, drop or text shadow, `transition-all`, `hover:scale` | 0 | clean |
| Hype words, greeting headlines, exclamation marks | 0 | clean |
| Gradients | 16, all hatching, fade masks, dot grounds, shimmer or tint layers | clean: none is decoration |
| Backdrop blur | 8, mostly scrims and two old canvases | fine |
| Emoji as icons | about 20 (📊 👍 👎 📄 ✅ ⚡ 🔒 🗑 …), plus 22 `⚠` | small, real; `✓`/`✕` marks are CLARITY's and stay |
| `animate-pulse` | 2 | small |
| Italic for emphasis | 24 | small |
| Weight 700+ | 23 | small |
| Weight 600 | 338 in 138 files | hierarchy by weight, not size |
| **Uppercase tracked labels** | 158 in 83 files, on 20 of 23 screens | unslop's top sign, but **CLARITY §3 prescribes them**: a call (§5) |
| **Type sizes per screen** | 4–7; **`11` and `11.4` side by side on 23 of 23** | the scaling knob reaches Radix, not `.aug-fs-*` or inline px |
| **Text at 12px or less** | 66% of text elements | small type is the norm, not the exception |
| **Largest type** | 22px on 16 screens, 13–18px on the other 7 | no screen has a lead |
| **Equal figure cards on top** | 15 of 23 screens | the 10-13 rule, drifted |
| **Filled amber block** | 9 screens, 5–28% of the screen (Record 28.4%) | the bright element is a warning |
| First screen more than 200px empty | 9 of 23 (2 of them the guard's) | fine in an app; only Home is worth composing |
| Spacing off the 4px grid | 52% of inline gaps, 34% of inline padding, mostly 14, 6, 10 | **leave it**: 14 is CLARITY's own value and nothing reads as uneven |

## 3. Defects found, worst first

**Truth and copy**

| Sev | Where | Now | Should be |
|---|---|---|---|
| HIGH | Home lead, `components/home/HomeDesk.tsx:186-211` | "Revenue · Wed 14 Oct · **$97,274.71**", while the governed query reads that day as **$15,275.75** today (−84%) | The lead shows what the day reads now, and what it was reported as |
| HIGH | `aughor/monitors/notify.py:115` | "Why did Average Order Value (AOV) Average Order Value (AOV): its query could not run… 404 Not found: Table project-f9f4d726… Job ID…?" as a question | "Average Order Value can't be checked", with the error behind a door |
| HIGH | `components/now/NowPanel.tsx:225` | A run titled "[Scheduled-run context — written by code, not inferred] This is a scheduled daily run at…" | `lib/runTitle.ts` already solves this; Now does not call it |
| MED | `components/inquiries/InquiriesPanel.tsx:191` (`whoLabel`) | "opened by the a1c46186-81fb-4d03-ab24-b2acb2f2fdb5 monitor" | The monitor's name |
| MED | Security ▸ Queries | `automation:7473b250-3bed-4aea-b009-9bbe493abf32:top_sellers` | The automation's name |
| MED | Home, model prose | "profit of 231521.3", "margin of 0.599699 versus 0.598046", "vs 2026-10-13", "Totalled 610,184.21 USD" beside "$240,404" | CLARITY §2 already says humanise; prose escapes it |
| MED | `HomeDesk.tsx:211` | A 90-character lower-case sentence inside a chip | A chip is a fact; the sentence goes beside it |
| MED | Record | The same inquiry 3 times in a row; every Needs-you row printed again in the list below | CLARITY §2: say a thing once, fold repeats |
| LOW | Data Canvas | "Data Canvas" under every card's title, the same icon tile on each | Remove both |

*In passing, not UI:* the AOV monitor's error names a table `thelook.order items`, with a space. Its later status says it
runs again; worth one look.

**Craft bugs**

| Sev | Where | Now | Fix |
|---|---|---|---|
| HIGH | `components/CatalogScreen.tsx:536-540` | The search icon sits on the placeholder: "⌕earch catalog…" (icon at x 266–277, text starts at 259) | Use the input's own slot |
| HIGH | `components/ontology/EntityTypeMap.tsx:973` and 5 other `<Controls>` | The map's zoom buttons are **white** on the dark skin: `rgb(254,254,254)`, never themed | One rule in `globals.css` |
| MED | `components/sheets/SheetsHome.tsx:107` | Start-a-sheet tiles centre their content: icons at 15, 62, 41, 75px from the card edge | `justifyContent: "flex-start"` |
| MED | `components/QueryBuilder.tsx:1926,1969` | 📊 as an icon | The set's icon |
| MED | Home, Data Canvas | An input with its own border inside a bordered card (CLARITY: borders drawn twice) | One control |
| LOW | Monitors, Agent Ops | A chart whose whole content is one fat block | Fewer buckets, or the count as a figure |

## 4. What to take, what to leave

**Take**

- **One lead per screen, from the product's own material.** Unslop calls it one bright element. For Aughor it is not an
  image: it is a number with its proof. The theLook chart in the mockup is the argument. The settled line, the hatched days
  that have not settled, and a dot where $97,275 was reported above the $15,276 it became. No other product can draw that.
- **Hierarchy from size, not weight.** A lead figure at 40–44px weight 500, then the existing small sizes. One scale, so
  `11` and `11.4` stop appearing together.
- **Charts have a hierarchy.** One main chart, one accent, direct labels. CLARITY §5 has most of this already.
- **The template check**, added to CLARITY §6: *swap the product's name; would the screen still fit?*
- **The direction, as five lines** (below). They hold the polish together.
- **The pass order** for doing the work: spacing, colour, icons, copy, type, layout, details, visuals, motion.

| Direction | |
|---|---|
| Product | Checks what a business's numbers say and tells the people who run it what moved, why, and what to do, with the proof attached |
| Character | exact, accountable, unhurried |
| World | an auditor's working papers: figures, tick marks, what was restated and when |
| Moments | one per screen, the number and its proof: Home the lead chart, Ontology the map, Spend the hatched unpriced tokens |
| Signature | the checkable figure: the receipt behind a number, already built as `components/ui/trust.tsx`, used more visibly |

**Leave**

| unslop says | Why not |
|---|---|
| Cap content at 1440–1600 | The user's standing rule: every page uses the full width |
| Mono for figures | CLARITY §4: tabular Inter, mono for ids and code |
| Cards at 12–16 radius | The Look's corners knob is each person's own |
| Sweep every value to 4px | Churn in 186+ files for something nobody can see; fix only where it reads as uneven |
| Generated scenes, glyph effects, an object render | Dashboards rarely need them, it says so itself, and Aughor has no landing page |
| Story video | For posting, not for quality. Could serve the launch video later |
| Install it as a skill | Its defaults contradict CLARITY in the three ways above; better to take the rules into CLARITY, with credit |

## 5. Calls, the user's

1. **The direction in the mockup, yes or no.** Recommended: yes.
2. **Section labels: sentence case or uppercase?** Unslop's top sign, and CLARITY §3's own rule, from the mockup the user
   called "absolute perfection". The rail is already sentence case, so two styles sit side by side. Recommended: sentence
   case. The mockup has a switch for this.
3. **"Needs you": an amber edge, or a filled amber block?** CLARITY §2 says "in amber", not filled. Recommended: the edge,
   with amber kept for the label and the marks, so a warning stops being the brightest thing on nine screens.
4. **Which screens lose the figure row?** Recommended: ledgers lead with their rows (Record, Inbox, Agent runs, Evals,
   Security, Notifications), counts moving into the filter. Cockpits and Spend keep theirs, where a number is the point.
   This is the 10-13 rule, applied.

**Reaction, same day.** The user, on the mockup: *"I like it.. but"* `Check again` and `Not worth it` do not read as buttons
*"only when a user hovers"*, and *"they should be across the platform"*. Measured: 133 of 270 action-sized controls on 21
screens had no edge, because 1,012 of 1,698 `<Button>`s were `ghost`. Built on `claude/visible-buttons`: `ghost` draws an edge,
`plain` is the counted exception, and the rule is in CLARITY §3. No verb action is left without an edge on those screens. The
remaining 40 are links in the accent colour, names, tree rows, tabs and pills. Calls 2 to 4 above are still open.

**Decided, same day** (the user, asked directly): uppercase section labels stay, so CLARITY §3 does not move · "Needs you" takes
an amber edge in place of the fill · all six ledgers lose the figure row · the buttons go live, then the fixes follow.

**Built, same day, on `claude/visible-buttons`:** the craft bugs, the machine text, the amber edge, the six ledgers (Record's five
tabs among them), and Home's lead chart. Home's figure now says what the day reads today and what it was reported as.
Left alone on purpose: the Data Canvas list (the user kept it as it was, 2026-10-12), one type scale (making the small sizes
follow the scaling knob would shrink text that is already 12px or less), model prose such as "Totalled 610,184.21 USD".

## 6. The work, if taken

| Step | What | Size |
|---|---|---|
| 1 | Craft bugs from §3 | under an hour, no design question |
| 2 | Reader-facing machine text from §3: monitor questions, run titles, UUIDs, chips, repeats | half a day to a day, backend and web |
| 3 | Kit level: `NeedsYou`, `Label`, one type scale | hours; reaches every screen at once. Needs calls 2 and 3 |
| 4 | Home: the lead chart, re-reading a restated figure, the layout in the mockup | a day |
| 5 | Ledgers lose the figure row, one screen at a time, each shown | a day or two. Needs call 4 |
| 6 | CLARITY: the template check, the direction, the rule that no machine text reaches a reader, a gate where one can hold it | an hour |

Rail, top bar, one skin, full width and the existing tabs do not move.
