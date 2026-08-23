"""CI-2 — the platform tool roster, and the claims that make it safe to hand a model.

Three claims worth a test file. The roster reuses the MCP knowledge bodies rather than
re-reading the stores (one body, two callers — the surfaces cannot disagree). The read
tier is actually read-only — most of all `get_briefing`, which must NEVER reach the
synthesizing path, because a lookup that can spend an LLM call on a cache miss is a
write dressed as a read. And every result is capped for the context window, with the
cut always declared — a silently-shortened list reads as "that is everything".
"""
from __future__ import annotations

from types import SimpleNamespace


from aughor.agent import converse_tools as ct
from aughor.agent import platform_tools as pt


# ── roster composition ───────────────────────────────────────────────────────────────

def test_the_platform_roster_rides_the_converse_tool_set():
    """CI-2's point: the conversation routes over ONE list — warehouse core plus the
    platform reads. A separate registry would be a second roster to drift."""
    names = [s.name for s in ct.converse_tools("c1")]

    for expected in ("answer_question", "run_sql", "list_tables", "describe_table",
                     "search_graph", "describe_entity", "list_findings", "get_briefing",
                     "get_table_health", "list_trusted_queries", "list_monitors",
                     "list_packs", "platform_help"):
        assert expected in names, f"{expected} missing from the roster"


def test_platform_tools_bind_the_connection_by_closure():
    """Same rule as the core four: a tool that cannot express the wrong connection
    cannot be talked into it."""
    for spec in pt.platform_tools("c1"):
        props = spec.parameters.get("properties", {})
        assert "connection" not in props and "connection_id" not in props, spec.name


# ── the shared MCP bodies ────────────────────────────────────────────────────────────

def test_search_graph_calls_the_shared_body_and_compacts_for_the_window(monkeypatch):
    """One body, two callers: the converse tool must reach the SAME `knowledge_tools`
    read the MCP server exposes — and then trim the `data` blobs, because routing needs
    labels while `describe_entity` is the paid detail."""
    seen = {}

    def _search(cid, query, *, limit):
        seen.update(cid=cid, query=query, limit=limit)
        return {"available": True, "count": 1, "notice": "", "nodes": [
            {"id": "t1", "kind": "table", "label": "orders", "summary": "order facts",
             "data": {"source_tables": ["orders"], "columns": ["a"] * 200}},
        ]}

    monkeypatch.setattr("aughor.mcp.knowledge_tools.search_graph", _search)
    monkeypatch.setattr(pt, "_graph_staleness", lambda cid: "fresh")

    out = pt.search_graph("c1", {"query": "orders"})

    assert seen == {"cid": "c1", "query": "orders", "limit": pt._MAX_SEARCH_HITS}
    assert out["nodes"] == [{"id": "t1", "kind": "table", "label": "orders",
                             "summary": "order facts"}]
    assert out["staleness"] == "fresh"


def test_search_staleness_rides_the_result(monkeypatch):
    """A hit from a stale graph is a different claim than one from a fresh graph, and
    the model has no other way to know which it is making."""
    monkeypatch.setattr("aughor.mcp.knowledge_tools.search_graph",
                        lambda cid, q, limit: {"available": True, "nodes": []})
    monkeypatch.setattr("aughor.ontology.graph_freshness.staleness_of",
                        lambda cid: "stale")

    assert pt.search_graph("c1", {"query": "x"})["staleness"] == "stale"


def test_search_without_a_query_is_an_answer_not_a_crash():
    assert "error" in pt.search_graph("c1", {})


def test_describe_entity_caps_related_edges_and_says_so(monkeypatch):
    monkeypatch.setattr(
        "aughor.mcp.knowledge_tools.describe_entity",
        lambda cid, e: {"available": True, "entity": {"label": e},
                        "related": [{"edge": "join", "node_id": f"n{i}"}
                                    for i in range(50)]})

    out = pt.describe_entity("c1", {"entity": "orders"})

    assert len(out["related"]) == pt._MAX_RELATED
    assert out["related_truncated"] is True


