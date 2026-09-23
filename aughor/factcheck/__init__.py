"""Idea 7 · fact-check a document against the data.

Paste a board memo or an email, or upload a deck: every numeric claim in it is checked
against the warehouse — it matches, it does not (and by how much, against which definition
and window), or it cannot be checked (and why). The result is an answer envelope (Arc CP),
so every door renders it the way it renders any answer, and it is filed as a turn so it
can be exported and reloaded. The platform stops being only something that writes reports
and becomes something that checks everyone's.
"""
from aughor.factcheck.check import Claim, ClaimVerdict, Measurement, claims_in, factcheck  # noqa: F401
