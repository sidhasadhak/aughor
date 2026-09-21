"""The Curator's declared LIMITS (2026-09-22) — the two birth-time prompts whose size is a
function of the WAREHOUSE, capped from one registry.

Measured before this landed: the glossary autoseed was one model call per table with no
cap (and ran in an executor thread the kernel's budget cancel does not reach), and the
business-profile prompt carried the whole rendered schema (the provider chokepoint only
warns). A 1,500-table warehouse was 1.7–4M tokens on birth. These tests pin the ONE
registry every door reads — the charter's `knobs` — and that each door (governance store,
/agents route, inbox accept, Spotlight's Know/Act/Guide) speaks the registry's own words.

Every guard here is mutation-checked in the same file: the cap is shown to CHANGE the
call count / the text, not merely to be present.
"""
from __future__ import annotations

import pytest

from aughor.kernel.agents import (
    Knob,
    effective_governance,
    effective_limit,
    get_charter,
    get_knob,
    set_governance,
)

CURATOR = "curator"
AUTOSEED = "autoseed_max_tables"
PROFILE = "profile_schema_chars"


@pytest.fixture(autouse=True)
def _clean_curator_overrides():
    """The hermetic ledger persists across tests in one session — leave the Curator's
    app-scope knobs at inherit on both sides of every test here."""
    def _clear():
        for scope in (None, "ws-1"):
            try:
                set_governance(CURATOR, scope=scope, limits={AUTOSEED: None, PROFILE: None})
            except Exception:
                pass
    _clear()
    yield
    _clear()


# ── the registry ────────────────────────────────────────────────────────────────────

def test_curator_declares_the_two_warehouse_sized_knobs():
    c = get_charter(CURATOR)
    assert [k.id for k in c.knobs] == [AUTOSEED, PROFILE]
    for k in c.knobs:
        assert isinstance(k, Knob) and k.min <= k.default <= k.max
        assert k.applies_to and k.description and k.unit
    # The charter's wire shape carries the registry — the roster page and gen'd client read it.
    d = c.to_dict()
    assert {k["id"] for k in d["knobs"]} == {AUTOSEED, PROFILE}
    assert set(d["knobs"][0]) >= {"id", "label", "default", "min", "max", "unit", "applies_to"}


def test_autoseed_default_mirrors_the_profilers_table_cap():
    """The tables that get words are the tables the explorer can see — one number, pinned."""
    from aughor.tools.profiler import MAX_PROFILED_TABLES
    assert get_knob(CURATOR, AUTOSEED).default == MAX_PROFILED_TABLES


def test_no_other_charter_declares_knobs_yet():
    from aughor.kernel.agents import list_charters
    assert [c.id for c in list_charters() if c.knobs] == [CURATOR]


# ── resolution: charter default < app override < workspace override ─────────────────

def test_limits_resolve_default_then_app_then_workspace():
    assert effective_governance(CURATOR).limits == {AUTOSEED: 60, PROFILE: 60_000}
    set_governance(CURATOR, limits={AUTOSEED: 20})
    assert effective_limit(CURATOR, AUTOSEED) == 20
    assert effective_limit(CURATOR, PROFILE) == 60_000          # untouched knob inherits
    set_governance(CURATOR, scope="ws-1", limits={AUTOSEED: 5})
    assert effective_limit(CURATOR, AUTOSEED, "ws-1") == 5
    assert effective_limit(CURATOR, AUTOSEED) == 20             # app scope unchanged
    set_governance(CURATOR, limits={AUTOSEED: None})             # None clears to inherit
    assert effective_limit(CURATOR, AUTOSEED) == 60


def test_undeclared_knob_is_refused_naming_the_declared_ones():
    with pytest.raises(ValueError) as exc:
        set_governance(CURATOR, limits={"vibes": 1})
    assert "vibes" in str(exc.value) and AUTOSEED in str(exc.value) and PROFILE in str(exc.value)
    with pytest.raises(ValueError) as exc:
        set_governance("scout", limits={AUTOSEED: 1})
    assert "none" in str(exc.value)                              # the Explorer declares none


@pytest.mark.parametrize("value", [-1, 10_001, "twelve", None])
def test_out_of_range_or_non_integer_is_refused_naming_the_range(value):
    if value is None:
        return                                                    # None = clear, not a value
    with pytest.raises(ValueError) as exc:
        set_governance(CURATOR, limits={AUTOSEED: value})
    assert "10,000" in str(exc.value) or "whole number" in str(exc.value)
    assert effective_limit(CURATOR, AUTOSEED) == 60               # nothing was written


