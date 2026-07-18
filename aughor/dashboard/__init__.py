"""User-authored dashboard cards — the standing (cockpit) layer of the Briefing.

A DashboardCard is a user-authored, grounded, refreshable card that lives alongside the
explorer's findings: a pinned KPI, a chart, a tracked topic ("watch"), or a free-text note.
It is the inverse of a finding — a question the user declares and asks Aughor to keep
answering. See docs/BRIEFING_COCKPIT_2026-07-18.md.

This package is the persistence foundation (Slice 0): the model + a SQLite store. The card
REFERENCES its grounded SQL (self-contained + optionally a SavedQuery) rather than overloading
SavedQuery, which is connection-scoped and carries no refresh/render/scope/links.
"""
