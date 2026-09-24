"""MI-3 — graded rows become a versioned, provenanced corpus.

The three receipts §3.9 asks for are the first three tests: the same corpus exports to the
same content hash, provenance walks a dataset back to the verdicts that fed it, and a
golden set actually SHOWS UP in the evals plane rather than merely existing in our own
store. The rest guard properties that are easy to lose later — disjointness, scrubbing,
and the fact that purging bytes must not erase the record of what was built.
"""
from __future__ import annotations

import pytest

from aughor.feedback.verdicts import record_verdict
from aughor.learning import exporters, store


def _asked(question: str, sql: str, connection_id: str = "conn-1") -> str:
    """A real answer to grade — its row carries the QUESTION the corpus prompts with and the SQL it RAN. The verdicts
    here used to name answers that did not exist, with a headline phrased like a question, which is what hid the
    exporter prompting with the headline; and a verdict's SQL now counts only when its answer ran it (PENDING
    item 23)."""
    from aughor.db.history import save_chat_turn
    return save_chat_turn(question=question, connection_id=connection_id, headline="an answer", sql=sql,
                          columns=["n"], rows=[[1]])


@pytest.fixture(autouse=True)
def _corrections_run(monkeypatch):
    """No warehouse stands behind `conn-1`; a correction's dry run is stubbed to bind (its refusal is pinned below)."""
    monkeypatch.setattr(exporters, "_runs", lambda connection_id, sql, cache: "")


def _seed(n: int = 12) -> None:
    """Accepted answers that carry SQL — the shape the live store does NOT yet have. The store is shared by every
    test here, so each test's own rows carry SQL no other test writes, and its assertions read its own prompts."""
    for i in range(n):
        record_verdict("conn-1", _asked(f"revenue question {i}", f"SELECT {i} AS seeded FROM orders"), "accept", headline=f"revenue answer {i}",
                       sql_source=f"SELECT {i} AS seeded FROM orders")


def _trained_on(question: str) -> str:
    """A question the stable split trains on — asserted, so a test that needs its row in a trainable corpus says
    so instead of passing by the luck of the hash."""
    assert not exporters._held_out(question), f"{question!r} is in the held-out tenth; pick another"
    return question


def _prompts(node: dict) -> set[str]:
    return {r["prompt"] for r in store.rows_of(node)}


# ── receipt 1: determinism ───────────────────────────────────────────────────────────

def test_the_same_corpus_exports_to_the_same_hash_and_makes_no_new_version():
    """An adapter's provenance cites a dataset by content. If an unchanged corpus produced
    a new hash — or a new version — every export would invalidate every citation."""
    _seed()
    first = exporters.export_sft(name="det-sft")
    second = exporters.export_sft(name="det-sft")

    assert first["data_id"] == second["data_id"], "identical rows produced different hashes"
    assert first["version"] == second["version"] == 1, "an unchanged corpus minted a version"


def test_a_grown_corpus_does_make_a_new_version():
    """The other direction, or the test above is satisfied by an exporter that never works."""
    _seed(3)
    v1 = exporters.export_sft(name="grow-sft")
    record_verdict("conn-1", _asked("new question", "SELECT 999 FROM orders"), "accept", headline="new question",
                   sql_source="SELECT 999 FROM orders")
    v2 = exporters.export_sft(name="grow-sft")

    assert v2["version"] == v1["version"] + 1
    assert v2["data_id"] != v1["data_id"]


# ── receipt 2: provenance ────────────────────────────────────────────────────────────

def test_provenance_walks_a_dataset_back_to_the_verdicts_that_fed_it():
    """The question MI-4 owes any adapter it promotes: whose judgements are in here."""
    _seed(5)
    node = exporters.export_sft(name="prov-sft")
    lineage = store.lineage_of(node["id"])

    assert lineage, "a dataset with no recorded lineage is unauditable"
    # KI-4 widened the corpus: human-approved trusted queries export too, under their
    # own lineage kind. The seeded verdicts must all be present; a trusted_query row
    # appearing beside them is the new contract, not contamination.
    kinds = {row["source_kind"] for row in lineage}
    assert "finding_verdict" in kinds and kinds <= {"finding_verdict", "trusted_query"}
    assert len(lineage) >= node["row_count"]


# ── receipt 3: the golden set reaches the plane that measures ────────────────────────