def test_a_stored_value_outside_todays_range_is_clamped_on_read():
    """The store is history, the registry is the law: a value written under a wider
    range yesterday reads as today's bound, never as a silent unbounded."""
    from aughor.kernel.agents import _APP_SCOPE, _GOV_STORE, _ledger
    _ledger().kv_put(_GOV_STORE, f"{_APP_SCOPE}:{CURATOR}", {"limits": {AUTOSEED: 999_999,
                                                                          "gone_knob": 3}})
    assert effective_limit(CURATOR, AUTOSEED) == 10_000
    assert "gone_knob" not in effective_governance(CURATOR).limits


def test_effective_limit_fails_safe_to_the_default_never_to_unbounded(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ledger down")
    monkeypatch.setattr("aughor.kernel.agents.effective_governance", boom)
    assert effective_limit(CURATOR, AUTOSEED) == 60
    with pytest.raises(KeyError):
        effective_limit(CURATOR, "not_a_knob")


# ── enforcement site 1: the glossary autoseed ───────────────────────────────────────

def _blocks(n: int) -> str:
    """n tables with DISTINCT row counts, in shuffled render order — t1 smallest."""
    order = list(range(1, n + 1))
    order = order[::2] + order[1::2]
    return "\n\n".join(f"TABLE: t{i}  ({i * 1000:,} rows)\n  id  INT\n  name  VARCHAR"
                       for i in order) + "\n\nSQL HINTS\n- none"


def test_eligible_tables_are_the_largest_by_rows_ties_and_unknowns_by_name():
    from aughor.semantic.autoseed import _parse_table_blocks, eligible_tables
    tb = _parse_table_blocks("TABLE: a  (10 rows)\n  x INT\n\nTABLE: b (1,200 rows) [x]\n  x INT\n\n"
                             "TABLE: c\n  x INT\n\nTABLE: d  (500 rows)\n  x INT\n\n"
                             "TABLE: e  (500 rows)\n  x INT\n")
    assert eligible_tables(tb, 3) == ["b", "d", "e"]
    assert eligible_tables(tb, 100) == ["b", "d", "e", "a", "c"]   # unknown count last
    assert eligible_tables(tb, 0) == []


class _Provider:
    def __init__(self):
        self.seen: list[str] = []

    def complete(self, *, system, user, response_model, temperature):
        from aughor.semantic.autoseed import TableAnnotation
        self.seen.append(user.splitlines()[2].split()[1])       # "TABLE: tN  (…)"
        return TableAnnotation(description="d", grain="one row per id", columns=[])


@pytest.fixture
def seed_env(monkeypatch, tmp_path):
    """Drive `_seed` for real: a counting provider, an isolated glossary, no data probes."""
    prov = _Provider()
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda *a, **k: prov)
    monkeypatch.setattr("aughor.semantic.autoseed.verify_grain_claim",
                        lambda grain, *a, **k: grain)
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(tmp_path / "glossary.yaml"))
    monkeypatch.setenv("AUGHOR_GLOSSARY_SEED_PATH", str(tmp_path / "seed.yaml"))
    return prov


def test_autoseed_spends_one_call_per_table_only_up_to_the_cap(seed_env):
    from aughor.semantic import autoseed
    set_governance(CURATOR, limits={AUTOSEED: 2})
    wrote = autoseed._seed(_blocks(7), schema=None, connection_id="conn-cap", conn=None)
    assert wrote is True
    assert sorted(seed_env.seen) == ["t6", "t7"]                 # the two largest, no others


def test_autoseed_cap_mutation_check_the_cap_is_what_bounds_the_calls(seed_env):
    """Same warehouse, cap raised past the table count → every table is a call. Proves
    the previous test passed BECAUSE of the cap, not because the loop happened to stop."""
    from aughor.semantic import autoseed
    set_governance(CURATOR, limits={AUTOSEED: 100})
    autoseed._seed(_blocks(7), schema=None, connection_id="conn-nocap", conn=None)
    assert len(seed_env.seen) == 7


def test_autoseed_cap_zero_makes_no_model_call_and_writes_nothing(seed_env):
    from aughor.semantic import autoseed
    set_governance(CURATOR, limits={AUTOSEED: 0})
    wrote = autoseed._seed(_blocks(3), schema=None, connection_id="conn-off", conn=None)
    assert wrote is False and seed_env.seen == []