# ── findings ─────────────────────────────────────────────────────────────────────────

def test_findings_filter_the_quarantined_and_declare_the_cut(monkeypatch):
    """A finding the user dismissed must not resurface in chat wearing fresh
    confidence — and a capped list must say it was capped, or the model reports
    twelve findings as the whole story."""
    stored = ([{"id": f"i{n}", "finding": f"f{n}", "domain": "sales",
                "confidence": 0.9, "novelty": 0.5, "sql": "SELECT 1" * 200}
               for n in range(20)]
              + [{"id": "bad", "finding": "dismissed", "invalid": True}])
    monkeypatch.setattr("aughor.explorer.store.schema_run_keys", lambda cid: [])
    # The fake state must carry the store's legacy key, exactly as the real one does.
    monkeypatch.setattr("aughor.explorer.store.load",
                        lambda cid: {"phase": "complete", "insights": stored})

    out = pt.list_findings("c1", {})

    assert out["count"] == 20, "the quarantined finding must not even be counted"
    assert len(out["findings"]) == pt._MAX_FINDINGS
    assert out["truncated"] is True
    assert all(f["id"] != "bad" for f in out["findings"])
    assert all(len(f.get("sql", "")) <= pt._SQL_PREVIEW for f in out["findings"])


def test_findings_resolve_the_aggregate_for_per_schema_runs(monkeypatch):
    """The same resolution the findings endpoint does: a connection explored per-schema
    answers from the aggregate, not the empty connection-level state."""
    monkeypatch.setattr("aughor.explorer.store.schema_run_keys",
                        lambda cid: [f"{cid}__main"])
    monkeypatch.setattr("aughor.explorer.store.load_aggregate",
                        lambda cid: {"phase": "complete",
                                     "insights": [{"id": "i1", "finding": "f"}]})

    assert pt.list_findings("c1", {})["count"] == 1


# ── the briefing read ────────────────────────────────────────────────────────────────

def test_get_briefing_never_synthesizes(monkeypatch):
    """THE read-only claim. `get_briefing` (the generating read) costs an LLM call plus
    a coverage fan-out on a miss — if the tool can reach it, a lookup became the most
    expensive sentence in the product."""
    def _forbidden(*a, **k):
        raise AssertionError("the read tool reached the synthesizing path")

    monkeypatch.setattr("aughor.knowledge.briefing.get_briefing", _forbidden)
    monkeypatch.setattr("aughor.knowledge.briefing.peek_briefing", lambda key: None)
    monkeypatch.setattr("aughor.explorer.store.schema_run_keys", lambda cid: [])

    out = pt.get_briefing("c1", {})

    assert out["available"] is False
    assert "Briefing page" in out["reason"], "absent must say where it gets built"


def test_per_schema_briefs_are_named_not_denied(monkeypatch):
    """A connection explored per-schema caches briefs under `{conn}:{schema}`. The bare
    peek missing them must not become 'no briefing exists' while the Briefing page is
    showing one — the reason may never claim more absence than is true."""
    briefs = {"c1:main": {"narrative": "n1"}, "c1:scm": {"narrative": "n2"}}
    monkeypatch.setattr("aughor.knowledge.briefing.peek_briefing", briefs.get)
    monkeypatch.setattr("aughor.explorer.store.schema_run_keys",
                        lambda cid: ["c1__main", "c1__scm", "c1__empty"])

    out = pt.get_briefing("c1", {})

    assert out["available"] is False
    assert "main" in out["reason"] and "scm" in out["reason"]
    assert "empty" not in out["reason"], "a schema with no brief must not be offered"

    # And the named schema is servable on the second call.
    assert pt.get_briefing("c1", {"schema": "scm"})["narrative"] == "n2"


