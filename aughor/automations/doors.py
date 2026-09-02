"""DS-17 · Deploy is a menu of doors — what THIS deployment can open for one chain.

Every plane named here already existed. A chain could run on a schedule (Wave A2), be
posted into Slack as a bot (RC-5), and be called as an MCP tool (DS-14) — but each was
armed on a different screen, in a different vocabulary, and nowhere did a person see the
list. So "is this thing live?" had no answer short of visiting three surfaces and knowing
which flags to read on each. Deploying an agent has always meant binding doors; this
module says it on the surface where the behaviour lives.

**The contract is the palette's, with one axis added.** The palette answers *can this be
placed here* — `ready | needs_setup | unavailable`. A door also has a POSITION, so `ready`
splits: `open` means traffic comes through right now, `closed` means everything is in
place and one gesture opens it. That distinction is the entire product here. A reader
looking at a finished chain wants to know which of the two they are looking at, and the
palette's three states cannot say.

**The alt-door rule, honoured per door rather than recited.** §3.4's rule is that a
surface must offer the door THIS deployment can open, not the canonical one. Both places
it bites here were bought by earlier waves:

- The **clock** is not always a thread. On serverless the in-process heartbeat is off by
  design and an external cron drives `/cron/tick`; a door that looked for the thread would
  tell a Vercel deployment its schedules are dead while they fire every minute. So it asks
  `scheduler.clock()`, which knows all three answers including the one nothing else reports
  — that no clock is running at all.
- **Slack is not OAuth here.** Slack refuses `http://localhost` callbacks, so a fresh clone
  pointed at the OAuth door is pointed at a door it cannot open (the RC-5 lesson, bought
  live with the user). The sentence names the manifest path — Socket Mode, an OUTBOUND
  socket, no tunnel — which is what `slack_post` actually uses.

**Nothing is opened by reading.** Every state here is computed from stored records and
measured absences; the verbs live on routes the surfaces already had (`/enabled`, the
webhook token, `exposed_as_tool`). A module that could arm a chain as a side effect of
rendering a menu would be exactly the mistake DS-15's draft refuses — deciding for the
human the thing they came here to decide.

**A failed probe leaves a door where it was.** The palette's asymmetry, and for its
reason: an unreachable store is our problem, and a door greyed out by our outage teaches a
reader something false that they cannot check. Only a measured absence closes anything.
"""
from __future__ import annotations

from dataclasses import dataclass

from aughor.automations.models import Automation

#: Traffic comes through right now.
OPEN = "open"
#: Everything this door needs is in place; one gesture opens it.
CLOSED = "closed"
#: Something is missing that the reader can fix, and `reason` names the fix.
NEEDS_SETUP = "needs_setup"
#: This deployment cannot open it, and `reason` says why.
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Door:
    """One way into a chain from outside it."""

    kind: str
    label: str
    #: What opening this door DOES — present tense, from the caller's side.
    description: str
    icon: str
    priority: int
    state: str
    #: Why it is in that state. Names the fix when there is one; empty when open.
    reason: str
    #: The fact behind the state — the cron, the issue date, the tool name. What a reader
    #: checks the sentence against.
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "label": self.label, "description": self.description,
            "icon": self.icon, "priority": self.priority,
            "state": self.state, "reason": self.reason, "detail": self.detail,
        }


def doors(automation: Automation) -> list[dict]:
    """Every door for this chain, in menu order.

    One automation, not a connection: a door is a property of the chain (does it have a
    schedule trigger, is it exposed) crossed with a property of the deployment (is a clock
    running, is there a bot). Both halves are needed for any of these sentences to be true.
    """
    out = [
        _schedule_door(automation),
        _webhook_door(automation),
        _slack_door(automation),
        _mcp_door(automation),
    ]
    return [d.as_dict() for d in sorted(out, key=lambda d: (d.priority, d.label))]


# ── schedule ─────────────────────────────────────────────────────────────────────

