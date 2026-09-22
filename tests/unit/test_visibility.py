"""CB-5 — show how much of the business the platform can see (Arc CB, 2026-09-23).

Measured before this wave: `declarations.Coverage` was imported only by its own test; the departure
gate held sends for a missing approved definition and nobody counted which definition held the most.
These tests pin: the share of tables the ontology maps against the profiler's universe, declared
exclusions out of the denominator; a never-profiled connection says its denominator is unknown
rather than reporting 100%; held sends are grouped by the definition that would clear them, read
structurally from the record (and from the guard's own sentence on older rows), marked ones set
aside; the gate now records the missing definitions structurally; and the doors.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aughor.ontology import visibility as V


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    import aughor.ontology.recommendations as R
    monkeypatch.setattr(R, "_ROOT", tmp_path / "decisions")
    yield


def _graph(*tables):
    return SimpleNamespace(entities={t: SimpleNamespace(source_tables=[t]) for t in tables}, schema_name="main")


UNIVERSE = ["orders", "order_items", "users", "events_raw", "_dbt_tmp"]


class TestTheShareOfTablesSeen:
    def test_mapped_over_the_profilers_universe_with_exclusions_out(self):
        V.declare_exclusion("c1", "main", "_dbt_tmp", "system_table", note="dbt scratch")
        t = V.table_coverage("c1", "main", _graph("orders", "order_items", "users"), universe=UNIVERSE)
        assert (t["total"], t["mapped"], t["excluded"], t["in_scope"]) == (5, 3, 1, 4)
        assert t["share"] == 0.75 and t["band"] == "orange" and t["basis"] == "profiler"
        assert t["unmapped"] == ["events_raw"] and t["exclusions"][0]["table"] == "_dbt_tmp"

    def test_a_never_profiled_connection_has_no_honest_denominator(self):
        t = V.table_coverage("c1", "main", _graph("orders"), universe=[])
        assert t["basis"] == "unknown" and t["share"] is None and t["band"] == "unknown" and "not been profiled" in t["note"]

    def test_an_exclusion_needs_an_honest_reason_and_can_be_withdrawn(self):
        with pytest.raises(ValueError):
            V.declare_exclusion("c1", "main", "events_raw", "dont-care")
        with pytest.raises(ValueError):
            V.declare_exclusion("c1", "main", "", "deprecated")
        V.declare_exclusion("c1", "main", "events_raw", "deprecated")
        V.declare_exclusion("c1", "main", "events_raw", "out_of_domain")           # replaces
        assert [e.reason for e in V.load_exclusions("c1", "main")] == ["out_of_domain"]
        assert V.withdraw_exclusion("c1", "main", "events_raw") is True
        assert V.withdraw_exclusion("c1", "main", "events_raw") is False
        assert V.load_exclusions("c1", "other") == []


def _row(conn="c1", *, missing=None, summary="", automation="auto-1", ts="2026-09-22T10:00:00", verdict=""):
    checks = {"definition": summary}
    if missing:
        checks["definition_missing"] = " · ".join(missing)
    return {"conn_id": conn, "checks": json.dumps(checks), "automation_id": automation, "ts": ts, "verdict": verdict}


class TestTheOneDefinitionHoldingTheMostBack:
    def test_read_structurally_and_from_the_older_sentence(self):
        assert V.missing_definitions_of(_row(missing=["revenue", "gross margin"])) == ["revenue", "gross margin"]
        legacy = ("revenue is stated with a number and its definition is draft, not approved; "
                  "'gross margin' is stated with a number and no approved metric defines it on this connection")
        assert V.missing_definitions_of(_row(summary=legacy)) == ["revenue", "gross margin"]
        assert V.missing_definitions_of(_row(summary="cites metric revenue v2")) == []

    def test_holds_are_counted_per_definition_marked_and_foreign_rows_set_aside(self):
        rows = [_row(missing=["revenue"]), _row(missing=["revenue"], automation="auto-2", ts="2026-09-23T09:00:00"),
                _row(missing=["revenue", "margin"]), _row(missing=["revenue"], verdict="accept"),
                _row(conn="other", missing=["revenue"])]
        groups = V.definition_holds("c1", rows=rows)
        assert groups[0] == {"definition": "revenue", "holds": 3, "automations": ["auto-1", "auto-2"], "latest": "2026-09-23T09:00:00"}
        assert groups[1]["definition"] == "margin" and groups[1]["holds"] == 1

    def test_the_line_a_person_reads(self):
        out = V.visibility("c1", "main", _graph("orders", "users"), universe=["orders", "users", "events_raw"],
                           held_rows=[_row(missing=["revenue"]), _row(missing=["revenue"], automation="auto-2")])
        assert out["top_blocker"]["definition"] == "revenue" and out["top_blocker"]["holds"] == 2
        assert out["line"] == "sees 2 of 3 tables (67%) · approve `revenue` and 2 held sends unblock"
        none = V.visibility("c1", "main", _graph("orders"), universe=[], held_rows=[])
        assert none["top_blocker"] is None and "denominator is unknown" in none["line"]


class TestTheGateRecordsWhatWouldClearAHold:
    def test_the_definition_check_names_the_missing_definitions_structurally(self, monkeypatch):
        from aughor.govern import departure as G
        import aughor.semantic.metrics as M
        import aughor.explorer.metric_coherence as MC
        import aughor.semantic.enforcement as EN
        draft = SimpleNamespace(name="revenue", status="draft", version=1, connection="c1")
        monkeypatch.setattr(M, "list_metrics", lambda path=None, connection_id=None: [draft])
        monkeypatch.setattr(G, "metric_is_approved", lambda m: False)
        monkeypatch.setattr(MC, "asserted_governed_metrics", lambda text, conn_id: [draft])
        monkeypatch.setattr(EN, "propose_undefined_metrics", lambda clause, approved: [{"phrase": "gross margin", "slug": "gross_margin"}])
        chk = G._definition("Revenue was $1.2M and gross margin 41%", "c1", "", "")
        assert chk.outcome == G.HOLDS
        assert chk.detail["missing"] == ["revenue", "gross margin"]


class TestTheDoors:
    def test_visibility_and_exclusions(self, client, monkeypatch):
        import aughor.agent.framing as F
        import aughor.tools.profile_cache as PC
        import aughor.govern.departure_store as DS
        monkeypatch.setattr(F, "served_graph", lambda cid, schema=None: _graph("orders", "users"))
        monkeypatch.setattr(PC, "latest_profiled_tables", lambda cid: ["orders", "users", "events_raw", "_dbt_tmp"])
        monkeypatch.setattr(DS, "list_departures", lambda **k: [_row("fixture", missing=["revenue"])])
        r = client.put("/visibility/exclusions", params={"connection_id": "fixture", "schema_name": "main"},
                       json={"table": "_dbt_tmp", "reason": "system_table"})
        assert r.status_code == 200, r.text
        assert client.put("/visibility/exclusions", params={"connection_id": "fixture", "schema_name": "main"},
                          json={"table": "x", "reason": "nope"}).status_code == 422
        body = client.get("/visibility", params={"connection_id": "fixture", "schema_name": "main"}).json()
        assert body["tables"]["mapped"] == 2 and body["tables"]["in_scope"] == 3 and body["tables"]["excluded"] == 1
        assert body["top_blocker"]["definition"] == "revenue" and body["top_blocker"]["holds"] == 1
        assert body["line"].startswith("sees 2 of 3 tables (67%), 1 excluded")
        assert "system_table" in body["exclusion_reasons"]
        assert client.delete("/visibility/exclusions", params={"connection_id": "fixture", "schema_name": "main", "table": "_dbt_tmp"}).status_code == 200
        assert client.delete("/visibility/exclusions", params={"connection_id": "fixture", "schema_name": "main", "table": "_dbt_tmp"}).status_code == 404