def test_a_single_schema_brief_is_served_without_a_second_call(monkeypatch):
    briefs = {"c1:main": {"narrative": "only one"}}
    monkeypatch.setattr("aughor.knowledge.briefing.peek_briefing", briefs.get)
    monkeypatch.setattr("aughor.explorer.store.schema_run_keys",
                        lambda cid: ["c1__main"])

    out = pt.get_briefing("c1", {})

    assert out["available"] is True
    assert out["narrative"] == "only one"
    assert out["schema"] == "main", "the served scope must be named"


def test_a_cached_briefing_is_served_with_capped_citations(monkeypatch):
    monkeypatch.setattr(
        "aughor.knowledge.briefing.peek_briefing",
        lambda key: {"narrative": "Revenue is up.", "headline_theme": "growth",
                     "citations": [{"id": f"c{i}"} for i in range(30)],
                     "generated_at": "2026-08-12T00:00:00Z"})

    out = pt.get_briefing("c1", {})

    assert out["available"] is True
    assert out["narrative"] == "Revenue is up."
    assert len(out["citations"]) == pt._MAX_CITATIONS
    assert out["citations_truncated"] is True


# ── monitors ─────────────────────────────────────────────────────────────────────────

def test_monitors_report_watch_state_and_unacknowledged_alerts(monkeypatch):
    mon = SimpleNamespace(id="m1", name="Revenue drop", metric_name="revenue",
                          freshness_table=None, alert_on="threshold", enabled=True,
                          check_cron="0 * * * *")
    alert = SimpleNamespace(monitor_name="Revenue drop", severity="critical",
                            triggered_at="2026-08-12T09:00:00Z", message="x" * 500)
    monkeypatch.setattr("aughor.monitors.store.list_monitors", lambda cid: [mon])
    monkeypatch.setattr("aughor.monitors.store.get_alerts",
                        lambda **kw: [alert] * 7)

    out = pt.list_monitors("c1", {})

    assert out["count"] == 1
    assert out["monitors"][0]["watches"] == "revenue"
    assert out["unacknowledged_alerts"] == 7, "the true count must survive the preview"
    assert len(out["recent_alerts"]) == pt._MAX_ALERTS
    assert len(out["recent_alerts"][0]["message"]) <= 200


# ── packs ────────────────────────────────────────────────────────────────────────────

def test_packs_name_the_bound_one_and_carry_its_playbooks(monkeypatch, tmp_path):
    """The bound pack is the one whose detail a conversation can use — and only that
    one is loaded past its manifest."""
    playbook = SimpleNamespace(trigger_metric="gmv", trigger_operator="<",
                               trigger_condition="baseline", recommendation="r" * 500)
    from aughor.packs.loader import PROSE_FIELD
    pack = SimpleNamespace(
        manifest=SimpleNamespace(name="Finance", status="active", domains=["finance"],
                                 partial=False, source="", source_url="", licence=""),
        playbooks=[playbook], **{PROSE_FIELD: "Reads the P&L before the dashboard."})
    # The AUTHORED root, through its env override: reads now resolve via
    # `packs.roots`, which spans two directories, so patching one module constant
    # no longer redirects them.
    monkeypatch.setenv("AUGHOR_PACKS_DIR", str(tmp_path))
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path / "_none"))
    # The tool resolves ids through `packs.roots` now, and the fake pack is not on disk,
    # so the resolution is stubbed alongside the loader it feeds.
    monkeypatch.setattr("aughor.packs.roots.all_pack_ids", lambda: ["finance"])
    monkeypatch.setattr("aughor.packs.roots.pack_dir", lambda pid: tmp_path / pid)
    monkeypatch.setattr("aughor.packs.load_pack", lambda root: pack)
    monkeypatch.setattr("aughor.packs.load_binding",
                        lambda pid, cid, schema="": {"pack": pid})

    out = pt.list_packs("c1", {})

    entry = out["packs"][0]
    assert entry["bound_to_this_connection"] is True
    assert entry["playbooks"][0]["trigger"] == "gmv < baseline"
    assert len(entry["playbooks"][0]["recommendation"]) <= 200


