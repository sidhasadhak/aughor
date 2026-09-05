"""DS-15 — conversation authors the canvas, and the canvas still refuses a bad chain.

The wave's shape is the one every governed write here already has: the model DRAFTS, the
same validators a save runs refuse a draft that could not be saved, a dry run shows what
it would do, and a human arms it. A grant is permission to propose.

Every test injects its provider. This repo has already paid once for a suite that reached
a live model, so the rule is structural rather than remembered: `propose_chain` takes the
provider as an argument and the default is only resolved when nobody passed one.

What is pinned:

* **The prompt carries THIS deployment's truth** — the palette's own verdict on what is
  placeable and why, and the real ids. A model never shown a bot it cannot post as cannot
  propose posting as one.
* **A draft that would not save is not drawn.** Constructing the `Automation` runs every
  model validator and `validate_chain`; the refusal comes back with the reason.
* **It fails CLOSED.** `actions/propose.py` fails open to `[]` because it garnishes an
  answer somebody already asked for; here the proposal IS the request, so a silent empty
  would be answering "nothing" to "build me a chain".
* **Nothing is saved.** The one thing this module must never learn to do.
"""
from __future__ import annotations

import pytest

from aughor.automations.propose import ProposedChain, propose_chain
from aughor.automations.store import list_automations

CONN = "ds15"


class _Provider:
    """A stand-in for the LLM. Records the prompt, returns a scripted draft."""

    def __init__(self, draft=None, boom: bool = False):
        self.draft, self.boom = draft, boom
        self.system = ""
        self.user = ""

    def complete(self, *, system, user, response_model, temperature=0.0):
        self.system, self.user = system, user
        if self.boom:
            raise RuntimeError("model unreachable")
        return self.draft


def _chain(**kw) -> ProposedChain:
    base = dict(
        name="Monday pipeline summary",
        description="posts a summary on Mondays",
        conditions=[{"kind": "schedule", "config": {"cron": "0 9 * * 1"}}],
        effects=[{"kind": "investigate", "alias": "numbers",
                  "config": {"question": "how is the pipeline?"}}],
    )
    base.update(kw)
    return ProposedChain(**base)


@pytest.fixture(autouse=True)
def _no_leftovers():
    """The automations store is session-scoped. Nothing here should save — and this
    fixture is also how the "nothing is saved" test can trust its own count."""
    from aughor.automations.store import delete_automation
    for a in list_automations(conn_id=CONN):
        delete_automation(a.id)
    yield
    for a in list_automations(conn_id=CONN):
        delete_automation(a.id)


# ── the proposal ──────────────────────────────────────────────────────────────

def test_a_described_outcome_becomes_an_editable_chain_with_a_receipt():
    p = _Provider(_chain())
    out = propose_chain("post a Monday pipeline summary", conn_id=CONN, provider=p)
    assert out.verdict == "proposed"
    assert out.draft["name"] == "Monday pipeline summary"
    assert out.draft["conn_id"] == CONN
    assert out.draft["effects"][0]["kind"] == "investigate"
    # The receipt: a dry run of the DRAFT, not of anything stored.
    assert out.dry_run.get("outcome") in {"fired", "not_fired", "gated"}
    assert p.user == "post a Monday pipeline summary"


def test_nothing_is_saved():
    """The one thing this module must never learn to do."""
    before = len(list_automations(conn_id=CONN))
    propose_chain("anything at all", conn_id=CONN, provider=_Provider(_chain()))
    assert len(list_automations(conn_id=CONN)) == before


def test_the_draft_carries_no_armed_state():
    """A proposal that arrived already enabled — or already exposed as an MCP tool — would
    have made the decision the human is being asked to make."""
    out = propose_chain("x", conn_id=CONN, provider=_Provider(_chain()))
    assert "enabled" not in out.draft
    assert "exposed_as_tool" not in out.draft
    assert "id" not in out.draft


# ── refusals, all of them closed ──────────────────────────────────────────────

def test_a_draft_that_would_not_save_is_refused_rather_than_drawn():
    """A canvas showing a chain the Save button will reject is worse than a refusal: it
    looks like work that is nearly done. `slack_post` requires a channel."""
    bad = _chain(effects=[{"kind": "slack_post", "config": {"bot_id": "b1"}}])
    out = propose_chain("post something", conn_id=CONN, provider=_Provider(bad))
    assert out.verdict == "refused"
    assert "channel" in out.reason


def test_an_invented_effect_kind_is_refused():
    bad = _chain(effects=[{"kind": "send_carrier_pigeon", "config": {}}])
    out = propose_chain("mail it", conn_id=CONN, provider=_Provider(bad))
    assert out.verdict == "refused"


def test_a_binding_onto_a_step_that_does_not_exist_is_refused():
    """`validate_chain` is the same refusal a save performs — the proposer gets it for
    free by constructing the real model rather than a look-alike."""
    bad = _chain(effects=[
        {"kind": "investigate", "alias": "one", "config": {"question": "q"}},
        {"kind": "notify", "config": {"trigger_id": "t1",
                                      "message": {"$from": "ghost.answer"}}},
    ])
    out = propose_chain("chain them", conn_id=CONN, provider=_Provider(bad))
    assert out.verdict == "refused"
    assert "ghost" in out.reason


def test_an_empty_draft_comes_back_as_a_refusal_carrying_the_models_reason():
    """The model is asked to say what it could not do. A partial chain that silently drops
    half the request is worse, because a person reading a drawn canvas cannot see an
    absence."""
    out = propose_chain("do the impossible", conn_id=CONN,
                        provider=_Provider(_chain(effects=[], notes="no Slack bot exists here")))
    assert out.verdict == "refused"
    assert out.reason == "no Slack bot exists here"


