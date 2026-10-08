# The cockpit as a canvas, the Briefing as a reading — 2026-10-08

The user, on the Metrics cockpit (2026-10-08): *"the way I am asking you to remove certain parts from
briefing, making changes in the cockpit, et cetera, the actual user from an organisation which will
deploy this platform will not have access to change all these components.. but it's such a strong
feature to have that the user can make changes in terms of what they see in the briefing or in a
custom cockpit (not the default one which has all the metrics).. this makes briefing and the custom
cockpit more like a canvas on which user can place literally anything.. a cross-domain manager can
put cards from marketing, pricing, supply.. an image as a static card for reference or even just
plain text as a mental reminder.. this is more of a product design decision that we need to really
think through."*

This note is the thinking. It opens with what exists, because the answer is mostly an extension of
it; then the four calls the user made; then the laws a static element must keep; then the build
order. Nothing here is built.

## 1 · What exists (measured on `claude/cockpit-periods`, 2026-10-08)

**The Cockpit is already a canvas with a grammar.** A person's cockpit is a spec of five components —
Cockpit → Tabs → Tab → Section → Card (`web/lib/cockpit/catalog.ts`, `MAY_HOLD`) — up to 8 tabs, 60
cards, 200 elements (`web/lib/cockpit/rules.ts`). A Card names a card in the store by id and carries
no figure and no SQL. A Section or a Card may be shown by a condition on the host's state; a Tab may
not. The spec is accepted whole or refused whole, with sentences (`aughor/cockpit/validate.py`), by
the same rules the browser draws it with; a title a model wrote is held to the numerals law, a title
a person wrote is theirs. Every keep is a version in the Ledger with who approved it, where it came
from and a note (`aughor/cockpit/versions.py`); going back is a new version.

**A card is a measured thing.** `aughor/dashboard/models.py` knows four kinds — `note`, `kpi`,
`chart`, `watch` — and four sources: a finding pinned from the Briefing (door 1, its SQL re-run
through the guard battery), a Query Builder query (door 2, the same battery), an approved metric
(the composer), a watch. `note` exists in the model with a `body` and is drawn by nothing: no
cockpit tile has a branch for it. Provenance on every card: the finding and receipt it came from,
the metric and version it was made from, and since today the card that supersedes it.

**One connection per cockpit.** `Home(connection_id, owner, cockpit_id)` (`aughor/cockpit/home.py`);
`cards.place` refuses a card of another connection. A cockpit may place the person's own cards and
the connection's shared ones (`cards_of`). A reader who may not see a card's data sees the card
standing and saying it is withheld (`ComposedCockpit`).

**A model already drafts and edits a cockpit from words.** In the Briefing a person names an area and a
model drafts one proposal — the cards to make and the spec that arranges them — which the person
keeps whole or not at all (`aughor/cockpit/propose.py`, CT-5; `POST /cockpits/draft`, which spends
model calls). An edit is the same act, arriving as RFC 6902 operations against the version on screen
(`web/lib/cockpit/patch.ts`, applied strictly: an operation does exactly what it says or the whole
edit is refused). The model writes no SQL and states no figure; every new card names the record it
is made from and is run through the guard battery before it is offered. This is the natural-language
door, and it is a proposal door: words never write, a person's approval does.

**The Briefing is one fixed reading.** Verdict and its largest moves, the Key Metrics tiles, the
findings ledger, the full synthesis, where it was sent, the person's pinned-cards strip. Its layout
is code — which is why today's edits to it are the builder's and nobody else's. The per-person
part is the pinned strip. A per-user preferences store exists already (`GET/PUT /me/preferences`,
`aughor/db/user_prefs`; a cosmetic, self-scoped write with no capability gate) and holds nothing
about the Briefing yet.

**What the platform vouches for leaves through a gate.** A Briefing send is held on an ungrounded
numeral or a causal claim (`aughor/govern/departure.py`); CT-6 names "the same spec to PDF, to an
image card for Slack" as doors not yet scheduled. A static element on a cockpit will meet that gate
the day a cockpit is sent.

**Files and people.** Bytes go into a volume under the tenant's vended path with a metadata row
(`aughor/files/ops.py`: `put_object`, `read_object`) — the home an image has. Groups, roles and
role assignments exist (`aughor/rbac/`: `Group`, `Role`, `RoleAssignment`, `Permission`) — the
addressees a published cockpit has.

## 2 · The four calls (the user, 2026-10-08, asked with options)

1. **The Cockpit is the canvas; the Briefing gets switches.** A custom cockpit takes any element the
   grammar names. The Briefing lets a person show, hide and order its sections and choose which
   cockpit strip rides with it; its content is never edited by hand. The default Metrics cockpit
   stays the product's.
2. **A person may place, beyond measured cards: text notes, images, and any finding from the
   ledger.** Declined: cards from other connections — each connection has its own lag and its own
   data edge, and one period over two edges is two periods. Revisit when a cross-connection object
   metric exists (`object_metrics`, ROADMAP §3) and can say one "data through" for both.
3. **Personal, plus publish to a team or role.** As today for the author; publishing makes a version
   visible to a named group or role, kept under the publisher's name with the same record a kept
   version has.
4. **The Briefing's measured table, its segment breakdown and the early read come off** — they are
   the Metrics cockpit's. The Key Metrics tiles and the hero's largest moves stay. (Built today.)