def test_an_unloadable_pack_is_listed_not_hidden(monkeypatch, tmp_path):
    """A pack that fails validation still EXISTS — hiding it would have the model deny
    what the packs page shows."""
    def _boom(root):
        raise ValueError("bad manifest")

    # The AUTHORED root, through its env override: reads now resolve via
    # `packs.roots`, which spans two directories, so patching one module constant
    # no longer redirects them.
    monkeypatch.setenv("AUGHOR_PACKS_DIR", str(tmp_path))
    monkeypatch.setenv("AUGHOR_IMPORTED_PACKS_DIR", str(tmp_path / "_none"))
    monkeypatch.setattr("aughor.packs.roots.all_pack_ids", lambda: ["broken"])
    monkeypatch.setattr("aughor.packs.roots.pack_dir", lambda pid: tmp_path / pid)
    monkeypatch.setattr("aughor.packs.load_pack", _boom)

    out = pt.list_packs("c1", {})

    assert out["packs"][0]["id"] == "broken"
    assert out["packs"][0]["error"] == "pack failed to load"


# ── platform help ────────────────────────────────────────────────────────────────────

def test_help_answers_the_product_question():
    out = pt.platform_help("c1", {"topic": "connect"})

    assert out["topic"] == "connect"
    assert "Snowflake" in out["help"]


def test_help_routes_aliases_to_their_topic():
    assert pt.platform_help("c1", {"topic": "snowflake"})["topic"] == "connect"


def test_an_unknown_topic_answers_with_the_overview_and_the_topic_list():
    """P2: name what CAN be asked instead of guessing at what was."""
    out = pt.platform_help("c1", {"topic": "quantum"})

    assert out["note"]
    assert out["help"] == pt._HELP_TOPICS["overview"]
    assert set(out["topics"]) == set(pt._HELP_TOPICS)


# ── through the loop ─────────────────────────────────────────────────────────────────

def test_the_loop_can_choose_a_platform_tool(monkeypatch):
    """Loop-level proof for the roster: the model names `platform_help`, the loop finds
    it in the converse set, and the curated answer survives the JSON hop back."""
    from aughor.llm.faux import FauxToolCall, set_responses
    from aughor.llm.provider import LLMProvider

    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    set_responses([
        FauxToolCall(payload={"topic": "connect"}, name="platform_help"),
        "add it from the Connections page",
    ])

    result = ct.converse("c1", "how do I connect Snowflake?",
                         provider=LLMProvider(backend="faux", role="coder"))

    assert result.answer == "add it from the Connections page"
    assert [s.tool for s in result.steps] == ["platform_help"]
    assert result.steps[0].ok is True


# ── org context in the conversation prompt ───────────────────────────────────────────

def test_org_context_reaches_the_converse_prompt(monkeypatch):
    """CI-2: the declared org identity `/ask` already injects reaches the conversation
    too — the most conversational surface must not be the one that cannot see facts
    the operator explicitly stated."""
    import aughor.orgsettings as og

    monkeypatch.setattr(
        og, "org_context",
        lambda **kw: f"ORGANIZATION reading {kw.get('reading')}: industry: retail.\n")

    prompt = ct.converse_system_prompt("c1")

    assert "industry: retail" in prompt
    assert "this conversation" in prompt, "the block must name THIS artifact, not a brief"


def test_an_unconfigured_org_leaves_the_prompt_unpolluted(monkeypatch):
    import aughor.orgsettings as og

    monkeypatch.setattr(og, "org_context", lambda **kw: "")

    assert "ORGANIZATION" not in ct.converse_system_prompt("c1")


def test_a_broken_org_store_does_not_break_the_conversation(monkeypatch):
    """Additive means additive: the conversation stands without it."""
    import aughor.orgsettings as og

    def _boom(**kw):
        raise RuntimeError("store down")

    monkeypatch.setattr(og, "org_context", _boom)

    assert "c1" in ct.converse_system_prompt("c1")