def test_a_golden_set_shows_up_in_the_evals_plane():
    """`golden` in our own store proves only that we wrote one. The evals plane is where
    promotion gates are enforced."""
    from aughor.evals import store as evals_store

    _seed(60)                       # enough that the 1-in-10 hold-out is non-empty
    node = exporters.export_golden(name="gold-set")
    assert node["row_count"] > 0, "the hold-out is empty — the split never fires"

    suite_id = exporters.publish_golden_to_evals(node)
    assert suite_id, "a golden set that reaches no suite is a measuring stick nobody uses"
    cases = evals_store.list_cases(suite_id)
    assert len(cases) == node["row_count"]
    assert all("golden" in c["tags"] for c in cases)


def test_publishing_the_same_golden_version_twice_is_idempotent():
    _seed(60)
    node = exporters.export_golden(name="gold-idem")
    first = exporters.publish_golden_to_evals(node)
    assert exporters.publish_golden_to_evals(node) == first


def test_only_a_golden_dataset_may_enter_the_evals_plane():
    import pytest
    _seed(5)
    sft = exporters.export_sft(name="not-golden")
    with pytest.raises(ValueError, match="only a golden dataset"):
        exporters.publish_golden_to_evals(sft)


# ── the properties that are easy to lose ─────────────────────────────────────────────

def test_golden_and_sft_are_disjoint():
    """A corpus that trains on its own benchmark cannot be measured by it. The split is a
    stable hash, so this holds across re-exports rather than by luck — by question AND by SQL."""
    _seed(60)
    sft = store.rows_of(exporters.export_sft(name="dis-sft"))
    golden = store.rows_of(exporters.export_golden(name="dis-gold"))

    assert sft and golden, "one side is empty — disjointness would be trivially true"
    assert not ({r["prompt"] for r in sft} & {r["prompt"] for r in golden})
    assert not ({r["completion"] for r in sft} & {r["completion"] for r in golden})


def test_a_question_asked_many_times_is_held_out_every_time():
    """PENDING item 23: the split was keyed on the ANSWER's id, so one question asked ten times — the commonest shape
    of a real corpus — landed on both sides nearly always (1 − 0.9¹⁰ − 0.1¹⁰), and the model trained on the question
    it was then measured by. Keyed on the question, it is held out every time or never."""
    question = "how much revenue did we make in March?"
    assert exporters._held_out(question)
    for _ in range(10):
        record_verdict("conn-1", _asked(question, "SELECT SUM(amount) AS march FROM orders WHERE month = 3"), "accept", headline="Revenue in March was $1.2M",
                       sql_source="SELECT SUM(amount) AS march FROM orders WHERE month = 3")
    assert question in _prompts(exporters.export_golden(name="many-gold"))
    assert question not in _prompts(exporters.export_sft(name="many-sft"))


def test_a_paraphrase_of_a_golden_question_is_not_trained_on():
    """The question hash cannot see a paraphrase; the golden row's SQL can. One query under two wordings is one
    example, and it is the benchmark's."""
    golden_sql = "SELECT SUM(amount) AS feb FROM orders WHERE month = 2"
    held = next(q for q in (f"how much revenue did we make in February, take {i}?" for i in range(200))
                if exporters._held_out(q))
    record_verdict("conn-1", _asked(held, golden_sql), "accept", headline="x", sql_source=golden_sql)
    record_verdict("conn-1", _asked(_trained_on("February revenue in total"), golden_sql), "accept", headline="x",
                   sql_source=golden_sql)
    sft = store.rows_of(exporters.export_sft(name="paraphrase-sft"))
    assert not any(r["completion"] == golden_sql for r in sft)
    assert golden_sql in {r["completion"] for r in store.rows_of(exporters.export_golden(name="paraphrase-gold"))}


def test_agent_goldens_feed_the_golden_set_whole_and_never_sft():
    """The third graded source (joined 2026-09-06): per-agent goldens are human-verified
    (question, reference_sql) pairs — and they ARE each agent's own eval suite, so they
    enter the golden set WHOLE (no tenth-split) and must never appear in SFT, or an
    adapter would train on the very cases its agent is measured by."""
    from aughor.custom_agents.store import add_golden, create_agent

    agent = create_agent("Golden Feeder", instructions="answers golden questions")
    for i in range(3):
        add_golden(agent.id, f"agent question {i}", f"SELECT {i} FROM agent_table")

    golden = exporters.export_golden(name="ag-golden")
    sft = exporters.export_sft(name="ag-sft")

    golden_prompts = {r["prompt"] for r in store.rows_of(golden)}
    sft_prompts = {r["prompt"] for r in store.rows_of(sft)}
    assert {"agent question 0", "agent question 1", "agent question 2"} <= golden_prompts
    assert not any(p.startswith("agent question") for p in sft_prompts)
    # Provenance names the source kind, so MI-4 can answer "which humans fed this".
    kinds = {entry["source_kind"] for entry in store.lineage_of(golden["id"])}
    assert "agent_golden" in kinds


