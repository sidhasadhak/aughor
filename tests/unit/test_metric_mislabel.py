"""Named-metric ↔ SQL coherence — industry-KB-driven (no hardcoded list). The explorer trust gate
rejects a finding whose query is ALIASED as one metric while the prose asserts a DIFFERENT one
(the AOV-aliased-`aov`-narrated-"ROAS" bug). The metric vocabulary comes from data/kb/industry/*.json
matched to the connection's industry — so airline/manufacturing/SaaS are covered by their JSON."""
from __future__ import annotations

from aughor.explorer.agent import verify_insight
from aughor.explorer.metric_coherence import mislabeled_named_metric
from aughor.profile.metric_kb import metric_vocabulary

_RETAIL = "Retail / E-commerce"
_AOV_SQL = ("SELECT o.marketing_channel, SUM(o.order_value) / NULLIF(COUNT(DISTINCT o.order_id), 0) "
            "AS aov FROM missimi.orders o GROUP BY o.marketing_channel ORDER BY aov DESC")
_REAL_ROAS_SQL = "SELECT channel, SUM(revenue) / NULLIF(SUM(ad_spend), 0) AS roas FROM perf GROUP BY channel"


def _vocab(industry: str) -> dict:
    return {t: (label, formula) for (t, label, formula) in metric_vocabulary(industry)}


# ── the vocabulary is data-driven + industry-scoped ──────────────────────────────

def test_retail_vocab_recognizes_its_metrics():
    v = _vocab(_RETAIL)
    assert "aov" in v and "roas" in v and "cac" in v
    assert "average order value" in v["aov"][0].lower()


def test_vocab_is_industry_scoped():
    air = {t for (t, _l, _f) in metric_vocabulary("Airline / Commercial Aviation")}
    assert "loadfactor" in air and "aov" not in air   # airline KB, not retail


# ── the guard: alias ≠ asserted metric ───────────────────────────────────────────

def test_the_aov_as_roas_bug_is_flagged():
    why = mislabeled_named_metric("Email CRM has the highest ROAS at 6.23", _AOV_SQL, _vocab(_RETAIL))
    assert why and "mislabel" in why and "Average Order Value" in why


def test_correctly_labelled_aov_passes():
    assert mislabeled_named_metric("Email CRM has the highest AOV at 6.23", _AOV_SQL, _vocab(_RETAIL)) is None


def test_real_roas_aliased_roas_passes():
    assert mislabeled_named_metric("Email CRM ROAS at 6.2 leads", _REAL_ROAS_SQL, _vocab(_RETAIL)) is None


def test_passing_mention_without_a_value_passes():
    assert mislabeled_named_metric("AOV leads; ROAS would be worth checking", _AOV_SQL, _vocab(_RETAIL)) is None


def test_claim_naming_the_computed_metric_among_others_passes():
    # the SQL metric (AOV) IS among the asserted metrics → not a mislabel
    assert mislabeled_named_metric("AOV is 6.23 here and ROAS tracks it", _AOV_SQL, _vocab(_RETAIL)) is None


def test_unaliased_or_unknown_metric_query_is_ignored():
    assert mislabeled_named_metric("ROAS was 6.23", "SELECT channel, SUM(rev) AS total FROM t GROUP BY channel", _vocab(_RETAIL)) is None
    assert mislabeled_named_metric("ROAS was 6.23", _AOV_SQL, {}) is None   # empty vocab → no-op


# ── wired into the pre-emission trust gate ───────────────────────────────────────

def test_gate_rejects_the_mislabel_and_accepts_the_correct_label():
    rows = [["email_crm", 6.23], ["display", 4.75]]
    ok, reason = verify_insight(rows, "Email CRM has the highest ROAS at 6.23, then display at 4.75",
                                _AOV_SQL, industry=_RETAIL)
    assert ok is False and "mislabel" in reason
    ok2, _ = verify_insight(rows, "Email CRM has the highest AOV at 6.23, then display at 4.75",
                            _AOV_SQL, industry=_RETAIL)
    assert ok2 is True
