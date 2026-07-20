"""Unit tests for briefing triage — impact ranking + plausibility gates.

Grounded in the real missimi brief that motivated the feature: the synthesiser led
with a noise-level ROAS split while margin/AOV slid, and printed an impossible
turnover and an anti-causal correlation as fact.
"""
from aughor.knowledge.triage import (
    extract_change,
    plausibility,
    impact_score,
    north_star_tokens,
    currency_symbol,
)


# ── extract_change ───────────────────────────────────────────────────────────

def test_change_before_after_arrow():
    ch = extract_change("Gross margin is compressing, 47% to 34% — wait, 47 → 34.")
    assert ch is not None
    assert ch.big == 47.0 and ch.small == 34.0
    assert abs(ch.rel - (13.0 / 47.0)) < 1e-9


def test_change_picks_largest_relative_move_across_pairs():
    # The real ROAS finding: every contrast is tiny; the biggest is ~8%.
    f = ("acquisition shows higher ROAS in email_crm (6.30 vs 5.92), display (4.72 vs 5.12), "
         "affiliate (4.42 vs 4.46), paid_search (4.02 vs 3.65)")
    ch = extract_change(f)
    assert ch is not None
    assert ch.rel < 0.12          # noise-level — must score low


def test_trivial_contrast_is_near_zero():
    ch = extract_change("affiliate ROAS 4.42 vs 4.46")
    assert ch is not None
    assert ch.rel < 0.02


def test_level_only_finding_has_no_change():
    assert extract_change("affiliate marketing drives 86.8% of new-customer orders") is None


def test_from_to_days():
    ch = extract_change("lead time rises from 5 to 14 days")
    assert ch is not None
    assert ch.big == 14.0 and ch.small == 5.0


# ── plausibility: implausible magnitude (suppress) ────────────────────────────

def test_turnover_3600_is_implausible():
    v = plausibility("inventory turnover is far higher in mass-tier (skincare_face at 3600.37) "
                     "than premium (409.86)")
    assert not v.ok
    assert v.severity == "implausible"


def test_sane_turnover_survives():
    v = plausibility("inventory turnover averaged 8.4× across categories last year")
    assert v.ok and v.severity == "ok"


def test_turnover_percentage_not_tripped():
    # A rate that merely mentions turnover at 95% is not 95 "turns".
    v = plausibility("stock turnover efficiency reached 95% of target")
    assert v.ok


# ── plausibility: non-additive aggregate — SUM/AVG over a non-numeric column ──────

# The real bug: SUM(signup_fy) where signup_fy is a VARCHAR fiscal-year label — DuckDB
# coerces "2020"+"2021"+… and returns a big, real-looking, meaningless total that then
# headlines the brief.
_SIGNUP_SQL = ("SELECT is_top_customer, SUM(signup_fy) AS m_signupfy FROM luxexperience.customers "
               "GROUP BY is_top_customer ORDER BY m_signupfy DESC LIMIT 20")
_SIGNUP_FINDING = ("Top-customer signups total 2,493,788 versus 68,569,371 for non-top customers, "
                   "meaning top customers represent only about 3.5% of all signups")


def test_sum_over_varchar_is_implausible():
    v = plausibility(_SIGNUP_FINDING, _SIGNUP_SQL, {"signup_fy": "VARCHAR"})
    assert not v.ok and v.severity == "implausible"
    assert "signup_fy" in v.reason and "VARCHAR" in v.reason


def test_avg_over_text_is_implausible():
    v = plausibility("Average fiscal year is ~2020", "SELECT AVG(signup_fy) FROM customers", {"signup_fy": "TEXT"})
    assert v.severity == "implausible"


def test_sum_over_qualified_varchar():
    v = plausibility(_SIGNUP_FINDING, "SELECT SUM(customers.signup_fy) FROM customers",
                     {"customers.signup_fy": "VARCHAR"})
    assert v.severity == "implausible"


