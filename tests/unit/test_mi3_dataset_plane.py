"""MI-3 — graded rows become a versioned, provenanced corpus.

The three receipts §3.9 asks for are the first three tests: the same corpus exports to the
same content hash, provenance walks a dataset back to the verdicts that fed it, and a
golden set actually SHOWS UP in the evals plane rather than merely existing in our own
store. The rest guard properties that are easy to lose later — disjointness, scrubbing,
and the fact that purging bytes must not erase the record of what was built.
"""
from __future__ import annotations

from aughor.feedback.verdicts import record_verdict
from aughor.learning import exporters, store


def _seed(n: int = 12) -> None:
    """Accepted findings that carry SQL — the shape the live store does NOT yet have."""
    for i in range(n):
        record_verdict("conn-1", f"inv-{i}", "accept", headline=f"revenue question {i}",
                       sql_source=f"SELECT {i} FROM orders")


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
    record_verdict("conn-1", "inv-grown", "accept", headline="new question",
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
    assert {row["source_kind"] for row in lineage} == {"finding_verdict"}
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
    stable hash, so this holds across re-exports rather than by luck."""
    _seed(60)
    sft = store.rows_of(exporters.export_sft(name="dis-sft"))
    golden = store.rows_of(exporters.export_golden(name="dis-gold"))

    assert sft and golden, "one side is empty — disjointness would be trivially true"
    assert not ({r["completion"] for r in sft} & {r["completion"] for r in golden})


def test_a_correct_verdict_without_a_correction_is_not_a_preference_pair():
    """A `correct` verdict with no `corrected_sql` is a judgement without a lesson.
    Including it would fabricate a preference nobody expressed — and on the live store
    2026-09-03 that is EVERY `correct` row."""
    record_verdict("conn-1", "inv-nofix", "correct", headline="close but wrong",
                   sql_source="SELECT 1")
    record_verdict("conn-1", "inv-fix", "correct", headline="close but wrong",
                   sql_source="SELECT 1", corrected_sql="SELECT 2")

    rows = store.rows_of(exporters.export_dpo(name="dpo-pairs"))
    assert len(rows) == 1
    assert rows[0]["completion"] == "SELECT 2"
    assert rows[0]["rejected"] == "SELECT 1"


def test_examples_are_deduped():
    for _ in range(4):
        record_verdict("conn-1", "inv-dupe", "accept", headline="same question",
                       sql_source="SELECT 1 FROM orders")
    rows = store.rows_of(exporters.export_sft(name="dedupe-sft"))
    assert len([r for r in rows if r["completion"] == "SELECT 1 FROM orders"]) == 1


def test_text_is_scrubbed_on_the_way_out():
    record_verdict("conn-1", "inv-pii", "accept",
                   headline="what did alice@example.com order",
                   sql_source="SELECT 1 FROM orders")
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
