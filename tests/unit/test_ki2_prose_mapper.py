"""KI-2's deferred half — the LLM prose mapper and its falsifier.

No test here spends a token: `prose.extract` is patched everywhere, and the module
does nothing at import time. What IS tested for real: the deterministic validation
that stands between the model and the lane (nameless drops, formula-less metrics
demote to definitions, synonyms forced to `llm_candidate`), the cross-slice
governance property that an accepted LLM synonym stays OUT of the prompt block until
a human promotes it, and the falsifier itself — the edit-rate is measured from the
lane's own resolutions and published per import.
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.intake import prose

client = TestClient(app)

CONN = "prose_conn"


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_INTAKE_DB", str(tmp_path / "intake.db"))
    monkeypatch.setenv("AUGHOR_TRUSTED_QUERIES_PATH", str(tmp_path / "tq.json"))
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(tmp_path / "glossary.yaml"))
    monkeypatch.setenv("AUGHOR_VOCABULARY_ROOT", str(tmp_path / "vocab"))
    import aughor.semantic.connection_kb as kb
    monkeypatch.setattr(kb, "_DATA_DIR", tmp_path / "kb")
    monkeypatch.setattr(kb, "_index_entry", lambda e: None)
    monkeypatch.setattr(kb, "_delete_from_index", lambda c, i: None)
    monkeypatch.setattr(kb, "_invalidate_linker_hints", lambda c: None)
    return tmp_path


@pytest.fixture()
def demo_conn(tmp_path, monkeypatch):
    dbfile = tmp_path / "prose.duckdb"
    c = duckdb.connect(str(dbfile))
    c.execute("CREATE TABLE orders AS SELECT 1 AS id")
    c.close()
    from aughor.db import connection as conn_mod

    def _open(conn_id, *args, **kwargs):
        if conn_id != CONN:
            raise KeyError(conn_id)
        return conn_mod.DuckDBConnection(dbfile, connection_id=conn_id)

    monkeypatch.setattr(conn_mod, "open_connection_for", _open)
    return CONN


EXTRACTION = prose.ProseExtraction(
    metrics=[
        prose.ExtractedMetric(name="Net Revenue", sql="SUM(amount)", unit="EUR"),
        prose.ExtractedMetric(name="Churn Rate",
                              caveats="Share of customers lost per period."),
        prose.ExtractedMetric(name="   "),   # nameless — dropped
    ],
    definitions=[prose.ExtractedDefinition(
        title="Active customer", body="Ordered within the last 90 days.")],
    synonyms=[prose.ExtractedSynonym(term="takings", means="orders.amount",
                                     subject_kind="column"),
              prose.ExtractedSynonym(term="whales", means="big customers",
                                     subject_kind="segmenty")],  # bad kind → term
    rules=[prose.ExtractedRule(title="Revenue counting",
                               body="Only completed orders count as revenue.")],
    glossary=[prose.ExtractedGlossaryTable(
        table="orders", columns={"amount": "Line total, EUR."})],
)


# ── the deterministic half ───────────────────────────────────────────────────────────


def test_validation_stands_between_the_model_and_the_lane():
    sections = prose.to_sections(EXTRACTION)
    # A stated formula becomes a metric; a described one demotes to a definition.
    assert [m["name"] for m in sections["metrics"]] == ["net_revenue"]
    titles = [d["title"] for d in sections["definitions"]]
    assert titles == ["Churn Rate", "Active customer"]
    assert all(d["tags"] == ["mined:llm"] for d in sections["definitions"])
    # Synonyms are FORCED to llm_candidate; an unknown subject kind degrades to term.
    assert all(s["source"] == "llm_candidate" for s in sections["synonyms"])
    kinds = {s["synonym"]: s["subject_kind"] for s in sections["synonyms"]}
    assert kinds == {"takings": "column", "whales": "term"}
    assert sections["glossary"][0]["columns"]["amount"]["description"] == "Line total, EUR."


def test_empty_extraction_yields_no_sections():
    assert prose.to_sections(prose.ProseExtraction()) == {}


# ── the door, and the governance property that makes it safe ─────────────────────────


def _post_prose(text="Our finance dictionary…", **over):
    return client.post("/intake/prose", json={
        "connection_id": CONN, "actor": "ana@example.com", "text": text, **over})


def test_prose_stages_and_llm_synonyms_stay_out_of_the_prompt(
        stores, demo_conn, monkeypatch):
    monkeypatch.setattr(prose, "extract", lambda text: EXTRACTION)
    r = _post_prose(source="wiki-page")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["bundle"]["source"] == "llm:wiki-page"
    assert body["mapper_stats"]["threshold"] == prose.EDIT_RATE_THRESHOLD

    cands = {(c["kind"], c["payload"].get("synonym") or c["payload"].get("title")
              or c["payload"].get("name") or c["payload"].get("table")): c
             for c in body["candidates"]}
    syn = cands[("synonym", "takings")]

    res = client.post(f"/intake/bundles/{body['bundle']['id']}/resolve",
                      json={"actor": "ana@example.com", "accept": [syn["id"]]})
    assert res.status_code == 200 and res.json()["errors"] == 0

    # The cross-slice law: accepted as llm_candidate ⇒ retrieval widens,
    # prompt does NOT — until a human promotes it.
    from aughor.ontology.vocabulary import add_synonym, build_synonyms_block, synonyms_for
    assert any(s.synonym == "takings" and s.source == "llm_candidate"
               for s in synonyms_for(CONN))
    assert build_synonyms_block(CONN) == ""
    add_synonym(CONN, "column", "orders.amount", "takings", source="human")
    assert '"takings"' in build_synonyms_block(CONN)


def test_edit_rate_is_measured_from_the_lanes_own_resolutions(
        stores, demo_conn, monkeypatch):
    monkeypatch.setattr(prose, "extract", lambda text: EXTRACTION)
    body = _post_prose().json()
    by_kind: dict = {}
    for c in body["candidates"]:
        by_kind.setdefault(c["kind"], []).append(c)

    defs = by_kind["definition"]
    rule = by_kind["rule"][0]
    client.post(f"/intake/bundles/{body['bundle']['id']}/resolve",
                json={"actor": "ana@example.com",
                      "accept": [defs[0]["id"], defs[1]["id"], rule["id"]],
                      "dismiss": [by_kind["metric"][0]["id"]],
                      "edits": {defs[0]["id"]: {
                          "title": defs[0]["payload"]["title"],
                          "body": "Ordered within the last 60 days.",
                          "tags": ["mined:llm"]}}})

    stats = client.get("/intake/mapper-stats").json()
    assert stats["accepted_edited"] == 1 and stats["accepted_clean"] == 2
    assert stats["dismissed"] == 1 and stats["pending"] >= 1
    assert stats["edit_rate"] == round(1 / 3, 3)
    assert stats["threshold"] == 0.5
    # …and the same numbers ride the next import's response (published per import).
    again = _post_prose(text="More prose, same content different text.").json()
    assert again["mapper_stats"]["accepted_edited"] == 1


def test_mapper_failures_answer_plainly_and_text_is_bounded(stores, monkeypatch):
    def _boom(text):
        raise RuntimeError("no binding for role 'coder'")

    monkeypatch.setattr(prose, "extract", _boom)
    r = _post_prose()
    assert r.status_code == 503 and "model binding" in r.json()["detail"]

    r2 = _post_prose(text="x" * (prose.MAX_TEXT_CHARS + 1))
    assert r2.status_code == 413 and "split the document" in r2.json()["detail"]

    monkeypatch.setattr(prose, "extract", lambda text: prose.ProseExtraction())
    r3 = _post_prose()
    assert r3.status_code == 201 and r3.json()["staged"] is False
    assert "nothing" in r3.json()["note"]