def test_a_correct_verdict_without_a_correction_is_not_a_preference_pair():
    """A `correct` verdict with no `corrected_sql` is a judgement without a lesson.
    Including it would fabricate a preference nobody expressed — and on the live store
    2026-09-03 that is EVERY `correct` row."""
    question = _trained_on("close but wrong")
    record_verdict("conn-1", _asked(question, "SELECT 1"), "correct", headline="close but wrong",
                   sql_source="SELECT 1")
    record_verdict("conn-1", _asked(question, "SELECT 1"), "correct", headline="close but wrong",
                   sql_source="SELECT 1", corrected_sql="SELECT 2")

    rows = [r for r in store.rows_of(exporters.export_dpo(name="dpo-pairs")) if r["prompt"] == question]
    assert len(rows) == 1
    assert rows[0]["completion"] == "SELECT 2"
    assert rows[0]["rejected"] == "SELECT 1"


def test_examples_are_deduped():
    question = _trained_on("same question")
    for _ in range(4):
        record_verdict("conn-1", _asked(question, "SELECT 'dedupe' FROM orders"), "accept", headline="same question",
                       sql_source="SELECT 'dedupe' FROM orders")
    rows = store.rows_of(exporters.export_sft(name="dedupe-sft"))
    assert len([r for r in rows if r["prompt"] == question]) == 1


def test_text_is_scrubbed_on_the_way_out():
    record_verdict("conn-1", _asked(_trained_on("what did alice@example.com order"), "SELECT 'pii' FROM orders"), "accept",
                   headline="what did alice@example.com order",
                   sql_source="SELECT 'pii' FROM orders")
    rows = store.rows_of(exporters.export_sft(name="pii-sft"))
    joined = " ".join(r["prompt"] for r in rows)
    assert "alice@example.com" not in joined, "an email left the box in a training corpus"
    # Assert the POSITIVE too. `_scrub` fails closed by returning "", so an absence check
    # alone would pass just as happily if scrubbing had broken entirely and blanked every
    # example — a failed probe and a true negative look identical.
    assert "what did" in joined and "order" in joined, \
        "scrubbing blanked the text instead of redacting it"


def test_purging_bytes_keeps_the_node_and_its_lineage():
    """§6.7's annex implies withdrawal without amnesia: a corpus can be removed while the
    record that it existed, and what it was built from, survives."""
    _seed(5)
    node = exporters.export_sft(name="purge-sft")
    assert store.purge_bytes(node["data_id"]) is True

    assert store.rows_of(node) == [], "bytes survived a purge"
    assert store.get("purge-sft") is not None, "the node vanished with its bytes"
    assert store.lineage_of(node["id"]), "provenance did not survive the purge"
    assert store.purge_bytes(node["data_id"]) is False, "purge is not idempotent"


def test_gate_status_reports_distance_to_mi4():
    """The arc stays falsifiable only if the distance to its own entry gates is a number
    somebody can read."""
    _seed(5)
    exporters.export_sft(name="gate-sft")
    gates = exporters.gate_status()

    assert gates["sft"]["need"] == 1000 and gates["dpo"]["need"] == 150
    assert gates["sft"]["have"] >= 1
    assert gates["sft"]["passes"] is False, "5 seeded rows cannot pass a 1,000-pair gate"


# ── PENDING item 23 — what the corpora now refuse to learn from ─────────────────────────

def test_the_prompt_is_the_question_asked_never_the_answers_headline():
    """Read across both sides of the split: which side this question lands on is the hash's business, not this
    test's."""
    record_verdict("conn-1", _asked("how much revenue did we make in March?", "SELECT SUM(amount) FROM orders"), "accept",
                   headline="Revenue in March was $1.2M", sql_source="SELECT SUM(amount) FROM orders")
    prompts = (_prompts(exporters.export_sft(name="question-sft"))
               | _prompts(exporters.export_golden(name="question-gold")))
    assert "how much revenue did we make in March?" in prompts
    assert "Revenue in March was $1.2M" not in prompts


