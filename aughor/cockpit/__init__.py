"""The composed cockpit — a board a person asks for, arranged by a spec, measured by the cards.

Arc CT (ROADMAP §3.50; docs/COCKPIT_JSON_RENDER_STUDY_2026-09-28.md). The law of the arc: the
spec arranges, the card store measures. A spec holds tabs, sections and the ids of cards; what
a card measures, its limits and its history stay in ``aughor.dashboard``.

This package holds the server's half of CT-2: the validator that accepts a spec whole or
refuses it whole, with sentences. It keeps nothing — CT-3 keeps the spec, as a versioned
artifact in the Ledger.
"""