def test_autoseed_cap_is_on_the_connection_not_a_per_run_allowance(seed_env):
    """A second build under the same cap re-selects the SAME largest tables (now already
    seeded) and spends nothing — the cap cannot creep to every table over rebuilds."""
    from aughor.semantic import autoseed
    set_governance(CURATOR, limits={AUTOSEED: 2})
    autoseed._seed(_blocks(7), schema=None, connection_id="conn-creep", conn=None)
    first = list(seed_env.seen)
    autoseed._seed(_blocks(7), schema=None, connection_id="conn-creep", conn=None)
    assert seed_env.seen == first                                  # no new calls


# ── enforcement site 2: the business-profile prompt ─────────────────────────────────

def _schema(n: int) -> str:
    return ("HEAD\n\n" + "\n\n".join(f"TABLE: t{i}  ({i * 100:,} rows)\n  a  INT\n  b  VARCHAR"
                                      for i in range(1, n + 1)) + "\n\nSQL HINTS\n- x")


def test_cap_schema_is_byte_identical_under_the_limit():
    from aughor.business_profile.infer import cap_schema
    s = _schema(8)
    assert cap_schema(s, len(s)) == s and cap_schema(s, 0) == s


def test_cap_schema_keeps_the_largest_tables_in_render_order_and_says_the_cut():
    from aughor.business_profile.infer import cap_schema
    s = _schema(20)
    assert len(s) > 700
    out = cap_schema(s, 600)
    assert len(out) <= 600
    ids = [int(ln.split("t")[1].split()[0]) for ln in out.splitlines() if ln.startswith("TABLE:")]
    assert 0 < len(ids) < 20
    assert ids == list(range(21 - len(ids), 21))      # exactly the top-k by rows, in render order
    assert f"showing {len(ids)} of 20 tables" in out
    assert "Business profile · schema chars per prompt" in out                       # the knob, named
    assert out.startswith("HEAD") and out.rstrip().endswith("- x")                  # preamble + trailer kept


def test_cap_schema_never_returns_a_schema_with_no_table():
    from aughor.business_profile.infer import cap_schema
    one = "TABLE: wide  (5 rows)\n" + "\n".join(f"  c{i}  INT" for i in range(300))
    out = cap_schema(one, 500)
    assert len(out) <= 500 and out.startswith("TABLE: wide") and "truncated" in out


def test_profile_context_reads_the_curator_knob(monkeypatch):
    """The knob is what `_gather_context` applies — a mutation of the knob moves the text."""
    from aughor.business_profile import infer

    class _Db:
        def get_schema(self):
            return _schema(12)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: _Db())
    monkeypatch.setattr("aughor.semantic.glossary.apply_glossary", lambda s, **k: s)
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda *a, **k: None)
    full, _ = infer._gather_context("conn-p", None)
    assert full == _schema(12)                                    # under the 60k default
    set_governance(CURATOR, limits={PROFILE: 2_000})              # the knob's floor
    capped, _ = infer._gather_context("conn-p", None)
    assert capped == _schema(12)                                  # still under 2,000 chars
    set_governance(CURATOR, limits={PROFILE: 2_000})
    monkeypatch.setattr(_Db, "get_schema", lambda self: _schema(80))
    capped, _ = infer._gather_context("conn-p", None)
    assert len(capped) <= 2_000 and "showing" in capped


# ── door: the /agents route ─────────────────────────────────────────────────────────

def test_route_lists_knobs_and_patches_limits(client):
    roster = {a["id"]: a for a in client.get("/agents").json()}
    assert [k["id"] for k in roster[CURATOR]["knobs"]] == [AUTOSEED, PROFILE]
    assert roster[CURATOR]["governance"]["limits"] == {AUTOSEED: 60, PROFILE: 60_000}
    r = client.patch(f"/agents/{CURATOR}", json={"limits": {AUTOSEED: 25}})
    assert r.status_code == 200 and r.json()["governance"]["limits"][AUTOSEED] == 25
    assert effective_limit(CURATOR, AUTOSEED) == 25
    r = client.patch(f"/agents/{CURATOR}", json={"limits": {"vibes": 1}})
    assert r.status_code == 400 and AUTOSEED in r.json()["detail"]
    r = client.patch(f"/agents/{CURATOR}", json={"limits": {PROFILE: 1}})
    assert r.status_code == 400 and "2,000" in r.json()["detail"]