def test_a_verdict_on_an_answer_nobody_asked_is_left_out():
    """An explorer finding has no question — its headline states what its SQL found."""
    record_verdict("conn-1", "finding-77", "accept", headline="Premium share grew to 31%",
                   sql_source="SELECT 77 FROM orders")
    for node in (exporters.export_sft(name="noquestion-sft"), exporters.export_golden(name="noquestion-gold")):
        assert not any(r["completion"] == "SELECT 77 FROM orders" for r in store.rows_of(node))


def test_a_later_reject_overrules_an_earlier_accept():
    question = _trained_on("how many orders shipped late?")
    inv = _asked(question, "SELECT 'late' FROM orders")
    record_verdict("conn-1", inv, "accept", headline="12 orders", sql_source="SELECT 'late' FROM orders")
    assert question in _prompts(exporters.export_sft(name="overruled-sft"))
    record_verdict("conn-1", inv, "reject", note="it counted cancelled ones")
    assert question not in _prompts(exporters.export_sft(name="overruled-sft"))


def test_a_corpus_that_shrinks_back_is_a_new_version_and_the_latest_is_served():
    """A reject can take a corpus back to an earlier snapshot's exact content. Matching ANY earlier version returned
    that old node while `get()` kept serving the newer one — the rejected row still in it."""
    name = "shrink-sft"
    _seed(3)
    v1 = exporters.export_sft(name=name)
    inv = _asked(_trained_on("a question someone later rejects"), "SELECT 'shrinks' FROM orders")
    record_verdict("conn-1", inv, "accept", headline="x", sql_source="SELECT 'shrinks' FROM orders")
    v2 = exporters.export_sft(name=name)
    record_verdict("conn-1", inv, "reject", note="wrong")
    v3 = exporters.export_sft(name=name)
    assert v3["data_id"] == v1["data_id"] and v3["version"] == v2["version"] + 1
    assert store.get(name)["id"] == v3["id"]
    assert "a question someone later rejects" not in _prompts(store.get(name))


def test_a_correction_that_does_not_run_is_not_a_preference(monkeypatch):
    monkeypatch.setattr(exporters, "_runs",
                        lambda connection_id, sql, cache: "" if sql == "SELECT 'fixed'" else "it does not run: syntax")
    asked = [_trained_on("which region grew?"), _trained_on("which region fell?")]
    record_verdict("conn-1", _asked(asked[0], "SELECT 1"), "correct", headline="EU",
                   sql_source="SELECT 1", corrected_sql="SELEC 'typo' FORM x")
    record_verdict("conn-1", _asked(asked[1], "SELECT 1"), "correct", headline="US",
                   sql_source="SELECT 1", corrected_sql="SELECT 'fixed'")
    rows = [r for r in store.rows_of(exporters.export_dpo(name="verified-dpo")) if r["prompt"] in asked]
    assert [(r["prompt"], r["completion"]) for r in rows] == [("which region fell?", "SELECT 'fixed'")]


def test_every_row_carries_what_it_was_answered_against():
    record_verdict("conn-1", _asked(_trained_on("revenue by region?"), "SELECT region, SUM(amount) FROM sales.orders GROUP BY 1"), "accept", headline="EU leads",
                   sql_source="SELECT region, SUM(amount) FROM sales.orders GROUP BY 1")
    (row,) = [r for r in store.rows_of(exporters.export_sft(name="context-sft"))
              if r["prompt"] == "revenue by region?"]
    assert row["context"]["connection_id"] == "conn-1"
    assert row["context"]["tables"] == ["sales.orders"] and row["tier"] == "silver"


def test_a_re_exported_corpus_is_counted_once():
    """Each version is a whole snapshot; the gate report summed them, so 3 then 4 read as 7. Read as the change
    between two exports, because every other test's corpora share this org."""
    _seed(3)
    first = exporters.export_sft(name="count-sft")
    before = store.stats()["sft"]["examples"]
    record_verdict("conn-1", _asked(_trained_on("one more question"), "SELECT 1000 FROM t"), "accept", headline="x",
                   sql_source="SELECT 1000 FROM t")
    latest = exporters.export_sft(name="count-sft")
    assert latest["version"] == first["version"] + 1
    assert store.stats()["sft"]["examples"] - before == latest["row_count"] - first["row_count"]


def test_the_gate_report_checks_all_four_gates_and_never_gates_on_machine_grades(monkeypatch):
    from aughor.security import audit
    monkeypatch.setattr(audit.GuardVerdicts, "first_live_fire",
                        classmethod(lambda cls, org_id=None: "2026-08-01T00:00:00+00:00"))
    gates = exporters.gate_status()
    assert gates["guard_days"]["need"] == 30 and gates["guard_days"]["passes"] is True
    assert gates["sft_bronze"]["passes"] is None and gates["dpo_repair"]["passes"] is None


