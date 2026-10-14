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


# The words a state is known by. A value naming one, whole or as part ("Cancelled", "pending_review"), is a
# recognised state; the rest of a status column's values may be states this list has never heard of.
TERMINAL = frozenset({
    "canceled", "cancelled", "returned", "closed", "archived", "failed",
    "rejected", "expired", "deleted", "churned", "lost", "void", "voided",
    "refunded", "bounced", "blocked",
    # "completed", "done", "delivered", "shipped" removed — these are
    # context-dependent (e.g. "shipped" is mid-flow in fulfillment).
    # Terminal classification is now advisory, not filtering.
})
ACTIVE = frozenset({
    "active", "live", "running", "processing", "open", "pending", "approved",
    "in_progress", "inprogress", "scheduled", "confirmed", "new", "created",
    "placed", "accepted", "ready", "invoiced",
})
TERMINAL_SUBS = ("cancel", "fail", "reject", "expir", "close", "archiv", "delet", "return", "void", "refund", "churn")
ACTIVE_SUBS = ("pend", "process", "approv", "creat", "open", "activ", "run", "sched", "place", "accept", "new")

#: A column named for what it holds: `status`, `order_state`, `stage`, `phase`, `lifecycle`.
_STATUS_NAME = re.compile(r"(?:^|_)(?:status|state|stage|phase|lifecycle)(?:$|_)", re.IGNORECASE)


def names_a_state(value: object) -> bool:
    """Is this value one of the state words, whole or in part?"""
    v = str(value).lower()
    return v in TERMINAL | ACTIVE or any(s in v for s in TERMINAL_SUBS + ACTIVE_SUBS)


def reads_as_status_column(column: str, values: list) -> bool:
    """Does a column with these values hold a lifecycle? One that is named for it (`status`, `stage`) needs one
    value that names a state; any other needs half of them to. A single word was enough for every column, so on
    LuxExperience a stylist's city ("New York" has "new"), a GL account ("Payment processing") and a warehouse's name
    were status columns, and on theLook a product category ("Active") and a distribution centre's name (2026-10-14)."""
    states = [v for v in (values or []) if is_lifecycle_state(v)]
    if not plausible_lifecycle_states(states):
        return False
    named = sum(1 for v in states if names_a_state(v))
    return named >= 1 if _STATUS_NAME.search(str(column or "")) else named * 2 >= len(states)


def held_lifecycle_maps(maps: dict) -> dict:
    """The stored lifecycle maps whose column reads as a status column today — a map written under an older rule
    stays on disk until its run is saved again, and is not served."""
    return {t: lm for t, lm in (maps or {}).items()
            if isinstance(lm, dict) and reads_as_status_column(
                lm.get("status_column", ""),
                lm.get("states") or (lm.get("active_states") or []) + (lm.get("terminal_states") or []))}

