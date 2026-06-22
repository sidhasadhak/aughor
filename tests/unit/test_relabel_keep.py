"""Fix #159 — relabel-and-keep. Instead of DROPPING a mislabeled finding (the query computes
metric A, the prose asserts a different metric B), rewrite B's name to A's canonical label and
KEEP the real signal. Safe because verify_insight's grounding check still guards the number: a
mislabel with a REAL number survives corrected (the missimi 'email CRM AOV $69.15' a bad LLM draw
called 'ROAS'), while a mislabel whose number was ALSO fabricated is still dropped by grounding."""
from __future__ import annotations

from aughor.explorer.agent import relabel_mislabeled_finding, verify_insight, _metric_vocab_for

_VOCAB = {
    "aov": ("Average Order Value", "SUM(order_value)/COUNT(DISTINCT order_id)"),
    "roas": ("ROAS", "SUM(attributed_revenue)/SUM(spend)"),
    "cac": ("CAC", "SUM(spend)/COUNT(DISTINCT customer_id)"),
}
_AOV_SQL = ("SELECT marketing_channel, SUM(order_value) / NULLIF(COUNT(DISTINCT order_id), 0) AS aov "
            "FROM orders GROUP BY marketing_channel ORDER BY aov DESC")
_RETAIL = "Retail / E-commerce"
_ROWS = [["email_crm", 69.15], ["display", 69.57]]   # real AOV cell values


# ── the pure relabel (grounded number → rescue) ───────────────────────────────────

def test_relabels_wrong_metric_name_to_what_the_sql_computes():
    out = relabel_mislabeled_finding("Email CRM has the highest ROAS at 69.15.", _AOV_SQL, _VOCAB, _ROWS)
    assert out == "Email CRM has the highest Average Order Value at 69.15."


def test_ungrounded_number_is_not_relabeled():
    # 6.23 is NOT a cell value (rows are ~69) → strict grounding refuses to rescue (don't keep a wrong number).
    assert relabel_mislabeled_finding("Email CRM has the highest ROAS at 6.23.", _AOV_SQL, _VOCAB, _ROWS) is None


def test_coherent_finding_is_not_relabeled():
    assert relabel_mislabeled_finding("Email CRM has the highest AOV at 69.15.", _AOV_SQL, _VOCAB, _ROWS) is None


def test_no_resolvable_sql_alias_is_not_relabeled():
    assert relabel_mislabeled_finding("ROAS is 69.15.", "SELECT channel, SUM(x) AS total FROM t GROUP BY channel", _VOCAB, _ROWS) is None


def test_empty_vocab_is_a_noop():
    assert relabel_mislabeled_finding("ROAS is 69.15.", _AOV_SQL, {}, _ROWS) is None


def test_no_rows_means_no_rescue():
    assert relabel_mislabeled_finding("Email CRM has the highest ROAS at 69.15.", _AOV_SQL, _VOCAB, None) is None


def test_multiple_occurrences_all_relabeled():
    out = relabel_mislabeled_finding("ROAS leads; the ROAS of 69.15 tops the table.", _AOV_SQL, _VOCAB, _ROWS)
    assert "ROAS" not in out and out.count("Average Order Value") == 2


# ── end-to-end: relabel then verify_insight (grounding still guards the number) ───

def test_grounded_mislabel_is_rescued_and_kept():
    vocab = _metric_vocab_for(None, _RETAIL)
    rows = [["email_crm", 69.15], ["display", 69.57]]
    finding = "Email CRM has the highest ROAS at 69.15, ahead of display at 69.57."
    relabeled = relabel_mislabeled_finding(finding, _AOV_SQL, vocab, rows)
    assert relabeled and "ROAS" not in relabeled and "Average Order Value" in relabeled
    ok, why = verify_insight(rows, relabeled, _AOV_SQL, industry=_RETAIL)
    assert ok is True, why                      # grounded + now coherent → kept


def test_fabricated_number_mislabel_is_not_rescued_then_dropped():
    vocab = _metric_vocab_for(None, _RETAIL)
    rows = [["email_crm", 69.15], ["display", 69.57]]      # real AOV values
    finding = "Email CRM has the highest ROAS at 6.23."    # 6.23 is NOT in the rows
    assert relabel_mislabeled_finding(finding, _AOV_SQL, vocab, rows) is None   # strict grounding refuses
    ok, why = verify_insight(rows, finding, _AOV_SQL, industry=_RETAIL)         # so the mislabel guard drops it
    assert ok is False and "mislabel" in why


def test_without_relabel_the_grounded_mislabel_would_be_dropped():
    # proves relabel is what rescues it: the SAME grounded finding, NOT relabeled, is rejected
    # by verify_insight's mislabel guard.
    rows = [["email_crm", 69.15], ["display", 69.57]]
    ok, why = verify_insight(rows, "Email CRM has the highest ROAS at 69.15, ahead of display at 69.57.",
                             _AOV_SQL, industry=_RETAIL)
    assert ok is False and "mislabel" in why