def test_a_verdict_whose_sql_the_answer_never_ran_is_left_out():
    """A verdict's SQL is whatever the door POSTED. Anyone who can grade an answer could otherwise put SQL the answer
    never ran into the silver tier under a person's name."""
    question = _trained_on("which stores closed last year?")
    record_verdict("conn-1", _asked(question, "SELECT store FROM stores WHERE closed = 2025"), "accept",
                   headline="x", sql_source="DROP TABLE stores")
    assert question not in _prompts(exporters.export_sft(name="posted-sft"))


def test_a_verdict_on_another_organisations_answer_is_left_out():
    """History is read by id, not by organisation; the corpus is one organisation's."""
    from aughor.org.context import using_org
    question = _trained_on("whose answer is this?")
    with using_org("org-other"):
        other = _asked(question, "SELECT 'theirs' FROM t")
    record_verdict("conn-1", other, "accept", headline="x", sql_source="SELECT 'theirs' FROM t")
    assert question not in _prompts(exporters.export_sft(name="cross-org-sft"))


# ── the chat's accept (PENDING item 23) ────────────────────────────────────────────────────

def _thumbs(turn_id: str, verdict: str = "helpful", conn: str = "conn-1") -> dict:
    from fastapi.testclient import TestClient

    from aughor.api import app
    res = TestClient(app).post("/chat/feedback", json={"conn_id": conn, "turn_id": turn_id, "verdict": verdict})
    assert res.status_code == 200, res.text
    return res.json()


def test_a_thumbs_up_in_the_chat_is_an_accept_carrying_the_sql_the_turn_ran():
    from aughor.feedback.verdicts import latest_verdict
    question = _trained_on("how many returns came back in May?")
    turn = _asked(question, "SELECT COUNT(*) AS returns FROM returns WHERE month = 5")
    assert _thumbs(turn)["accepted"] is True
    v = latest_verdict(turn)
    assert v["verdict"] == "accept" and v["sql_source"] == "SELECT COUNT(*) AS returns FROM returns WHERE month = 5"
    assert question in _prompts(exporters.export_sft(name="thumbs-sft"))


def test_a_second_thumbs_up_records_nothing_more_and_a_thumbs_down_records_no_verdict():
    from aughor.feedback.verdicts import list_verdicts
    turn = _asked(_trained_on("how many refunds were issued?"), "SELECT COUNT(*) FROM refunds")
    mine = lambda: [v for v in list_verdicts("conn-1", 500) if v["investigation_id"] == turn]  # noqa: E731
    _thumbs(turn), _thumbs(turn)
    assert len(mine()) == 1, "a second click inflated the acceptance rate"
    other = _asked(_trained_on("how many refunds were denied?"), "SELECT COUNT(*) FROM denials")
    assert _thumbs(other, "unhelpful")["accepted"] is False
    assert not [v for v in list_verdicts("conn-1", 500) if v["investigation_id"] == other]


def test_a_thumbs_up_names_the_turn_and_its_connection_or_records_nothing():
    turn = _asked(_trained_on("what is our return rate?"), "SELECT 0.1")
    assert _thumbs(turn, conn="conn-2")["accepted"] is False       # the turn was answered on conn-1
    assert _thumbs("no-such-turn")["accepted"] is False


# ── the tiers graded by execution and by the guards (PENDING item 23) ─────────────────────────

def _turn(question: str, sql: str, *, receipts=(), caveats=(), rechecks=(), rows=((1,),)) -> str:
    """A chat answer as the quick path files it: the turn, then its envelope (CP-4) — the receipts the guards made."""
    from aughor.db.history import _conn, attach_envelope, save_chat_turn
    turn = save_chat_turn(question=question, connection_id="conn-1", headline="h", sql=sql,
                          columns=["n"], rows=[list(r) for r in rows])
    attach_envelope(turn, {"question": question, "headline": "h", "caveats": list(caveats),
                           "provenance": {"connection_id": "conn-1", "guard_receipts": list(receipts)}})
    if rechecks:
        import json
        c = _conn()
        report = json.loads(c.execute("SELECT report_json FROM investigations WHERE id=?", (turn,)).fetchone()[0])
        report["rechecks"] = list(rechecks)
        c.execute("UPDATE investigations SET report_json=? WHERE id=?", (json.dumps(report), turn))
        c.commit()
        c.close()
    return turn