5. **Every change can be asked for in natural language — except uploading an image and adding a
   text note**, which are by hand only (the user, later the same day). So "hide the findings
   section", "add the finding about returns by category to my cockpit", "move my note to the top",
   "share this with the sales team" are all one door: the model proposes, the person approves.
   "Write me a note saying…" is not: a note is the person's words, typed by the person.

## 3 · Laws for a static element

These extend the invariants in `AGENTS.md`; none is new in kind.

- **A static thing says it is static.** A Note shows its author and the date it was written; an
  Image its uploader, date and file name. Neither shows a status chip, a period or a comparison,
  because neither was measured for one — a reader must never take a note's number for a figure
  the platform read.
- **The platform never speaks a person's words as its own.** A Note is not a source: the narrator
  does not read it, no claim cites it, the Explorer does not learn from it. A Note may hold numerals
  — they are the person's, the validator's `model_written=False` reading — and they ground nothing.
- **Provenance stays required.** A Note carries `author`, `written_at`; an Image carries
  `object_id`, `uploaded_by`, `uploaded_at`. A static element with no author is refused.
- **Withheld is said.** An Image whose object the reader may not read, or that is gone, stands as
  its caption and says why. A finding placed from the ledger that the reader may not see stands
  and says it is withheld, as a card does today.
- **Supersede, do not delete.** A Note edited is a new cockpit version with the old text in the
  version before; an Image replaced keeps the old object until nothing references it.
- **The grammar grows by element, not by freedom.** Note and Image are components with fixed props,
  placed in a Section like a Card, shown or hidden by the same conditions, counted in the same
  limits. No free text outside a Note, no HTML, no embeds, no script.
- **A model arranges a Note or an Image; it never makes one.** The drafting model may move or take
  off a Note or an Image the person placed, because that is arrangement. It may not write a Note's
  text or pick an Image: the first would be the platform speaking in a person's name, the second a
  choice only the person can make. A proposal that tries is refused by the validator, not by the
  prompt.
- **Natural language is a proposal, never a write.** Every change asked for in words lands as the
  same staged proposal a drafted cockpit is — shown, then kept whole or refused whole on the
  version it was written against. A Briefing switch asked for in words is a proposed preference
  change the person confirms.
- **A send strips what the platform did not measure.** When a cockpit leaves (CT-6), Notes and
  Images travel marked as the person's, or not at all; the departure gate judges only the measured
  cards. A Briefing send is unaffected by a person's switches: it carries the platform's Briefing.

## 4 · Build order

Each step is its own PR, each behind nothing: none changes what exists for a person who uses none
of it.

**B1 · Briefing switches** (small). A `briefing.sections` preference per person: the named sections
in order, each shown or hidden, and which cockpit strip rides with the Briefing. One "Sections"
menu at the top of the Briefing; a hidden section leaves one line saying it is hidden and how to
show it. Stored through `/me/preferences`. Nothing about a section's content changes. *In words:*
"hide the findings, put the synthesis first" — the model proposes the preference, the person
confirms; the Briefing's "Ask this briefing" is the place to say it.

**B2 · Note** (medium). `Note` in the catalog (`text` up to ~600 characters, plain; `author` and
`written_at` stamped by the server, never by the client); `MAY_HOLD.Section` gains it; the validator
counts it; a tile draws it as the person's words with the stamp; "+ Note" beside "+ Card" in the
cockpit's own hand; the drafting model may not write one (a model-drafted cockpit holds measured
cards only). *In words:* only "move my note", "take my note off" — arrangement.

**B3 · A finding from the ledger as a card** (small). Door 1 takes any recorded finding of the
connection, not only this cycle's Briefing: the same guard-on-write, the same link back. A finding
with no query has nothing to measure and is refused as it is today, with the reason. A picker in
"+ Card" lists the ledger's findings by domain. *In words:* "add the finding about returns by
category" — the draft door resolves the finding from the ledger and runs it before offering it.

**B4 · Image** (medium). Upload into a per-connection cockpit volume (`files/ops.put_object`; image
types only; a size cap stated in the refusal); `Image` in the catalog (`object_id`, `caption` up to
~120 characters; uploader and date from the volume's row); a tile draws it with the stamp; read
access through the same volume read as any object. *In words:* arrangement only, as for a Note.

**B5 · Publish to a group or role** (medium–large). A version carries `published_to`
(group or role ids) and the publisher; readers list "Shared with you" beside their own cockpits,
read-only, with "Start my cockpit from this" as a copy; unpublishing is a version; a card the reader
may not read stands and says so. The period a reader sees is the reader's own choice. *In words:*
"share this with the sales team" — a proposal naming the group; the person's keep publishes it.

## 5 · Not built, and said so

- Cards from other connections on one cockpit (declined, §2.2).
- Free placement on the Briefing (declined, §2.1).
- Embeds, links as cards, HTML, iframes — outside the grammar on purpose.
- Admin-edited org-wide defaults: the Metrics cockpit stays the product's; a team's shared view
  is a published cockpit, not a changed default.
- A cockpit send (CT-6) — the laws above say what it must do when it comes.

## 6 · Open for the user

- Note length and whether plain text is enough (no Markdown proposed).
- Image size cap and types (proposed: PNG, JPEG, SVG, 2 MB).
- Who may publish: any member, or a capability. Proposed: any member may publish to a group they
  belong to; a role needs the role's own permission.