def test_sum_over_numeric_is_ok():
    assert plausibility("Revenue totals 2.4M", "SELECT SUM(amount) FROM orders", {"amount": "DECIMAL(18,2)"}).ok
    for t in ("INTEGER", "BIGINT", "HUGEINT", "DOUBLE", "NUMERIC", "FLOAT", "REAL"):
        assert plausibility("total", "SELECT SUM(x) FROM t", {"x": t}).ok, t


def test_sum_over_boolean_is_ok():
    # SUM(bool) legitimately counts the true rows — not flagged.
    assert plausibility("120 flagged", "SELECT SUM(is_top_customer) FROM customers",
                        {"is_top_customer": "BOOLEAN"}).ok


def test_count_over_varchar_is_ok():
    # COUNT of anything is fine — only SUM/AVG imply additivity.
    assert plausibility("2493788 signups", "SELECT COUNT(signup_fy) FROM customers", {"signup_fy": "VARCHAR"}).ok


def test_sum_over_expression_left_alone():
    # An expression (not a bare column) is never flagged — the guard can't know its type.
    assert plausibility("gmv 2.4M", "SELECT SUM(price * qty) FROM t", {"price": "VARCHAR"}).ok


def test_no_coltypes_no_misfire():
    # Without column types the guard no-ops (can't know the schema) — never a false positive.
    assert plausibility(_SIGNUP_FINDING, _SIGNUP_SQL).ok
    assert plausibility(_SIGNUP_FINDING, _SIGNUP_SQL, {}).ok


def test_unknown_column_type_no_misfire():
    # Column not in the type map → skip (an unmapped schema must not trip the guard).
    assert plausibility(_SIGNUP_FINDING, _SIGNUP_SQL, {"other_col": "VARCHAR"}).ok


def test_nonadditive_beats_confound():
    # A SUM-over-text finding that ALSO reads anti-causal is still 'implausible' (check 0 first).
    v = plausibility("stockouts fall as SUM rises", "SELECT SUM(signup_fy) FROM t", {"signup_fy": "VARCHAR"})
    assert v.severity == "implausible"


# ── plausibility: the broader aggregate ↔ type matrix ─────────────────────────

def test_stddev_over_text_is_implausible():
    assert plausibility("std", "SELECT STDDEV(signup_fy) FROM customers", {"signup_fy": "VARCHAR"}).severity == "implausible"


def test_median_over_text_is_implausible():
    assert plausibility("mid", "SELECT MEDIAN(name) FROM customers", {"name": "TEXT"}).severity == "implausible"


def test_sum_over_date_is_implausible():
    v = plausibility("total dates", "SELECT SUM(order_date) FROM orders", {"order_date": "DATE"})
    assert v.severity == "implausible" and "date/time" in v.reason


def test_avg_over_timestamp_is_implausible():
    assert plausibility("avg ts", "SELECT AVG(created_at) FROM orders", {"created_at": "TIMESTAMP"}).severity == "implausible"


def test_sum_over_struct_is_implausible():
    assert plausibility("x", "SELECT SUM(meta) FROM t", {"meta": "STRUCT(a INTEGER)"}).severity == "implausible"


def test_sum_over_interval_is_ok():
    # Intervals are additive — SUM/AVG of a duration is legitimate.
    assert plausibility("total wait", "SELECT SUM(wait) FROM t", {"wait": "INTERVAL"}).ok


def test_stats_over_numeric_ok():
    for fn in ("STDDEV", "VARIANCE", "MEDIAN", "STDDEV_SAMP"):
        assert plausibility("s", f"SELECT {fn}(x) FROM t", {"x": "DECIMAL(10,2)"}).ok, fn


def test_min_max_over_text_is_ok():
    # MIN/MAX order any type — not a numeric aggregate, never flagged.
    assert plausibility("earliest", "SELECT MIN(name), MAX(name) FROM customers", {"name": "VARCHAR"}).ok