def test_bronze_is_what_ran_clean_and_nobody_rejected():
    ok = _trained_on("bronze: orders per day")
    _turn(ok, "SELECT day, COUNT(*) FROM orders GROUP BY 1")
    warned = _trained_on("bronze: revenue by store")
    _turn(warned, "SELECT store, SUM(x) FROM a JOIN b USING (id) GROUP BY 1",
          receipts=[{"guard": "fanout_detected", "action": "flagged", "detail": "fans out"}])
    caveated = _trained_on("bronze: margin by brand")
    _turn(caveated, "SELECT brand, AVG(m) FROM p GROUP BY 1", caveats=["an average of ratios"])
    broke = _trained_on("bronze: stock on hand")
    _turn(broke, "SELECT SUM(qty) FROM stock",
          rechecks=[{"status": "unchecked", "reason": "re-running its query failed: no such table"}])
    rejected = _trained_on("bronze: churned customers")
    turn = _turn(rejected, "SELECT COUNT(*) FROM churn")
    record_verdict("conn-1", turn, "reject", note="wrong definition")
    empty = _trained_on("bronze: orders from Mars")
    _turn(empty, "SELECT * FROM orders WHERE planet = 'Mars'", rows=())

    rows = {r["prompt"]: r for r in store.rows_of(exporters.export_bronze(name="bronze-tier"))}
    assert ok in rows and rows[ok]["tier"] == "bronze" and rows[ok]["accepted"] is False
    for left_out in (warned, caveated, broke, rejected, empty):
        assert left_out not in rows, left_out


def test_bronze_cannot_vouch_for_an_answer_filed_before_envelopes():
    from aughor.db.history import save_chat_turn
    question = _trained_on("bronze: an answer from before CP-4")
    save_chat_turn(question=question, connection_id="conn-1", headline="h", sql="SELECT 1 AS old",
                   columns=["n"], rows=[[1]])
    assert question not in _prompts(exporters.export_bronze(name="bronze-old"))


def test_every_guard_rewrite_is_a_pair_and_a_cut_one_is_not():
    question = _trained_on("repairs: revenue by region")
    long_before = "SELECT " + ", ".join(f"c{i}" for i in range(600)) + " FROM t"
    _turn(question, "SELECT region, SUM(amount) FROM orders GROUP BY region", receipts=[
        {"guard": "fanout_defan", "action": "rewrote_sql", "before": "SELECT r, SUM(a) FROM o JOIN i USING (id)",
         "after": "SELECT r, SUM(a) FROM o"},
        {"guard": "preflight_repair", "action": "repaired_sql", "before": "SELECT Region FROM orders",
         "after": "SELECT region FROM orders"},
        {"guard": "sql_repair", "action": "repaired_sql", "before": "SELECT regoin FROM orders",
         "after": "SELECT region, SUM(amount) FROM orders GROUP BY region"},
        {"guard": "repair_recheck", "action": "kept_original", "before": "SELECT 1", "after": "SELECT 2"},
        {"guard": "sql_lint", "action": "rewrote_sql", "before": long_before[:2000], "after": "SELECT c0 FROM t"},
    ])
    pairs = [r for r in store.rows_of(exporters.export_repair_pairs(name="repair-pairs")) if r["prompt"] == question]
    assert sorted(r["guard"] for r in pairs) == ["fanout_defan", "preflight_repair", "sql_repair"]
    assert all(r["tier"] == "guard_rewrite" and r["completion"] != r["rejected"] for r in pairs)


# ── the trace a row was answered under (PENDING item 23) ──────────────────────────────────

def test_a_history_row_carries_the_trace_it_was_answered_under():
    """The guard log keeps each fire's trace id; the bridge from a trace to its question was the session log, swept
    after 14 days. The row itself now carries it, so the join outlives the sweep."""
    from aughor.db.history import create_investigation, get_investigation
    from aughor.telemetry import bind_trace
    with bind_trace("trace-item23"):
        turn = _asked("under a trace", "SELECT 1")                       # a quick answer's row
        run = create_investigation("a deep run under a trace", "conn-1")  # a deep run's row
    assert get_investigation(turn)["trace_id"] == "trace-item23"
    assert get_investigation(run)["trace_id"] == "trace-item23"
    assert get_investigation(_asked("outside any trace", "SELECT 1"))["trace_id"] == ""
