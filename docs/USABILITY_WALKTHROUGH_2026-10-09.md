# Usability walk-through — designing operations from the screen (2026-10-09)

Three jobs a business user must be able to do alone, walked on theLook through the live app (`:3000`, viewport
1440×900), the way a person would: **design a process**, **declare an action**, **build a cockpit on it**. Nothing was
written — every form was filled up to its submit and cancelled; the API log shows reads only, and no model call was spent.
The data behind each form was measured read-only, to see what the person would have shipped.

## The finding that matters most

A delivery process typed the way a person would — *shipped → delivered within 5 days* on Order — would have published
a board of **≈35,750 late deliveries** against a **0 % breach rate** among delivered orders. On theLook 37,243 orders
reached *Shipped* and never *Delivered*; 22,152 of them over a year ago (back to 2019), and some `shipped_at` values fall
after the data's last day. In this data an order stuck at *Shipped* is a dead record, not a late one. **Nothing on the
screen shows the person any of it before they publish**: the form asks for column names and shows no counts, no
durations, no examples; the server has no way to count a draft without writing it (the type-backing form has a preview;
the process form does not); and how an object leaves a process cannot be declared on screen. Late dispatch came out
right only because the 18,726 cancelled orders were found by hand afterwards.

## Job 1 — design a process (*Order delivery: shipped → delivered within 5 days*)

| # | What happened | Why it matters |
|---|---|---|
| 1 | No rail entry says ontology, process or operations. *Semantic Layer* (metrics, annotations, knowledge…) and *Catalog* (>5 s on "Loading the catalog…") are dead ends. The Ontology is one of **ten layer tabs inside the Briefing** page. | The place where the business is designed cannot be found. |
| 2 | The *Processes* list in the Ontology's left column has no "new process". The only door is **Declare a process**, in the object type's detail column — **359 px wide (25 % of the screen), 2,639 px down: four screens of scrolling**, after eight other sections. | A critical job sits where an afterthought would. |
| 3 | Filled as a person writes — "Delivery time", stages "Shipped" and "Delivered", within 5 days — **Declare the process stays disabled with no message**. It wants snake_case (`delivery_time`, `shipped`). | A silent dead end on the first try. |
| 4 | A stage's *moment* is a dropdown of raw column names (`created_at`, `returned_at`, `shipped_at`, `delivered_at`) in column order — no labels, no counts, no example dates; only the type's own columns. | The person picks blind, and cannot reach a status, a linked record or another system. |
| 5 | **No preview of any kind before writing** (see above): nothing says how many objects reach each stage, how long they take, how often the promise is broken, what would be called overdue. | The process is wrong in ways only the data can show — and the data is not shown. |
| 6 | The engine accepts far more than the form asks: owner, description, stage display names, a stage reached by **status**, a moment on a **linked object**, a **deadline** promise, a promise kept per another type, a **target** rate, **exits**, stages on **another connection**. | About a third of the model is reachable from the screen. |
| 7 | Scrolling to the form shifted the page sideways; the rail then covered half of the object list. | A layout fault. |
| 8 | The surface speaks the builder's language: "key unique", "joins measured 9 of 9", "approve 'revenue' and 4 held sends unblock", "semantically enriched", "Withdrawn", "PATH TO … hop by hop". | A business user cannot read the page they are meant to work in. |

## Job 2 — declare an action (*flag a late delivery for the carrier team*)

| # | What happened | Why it matters |
|---|---|---|
| 9 | One form of **14 inputs and 7 dropdowns** mixing the business meaning with a webhook integration: kind, risk, typed parameters (`NUMERIC`), a criterion expression, an overlay edit, HTTP method, URL, auth header, credential, JSON headers and body, a verification **SQL statement**, reversibility, undo id, window. Defaults: `side_effect`, risk `high`. | A developer's form for a business decision. |
| 10 | Three fields are **pre-filled with real values from a refund example**: parameter `amount_eur`, criterion `amount_eur <= 10000` with *"Refunds over EUR 10,000 need finance sign-off."*, and body `{"summary": "{amount_eur}"}`. | A person saves someone else's refund rule unless they notice and delete it. |
| 11 | "Entity this action is about" is a free-text box, not a choice of the ontology's object types. | The action's link to the model rests on spelling. |

## Job 3 — build a cockpit on it

| # | What happened | Why it matters |
|---|---|---|
| 12 | **+ New cockpit** offers only *Draft it*: a model drafts one from metrics, trusted queries and findings (about a minute, model calls spent). The process pieces exist only on the toolbar of a cockpit already kept (*From the ontology*). | There is no way to start "a cockpit for this process". |
| 13 | The pieces are placed one at a time from four tabs; the table needs the segment's id (`overdue_dispatch`). | Four steps for what is one intent. |
| 14 | *Retire this cockpit* is inside **History**. | Removal reads as absent. |
| 15 | Once built, the cockpit reads well: the board's stage counts, the broken promise, the exits said, the overdue table beside one object's detail. | The destination works; the road to it does not. |

## What follows

The engine is ahead of the surface. The fix is not more fields in the side column but a **process designer**: its own
page inside the Ontology (the rail unchanged), that designs *from* the data — candidate stages proposed from the
timestamps and statuses the object and its linked records carry, live counts and durations on every stage, the promise's
breach rate as the number is typed, exits drawn from the statuses objects actually end in, plain-language checks before
publishing (the 35,750 above, asked as a question), and what it creates — the overdue list, the rate, a board — shown
before it is published. Then the same treatment for actions (business meaning first, the integration as a separate,
optional step) and for starting a cockpit from a process.
