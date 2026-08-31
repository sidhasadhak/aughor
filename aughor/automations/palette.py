"""DS-1 · the palette — what a person can put on a Design canvas, **here**.

The canvas has always been able to add a step; what it could not do was tell you what the
steps ARE. The kind list lived in the client as a `<select>`, its descriptions were written
and never rendered, and every deployment was offered every kind whether or not the object
that kind REFERENCES existed on it — so "Post to Slack" looked identical on an install with
three bots and on one with none, and the difference surfaced at save, or at 09:00.

This module is the other half: one server-owned table of what may be placed, and one
honest answer per entry about whether it can be used on THIS deployment.

**The availability rule, stated once.** A kind whose required config key NAMES another
object is available only when at least one such object exists here. That is the whole rule
— `slack_post` needs a bot, `notify` a trigger, `brief` a subscription, `metric` a monitor
— and it falls straight out of `_EFFECT_REQUIRED` / `_CONDITION_REQUIRED`, so it cannot
drift from what the save actually demands. A kind whose required key is a VALUE a person
types (`schedule`'s cron, `investigate`'s question, the two table triggers) has nothing to
be missing and is always ready.

Two deliberate exclusions, both measured rather than assumed:

- **The declared-action kind is always ready.** Its objects are declared in a connection's
  ontology overrides, and reading them means building an ontology graph — a cost this repo
  already knows it pays per open, and one a palette render must not add. The flag route is
  worse than useless: that flag was HARDWIRED on 2026-08-02 and DELETED, so `flag_enabled`
  answers False for an unregistered name and every deployment would be told its declared
  actions are off. The rail's action picker already reads the ontology route when a reader
  actually needs the list.
- **No LLM readiness on `investigate`.** Whether a model is bound is a property of the
  deployment, not of this entry, and `/health` already answers it. A palette that dimmed
  every agent-shaped row when a key was missing would be reporting one fact in nine places.

Nothing here is served that nothing reads — no badge fields, no structured "door" key —
because a field with no consumer is the failure this codebase has a guard test for. The
reason sentence names the door in words; a structured destination lands when the surfaces
it would point at exist (DS-11).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

READY = "ready"
NEEDS_SETUP = "needs_setup"


@dataclass(frozen=True)
class PaletteEntry:
    """One placeable thing. `priority` orders a group; the client sorts by it, then by
    name, so a curated order is the server's to state rather than the client's to guess."""

    kind: str
    group: str  # "trigger" | "action"
    label: str
    description: str
    icon: str
    priority: int


# The labels and descriptions are the ones already shipping in the client's kind pickers,
# moved to the side that owns the vocabulary. The client keeps its own copy for the
# synchronous `<select>`; `tests/unit/test_automation_palette_labels.py` asserts the two
# spell the same words, the way the required-keys mirror is kept honest.
#
# `monitor` and `agent_alert` are absent on purpose: the model's own docstring says they
# are adopted objects, "not authored by hand". A palette that offered them would invite a
# reader to hand-write a duplicate of an object they already have.
TRIGGERS: tuple[PaletteEntry, ...] = (
    PaletteEntry("schedule", "trigger", "Schedule",
                 "Fire on a cron cadence", "clock", 10),
    PaletteEntry("metric", "trigger", "Metric",
                 "Delegate to an existing monitor by id", "gauge", 20),
    PaletteEntry("source_change", "trigger", "Source change",
                 "A table's rows changed (add / delete / backfill)", "table", 30),
    PaletteEntry("entity_appears", "trigger", "New entity",
                 "A new key appeared in a table", "key", 40),
)

ACTIONS: tuple[PaletteEntry, ...] = (
    PaletteEntry("investigate", "action", "Investigate",
                 "Run the Agent", "search", 10),
    PaletteEntry("slack_post", "action", "Post to Slack",
                 "Post into a channel as one of your bots — mentionable, and repliable "
                 "in thread", "send", 20),
    PaletteEntry("notify", "action", "Notify",
                 "Send through a Notifications trigger", "bell", 30),
    PaletteEntry("brief", "action", "Deliver briefing",
                 "Deliver a briefing subscription", "brief", 40),
    PaletteEntry("kinetic_action", "action", "Declared action",
                 "Run a declared, governed action — through its approval gate", "bolt", 50),
)

ENTRIES: tuple[PaletteEntry, ...] = TRIGGERS + ACTIONS


@dataclass(frozen=True)
class _Prereq:
    """The object a kind names, how to count them here, and what to say when there are none."""

    count: Callable[[], int]
    reason: str


def _prereqs(conn_id: Optional[str]) -> dict[str, _Prereq]:
    """Imports live inside the closures: a palette render must not drag four stores into
    memory to answer about kinds the reader never opens, and one unimportable subsystem
    must not take the whole surface down."""

    def bots() -> int:
        from aughor.slackbots.store import list_bots
        # A disabled bot cannot post, so it cannot count as the prerequisite being met.
        return sum(1 for b in list_bots() if getattr(b, "enabled", True))

    def triggers() -> int:
        from aughor.notifications.store import list_triggers
        return len(list_triggers())

    def subscriptions() -> int:
        from aughor.briefing.store import list_subscriptions
        return len(list_subscriptions(conn_id))

    def monitors() -> int:
        from aughor.monitors.store import list_monitors
        return len(list_monitors(conn_id))

    return {
        # The Slack sentence is the one the rail already shows, word for word: two
        # surfaces explaining the same absence differently is how a reader learns the
        # product has two opinions about it.
        "slack_post": _Prereq(bots, "No Slack bots configured — create one first, then "
                                    "this step can post as it."),
        "notify": _Prereq(triggers, "No notification triggers configured — create one "
                                    "first, then this step can send through it."),
        "brief": _Prereq(subscriptions, "No briefing subscriptions on this connection — "
                                        "create one first, then this step can deliver it."),
        "metric": _Prereq(monitors, "No monitors on this connection — create one first, "
                                    "then this trigger can delegate to it."),
    }


def entries(conn_id: Optional[str] = None) -> list[dict]:
    """Every placeable entry, with the ports it carries and whether it works here.

    A probe that RAISES leaves its entry ready. An unreachable store is our problem, not
    the reader's: dimming a row that would have worked teaches a lie the reader cannot
    check, while leaving it lit costs at most the save-time error they get today. Only a
    successful count of zero — a measured absence — dims anything.
    """
    from aughor.automations.dataflow import BINDABLE_FIELDS, PUBLISHED_KEYS

    prereqs = _prereqs(conn_id)
    out: list[dict] = []
    for entry in ENTRIES:
        availability, reason = READY, ""
        prereq = prereqs.get(entry.kind)
        if prereq is not None:
            try:
                if prereq.count() == 0:
                    availability, reason = NEEDS_SETUP, prereq.reason
            except Exception as exc:  # noqa: BLE001 — see the docstring; ready is the safe read
                from aughor.kernel.errors import tolerate
                tolerate(exc, f"palette: prerequisite probe failed for {entry.kind}",
                         counter="palette.probe")

        # Ports come from the SAME tables `validate_chain` refuses against, so a palette
        # row cannot advertise a port the save would reject. `publishes: null` is the open
        # set, exactly as `/automations/vocabulary` spells it.
        published = PUBLISHED_KEYS.get(entry.kind, ())
        out.append({
            "kind": entry.kind,
            "group": entry.group,
            "label": entry.label,
            "description": entry.description,
            "icon": entry.icon,
            "priority": entry.priority,
            "publishes": list(published) if published is not None else None,
            "bindable": list(BINDABLE_FIELDS.get(entry.kind, ())),
            "availability": availability,
            "reason": reason,
        })
    return out
