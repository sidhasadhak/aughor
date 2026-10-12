"""What counts as a lifecycle state — one rule for the explorer, the schema annotations and the
ontology builder, which each carried their own copy.

A state is a short identifier ("Complete", "Shipped"), never a description, a formula, a
two-letter code or a document. The explorer's status-column finder matches by substring, so
without this rule a single-row JSON column whose text merely contains "complete" became a
"status column" and its 1.6M-character value a "terminal state": rendered twice into every
schema prompt on LuxExperience (2026-10-12), it made the business-profile prompt 1.8M tokens,
over every provider's limit, so no profile and no metrics were ever built.
"""
from __future__ import annotations

import re

#: The longest text that can still be a state identifier; longer is a description.
MAX_STATE_CHARS = 30


def is_lifecycle_state(value: object) -> bool:
    """A value that can name a state: short, not a formula, not a bare ISO-2 code."""
    s = str(value).strip()
    if not s or s == "null":
        return False
    if "/" in s:                              # formula strings: "Revenue / Ad Spend"
        return False
    if re.fullmatch(r"[A-Z]{2}", s):          # bare 2-letter ISO codes: SP, CA, NY
        return False
    if len(s) > MAX_STATE_CHARS:              # descriptions, documents — not state identifiers
        return False
    return True


def plausible_lifecycle_states(states: list) -> bool:
    """Do these values read as process stages? Real states are terse (average ≤ 15 chars, ≤ 2
    words); KPI names and descriptions fail both. Judged on the values that are states at all."""
    valid = [str(s) for s in states if is_lifecycle_state(s)]
    if not valid:
        return False
    avg_len = sum(len(s) for s in valid) / len(valid)
    avg_words = sum(len(s.split()) for s in valid) / len(valid)
    return avg_len <= 15 and avg_words <= 2