def test_a_dead_model_fails_CLOSED_with_a_reason():
    """`actions/propose.py` fails open to [] because it garnishes an answer somebody
    already asked for. Here the proposal IS the request."""
    out = propose_chain("anything", conn_id=CONN, provider=_Provider(boom=True))
    assert out.verdict == "refused"
    assert "model unreachable" in out.reason


def test_an_empty_outcome_never_reaches_the_model():
    p = _Provider(_chain())
    out = propose_chain("   ", conn_id=CONN, provider=p)
    assert out.verdict == "refused"
    assert p.system == "", "an empty request must not spend a token"


# ── the binding the live model got wrong ──────────────────────────────────────

def test_a_binding_written_as_a_STRING_is_repaired():
    """Found by driving it live, not by a test — which is the point of driving it.

    The model returned `"{\"$from\": \"step.key\"}"`: a string holding the JSON of a
    binding. Nothing refused it, because a string is a legal literal — the chain
    validated, the dry run was clean, and it would have posted those characters to Slack.
    """
    draft = _chain(effects=[
        {"kind": "investigate", "alias": "summary", "config": {"question": "how are sales?"}},
        {"kind": "notify", "config": {"trigger_id": "t1",
                                      "message": '{"$from": "summary.answer"}'}},
    ])
    out = propose_chain("summarise and tell someone", conn_id=CONN,
                        provider=_Provider(draft))
    assert out.verdict == "proposed", out.reason
    assert out.draft["effects"][1]["config"]["message"] == {"$from": "summary.answer"}


def test_a_binding_EMBEDDED_in_a_sentence_is_left_alone():
    """Deliberately not repaired. The engine cannot interpolate a binding into prose, so
    guessing what the author meant would swap a visible mistake for an invisible one — the
    step still reads as a literal, and a person can see that it does."""
    draft = _chain(effects=[
        {"kind": "investigate", "alias": "summary", "config": {"question": "q"}},
        {"kind": "notify", "config": {
            "trigger_id": "t1",
            "message": 'revenue is {"$from": "summary.answer"} today'}},
    ])
    out = propose_chain("x", conn_id=CONN, provider=_Provider(draft))
    assert out.draft["effects"][1]["config"]["message"] == \
        'revenue is {"$from": "summary.answer"} today'


def test_an_ordinary_string_that_merely_starts_with_a_brace_survives():
    """The repair matches an EXACT single-key `$from` object and nothing else."""
    draft = _chain(effects=[{"kind": "investigate",
                             "config": {"question": '{"not": "a binding"}'}}])
    out = propose_chain("x", conn_id=CONN, provider=_Provider(draft))
    assert out.draft["effects"][0]["config"]["question"] == '{"not": "a binding"}'


def test_the_prompt_shows_what_a_bound_field_looks_like():
    """The repair is a net, not a fix. The prompt now carries the correct and incorrect
    shapes side by side, because a model that never writes the bug needs no net."""
    p = _Provider(_chain())
    propose_chain("x", conn_id=CONN, provider=p)
    assert "never text inside a string" in p.system
    assert "posts the literal characters" in p.system


# ── what the model is told ────────────────────────────────────────────────────

def test_the_prompt_carries_this_deployments_own_verdict_on_each_kind():
    """Built from the SAME palette the canvas reads, so the prompt cannot drift from what
    the save enforces. A hand-written kind list in a prompt rots in the worst direction:
    it offers something the code refuses."""
    p = _Provider(_chain())
    propose_chain("x", conn_id=CONN, provider=p)
    assert "AVAILABLE TRIGGERS AND STEPS" in p.system
    assert "investigate" in p.system and "Requires: question" in p.system
    # An unavailable kind is named as unavailable WITH the palette's reason, so the model
    # is told why rather than simply not offered it.
    assert "UNAVAILABLE" in p.system


def test_the_prompt_forbids_inventing_an_id_and_lists_the_real_ones():
    p = _Provider(_chain())
    propose_chain("x", conn_id=CONN, provider=p)
    assert "never invent an id" in p.system
    assert "SLACK BOTS" in p.system


def test_a_list_publishing_key_is_marked_as_one():
    """DS-12 gave this plane its first declared list. The proposer has to know which key a
    `for_each` may fan over, or it will propose fanning over a string.

    The condition is MADE, not scanned for. The first version of this test asked "if
    trusted_query appears, assert the marker" — which passes on a deployment with no
    trusted queries by never asserting anything, and that is the vacuous shape this repo
    has a standing lesson about. Seeding one makes the kind available, which is the only
    state in which the marker should appear at all.
    """
    from aughor.semantic import trusted_queries as tq

    tq.save_trusted(tq.TrustedQuery(id="tq_ds15", connection_id=CONN,
                                    question="which accounts churned?",
                                    sql="SELECT 1", tables=[], status="approved"))
    try:
        p = _Provider(_chain())
        propose_chain("x", conn_id=CONN, provider=p)
        assert "trusted_query" in p.system
        assert "(a list: rows)" in p.system, p.system
    finally:
        tq.delete_trusted("tq_ds15")


def test_an_unavailable_kind_is_named_as_unavailable_and_not_offered_ports():
    """The other half: with no trusted query on the connection the kind is listed with the
    palette's reason and WITHOUT its ports, so the model is told why rather than tempted."""
    p = _Provider(_chain())
    propose_chain("x", conn_id=CONN, provider=p)
    line = next(ln for ln in p.system.splitlines() if ln.startswith("- trusted_query"))
    assert "UNAVAILABLE" in line
    assert "(a list: rows)" not in line
