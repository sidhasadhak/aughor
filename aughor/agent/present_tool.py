"""AV-0/AV-2 (§3.11, third movement) — the answer vocabulary, and the one tool that emits it.

The reading the movement takes from Adaptive Cards: not a widget library, a CLOSED,
versioned vocabulary of parts an agent may emit as its answer, plus a fixed set of
typed actions the host executes. The agent composes an interface; the host guarantees
what any click can do. So this module is two things and refuses to be a third:

* **The schema** (:func:`validate_parts`) — part kinds v1, each with bounded fields,
  refused WHOLE with sentences when anything fails. All-or-nothing on purpose: a half
  -rendered answer is worse than prose, and the sentences go back to the MODEL, which
  can fix the part or say it in words — the propose-chain pattern applied to
  presentation.
* **The tool** (:func:`present_tools`) — offered only on a STREAMING turn (``emit``
  bound; a sync caller has nowhere to render), it validates and emits ONE
  ``answer_parts`` frame. Nothing stages, nothing executes, nothing is stored:
  presentation only.

What it must never become: an open UI language. An action here names an EXISTING
door — ``follow_up`` rides the same ask path the follow-up chips already ride, and
``proposal_ref`` renders the real approval card whose Accept goes through the one
inbox. A button the model could define would be a custody bypass wearing a label.
"""
from __future__ import annotations

import logging

from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)

#: The vocabulary's version, carried on every frame so a client can refuse a future
#: shape it does not know instead of guessing at it.
VOCABULARY_VERSION = 1

#: The closed set of part kinds. Growing it is a schema change: a new kind lands here,
#: in the web's organ (`AnswerParts.tsx`), and in both frame declarations — the tests
#: on each side hold the ends together.
PART_KINDS = frozenset({"fact_set", "status", "progress", "section",
                        "action_set", "proposal_ref"})

#: The one semantic scale, shared by `status` parts and a fact's optional status —
#: the web maps these to the established chip hues, so color meaning cannot fork.
TONES = frozenset({"good", "warn", "bad", "info", "neutral"})

#: The closed action set. An action is a DOOR the platform already has, never a
#: behavior the model defines.
ACTION_KINDS = frozenset({"follow_up"})

_MAX_PARTS = 12
_MAX_FACTS = 16
_MAX_ACTIONS = 4
_MAX_LABEL = 120
_MAX_VALUE = 400
_MAX_BODY = 4000


def _text(v, cap: int) -> str:
    return str(v if v is not None else "").strip()[:cap]


def _validate_part(i: int, part: dict) -> tuple[dict, list[str]]:
    """One part, checked and rebuilt field by field — only known fields survive, so a
    payload cannot smuggle anything the vocabulary does not name."""
    problems: list[str] = []
    kind = str(part.get("kind") or "")
    if kind not in PART_KINDS:
        return {}, [f"part {i}: unknown kind {kind!r} — one of: {', '.join(sorted(PART_KINDS))}"]
    clean: dict = {"kind": kind}

    if kind == "fact_set":
        facts = part.get("facts")
        if not isinstance(facts, list) or not facts:
            problems.append(f"part {i}: fact_set needs a non-empty facts list")
        else:
            rows = []
            for j, f in enumerate(facts[:_MAX_FACTS], start=1):
                f = f if isinstance(f, dict) else {}
                label = _text(f.get("label"), _MAX_LABEL)
                value = _text(f.get("value"), _MAX_VALUE)
                if not label or not value:
                    problems.append(f"part {i}: fact {j} needs both label and value")
                    continue
                row = {"label": label, "value": value}
                tone = str(f.get("status") or "")
                if tone:
                    if tone not in TONES:
                        problems.append(f"part {i}: fact {j} status {tone!r} — one of: {', '.join(sorted(TONES))}")
                    else:
                        row["status"] = tone
                rows.append(row)
            clean["facts"] = rows
        title = _text(part.get("title"), _MAX_LABEL)
        if title:
            clean["title"] = title

    elif kind == "status":
        clean["label"] = _text(part.get("label"), _MAX_LABEL)
        tone = str(part.get("tone") or "")
        if not clean["label"]:
            problems.append(f"part {i}: status needs a label")
        if tone not in TONES:
            problems.append(f"part {i}: status tone {tone!r} — one of: {', '.join(sorted(TONES))}")
        clean["tone"] = tone

    elif kind == "progress":
        # FL-5's law, held at the schema: a progress bar exists only with a REAL
        # denominator. A fraction with no total is a feeling, not progress.
        clean["label"] = _text(part.get("label"), _MAX_LABEL)
        try:
            done, total = int(part.get("done")), int(part.get("total"))
        except (TypeError, ValueError):
            done, total = -1, -1
        if not clean["label"]:
            problems.append(f"part {i}: progress needs a label")
        if total <= 0 or done < 0 or done > total:
            problems.append(f"part {i}: progress needs integers 0 <= done <= total with total > 0")
        else:
            clean["done"], clean["total"] = done, total

    elif kind == "section":
        clean["title"] = _text(part.get("title"), _MAX_LABEL)
        clean["body"] = _text(part.get("body"), _MAX_BODY)
        clean["collapsed"] = bool(part.get("collapsed"))
        if not clean["title"] or not clean["body"]:
            problems.append(f"part {i}: section needs a title and a body")

    elif kind == "action_set":
        actions = part.get("actions")
        if not isinstance(actions, list) or not actions:
            problems.append(f"part {i}: action_set needs a non-empty actions list")
        else:
            if len(actions) > _MAX_ACTIONS:
                problems.append(f"part {i}: at most {_MAX_ACTIONS} actions — fewer, chosen well")
            rows = []
            for j, a in enumerate(actions[:_MAX_ACTIONS], start=1):
                a = a if isinstance(a, dict) else {}
                door = str(a.get("action") or "")
                if door not in ACTION_KINDS:
                    problems.append(f"part {i}: action {j} names no door — one of: {', '.join(sorted(ACTION_KINDS))}")
                    continue
                label = _text(a.get("label"), _MAX_LABEL)
                question = _text(a.get("question"), _MAX_VALUE)
                if not label or not question:
                    problems.append(f"part {i}: action {j} needs a label and the question it asks")
                    continue
                rows.append({"action": door, "label": label, "question": question})
            clean["actions"] = rows

    elif kind == "proposal_ref":
        pid = _text(part.get("proposal_id"), _MAX_LABEL)
        if not pid:
            problems.append(f"part {i}: proposal_ref needs the proposal_id a staging tool returned")
        clean["proposal_id"] = pid

    return clean, problems


