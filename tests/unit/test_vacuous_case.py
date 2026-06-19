"""Unit tests for the vacuous-CASE dimension guard (emission trust gate).

Grounded in the real missimi finding: a CASE bucketed every row into 'unknown' because
its hardcoded brand names ('CeraVe', 'La Mer', …) matched none of the synthetic
'Brand_000'-style names, while a real brand_tier column was ignored.
"""
from aughor.explorer.agent import _vacuous_case_dimension, verify_insight

TIER_SQL = """
WITH brand_tier AS (
  SELECT b.brand_id, b.brand_name,
    CASE
      WHEN b.brand_name IN ('CeraVe', 'Neutrogena', 'The Ordinary') THEN 'mass'
      WHEN b.brand_name IN ('La Roche-Posay', 'Klairs', 'Glossier') THEN 'premium'
      WHEN b.brand_name IN ('Sisley', 'La Mer', 'Tom Ford Beauty') THEN 'luxury'
      ELSE 'unknown'
    END AS tier
  FROM brands b
)
SELECT tier, gross_margin_rate, inventory_turnover FROM ... ORDER BY 1
"""


def test_flags_all_rows_collapsed_to_else():
    # Result has only the ELSE bucket ('unknown'); no THEN label ever appears.
    rows = [["unknown", 0.47, 96295.6]]
    why = _vacuous_case_dimension(TIER_SQL, rows)
    assert why is not None
    assert "vacuous categorization" in why
    assert "unknown" in why


def test_not_flagged_when_a_real_category_appears():
    # If even one intended category materialised, the scheme is working — keep it.
    rows = [["mass", 0.40, 6.8], ["luxury", 0.50, 9.5], ["unknown", 0.47, 7.0]]
    assert _vacuous_case_dimension(TIER_SQL, rows) is None


def test_ignores_quoted_in_lists_in_when_conditions():
    # The WHEN IN-list literals ('CeraVe' …) must NOT be read as result categories.
    # Result row's only string is the ELSE label → still flagged.
    rows = [{"tier": "unknown", "margin": 0.47}]
    assert _vacuous_case_dimension(TIER_SQL, rows) is not None


def test_single_branch_case_not_flagged():
    sql = "SELECT CASE WHEN x > 0 THEN 'pos' ELSE 'neg' END AS s, COUNT(*) FROM t GROUP BY 1"
    # Only one THEN label → not a multi-category segmentation; never trips.
    assert _vacuous_case_dimension(sql, [["neg", 5]]) is None


def test_no_case_or_no_rows():
    assert _vacuous_case_dimension("SELECT a, b FROM t", [["x", 1]]) is None
    assert _vacuous_case_dimension(TIER_SQL, []) is None


def test_verify_insight_rejects_vacuous_case():
    ok, reason = verify_insight(
        rows=[["unknown", 0.47, 96295.6]],
        finding_text="The 'unknown' brand tier shows a gross margin of 47% and turnover of 96295.6",
        sql=TIER_SQL,
    )
    assert ok is False
    assert "vacuous categorization" in reason


# ── implausible-magnitude check lifted to the emission gate (universal, not brief-only) ──

def test_verify_insight_rejects_impossible_magnitude_at_emission():
    # An impossible inventory turnover must be dropped at EMISSION (so it never reaches the
    # insight cards), reusing the briefing triage's operating-band KB as the single source.
    ok, reason = verify_insight(
        rows=[["mass", 3600.37], ["premium", 409.86]],
        finding_text="Inventory turnover is far higher in mass-tier (3600.37) than premium (409.86)",
        sql="SELECT tier, inventory_turnover FROM t",
    )
    assert ok is False
    assert "turnover" in reason.lower()


def test_verify_insight_keeps_legitimate_inverse_finding():
    # The confound check must NOT hard-reject at emission — an inverse relationship can be a
    # real, useful finding. It stays a soft demotion at synthesis, not an emission drop.
    ok, _ = verify_insight(
        rows=[["q1", 0.18, 100], ["q2", 0.12, 220]],
        finding_text="Churn rate decreases as engagement score increases across cohorts",
        sql="SELECT cohort, churn_rate, engagement FROM t",
    )
    assert ok is True