def _schedule_door(a: Automation) -> Door:
    crons = [c.cron for c in (a.conditions or []) if c.kind == "schedule" and c.cron]
    base = dict(kind="schedule", label="Schedule", icon="clock", priority=10,
                description="Runs itself on a cron cadence.")
    if not crons:
        return Door(**base, state=NEEDS_SETUP, reason=(
            "This chain has no Schedule trigger — add one on the canvas, then it can run "
            "on a clock."))

    detail = " · ".join(crons)
    state, clock_detail = _clock()
    if state == "stopped":
        # Not `closed`: enabling the chain would change nothing while nothing ticks. The
        # reason names the two doors that DO work — and both are the operator's, not this
        # screen's, which is why this state offers no verb.
        return Door(**base, state=UNAVAILABLE, detail=detail, reason=(
            "No clock is running here, so nothing evaluates a schedule. Restart the API "
            "to start the heartbeat, or drive it from outside with GET /cron/tick."))
    if not a.enabled:
        return Door(**base, state=CLOSED, detail=detail, reason=(
            f"The chain is switched off. Enable it and it runs on {detail} ({clock_detail})."))
    return Door(**base, state=OPEN, detail=detail,
                reason=f"Running on {detail} — {clock_detail}.")


def _clock() -> tuple[str, str]:
    """`scheduler.clock()`, or a stopped reading we do not pretend to know better than."""
    try:
        from aughor.automations.scheduler import clock
        return clock()
    except Exception as exc:  # noqa: BLE001 — see the module docstring's last paragraph
        from aughor.kernel.errors import tolerate
        tolerate(exc, "doors: could not read the clock state", counter="doors.clock")
        # Deliberately NOT "stopped": we failed to look, which is not the same as looking
        # and finding nothing. Reporting the heartbeat keeps the door where it was.
        return "heartbeat", "clock state unavailable"


# ── webhook ──────────────────────────────────────────────────────────────────────

def _webhook_door(a: Automation) -> Door:
    base = dict(kind="webhook", label="Webhook", icon="link", priority=20,
                description="Runs when something outside calls its URL.")
    if not any(c.kind == "webhook" for c in (a.conditions or [])):
        return Door(**base, state=NEEDS_SETUP, reason=(
            "This chain has no Webhook trigger — add one on the canvas, then it can be "
            "called from outside."))

    issued = _webhook_issued_at(a.id)
    if not issued:
        return Door(**base, state=CLOSED, reason=(
            "No URL has been issued. Issue one and anything holding it can run this "
            "chain — the token is shown once and never again."))
    if not a.enabled:
        # The URL still resolves; the lifecycle gate refuses the run. Saying "open" here
        # would promise a caller something the engine then declines, and saying nothing
        # about the URL would suggest revoking it is unnecessary. Both facts, in order.
        return Door(**base, state=CLOSED, detail=f"issued {issued}", reason=(
            "The chain is switched off, so a call is accepted and does nothing. Enable it "
            "to let the URL through, or revoke the URL if it should not exist."))
    return Door(**base, state=OPEN, detail=f"issued {issued}",
                reason="Anything holding the token can run this chain.")


def _webhook_issued_at(automation_id: str) -> str:
    try:
        from aughor.automations.webhooks import webhook_issued_at
        return webhook_issued_at(automation_id)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "doors: could not read the webhook token", counter="doors.webhook")
        return ""


# ── Slack ────────────────────────────────────────────────────────────────────────

#: The door a self-hosted install can actually open. NOT OAuth: Slack rejects
#: `http://localhost` callbacks (measured off their docs in RC-5 — Google and Microsoft
#: both accept it, Slack is the one that does not), so a laptop has no callback to give.
#: Socket Mode is an OUTBOUND socket — manifest, three tokens, no tunnel — and it is what
#: `slack_post` already uses.
_SLACK_ALT_DOOR = ("Add one under Slack bots — the app manifest path needs no public URL "
                   "(Socket Mode connects outward).")


def _slack_door(a: Automation) -> Door:
    base = dict(kind="slack", label="Slack", icon="chat", priority=30,
                description="Posts into Slack as a bot people can reply to.")
    posts = [e for e in (a.effects or []) if e.kind == "slack_post"]
    bots = _slack_bots()

    if bots == 0:
        # Measured absence first: with no bot, "add a step" would be advice a reader cannot
        # take — the step's own picker would be empty. Name the door that unblocks both.
        return Door(**base, state=NEEDS_SETUP,
                    reason=f"No Slack bot on this deployment. {_SLACK_ALT_DOOR}")
    if not posts:
        return Door(**base, state=NEEDS_SETUP, reason=(
            "This chain posts nowhere in Slack — add a Post to Slack step on the canvas, "
            "and its results arrive as a bot people can reply to."))

    channels = " · ".join(sorted({str(e.config.get("channel", "")) for e in posts
                                  if e.config.get("channel")}))
    detail = channels or f"{len(posts)} step(s)"
    if not a.enabled:
        return Door(**base, state=CLOSED, detail=detail, reason=(
            f"The chain is switched off, so nothing is posted. Enable it and its results "
            f"arrive in {detail}."))
    return Door(**base, state=OPEN, detail=detail,
                reason=f"Results arrive in {detail} as the bot.")


