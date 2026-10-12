"""A table turned off works like a schema turned off (`ontology.visibility.findings_left_out`).

Asked 2026-10-12: turning a table off kept its findings in the Briefing. The explorer stopped reading it and the door
refused new queries, but the findings made before stayed in the story, the lists and the desk; a rebuild's re-check
then re-ran some of them, the door refused, and they were marked invalid as "query no longer runs" — so turning the
table back on did not bring them back. Now they are left out of every Briefing read, said as left out, and come back
when the table is turned back on; the cached story citing one is rewritten; the re-check passes them by.
"""
from __future__ import annotations

import datetime as _dt
import uuid

import pytest

from aughor.ontology.visibility import (
    SCHEMA_WIDE, declare_exclusion, findings_left_out, left_out_said, off_read, refusal_for, withdraw_exclusion,
)

ORDERS = {"id": "luxexperience:sales__trend__1", "domain": "Sales", "finding": "AOV fell to €581.",
          "sql": "SELECT AVG(total) FROM orders"}
ARCHIVE = {"id": "luxexperience:sales__trend__2", "domain": "Sales", "finding": "Archived orders peaked in 2019.",
           "sql": "SELECT COUNT(*) FROM orders_archive a JOIN customers c ON c.id = a.customer_id"}
QUALIFIED = {"id": "luxexperience:ops__1", "domain": "Ops", "finding": "Loads failed 12 times.",
             "sql": "SELECT COUNT(*) FROM luxexperience.etl_load_log"}


def _conn() -> str:
    return f"toff-{uuid.uuid4().hex[:8]}"


def test_nothing_turned_off_returns_the_same_findings_untouched():
    found = {"Sales": [ORDERS, ARCHIVE]}
    kept, out = findings_left_out(_conn(), found, default_schema="luxexperience")
    assert kept is found and out == []


def test_a_finding_reading_a_table_turned_off_is_left_out_and_comes_back_when_it_is_turned_on():
    conn = _conn()
    declare_exclusion(conn, "luxexperience", "orders_archive", "out_of_domain", declared_by="amit")
    declare_exclusion(conn, "luxexperience", "etl_load_log", "system_table", declared_by="amit")
    found = {"Sales": [ORDERS, ARCHIVE], "Ops": [QUALIFIED]}
    kept, out = findings_left_out(conn, found, default_schema="luxexperience")
    assert kept == {"Sales": [ORDERS]}                                    # a domain left empty is not kept
    assert [(r["id"], r["table"], r["reason"], r["schema"]) for r in out] == [
        (ARCHIVE["id"], "luxexperience.orders_archive", "out_of_domain", "luxexperience"),
        (QUALIFIED["id"], "luxexperience.etl_load_log", "system_table", "luxexperience")]
    withdraw_exclusion(conn, "luxexperience", "orders_archive")
    withdraw_exclusion(conn, "luxexperience", "etl_load_log")
    kept, out = findings_left_out(conn, found, default_schema="luxexperience")
    assert kept == found and out == []                                    # nothing was written: they are back


def test_on_a_connection_read_whole_a_finding_is_read_in_its_own_schema():
    conn = _conn()
    declare_exclusion(conn, "gold_finance", "orders_archive", "out_of_domain")
    lux = {**ARCHIVE, "source_schema": "luxexperience"}
    fin = {**ARCHIVE, "id": "gold_finance:x", "source_schema": "gold_finance"}
    kept, out = findings_left_out(conn, {"Sales": [lux, fin]})
    assert kept == {"Sales": [lux]} and [r["id"] for r in out] == ["gold_finance:x"]


def test_a_finding_with_no_query_or_one_that_does_not_parse_is_kept():
    conn = _conn()
    declare_exclusion(conn, "luxexperience", "orders_archive", "out_of_domain")
    bare = {"id": "p", "domain": "Sales", "finding": "Hand-written note.", "sql": ""}
    junk = {"id": "j", "domain": "Sales", "finding": "x", "sql": "not sql at all ((("}
    kept, out = findings_left_out(conn, {"Sales": [bare, junk]}, default_schema="luxexperience")
    assert kept == {"Sales": [bare, junk]} and out == []


