"""The composed cockpit — a board a person asks for, arranged by a spec, measured by the cards.

Arc CT (ROADMAP §3.50; docs/COCKPIT_JSON_RENDER_STUDY_2026-09-28.md). The law of the arc: the
spec arranges, the card store measures. A spec holds tabs, sections and the ids of cards; what
a card measures, its limits and its history stay in ``aughor.dashboard``.

- ``validate`` (CT-2) accepts a spec whole or refuses it whole, with sentences, and fails
  closed when its rules cannot run.
- ``versions`` (CT-3) keeps a spec as versioned artifacts in the Ledger, one natural key per
  canvas. It is not a store of its own.
- ``cards`` (CT-3) keeps and lists a canvas's cards, in the card store, at canvas scope.
"""
