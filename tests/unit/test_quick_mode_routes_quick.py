"""The composer's Quick/Agent toggle must work in BOTH directions.

Reported 2026-09-18: "the Quick/Agent toggle is not working". It is not a UI fault —
the button sets its state, renders it, and transmits it. The value dies one layer down.

`ChatPanel` sends `mode: "ask"` for Quick and `mode: "investigate"` for Agent. But
`AskRequest.mode` is `Optional[Literal["investigate", "explore"]]` (R13: a named
starter's declared path), so "ask" has no wire representation at all. `ask_request_from`
coerced it to None, and the request arriving at `decide_route` was byte-identical to one
where the user had chosen nothing: mode_override=None, depth="auto", deep=False.

`decide_ask_route` then auto-classified. Its `causal` branch sends anything cause-shaped
to the full deep investigation:

    if causal or verdict.tier == "complex":
        return _route("deep", "investigate", "this asks for a cause or a multi-step breakdown")

So Agent pinned deep (because "investigate" IS in the accepted tuple) while Quick was
discarded. What the user then got depended entirely on what the classifier happened to
think: quick for a lookup, deep for anything cause-shaped — on precisely the questions
someone picks Quick to make cheap. One reliable direction out of two is why it reads as
"sometimes works".

Quick is a DEPTH choice, not a research path, so it maps onto the `depth="quick"` knob
`decide_route` has always honoured.
"""
import pytest
from ag_ui.core import RunAgentInput

from aughor.agent.ask_router import decide_ask_route as decide_route
from aughor.routers.agui import ask_request_from


def _req(**props):
    return ask_request_from(RunAgentInput(
        thread_id="t", run_id="r", state={}, messages=[], tools=[], context=[],
        forwarded_props={"connection_id": "8233e4fd", **props}))


class TestTheWireCarriesQuick:
    def test_quick_becomes_the_quick_depth(self):
        assert _req(mode="ask").depth == "quick"

    def test_agent_is_unchanged(self):
        r = _req(mode="investigate")
        assert r.mode == "investigate" and r.depth == "auto"

    def test_no_toggle_still_auto_routes(self):
        assert _req().depth == "auto"

    def test_an_explicit_depth_wins(self):
        """Quick only fills the `auto` default; a caller that named a depth keeps it —
        the auto+transparency re-run ("investigate this deeper") posts mode=ask with
        depth=deep, and must not be demoted back to quick."""
        assert _req(mode="ask", depth="deep").depth == "deep"

    def test_a_starter_route_survives(self):
        r = _req(mode="explore")
        assert r.mode == "explore" and r.depth == "auto"


class TestTheRouterHonoursIt:
    #: A cause-shaped question. `assess_complexity` scores its `causal` signal
    #: deterministically (no classifier call), so the auto path pins it deep — and with
    #: the toggle discarded, that override is what a user pressing Quick actually got.
    #:
    #: NOTE the reported question, "Where are we losing money since last 6 months?",
    #: is NOT one of these: the auto path scores it `simple` and already routes it
    #: quick. The dropped toggle bit there only in the other direction (Agent, which
    #: works). The defect is that an explicit choice was discarded at all; these are
    #: the questions where discarding it changed the outcome — and the cost.
    Q = "Why did revenue fall last month?"

    def test_the_causal_question_goes_deep_on_auto(self):
        """Pins the mechanism: with the toggle dropped, the request is byte-identical
        to one where nothing was chosen, and this question routes deep."""
        r = decide_route(self.Q, depth_override="auto", has_deep=True)
        assert r.depth == "deep" and r.mode == "investigate"
        assert not r.used_classifier, "must be deterministic — no model call in this test"

    def test_quick_now_reaches_the_router_and_wins(self):
        r = decide_route(self.Q, depth_override=_req(mode="ask").depth, has_deep=True)
        assert r.depth == "quick", "Quick must beat the causal classifier"
        assert r.mode == "direct" and r.forced == "quick"

    def test_agent_still_investigates(self):
        req = _req(mode="investigate")
        r = decide_route(self.Q, depth_override=req.depth, mode_override=req.mode, has_deep=True)
        assert r.depth == "deep" and r.mode == "investigate"

    @pytest.mark.parametrize("q", [
        "Why did revenue fall last month?",
        "Why did gross margin drop in Q3?",
        "What caused the decline in orders?",
        "Why are we losing money since last 6 months?",
    ])
    def test_quick_holds_across_causal_phrasings(self, q):
        """The drop was invisible on simple lookups (they route quick anyway). It showed
        only on cause-shaped questions, so that is where the fix has to hold."""
        assert decide_route(q, depth_override="auto", has_deep=True).depth == "deep"
        assert decide_route(q, depth_override=_req(mode="ask").depth,
                            has_deep=True).depth == "quick"