def test_the_door_and_the_briefing_read_by_one_rule():
    conn = _conn()
    declare_exclusion(conn, "luxexperience", "orders_archive", "out_of_domain", declared_by="amit")
    assert off_read(conn, ORDERS["sql"], default_schema="luxexperience") is None
    name, hit = off_read(conn, ARCHIVE["sql"], default_schema="luxexperience")
    assert name == "luxexperience.orders_archive" and hit.reason == "out_of_domain"
    assert refusal_for(conn, ARCHIVE["sql"], None, default_schema="luxexperience") == (
        "[EXCLUDED] luxexperience.orders_archive is turned off for analysis — it is excluded (out of domain, by amit)."
        " Turn it back on in the Catalog to use it.")
    declare_exclusion(conn, "luxexperience", SCHEMA_WIDE, "other")
    assert "its schema is excluded" in refusal_for(conn, ORDERS["sql"], None, default_schema="luxexperience")


def test_what_the_briefing_says_about_what_it_left_out():
    assert left_out_said([]) is None
    one = left_out_said([{"table": "luxexperience.orders_archive"}])
    assert one["said"] == ("1 finding read luxexperience.orders_archive, turned off for analysis, and is left out. "
                           "Turn it back on in the Catalog to bring it back.")
    many = left_out_said([{"table": t} for t in ("a", "b", "b", "c", "d")])
    assert many["count"] == 5 and many["tables"] == ["a", "b", "c", "d"]
    assert many["said"].startswith("5 findings read a, b, c and 1 more, turned off for analysis, and are left out. "
                                   "Turn them back on")


# ── the Briefing's reads ──────────────────────────────────────────────────────

@pytest.fixture
def lux_store(tmp_path, monkeypatch):
    from aughor.explorer import store
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    conn = _conn()
    store.save(f"{conn}__luxexperience", {**store._empty(), store.FINDINGS: [dict(ORDERS), dict(ARCHIVE)]})
    return conn


def test_every_briefing_read_leaves_the_finding_out(lux_store):
    from aughor.routers import exploration as ex
    conn = lux_store
    words = lambda: sorted(f["finding"] for items in ex.domain_findings_for(conn, "luxexperience").values()
                           for f in items)
    assert words() == ["AOV fell to €581.", "Archived orders peaked in 2019."]
    declare_exclusion(conn, "luxexperience", "orders_archive", "out_of_domain")
    assert words() == ["AOV fell to €581."]
    kept, out = ex.findings_and_left_out(conn, "luxexperience")
    assert [r["id"] for r in out] == [ARCHIVE["id"]]
    from aughor.knowledge.period_brief import connection_inputs
    assert [f["finding"] for items in connection_inputs(conn)[0].values() for f in items] == ["AOV fell to €581."]


def test_the_briefing_says_what_it_left_out(lux_store, monkeypatch):
    from aughor.routers import exploration as ex
    conn = lux_store
    declare_exclusion(conn, "luxexperience", "orders_archive", "out_of_domain")
    monkeypatch.setattr("aughor.routers._shared.canonical_schema", lambda c, s: s)
    seen: dict = {}

    def fake_briefing(**kw):
        seen["findings"] = [f["finding"] for items in kw["domain_data"].values() for f in items]
        return {"narrative": "AOV fell [1].", "citations": [], "generated_at": None}

    monkeypatch.setattr("aughor.knowledge.briefing.get_briefing", fake_briefing)
    monkeypatch.setattr("aughor.knowledge.patterns.get_patterns", lambda *a, **k: [])
    for name in ("_load_business_profile", "_connection_col_types", "_metric_moves_provider", "_promise_chains_provider"):
        monkeypatch.setattr(ex, name, lambda *a, **k: None)
    out = ex.generate_briefing(conn, schema="luxexperience")
    assert seen["findings"] == ["AOV fell to €581."]
    assert out["left_out"]["count"] == 1 and out["left_out"]["tables"] == ["luxexperience.orders_archive"]


# ── the cached story ──────────────────────────────────────────────────────────

ENTRY = {"narrative": "Archived orders peaked [1].", "generated_at": "2026-10-12T08:00:00+00:00",
         "citations": [{"ref": "1", "domain": "Sales", "angle": "", "finding": "x",
                        "sql": ARCHIVE["sql"]}]}


