"""DS-18 (§3.7 second movement) — write up what the step before produced.

The user, 2026-09-19: *"the component should say synthesize data output from previous node
and context can be added in the current node"*. Their original sentence is what the wave is
measured against — *"User know required SQL and needs its synthesis to be delivered either
in Inbox or slack or practically anywhere"*.

**The gap this closes, measured the same day.** `trusted_query` publishes `rows`, `columns`
and `count`; `investigate` binds exactly one field, `question`; and a binding REPLACES a
field, because this plane refuses an expression language for the same reason it refuses a
code node. So a chain could post raw rows, or ask a question in English and let the agent
write the SQL — and could not say *"here is my data, write it up."*

**Why this is not a "call an LLM" node.** A step that hands rows to a model and posts the
prose is a slop generator pointed at Slack, and this repo has the machinery to do better
already built. All of it is pointed at this step:

* **Every number in the answer must be in the data it was handed.** `check_grounding` is
  the report pipeline's own guard; one repair attempt names the offending figures, and a
  second failure FAILS the step. An ungrounded number that reaches a channel is worse than
  a step that did not run, because nobody downstream can tell it was invented.
* **Empty input is a stated refusal, not a paragraph about nothing.** §3.11's lesson —
  `or {}` erased the difference between "failed" and "healthy empty", and six sites then
  defaulted a metric to `SUM(revenue)`. Here the two are different outcomes with different
  words.
* **The cap is published, not implied.** `mcp_call`'s precedent: a reader of `answer` must
  be able to tell a whole one from half of one, so `truncated` is a value the chain can
  guard on rather than a fact buried in the prose.
* **The answer says what it read.** `source` names the binding it synthesised, so a Slack
  message's receipt reaches back to the query a person approved.

**Falsifier (the roadmap's, for this wave):** a `synthesize` answer that states a number
absent from its input. If that can happen, the step is wrong.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aughor.automations.models import Automation, Effect, EffectOutcome

logger = logging.getLogger(__name__)

#: How many rows reach the model. Not a refusal like `trusted_query`'s fan-out cap — a
#: summary of the first N rows is a legitimate thing to want, and the step SAYS it did
#: that. The cap exists because a prompt is a budget and an unbounded one is a bill.
MAX_ROWS = 200

#: What the step does when its author said nothing. Not a silent default of the useful
#: kind — it is written down, and it is what the node's placeholder promises.
DEFAULT_CONTEXT = "Summarise what this data shows, in a few sentences."

class Summary(BaseModel):
    """The one field this step publishes.

    Typed rather than free text because `LLMProvider.complete` takes a `response_model` —
    every call on this seam is structured, and discovering that from a live run is how this
    module learned it (the first cut called `complete()` without one and failed at the
    first real tick, while a test double that accepted `**kw` stayed green). The double
    now mirrors the real signature.
    """

    answer: str = Field(description="The summary itself, in plain sentences.")


_SYS = (
    "You write a short, factual summary of data a colleague has already computed.\n"
    "\n"
    "RULES, in order of importance:\n"
    "1. Every number you write must appear in the data given to you. Never compute a new "
    "one, never round into a different number, never estimate. If something is not in the "
    "data, say it is not in the data.\n"
    "2. Answer the reader's instruction. If the data cannot answer it, say exactly that "
    "and say what the data does show.\n"
    "3. No preamble, no restating the instruction, no offers to help further. Start with "
    "the finding.\n"
    "4. Plain sentences. No markdown headings. This is read in a chat message or an inbox."
)


def _evidence(data: Any) -> str:
    """The data, as the text the model reads AND the text grounding checks against.

    One serialisation for both, deliberately: a guard that checks against a different
    rendering than the model saw is a guard that fires on the formatting rather than on
    the claim.
    """
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, indent=1, default=str, ensure_ascii=False)
    except Exception:
        return str(data)


def _is_empty(data: Any) -> bool:
    """Nothing to write up. `0` and `False` are NOT empty — a metric that reads zero is a
    finding, and treating it as absence is how a real answer becomes a shrug."""
    if data is None:
        return True
    if isinstance(data, (str, list, tuple, dict, set)):
        return len(data) == 0
    return False


def _capped(data: Any) -> tuple[Any, bool]:
    """At most `MAX_ROWS` rows, and whether anything was left out."""
    if isinstance(data, (list, tuple)) and len(data) > MAX_ROWS:
        return list(data[:MAX_ROWS]), True
    return data, False


def dispatch_synthesize(effect: "Effect", automation: "Automation") -> "EffectOutcome":
    """Write up `config['data']` under `config['context']`, grounded in what it was given."""
    from aughor.automations.models import EffectOutcome

    data = effect.config.get("data")
    context = str(effect.config.get("context") or "").strip() or DEFAULT_CONTEXT
    label = effect.alias or "synthesize"

    if _is_empty(data):
        # A stated refusal. `skipped` rather than `failed` because an empty upstream is
        # usually a quiet day, not a fault — and the message says which it was, so a
        # reader is never left to infer it from an absent message.
        return EffectOutcome(
            kind=effect.kind, target=label, status="skipped",
            message="nothing to synthesise: the bound data was empty, so no summary was "
                    "written (an empty result is not a finding about the business)")

    shown, truncated = _capped(data)
    evidence = _evidence(shown)
    source = _source_ref(effect)

    user = (f"INSTRUCTION FROM THE READER:\n{context}\n\n"
            f"DATA{f' (first {MAX_ROWS} rows of a longer result)' if truncated else ''}:\n"
            f"{evidence}")

    from aughor.agent.report_checks import check_grounding
    from aughor.llm.provider import get_provider

    try:
        provider = get_provider("narrator")
        answer = str(provider.complete(system=_SYS, user=user, response_model=Summary,
                                       temperature=0.0).answer or "").strip()
    except Exception as exc:  # noqa: BLE001 — a model outage is a step failure, not a crash
        logger.warning("synthesize: provider failed: %s", exc)
        return EffectOutcome(kind=effect.kind, target=label, status="failed",
                             message=f"could not write the summary: {exc}")

    violations = check_grounding(answer, evidence)
    if violations:
        # ONE repair, naming the figures. Not a loop: `sql.writer:fix` is measured at 6.5
        # repairs per query and is recorded as a cost defect, so this wave does not open a
        # second one. Either the model can ground itself when told which numbers are
        # unsupported, or the step fails honestly.
        told = "; ".join(str(v) for v in violations)
        try:
            answer = str(provider.complete(
                system=_SYS,
                user=f"{user}\n\nYOUR PREVIOUS ANSWER WAS REJECTED:\n{told}\n\n"
                     f"Rewrite it using only numbers that appear in the data above.",
                response_model=Summary, temperature=0.0).answer or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("synthesize: repair failed: %s", exc)
            return EffectOutcome(kind=effect.kind, target=label, status="failed",
                                 message=f"could not write the summary: {exc}")
        violations = check_grounding(answer, evidence)

    if violations:
        # FAILED, and the answer is discarded rather than published with a caveat. A
        # caveat travels badly: this value is bound into a Slack message or an inbox note
        # where the surrounding prose is the author's, and nothing downstream would carry
        # the warning. The roadmap's falsifier for this wave is exactly this case.
        return EffectOutcome(
            kind=effect.kind, target=label, status="failed",
            message=("the summary stated numbers that are not in the data it was given, "
                     "twice, so it was not published: " + "; ".join(str(v) for v in violations)[:400]))

    if not answer:
        return EffectOutcome(kind=effect.kind, target=label, status="failed",
                             message="the model returned an empty summary")

    return EffectOutcome(
        kind=effect.kind, target=label, status="executed",
        message=f"summarised {source or 'the bound data'}"
                + (f" (first {MAX_ROWS} rows)" if truncated else ""),
        data={"answer": answer, "truncated": truncated, "source": source})


def _source_ref(effect: "Effect") -> str:
    """What this step read, by name — the provenance that travels with the answer.

    By dispatch time `config["data"]` holds the VALUE and the `{"$from": …}` that produced
    it is gone, so the engine carries the reference on the bound config — `AWAIT_KEY`'s
    precedent. Absent (a literal `data`, or a dry run), the answer simply does not claim a
    source, which is honest rather than empty.
    """
    from aughor.automations.engine import SYNTHESIS_SOURCE_KEY
    return str(effect.config.get(SYNTHESIS_SOURCE_KEY) or "")