def validate_parts(parts) -> tuple[list[dict], list[str]]:
    """The whole list, all-or-nothing: ``(clean parts, [])`` or ``([], sentences)``."""
    if not isinstance(parts, list) or not parts:
        return [], ["parts must be a non-empty list"]
    if len(parts) > _MAX_PARTS:
        return [], [f"at most {_MAX_PARTS} parts — an answer, not a page"]
    clean: list[dict] = []
    problems: list[str] = []
    for i, part in enumerate(parts, start=1):
        c, p = _validate_part(i, part if isinstance(part, dict) else {})
        problems.extend(p)
        clean.append(c)
    return ([], problems) if problems else (clean, [])


def present(args: dict, *, emit) -> dict:
    """Validate the parts and emit them as the turn's structured half."""
    clean, problems = validate_parts(args.get("parts"))
    if problems:
        return {"presented": False, "problems": problems,
                "summary": ("Nothing rendered — fix these and call again, or say it "
                            "in prose: " + "; ".join(problems))}
    if emit is None:
        # Constructed without a channel (a test, a sync caller that ignored the
        # roster rule) — refuse honestly rather than render into silence.
        return {"presented": False,
                "summary": "This turn has no rendering channel — say it in prose."}
    try:
        emit("answer_parts", {"version": VOCABULARY_VERSION, "parts": clean})
    except Exception:
        logger.debug("answer_parts frame dropped", exc_info=True)
        return {"presented": False,
                "summary": "The rendering channel failed — say it in prose."}
    kinds = ", ".join(p["kind"] for p in clean)
    return {"presented": True, "count": len(clean),
            "summary": (f"Rendered {len(clean)} part(s) ({kinds}) into the answer. "
                        f"They are already on screen — do NOT repeat their contents "
                        f"in prose; write only what the parts do not carry.")}


_PRESENT_PARAMS = {
    "type": "object",
    "properties": {
        "parts": {
            "type": "array",
            "description": (
                "The answer's structured half, in order. Each part is one of: "
                "{kind:'fact_set', title?, facts:[{label, value, status?('good'|'warn'|'bad'|'info'|'neutral')}]} — "
                "labeled facts a reader scans instead of parsing prose; "
                "{kind:'status', label, tone} — one state, said as a badge; "
                "{kind:'progress', label, done, total} — only with a REAL total; "
                "{kind:'section', title, body(markdown), collapsed?} — detail folded away; "
                "{kind:'action_set', actions:[{action:'follow_up', label, question}]} — "
                "next questions as one-click doors (at most 4); "
                "{kind:'proposal_ref', proposal_id} — a staged proposal rendered as its live "
                "approval card, with Accept and Reject in place."
            ),
            "items": {"type": "object"},
        },
    },
    "required": ["parts"],
}


def present_tools(*, emit) -> list[ToolSpec]:
    """The presentation roster — ONE tool, and only when the turn can render.

    A sync caller (MCP, a bare script, an eval) gets an empty list rather than a tool
    that always refuses: a tool the model can see is a tool it will spend a turn on.
    """
    if emit is None:
        return []
    return [ToolSpec(
        name="present",
        description=(
            "Render the STRUCTURED half of your answer as typed parts — labeled fact "
            "rows, status badges, a progress bar (only with a real total), collapsible "
            "detail sections, one-click follow-up questions, or a staged proposal's "
            "live approval card. Use it whenever the answer is facts, states or next "
            "steps a reader would otherwise have to parse out of prose; then write "
            "only the prose the parts do not carry. Rendering only — nothing is "
            "stored, staged or executed, and a refusal lists exactly what to fix."
        ),
        parameters=_PRESENT_PARAMS,
        run=lambda a: present(a, emit=emit),
    )]
