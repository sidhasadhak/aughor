"""DS-19 (§3.7 second movement) — SQL a person authored on a node.

The properties worth guarding are the three that make this safe rather than the one that
makes it convenient:

1. **It really ran before it was armed.** A save verifies; a refusal is at save, not 09:00.
2. **A model never authors it.** §6 item 26 (d) — the Investigate node is already the
   governed path where a model writes SQL.
3. **Scope is a flag, not a store.** A chain-owned query is hidden from the catalogue, the
   picker and every prompt, readable by the chain that owns it, and promoted by one field
   going empty — with its verification and approval untouched, because nothing about the
   content changed.
"""
from __future__ import annotations

import pytest

from aughor.automations.authored_sql import AuthoredSqlRefused, materialise_authored_sql
from aughor.automations.models import Automation, Condition, Effect
from aughor.semantic.trusted_queries import (TrustedQuery, get_trusted, list_trusted,
                                             save_trusted)


def _automation(config: dict, *, conn_id: str = "c1", aid: str = "a1") -> Automation:
    return Automation(
        id=aid, conn_id=conn_id, name="nightly",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="trusted_query", config=config)])


@pytest.fixture
def verified(monkeypatch):
    """`verify` passing, without a warehouse. Returns the calls it received."""
    calls: list[tuple[str, str]] = []

    def _verify(conn_id: str, sql: str) -> dict:
        calls.append((conn_id, sql))
        return {"passed": True, "execution": {"ok": True, "row_count": 3}, "blockers": []}

    monkeypatch.setattr("aughor.semantic.trusted_verify.verify", _verify)
    return calls


# ── 1 · it really ran before it was armed ────────────────────────────────────────

def test_authored_sql_is_verified_and_becomes_a_governed_query(verified):
    out = materialise_authored_sql(_automation(
        {"question": "how many returns?", "sql": "SELECT count(*) FROM returns"}))

    # The SQL really ran, against this automation's connection.
    assert verified == [("c1", "SELECT count(*) FROM returns")]

    # And the STORED step names a governed object — no sql at rest. This is the property
    # that keeps a saved node a reference rather than a carrier of behaviour.
    config = out.effects[0].config
    assert "sql" not in config and "question" not in config
    row = get_trusted(config["query_id"])
    assert row is not None
    assert row.sql == "SELECT count(*) FROM returns"
    assert row.question == "how many returns?"
    assert row.verification["passed"] is True
    assert row.last_executed_at


def test_a_refusal_lands_at_save_not_at_0900(monkeypatch):
    monkeypatch.setattr("aughor.semantic.trusted_verify.verify",
                        lambda c, s: {"passed": False, "blockers": ["no such table: retunrs"]})
    with pytest.raises(AuthoredSqlRefused) as exc:
        materialise_authored_sql(_automation(
            {"question": "typo", "sql": "SELECT * FROM retunrs"}))
    assert "no such table: retunrs" in str(exc.value)
    # Nothing was written — a query that failed to verify must not exist to be run.
    assert not [q for q in list_trusted("c1", include_unapproved=True,
                                        include_chain_owned=True)
                if q.question == "typo"]


def test_an_automation_with_no_authored_sql_is_returned_untouched(verified):
    picked = _automation({"query_id": "tq_already_vetted"})
    assert materialise_authored_sql(picked) is picked
    assert verified == []


def test_a_step_cannot_carry_both_a_query_id_and_sql():
    # Two answers to "what runs" is the shape that drifts the first time either is edited.
    with pytest.raises(ValueError, match="not both"):
        Effect(kind="trusted_query",
               config={"query_id": "tq_1", "question": "q", "sql": "SELECT 1"})


def test_authored_sql_still_requires_its_question():
    with pytest.raises(ValueError, match="question"):
        Effect(kind="trusted_query", config={"sql": "SELECT 1"})


def test_editing_a_step_rewrites_ITS_row_rather_than_orphaning_it(verified):
    first = materialise_authored_sql(_automation(
        {"question": "v1", "sql": "SELECT 1"}))
    qid = first.effects[0].config["query_id"]

    second = materialise_authored_sql(_automation({
        "question": "v2", "sql": "SELECT 2",
        "authored_query_id": qid}))
    # Same row, new content — not a second invisible row nobody will ever collect.
    assert second.effects[0].config["query_id"] == qid
    row = get_trusted(qid)
    assert row is not None and row.sql == "SELECT 2"


def test_a_copied_step_never_rewrites_the_chain_it_came_from(verified):
    mine = materialise_authored_sql(_automation({"question": "v1", "sql": "SELECT 1"},
                                                aid="a1"))
    qid = mine.effects[0].config["query_id"]

    # The same step, pasted into a DIFFERENT automation.
    theirs = materialise_authored_sql(_automation(
        {"question": "v1", "sql": "SELECT 99", "authored_query_id": qid}, aid="a2"))
    assert theirs.effects[0].config["query_id"] != qid
    assert get_trusted(qid).sql == "SELECT 1"       # untouched


# ── 2 · a model never authors it ─────────────────────────────────────────────────