# ── door: Spotlight Know / Act / Guide + the inbox ──────────────────────────────────

def test_platform_limits_reports_values_where_they_bite_and_the_act():
    from aughor.agent.spotlight_tools import platform_limits
    set_governance(CURATOR, limits={AUTOSEED: 12})
    out = platform_limits({})
    cur = next(a for a in out["agents"] if a["agent_id"] == CURATOR)
    by_id = {l["limit"]: l for l in cur["limits"]}
    assert by_id[AUTOSEED]["value"] == 12 and by_id[AUTOSEED]["default"] == 60
    assert "birth job" in by_id[AUTOSEED]["applies_to"]
    assert "12 tables (default 60)" in out["summary"] and "60,000 chars (the default)" in out["summary"]
    assert out["how_to_change"]["tool"] == "set_agent_limit"
    # The per-run budgets ride along — the whole "what is where" of spend in one read.
    assert "Explorer 200,000" in out["summary"]


def test_set_agent_limit_refuses_in_the_registrys_words():
    import aughor.agent.spotlight_act as act
    assert "Explorer (scout)" in act.set_agent_limit("c", {"agent": "hal", "limit": AUTOSEED,
                                                            "value": 1})["summary"]
    out = act.set_agent_limit("c", {"limit": "vibes", "value": 1})
    assert out["staged"] is False and AUTOSEED in out["summary"] and PROFILE in out["summary"]
    out = act.set_agent_limit("c", {"limit": AUTOSEED, "value": 10_001})
    assert out["staged"] is False and "10,000" in out["summary"]
    out = act.set_agent_limit("c", {"limit": "autoseed tables", "value": 60})
    assert out["staged"] is False and "already 60" in out["summary"]


def test_set_agent_limit_stages_then_accept_applies_and_reject_is_byte_identical():
    import aughor.agent.spotlight_act as act
    from aughor.actions.inbox import accept_proposal, get_proposal, reject_proposal

    out = act.set_agent_limit("conn-l", {"limit": "profile schema chars", "value": 30_000,
                                          "reasoning": "500 GB warehouse"})
    assert out["staged"] is True and out["before"] == 60_000 and out["value"] == 30_000
    assert "60,000 → 30,000 chars" in out["summary"]
    p = get_proposal(out["proposal_id"])
    assert p.kind == "agent_limit" and p.params["agent_id"] == CURATOR
    assert effective_limit(CURATOR, PROFILE) == 60_000            # nothing applied yet

    assert reject_proposal(p.id, actor="tester")
    assert effective_limit(CURATOR, PROFILE) == 60_000            # byte-identical

    out = act.set_agent_limit("conn-l", {"limit": PROFILE, "value": 30_000})
    res, _ = accept_proposal(out["proposal_id"], actor="tester")
    assert res.ok and res.status == "executed"
    assert effective_limit(CURATOR, PROFILE) == 30_000


def test_accept_revalidates_a_tampered_or_stale_limit_proposal():
    from aughor.actions.inbox import StagedProposal, accept_proposal, stage_proposal
    p = stage_proposal(StagedProposal(
        kind="agent_limit", org_id="", connection_id="conn-t", action_id="agent-limit:x",
        params={"agent_id": CURATOR, "limit": "vibes", "value": 3},
        reasoning="tampered", proposer="spotlight", source="agent"))
    res, _ = accept_proposal(p.id, actor="tester")
    assert not res.ok and "vibes" in res.message
    assert effective_governance(CURATOR).limits == {AUTOSEED: 60, PROFILE: 60_000}


def test_guide_limits_topic_resolves_from_plain_words_and_offers_the_act():
    from aughor.agent.spotlight_guide import platform_guide
    for word in ("cap", "budget", "spend", "autoseed", "limits"):
        assert platform_guide({"topic": word})["topic"] == "limits", word
    out = platform_guide({"topic": "limits"})
    assert out["offer"]["tool"] == "set_agent_limit"
    assert "Agent Ops" in out["steps"][0] and "Limits" in out["steps"][0]
    assert "60 tables" in out["summary"]                          # grounded in the live value


def test_the_new_tools_ride_every_transport_through_the_one_roster():
    from aughor.agent.spotlight_roster import spotlight_roster
    names = {t.name for t in spotlight_roster("conn-r")}
    assert {"platform_limits", "set_agent_limit"} <= names
