"""Intelligence-quality guards added to stop fabricated/nonsensical findings:

  RC4 — implausible turnover/ratio magnitude (the 96,295× inventory-turnover grain bug).
  RC2 — the connection's governed BusinessProfile metrics enter the canonical resolver.

These are the deterministic, pure pieces of the gate-on-the-authority + re-validate fix.
"""
from aughor.explorer.agent import _implausible_ratio_claim, _parse_magnitude, verify_insight


# ── RC4: implausible ratio/turnover magnitude ────────────────────────────────

def test_parse_magnitude_suffixes():
    assert _parse_magnitude("96,295.6") == 96295.6
    assert _parse_magnitude("12", "K") == 12_000.0
    assert _parse_magnitude("1.75", "M") == 1_750_000.0
    assert _parse_magnitude("nope") is None


def test_implausible_turnover_is_flagged():
    f = "gross margin rate of 47.0% and an extremely high inventory turnover of 96,295.6"
    assert _implausible_ratio_claim(f)            # truthy reason string


def test_times_multiplier_is_flagged():
    assert _implausible_ratio_claim("revenue grew to a 5,000x multiplier this quarter")


def test_ratio_of_large_value_is_flagged():
    assert _implausible_ratio_claim("review-to-order ratio of 1,200 across the catalog")


def test_healthy_turnover_passes():
    # 25× turnover + a $175M margin figure NEAR the word 'turnover' must NOT be flagged —
    # the dollar amount is not the ratio's number (the loose-window false-positive).
    f = ("Mass tier contributes the highest gross margin ($175.06M) and has the highest "
         "inventory turnover (25.0x), while luxury has the lowest turnover (32.0 days).")
    assert _implausible_ratio_claim(f) == ""


def test_percentage_and_roas_pass():
    assert _implausible_ratio_claim("gross margin rate of 47.0%") == ""
    assert _implausible_ratio_claim("Email CRM has the highest ROAS at 6.23") == ""


def test_large_revenue_without_ratio_word_passes():
    assert _implausible_ratio_claim("Mass tier contributes the highest gross margin ($175.06M)") == ""


def test_verify_insight_drops_implausible_ratio():
    # A result whose turnover cell is absurd → the finding is rejected by the trust gate.
    rows = [["unknown", 0.47, 96295.6]]
    ok, why = verify_insight(rows, "unknown tier inventory turnover of 96,295.6", "SELECT 1", None)
    assert ok is False
    assert "turnover/ratio" in why


def test_verify_insight_keeps_healthy_ratio():
    rows = [["mass", 0.42, 25.0]]
    ok, _ = verify_insight(rows, "Mass tier inventory turnover (25.0x)", "SELECT 1", None)
    assert ok is True


# ── RC3: metric name↔SQL coherence ───────────────────────────────────────────

def test_category_named_percent_metric_is_incoherent():
    from aughor.profile.validate import _name_sql_coherent
    ok, reason = _name_sql_coherent("Top Return Reason (by review score)", "percent 0-100")
    assert ok is False
    assert "category" in reason.lower()


def test_scalar_metrics_stay_coherent():
    from aughor.profile.validate import _name_sql_coherent
    assert _name_sql_coherent("Gross Margin Rate", "percent 0-100")[0] is True
    assert _name_sql_coherent("Average Order Value (AOV)", "USD")[0] is True
    # a "Top X (by units)" returning a count is fine — not a percent
    assert _name_sql_coherent("Top-Selling Products (by units)", "units (integer)")[0] is True


def test_distribution_named_ratio_is_incoherent():
    from aughor.profile.validate import _name_sql_coherent
    assert _name_sql_coherent("Channel mix distribution", "ratio 0-1")[0] is False


# ── RC2: governed BusinessProfile metrics reach the canonical resolver ────────

def test_profile_governed_source_outranks_ontology():
    from aughor.semantic.canonical import _SOURCE_RANK
    # catalog (human) > profile_governed > ontology_verified > ontology_unverified
    assert _SOURCE_RANK["catalog"] > _SOURCE_RANK["profile_governed"]
    assert _SOURCE_RANK["profile_governed"] > _SOURCE_RANK["ontology_verified"]
    assert _SOURCE_RANK["ontology_verified"] > _SOURCE_RANK["ontology_unverified"]
