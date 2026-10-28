"""Arc AP-4 — a dashboard built from a structure of pieces (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md
§3, and the user's ask of 2026-10-11, showing Workshop's blank app: "a widget based structure would be really helpful").

A section holds pieces on its own grid, or is laid out in columns, rows or tabs of sections of its own; a section may
hold nothing yet, for a builder to offer it a piece; and a section split into sections may go untitled. The web's rules
hold the structure's shape from the catalog the browser draws with (`web/lib/dashboards/rules.ts`, `checkStructure`).

The builder's picker adds (the study's §4.4) a list of objects as cards, a map, a timeline, a choose-one, a search, and a
drawer that opens beside the page on a chosen object. What each piece reads is checked as a table's is
(`pieces.not_resolved`).
"""
from __future__ import annotations

#: What the builder's picker adds — placed by a person, as every piece bound to the ontology is.
PIECES = ("ObjectList", "ObjectMap", "ObjectTimeline", "ChooseOne", "ObjectSearch", "Drawer")