def test_a_cached_story_citing_a_table_turned_off_since_is_rewritten(monkeypatch):
    from aughor.knowledge import briefing as B
    conn = _conn()

    class Cache:
        def get(self, key):
            return dict(ENTRY)

        def put(self, key, value):
            raise AssertionError("not reached")

    class Rewritten(Exception):
        pass

    def narrator(*a, **k):
        raise Rewritten

    monkeypatch.setattr(B, "_store", lambda: Cache())
    monkeypatch.setattr(B, "_brief_rebuild_decision", lambda *a: (False, None))
    monkeypatch.setattr(B, "_kept_version", lambda *a: {})
    monkeypatch.setattr(B, "generate_narrative", narrator)
    key = f"{conn}:luxexperience"
    assert B.get_briefing(connection_id=conn, domain_data={}, patterns=[], scope_key=key)["narrative"] == ENTRY["narrative"]
    assert not B.cites_turned_off(conn, ENTRY, key)
    declare_exclusion(conn, "luxexperience", "orders_archive", "out_of_domain")
    assert B.cites_turned_off(conn, ENTRY, key)
    assert B.cites_turned_off(conn, ENTRY, f"{key}#range:month:2026-09")           # a range edition's key
    assert not B.cites_turned_off(conn, {**ENTRY, "citations": [{**ENTRY["citations"][0], "sql": ""}]}, key)
    with pytest.raises(Rewritten):
        B.get_briefing(connection_id=conn, domain_data={}, patterns=[], scope_key=key)


# ── the re-check before a Briefing ────────────────────────────────────────────

def test_the_recheck_passes_a_turned_off_finding_by_and_never_marks_it_invalid(lux_store, monkeypatch):
    from aughor.explorer import revalidate_live as R
    from aughor.explorer import store
    conn = lux_store
    declare_exclusion(conn, "luxexperience", "orders_archive", "out_of_domain")
    ran: list[str] = []

    class Db:
        def execute(self, label, sql):
            ran.append(sql)
            return type("Res", (), {"error": "boom", "rows": []})()

    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema", lambda *a, **k: Db())
    R._revalidate_one_run(conn, f"{conn}__luxexperience", "luxexperience", 10)
    assert ran == [ORDERS["sql"]]
    held = {f["id"]: f for f in store.get_findings(f"{conn}__luxexperience", include_invalid=True)}
    assert not held[ARCHIVE["id"]].get("invalid")
    assert held[ORDERS["id"]].get("invalid")                                    # the check itself still works


# ── the desk ──────────────────────────────────────────────────────────────────

def test_the_desk_drops_a_claim_that_stands_on_a_table_turned_off(monkeypatch):
    from aughor.briefing import desk as D
    from aughor.record.claims import About, Claim, Statement
    conn = _conn()
    now = _dt.datetime(2026, 10, 12, 12, 0, tzinfo=_dt.timezone.utc)

    def claim(text, **extra):
        return Claim(kind=extra.pop("kind", "finding"), about=About(kind="connection", key=conn),
                     statement=Statement(text=text), tier="measured", status="Provisional", as_of="2026-10-11",
                     recorded_at=(now - _dt.timedelta(days=1)).isoformat(), extra=extra,
                     id=f"id-{abs(hash(text)) % 10**6}")

    claims = [claim("Archive Volume Trend: archived orders climbed.", writer="explorer",
                    finding_id=ARCHIVE["id"], schema="luxexperience"),
              claim("Order Value Trend: AOV slipped.", writer="explorer", finding_id=ORDERS["id"], schema="luxexperience"),
              claim("Archived revenue rose 4% in September 2026", kind="observation", investigation_id="inv1",
                    question="Why did archived revenue rise?", sql=ARCHIVE["sql"])]
    from aughor.record import claims as C
    from aughor.record import inquiry as I
    from aughor.semantic import metrics as SM
    monkeypatch.setattr(C, "list_claims", lambda **_: claims)
    monkeypatch.setattr(I, "list_inquiries", lambda **_: [])
    monkeypatch.setattr(SM, "list_metrics", lambda **_: [])
    titles = lambda **kw: [t["title"] for t in D.desk(conn, "luxexperience", now=now, **kw)["trends"]["items"]]
    assert titles() == ["Archive Volume Trend", "Order Value Trend", "Archived revenue rose 4% in September 2026"]
    declare_exclusion(conn, "luxexperience", "orders_archive", "out_of_domain")
    left = [{"id": ARCHIVE["id"], "schema": "luxexperience", "table": "luxexperience.orders_archive"}]
    assert titles(left_out=left) == ["Order Value Trend"]
    other = [{"id": ARCHIVE["id"], "schema": "gold_finance", "table": "gold_finance.orders_archive"}]
    assert "Archive Volume Trend" in titles(left_out=other)                     # same id, another schema's finding