def _slack_bots() -> int:
    """How many bots could actually post. A DISABLED bot is not a door, and counting rows
    would have said otherwise — the same distinction the palette draws for a revoked grant."""
    try:
        from aughor.slackbots.store import list_bots
        return len(list_bots(include_disabled=False))
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "doors: could not count Slack bots", counter="doors.slack")
        return 1          # a failed probe leaves the door where it was — see the docstring


# ── MCP tool ─────────────────────────────────────────────────────────────────────

def _mcp_door(a: Automation) -> Door:
    base = dict(kind="mcp_tool", label="MCP tool", icon="plug", priority=40,
                description="Callable by an outside agent as a tool.")
    name, clash = _tool_name(a)
    if clash:
        return Door(**base, state=NEEDS_SETUP, detail=name, reason=clash)
    if not name:
        # The MCP module would not import. That is this deployment's answer, not a chain
        # property, and it is the one case here that is genuinely `unavailable`.
        return Door(**base, state=UNAVAILABLE, reason=(
            "The MCP server module is not available on this deployment, so no chain can "
            "be offered as a tool."))

    if a.exposed_as_tool and a.enabled:
        return Door(**base, state=OPEN, detail=name, reason=(
            f"Offered as '{name}'. A client that was already connected sees it after "
            f"reconnecting — the tool list is read once at MCP server start."))
    if a.exposed_as_tool and not a.enabled:
        # DS-14's law, stated where it bites rather than only in the model's docstring.
        return Door(**base, state=CLOSED, detail=name, reason=(
            "Marked as a tool, but the chain is switched off — and a chain someone "
            "switched off must not stay callable from outside. Enable it to offer it."))
    return Door(**base, state=CLOSED, detail=name, reason=(
        f"Not offered. Expose it and an outside agent can call it as '{name}'; the run "
        f"lands in the same engine, with the same governance, as Run now."))


def _tool_name(a: Automation) -> tuple[str, str]:
    """This chain's tool name, and the refusal it would meet — ``("", "")`` if unreadable.

    Both collisions DS-14 refuses are checked BEFORE the door is opened rather than after,
    which is the difference between a menu and a report: a name that will be skipped at
    registration is a door that would read `open` and do nothing.
    """
    try:
        from aughor.mcp.server import automation_tool_name, mcp
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "doors: could not resolve the MCP tool name", counter="doors.mcp")
        return "", ""

    name = automation_tool_name(a.name)
    try:
        static = set(getattr(mcp._tool_manager, "_tools", {}) or {})
    except Exception:                       # a FastMCP internal we do not control
        static = set()
    if name in static:
        return name, (f"'{name}' is already one of this server's own tools, so exposing "
                      f"this chain would be skipped rather than shadow it. Rename the "
                      f"chain to offer it.")

    try:
        from aughor.automations.store import list_automations
        rivals = [x for x in list_automations(conn_id=a.conn_id or None)
                  if x.id != a.id and getattr(x, "exposed_as_tool", False) and x.enabled
                  and automation_tool_name(x.name) == name]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "doors: could not check for a tool-name clash", counter="doors.mcp")
        return name, ""
    if rivals:
        return name, (f"'{rivals[0].name}' already answers to '{name}'. Two tools a client "
                      f"cannot tell apart is worse than one missing tool — rename one of "
                      f"them to offer this chain.")
    return name, ""


def summary(door_rows: list[dict]) -> str:
    """One line for a surface with no room for four — "Live on 2 doors" / "Not live".

    A count of what is OPEN, deliberately: `needs_setup` and `closed` are both "not live",
    and a header that totalled them would tell a reader their chain was half-deployed when
    nothing was reachable at all.
    """
    n = sum(1 for d in door_rows if d.get("state") == OPEN)
    if n == 0:
        return "Not live"
    return f"Live on {n} door{'s' if n != 1 else ''}"