def test_the_proposer_refuses_a_chain_that_wrote_its_own_sql():
    """§6 item 26 (d), driven through the real path with an injected provider.

    Refused rather than stripped: an emptied step would fail the save with a confusing
    message about a missing `query_id`, and this deployment would never learn that its
    proposer had tried to write SQL.
    """
    from aughor.automations.propose import ProposedChain, propose_chain

    class _Provider:
        def complete(self, *, system, user, response_model, temperature=0.0):
            return ProposedChain(
                name="sneaky", description="",
                conditions=[{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
                effects=[{"kind": "trusted_query", "alias": "q",
                          "config": {"question": "revenue?",
                                     "sql": "SELECT sum(amount) FROM orders"}}])

    out = propose_chain("summarise revenue nightly", conn_id="c1", provider=_Provider())
    assert out.verdict == "refused"
    # The refusal names the step AND the door that is allowed to do this, because a
    # refusal that does not say where the capability lives teaches a person the platform
    # cannot do a thing it does.
    assert "may not carry SQL" in out.reason
    assert "Investigate" in out.reason


def test_a_proposed_chain_that_NAMES_a_query_is_still_fine():
    """The guard must bite on authorship, not on the kind — a proposer picking a vetted
    query by id is the whole point of the roster it is given."""
    from aughor.automations.propose import ProposedChain, propose_chain

    save_trusted(TrustedQuery(id="tq_vetted", connection_id="c1", question="ok",
                              sql="SELECT 1", status="approved"))

    class _Provider:
        def complete(self, *, system, user, response_model, temperature=0.0):
            return ProposedChain(
                name="fine", description="",
                conditions=[{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
                effects=[{"kind": "trusted_query", "alias": "q",
                          "config": {"query_id": "tq_vetted"}}])

    out = propose_chain("run the vetted rollup", conn_id="c1", provider=_Provider())
    assert out.verdict == "proposed", out.reason


# ── 3 · scope is a flag, not a store ─────────────────────────────────────────────

def test_a_chain_owned_query_is_hidden_from_the_catalogue_and_from_prompts(verified):
    out = materialise_authored_sql(_automation(
        {"question": "private rollup", "sql": "SELECT 1"}))
    qid = out.effects[0].config["query_id"]

    # The catalogue, the picker and prompt injection all read `list_trusted`, so one
    # default closes all three at once.
    assert qid not in [q.id for q in list_trusted("c1")]
    assert qid in [q.id for q in list_trusted("c1", include_chain_owned=True)]
    # And by id, for the chain that owns it.
    assert get_trusted(qid) is not None

    from aughor.semantic.trusted_queries import retrieve_trusted
    assert qid not in [q.id for q, _ in retrieve_trusted("private rollup", "c1")]


def test_promotion_is_a_flag_flip_that_touches_nothing_else(verified):
    out = materialise_authored_sql(_automation(
        {"question": "worth sharing", "sql": "SELECT 1"}))
    row = get_trusted(out.effects[0].config["query_id"])
    before = (row.sql, row.status, row.version, row.verification, row.verified_at)

    row.owner_automation = ""
    save_trusted(row)

    after = get_trusted(row.id)
    assert (after.sql, after.status, after.version, after.verification,
            after.verified_at) == before
    assert after.id in [q.id for q in list_trusted("c1")]   # now in the catalogue


def test_a_legacy_record_without_the_field_stays_in_the_catalogue():
    """Every pre-DS-19 row has no `owner_automation`, and must not vanish from the
    catalogue because a field was added — the grandfathering `status` already pays for."""
    save_trusted(TrustedQuery(id="tq_legacy", connection_id="c1", question="old",
                              sql="SELECT 1", status="approved"))
    assert "tq_legacy" in [q.id for q in list_trusted("c1")]


# ── 4 · what the chain may RUN ───────────────────────────────────────────────────

def test_a_chain_runs_its_own_authored_query_and_never_another_chains(verified, monkeypatch):
    """The dispatcher reads `list_trusted`, which now hides chain-owned rows by default —
    so without scoping, a chain could not run the very query it had just authored. The
    fix must open exactly one door: the catalogue, plus THIS automation's own.
    """
    from aughor.automations import engine

    mine = materialise_authored_sql(_automation({"question": "mine", "sql": "SELECT 1"},
                                                aid="a1"))
    theirs = materialise_authored_sql(_automation({"question": "theirs", "sql": "SELECT 2"},
                                                  aid="a2"))
    my_qid = mine.effects[0].config["query_id"]
    their_qid = theirs.effects[0].config["query_id"]
    save_trusted(TrustedQuery(id="tq_cat", connection_id="c1", question="shared",
                              sql="SELECT 3", status="approved"))

    seen: list[str] = []

    class _Result:
        error, columns, rows = None, ["n"], [(1,)]

    class _DB:
        def execute_bounded(self, label, sql, cap):
            seen.append(sql)
            return _Result()

        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(engine, "_warehouse", lambda a: _DB())

    def _run(automation, query_id):
        return engine._dispatch_trusted_query(
            Effect(kind="trusted_query", config={"query_id": query_id}), automation)

    a1 = _automation({"query_id": my_qid}, aid="a1")
    assert _run(a1, my_qid).status != "dispatch_error"          # its own: yes
    assert _run(a1, "tq_cat").status != "dispatch_error"        # the catalogue's: yes
    # …and the other chain's private SQL is simply not there, which is the whole point
    # of `owner_automation` being a scope rather than a label.
    assert _run(a1, their_qid).status == "dispatch_error"


def test_the_palette_no_longer_gates_the_trusted_query_step():
    """DS-19 makes the kind authorable, so gating it on a pre-existing query would dim a
    step that works — the exact failure `palette.py` exists to prevent, from the far side.
    """
    from aughor.automations.palette import entries

    row = next(e for e in entries("conn-with-nothing") if e["kind"] == "trusted_query")
    assert row["availability"] == "ready"
    assert row["reason"] == ""
