"""Arc AO-6 (a testing centre) and AO-7 (one closed learning loop per agent).

Measured 2026-10-03 (docs/AGENT_OPS_STUDY_2026-10-03.md §5): no learning store carried
`agent_id`; the platform learned per connection and an agent learned nothing as itself; six
verdicts in two months; the autonomy ladder read keys nothing wrote. These pin: a verdict
knows its agent and is backfilled from the turn; the agent's brief carries its own
corrections; an accepted answer becomes a CANDIDATE a person certifies; a change or N
verdicts re-evaluates; the eval counts certified goldens only and records its diff; the
drafter needs its flag and writes no SQL; the nightly run is once a day; `record_run`
derives evidence from what runs carry; a crystallised skill is staged, never saved.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.custom_agents import create_agent, delete_agent, get_agent, list_agents
from aughor.custom_agents.store import add_candidate, add_golden, certify_golden, list_goldens


@pytest.fixture(autouse=True)
def _clean_agents():
    yield
    for a in list_agents():
        delete_agent(a.id)


@pytest.fixture()
def client(monkeypatch):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled", lambda name: name == "agents.user_defined")
    from aughor.api import app
    return TestClient(app)


def _flags(monkeypatch, *on):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled", lambda name: name in on or name == "agents.user_defined")


def _turn(monkeypatch, *, agent_id="", sql="SELECT 1", headline="There were 49.",
          question="How many?", connection_id="conn-t"):
    from aughor.feedback import verdicts
    monkeypatch.setattr(verdicts, "_turn_record", lambda inv: {
        "agent_id": agent_id, "connection_id": connection_id, "headline": headline,
        "sql": sql, "question": question} if inv else {})


# ── AO-7a/7b · a verdict knows its agent, and is whole ──────────────────────────────

def test_a_verdict_is_backfilled_from_the_turns_record(monkeypatch):
    from aughor.feedback.verdicts import list_corrections, record_verdict
    _turn(monkeypatch, agent_id="ua_x", sql="SELECT COUNT(*) FROM orders")
    # The Slack ✅ arrives with an investigation id and nothing else.
    v = record_verdict("", "inv-1", "reject", note="wrong window")
    assert v["agent_id"] == "ua_x"
    assert v["connection_id"] == "conn-t"
    assert v["headline"] == "There were 49."
    assert v["sql_source"] == "SELECT COUNT(*) FROM orders"
    mine = list_corrections(agent_id="ua_x")
    assert [r["investigation_id"] for r in mine] == ["inv-1"]
    assert list_corrections(agent_id="ua_other") == []


def test_what_the_caller_says_wins_over_the_backfill(monkeypatch):
    from aughor.feedback.verdicts import record_verdict
    _turn(monkeypatch, agent_id="ua_x")
    v = record_verdict("conn-said", "inv-2", "correct", headline="said", sql_source="SELECT 2",
                       agent_id="ua_said")
    assert (v["agent_id"], v["connection_id"], v["headline"], v["sql_source"]) == \
        ("ua_said", "conn-said", "said", "SELECT 2")


def test_the_route_takes_the_agent(client, monkeypatch):
    _turn(monkeypatch, agent_id="")
    r = client.post("/verify/verdict", json={"connection_id": "c", "investigation_id": "inv-3",
                                             "verdict": "accept", "agent_id": "ua_r"})
    assert r.status_code == 200, r.text
    assert r.json()["agent_id"] == "ua_r"


# ── AO-7a · the agent's own corrections lead its brief and its priors ───────────────

def test_the_brief_carries_the_agents_own_corrections_only_with_the_loop_on(monkeypatch):
    from aughor.custom_agents.context import agent_brief_for
    from aughor.feedback.verdicts import record_verdict
    a = create_agent("Learner", instructions="Count carefully.")
    _turn(monkeypatch, agent_id=a.id, headline="There were 108 orders.")
    record_verdict("", "inv-4", "reject", note="it counted lines, not orders")
    off = agent_brief_for(a)
    assert "CORRECTED BEFORE" not in off, "off by default — the brief is byte-identical"
    _flags(monkeypatch, "agents.learning_loop")
    on = agent_brief_for(a)
    assert on.startswith("AGENT BRIEF")
    assert "CORRECTED BEFORE" in on and "There were 108 orders." in on
    assert "it counted lines, not orders" in on
    # Bounded: three rows at most, a line each.
    for i in range(5):
        record_verdict("", f"inv-4-{i}", "reject", note=f"n{i}")
    block = agent_brief_for(a)
    assert block.count("- [rejected]") == 3


def test_an_agents_lesson_outranks_the_connections_at_equal_resemblance(monkeypatch):
    from aughor.feedback.priors import _match_corrections
    from aughor.feedback.verdicts import record_verdict
    _turn(monkeypatch, agent_id="ua_other", headline="revenue by month was wrong")
    record_verdict("conn-p", "inv-5", "reject", headline="revenue by month was wrong")
    _turn(monkeypatch, agent_id="ua_mine", headline="revenue by month was wrong")
    record_verdict("conn-p", "inv-6", "reject", headline="revenue by month was wrong")
    rows = _match_corrections("what was revenue by month", "conn-p", 5, agent_id="ua_mine")
    assert [r["agent_id"] for r in rows][:1] == ["ua_mine"]
    assert {r["investigation_id"] for r in rows} == {"inv-5", "inv-6"}, "the connection's still count"


# ── AO-7c/7d · an accepted answer becomes a candidate; verdicts re-evaluate ────────

def test_an_accepted_answer_becomes_an_uncertified_candidate(monkeypatch):
    from aughor.feedback.verdicts import record_verdict
    a = create_agent("Candidate", instructions="x")
    _flags(monkeypatch, "agents.learning_loop")
    _turn(monkeypatch, agent_id=a.id, sql="SELECT COUNT(DISTINCT order_id) FROM orders",
          question="How many orders yesterday?")
    record_verdict("", "inv-7", "accept")
    cands = list_goldens(a.id, status="candidate")
    assert len(cands) == 1
    c = cands[0]
    assert c["source"] == "use" and c["from_investigation"] == "inv-7"
    assert c["reference_sql"] == "SELECT COUNT(DISTINCT order_id) FROM orders", \
        "the SQL that answered is the starting point, not the reference"
    assert list_goldens(a.id, status="certified") == [], "a ✅ is not a person's SQL"
    # The same turn accepted twice makes no second row; a reject makes none.
    record_verdict("", "inv-7", "accept")
    _turn(monkeypatch, agent_id=a.id, question="Another?")
    record_verdict("", "inv-8", "reject")
    assert len(list_goldens(a.id, status="candidate")) == 1


def test_certifying_a_candidate_makes_it_count(client, monkeypatch):
    a = create_agent("Certify", instructions="x")
    row = add_candidate(a.id, "How many orders?", source="use", reference_sql="SELECT COUNT(*) FROM o")
    r = client.post(f"/agents/custom/{a.id}/goldens/{row['id']}/certify",
                    json={"reference_sql": "DELETE FROM o"})
    assert r.status_code == 422, "read-only, parsed — the hand-written path's rule"
    r = client.post(f"/agents/custom/{a.id}/goldens/{row['id']}/certify",
                    json={"reference_sql": "SELECT COUNT(DISTINCT id) FROM o"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "certified" and r.json()["certified_at"]
    assert [g["id"] for g in list_goldens(a.id, status="certified")] == [row["id"]]
    assert client.get(f"/agents/custom/{a.id}/goldens").json()[0]["source"] == "use"


def test_every_fifth_verdict_and_a_configuration_change_reevaluate(monkeypatch):
    from aughor.custom_agents import learning, update_agent
    from aughor.feedback.verdicts import record_verdict
    a = create_agent("Reeval", instructions="v1")
    add_golden(a.id, "q", "SELECT 1")
    _flags(monkeypatch, "agents.learning_loop")
    ran: list = []
    monkeypatch.setattr(learning, "reevaluate", lambda aid, reason, background=True: ran.append(reason) or True)
    _turn(monkeypatch, agent_id=a.id)
    for i in range(5):
        record_verdict("", f"inv-r{i}", "reject")
    assert ran == ["5 verdicts"]
    update_agent(a.id, instructions="v2")
    assert ran[-1] == "configuration changed"
    update_agent(a.id, name="Renamed only")
    assert ran[-1] == "configuration changed", "a rename changes no governing field"


def test_the_loop_is_inert_when_off(monkeypatch):
    from aughor.custom_agents import learning, update_agent
    from aughor.feedback.verdicts import record_verdict
    a = create_agent("Off", instructions="v1")
    add_golden(a.id, "q", "SELECT 1")
    ran: list = []
    monkeypatch.setattr(learning, "reevaluate", lambda *a, **k: ran.append(1) or True)
    _turn(monkeypatch, agent_id=a.id)
    for i in range(5):
        record_verdict("", f"inv-o{i}", "accept")
    update_agent(a.id, instructions="v2")
    assert ran == [] and list_goldens(a.id, status="candidate") == []


# ── AO-6 · the evaluation counts certified goldens and records its diff ─────────────

def _db():
    import types as _types

    class _Res:
        def __init__(self, rows, error=None):
            self.rows, self.error = rows, error

    def _exec(qid, sql):
        return _Res([(1,)] if "1" in sql else [(2,)])

    return _types.SimpleNamespace(execute=_exec, get_schema=lambda: "t(x)")


def test_the_suite_counts_certified_goldens_only_and_writes_the_diff():
    from aughor.custom_agents.quality import evaluate_agent
    from aughor.custom_agents.store import previous_eval
    a = create_agent("Diff", instructions="x")
    g1 = add_golden(a.id, "one", "SELECT 1")
    add_candidate(a.id, "a candidate", source="synthetic")
    first = evaluate_agent(a, db=_db(), generate=lambda q, s: "SELECT 1")
    assert first["total"] == 1 and first["passed"] == 1, "the candidate is not counted"
    assert first["diff"]["before"] is None
    a = get_agent(a.id)
    second = evaluate_agent(a, db=_db(), generate=lambda q, s: "SELECT 2")
    assert second["passed"] == 0
    assert second["diff"]["before"] == {"passed": 1, "total": 1, "at": first["at"]}
    assert second["diff"]["newly_failing"] == [g1["id"]]
    assert previous_eval(a.id)["passed"] == 1
    assert get_agent(a.id).last_eval["passed"] == 0


def test_the_drafter_needs_its_flag_and_writes_questions_not_sql(client, monkeypatch):
    import types as _types
    from aughor.custom_agents import learning
    a = create_agent("Draft", instructions="x", purpose="Churn questions")
    assert client.post(f"/agents/custom/{a.id}/goldens/draft").status_code == 409
    _flags(monkeypatch, "agents.testing_centre")
    seen: dict = {}

    class _Prov:
        def complete(self, *, system, user, response_model, temperature=0.1):
            seen["user"] = user
            return response_model(questions=[
                {"question": "How many customers churned last month?", "why": "core metric"},
                {"question": "How many customers churned last month?", "why": "dup"},
                {"question": "What was revenue by region in Q3?", "why": "catalogue"},
            ])

    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role, **k: _Prov())
    monkeypatch.setattr(learning, "_catalogue_lines", lambda c, s: ["- Churn rate: customers lost / customers"])
    r = client.post(f"/agents/custom/{a.id}/goldens/draft")
    assert r.status_code == 201, r.text
    drafted = r.json()["drafted"]
    assert [d["question"] for d in drafted] == [
        "How many customers churned last month?", "What was revenue by region in Q3?"]
    assert all(d["status"] == "candidate" and d["source"] == "synthetic" and d["reference_sql"] == ""
               for d in drafted)
    assert "Churn questions" in seen["user"] and "Churn rate" in seen["user"]
    _ = _types


def test_the_nightly_run_is_once_a_day_and_behind_its_flag(monkeypatch):
    from datetime import datetime, timezone
    from aughor.custom_agents import learning
    from aughor.custom_agents import quality
    a = create_agent("Nightly", instructions="x")
    add_golden(a.id, "q", "SELECT 1")
    create_agent("NoGoldens", instructions="x")
    assert learning.nightly()["skipped"] == "off"
    _flags(monkeypatch, "agents.testing_centre")
    runs: list = []
    monkeypatch.setattr(quality, "evaluate_agent", lambda ag: runs.append(ag.id) or {"passed": 1, "total": 1})
    learning._last_nightly_day = None
    day = datetime(2026, 10, 3, tzinfo=timezone.utc)
    out = learning.nightly(now=day)
    assert runs == [a.id] and out["ran"][0]["agent_id"] == a.id
    assert learning.nightly(now=day)["skipped"] == "already ran today"
    assert learning.nightly(now=day, force=True)["ran"]


def test_the_learning_receipt(client, monkeypatch):
    from aughor.feedback.verdicts import record_verdict
    a = create_agent("Receipt", instructions="x")
    _flags(monkeypatch, "agents.learning_loop")
    _turn(monkeypatch, agent_id=a.id, question="Q1")
    record_verdict("", "inv-l1", "accept")
    record_verdict("", "inv-l2", "reject")
    cand = list_goldens(a.id, status="candidate")[0]
    certify_golden(cand["id"], a.id, "SELECT 1")
    body = client.get(f"/agents/custom/{a.id}/learning").json()
    assert body["verdicts"] == 2 and body["corrections"] == 1
    assert body["certified_from_use"] == 1 and body["candidates_from_use"] == 0
    assert body["loop_on"] is True and body["centre_on"] is False, "the flags' states are on the receipt"
    assert body["before"] is None and body["after"] is None


# ── AO-7e · evidence from what runs carry; a skill is staged, never saved ────────────

def test_record_run_derives_evidence_from_the_manifest_or_the_label(monkeypatch):
    from aughor.memory import _derive_evidence
    manifest_state = {"exploration_report": {"verification": {
        "earned_confidence": 0.82, "confidence_band": "high", "checks": [{"name": "rows"}]}}}
    assert _derive_evidence(manifest_state) == (True, 0.82, "verification_manifest")
    low = {"exploration_report": {"verification": {"earned_confidence": 0.1, "confidence_band": "low",
                                                    "checks": [{"name": "rows"}]}}}
    assert _derive_evidence(low)[0] is False
    monkeypatch.setattr("aughor.obs.trajectory.trajectory_of", lambda t: {"t": t})
    monkeypatch.setattr("aughor.learning.reward.run_label", lambda tr: {"label": "positive"})
    assert _derive_evidence({"trace_id": "tr-1"}) == (True, None, "reward_label")
    monkeypatch.setattr("aughor.learning.reward.run_label", lambda tr: {"label": "unlabeled"})
    assert _derive_evidence({"trace_id": "tr-1"})[2] == "unknown"
    assert _derive_evidence({"grounded": True, "confidence": 0.5}) == (True, 0.5, "state_keys")


def test_a_crystallised_skill_is_staged_to_the_inbox_not_saved(monkeypatch):
    from aughor.memory import skills
    staged: list = []
    monkeypatch.setattr(skills, "_autonomy_level", lambda conn: 2)
    monkeypatch.setattr(skills, "_run_signals", lambda inv: {"grounded": True, "read_only": True})
    monkeypatch.setattr(skills, "propose_skill_from_investigation",
                        lambda inv, table_to_entity=None: type("C", (), {"id": "sk_1", "name": "Orders by day"})())
    monkeypatch.setattr(skills, "resolve_active_schema", lambda conn: "main")
    monkeypatch.setattr(skills, "save_skill", lambda *a, **k: (_ for _ in ()).throw(AssertionError("saved directly")))
    monkeypatch.setattr("aughor.actions.inbox.stage_proposal", lambda p: staged.append(p) or p)
    skills.auto_crystallize("inv-s1", "conn-s")
    assert len(staged) == 1
    p = staged[0]
    assert p.kind == "skill_draft" and p.params["inv_id"] == "inv-s1"
    assert p.connection_id == "conn-s" and p.proposer == "memory"


def test_accepting_the_staged_skill_saves_through_the_governed_door(monkeypatch):
    from aughor.actions import inbox
    from aughor.memory import skills
    monkeypatch.setattr(skills, "accept_skill_draft", lambda inv, conn: (True, "saved learned skill sk_1"))
    outcomes: list = []
    monkeypatch.setattr(inbox, "_record_outcome", lambda pid, status, msg, out: outcomes.append((status, msg)))
    p = inbox.StagedProposal(kind="skill_draft", connection_id="conn-s", action_id="memory:crystallize_skill",
                             params={"inv_id": "inv-s1"})
    result = inbox._accept_skill_draft(p, actor="person")
    assert result.ok is True and outcomes == [("executed", "saved learned skill sk_1")]


# ── the fold: the Workspace reads the samples metrics whose tables it folds in ───────

def test_the_workspace_reads_the_samples_metrics_it_folds_in(monkeypatch, tmp_path):
    """Receipt 2026-10-03, fresh install: the shipped metrics are scoped to `samples`, an id
    the registry never lists, while the Workspace folds the samples TABLES in — so `revenue`
    and `aov` applied to no listed connection and the drafter had no governed metric. The
    tables and their metrics travel together; the Workspace's own entry of a name still
    wins, a global one still fills the gaps, and any other connection folds nothing."""
    from aughor.db import registry
    from aughor.semantic import metrics as m
    from aughor.semantic.metrics import MetricDefinition
    path = tmp_path / "metrics.instance.json"
    m.save_metric(MetricDefinition(name="revenue", connection="samples", label="Rev samples",
                                   sql="SUM(total_amount)"), path=path)
    m.save_metric(MetricDefinition(name="aov", connection="samples", label="AOV", sql="AVG(total_amount)"), path=path)
    m.save_metric(MetricDefinition(name="aov", connection="workspace", label="AOV mine", sql="AVG(x)"), path=path)
    m.save_metric(MetricDefinition(name="units", label="Units", sql="SUM(q)"), path=path)      # global

    # No samples warehouse on disk → the Workspace folds nothing in.
    monkeypatch.setattr(registry, "get_meta",
                        lambda cid: {"builtin_workspace": True} if cid == "workspace" else {})
    assert {x.name for x in m.list_metrics(path, connection_id="workspace")} == {"aov", "units"}

    # The warehouse is present → its metrics ride along; the Workspace's own `aov` shadows.
    monkeypatch.setattr(registry, "get_meta",
                        lambda cid: ({"builtin_workspace": True, "seed_duckdb": "/x/samples.duckdb"}
                                     if cid == "workspace" else {}))
    got = {x.name: x.label for x in m.list_metrics(path, connection_id="workspace")}
    assert got == {"revenue": "Rev samples", "aov": "AOV mine", "units": "Units"}
    assert m.get_metric("revenue", path, connection_id="workspace").sql == "SUM(total_amount)"
    assert m.get_metric("aov", path, connection_id="workspace").label == "AOV mine"
    assert m.get_metric("nope", path, connection_id="workspace") is None
    # Another connection folds nothing: only the global entry applies.
    assert {x.name for x in m.list_metrics(path, connection_id="c9")} == {"units"}
    # Unscoped reads are byte-identical to before: every row.
    assert len(m.list_metrics(path)) == 4