def test_count_distinct_int_id_is_ok():
    # The backbone case: counting distinct ids (int) must NEVER be flagged (it's a grain
    # question, not a type error). Guarding it would break real analytics.
    assert plausibility("1200 customers", "SELECT COUNT(DISTINCT customer_id) FROM orders",
                        {"customer_id": "BIGINT"}).ok


# ── plausibility: anti-causal correlation (demote) ────────────────────────────

def test_stockout_lead_time_is_confound():
    v = plausibility("Stockout frequency decreases as lead_time_days increases from 5 to 14 days")
    assert not v.ok
    assert v.severity == "confound"


def test_mirror_confound():
    v = plausibility("Return rate rises as review scores fall across categories")
    assert v.severity == "confound"


def test_plain_comonotonic_is_ok():
    # Both moving the same way is a cleaner finding — not flagged as a confound.
    v = plausibility("Repeat-purchase rate increases as customer tenure increases")
    assert v.ok


def test_implausible_beats_confound():
    v = plausibility("inventory turnover 3600 falls as lead time increases")
    assert v.severity == "implausible"


# ── north-star membership + impact ranking ────────────────────────────────────

NS = north_star_tokens(["Gross Margin Rate", "Repeat Purchase Rate",
                        "Average Order Value", "Review Sentiment"])


def test_north_star_membership():
    from aughor.knowledge.triage import _hits_north_star
    assert _hits_north_star("Fragrance has the highest repeat-purchase rate (16.87%)", NS)
    assert not _hits_north_star("Affiliate drives 86.8% of new-customer orders", NS)


def test_impact_ranks_real_swing_over_noise_split():
    roas = ("acquisition shows higher ROAS in email_crm (6.30 vs 5.92), display (4.72 vs 5.12), "
            "affiliate (4.42 vs 4.46)")
    margin = "Gross margin rate fell from 47% to 34% over the period"
    assert impact_score(margin, novelty=3, confidence=0.7, tokensets=NS) > \
           impact_score(roas, novelty=5, confidence=0.7, tokensets=NS)


def test_risk_tilt_fire_beats_equal_magnitude_gain():
    # Equal-magnitude moves: a margin DECLINE (fire) should edge out an order-count GAIN.
    fire = "Gross margin rate has fallen from 50% to 38% over the period"      # -24%
    gain = "New-customer orders have risen from 5000 to 6200 over the period"  # +24%
    assert impact_score(fire, novelty=3, confidence=0.7, tokensets=NS) > \
           impact_score(gain, novelty=3, confidence=0.7, tokensets=NS)


def test_risk_tilt_does_not_override_a_much_larger_gain():
    # A 3× gain still leads over a small margin dip — change term dominates the tilt.
    small_fire = "Gross margin rate has fallen from 50% to 47% over the period"   # -6%
    big_gain = "Repeat purchase rate has risen from 5% to 15% over the period"    # +200%
    assert impact_score(big_gain, novelty=3, confidence=0.7, tokensets=NS) > \
           impact_score(small_fire, novelty=3, confidence=0.7, tokensets=NS)


def test_impact_north_star_level_beats_bare_level():
    repeat = "Fragrance for women has the highest repeat-purchase rate at 16.87%"
    bare = "Affiliate marketing drives 86.8% of new-customer orders"
    # Even with no change term, touching a watched metric should outrank a bare level.
    assert impact_score(repeat, novelty=3, confidence=0.5, tokensets=NS) > \
           impact_score(bare, novelty=3, confidence=0.5, tokensets=NS)


# ── currency ──────────────────────────────────────────────────────────────────

def test_currency_symbol():
    assert currency_symbol("EUR") == "€"
    assert currency_symbol("USD") == "$"
    assert currency_symbol("GBP") == "£"
    assert currency_symbol(None) == "$"
    assert currency_symbol("SEK") == "SEK "
