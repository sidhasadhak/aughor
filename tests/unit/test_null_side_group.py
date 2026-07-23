"""group_by_outer_null_side — the SEMANTIC self-ratio (2026-07-23).

A LEFT JOIN silently demoted to an inner join by GROUP BY-ing on its null-producing
side. The luxexperience Briefing shipped "Beauty and jewelry_watches … 100% return
rate": COUNT(DISTINCT r.order_id) / COUNT(DISTINCT o.order_id) grouped by
returns.category, where `category` lives only on the returns (null) side — so the
denominator is silently restricted to matched rows and the ratio is 1.0 in every
bucket. The corrected rates are 12–39% and the true ranking is INVERTED (Beauty and
jewelry_watches are the LOWEST-return categories). self_ratio_tautology cannot see it:
the two aggregates are different expressions the join geometry forces to be equal.

A hit DROPS the finding at the explorer emission gate, so the guard must be
high-precision — hence the false-positive battery below. See aughor/sql/fanout.py.
"""
from aughor.sql.fanout import group_by_outer_null_side as guard

# table-name → columns; `category` is on returns + products, NOT orders (the real schema).
TC = {
    "orders": ["order_id", "gmv_eur", "ship_region", "customer_id", "platform"],
    "returns": ["return_id", "order_id", "category", "reason", "platform"],
    "products": ["product_id", "category", "retail_price_eur"],
    "order_items": ["order_item_id", "order_id", "product_id"],
}

# The exact shape that shipped — unqualified `category` resolved via table_cols, GROUP BY 1.
LUX_100PCT = """
SELECT category,
       COUNT(DISTINCT r.order_id) * 1.0 / NULLIF(COUNT(DISTINCT o.order_id), 0) AS return_rate
FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id
GROUP BY 1
"""


def test_flags_the_100pct_return_rate_artifact():
    reason = guard(LUX_100PCT, TC)
    assert reason is not None
    assert "null" in reason.lower()
    assert "1.0" in reason or "100%" in reason        # names the tautological outcome


def test_flags_qualified_null_side_group_without_table_cols():
    # A right-alias qualifier is authoritative — no table_cols needed.
    sql = ("SELECT r.category, SUM(o.gmv_eur) / NULLIF(COUNT(DISTINCT o.order_id), 0) AS aov "
           "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY r.category")
    assert guard(sql, None) is not None


def test_flags_right_join_on_its_null_side():
    sql = ("SELECT r.category, COUNT(DISTINCT o.order_id) n "
           "FROM returns r RIGHT JOIN orders o ON o.order_id = r.order_id GROUP BY 1")
    assert guard(sql, TC) is not None


def test_flags_bug_hidden_in_a_cte():
    sql = ("""WITH cat AS (
                SELECT category,
                       COUNT(DISTINCT r.order_id) * 1.0 / NULLIF(COUNT(DISTINCT o.order_id), 0) rr
                FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY 1)
              SELECT * FROM cat ORDER BY rr DESC""")
    assert guard(sql, TC) is not None


# ── must stay SILENT (a hit deletes a real finding) ──────────────────────────────

def test_silent_on_inner_join():
    # No outer join → no demotion.
    sql = ("SELECT r.category, COUNT(DISTINCT o.order_id) n "
           "FROM orders o JOIN returns r ON o.order_id = r.order_id GROUP BY 1")
    assert guard(sql, TC) is None


def test_silent_when_group_key_is_on_the_preserved_side():
    sql = ("SELECT o.ship_region, SUM(o.gmv_eur) g "
           "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY 1")
    assert guard(sql, TC) is None


def test_silent_on_null_tolerant_coalesce_bucketing():
    # Deliberately bucketing the unmatched rows — the NULL group is intentional.
    sql = ("SELECT COALESCE(r.category, 'none') c, COUNT(DISTINCT o.order_id) n "
           "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY 1")
    assert guard(sql, TC) is None


def test_silent_on_case_null_tolerant_group():
    sql = ("SELECT CASE WHEN r.category IS NULL THEN 'none' ELSE r.category END c, "
           "COUNT(DISTINCT o.order_id) n "
           "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY 1")
    assert guard(sql, TC) is None


def test_silent_without_a_preserved_side_aggregate():
    # Per-category return COUNT(*): the NULL bucket is the meaningful "no return" group,
    # and nothing preserved-side is being silently restricted.
    sql = ("SELECT r.category, COUNT(*) "
           "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY 1")
    assert guard(sql, TC) is None


def test_silent_on_ambiguous_column_owned_by_a_preserved_table_too():
    # `platform` is on orders (preserved) AND returns (null) → cannot place it on the
    # null side, so stay conservative and do not flag.
    sql = ("SELECT platform, COUNT(DISTINCT o.order_id) "
           "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY 1")
    assert guard(sql, TC) is None


def test_silent_when_unqualified_and_no_table_cols():
    # Can't resolve which side `category` belongs to → do not guess.
    sql = ("SELECT category, COUNT(DISTINCT o.order_id) "
           "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY 1")
    assert guard(sql, None) is None


def test_silent_without_group_by():
    sql = "SELECT COUNT(DISTINCT o.order_id) FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id"
    assert guard(sql, TC) is None


def test_never_raises_on_garbage():
    assert guard("SELECT ((( FROM", TC) is None
    assert guard("", TC) is None
    assert guard("not sql at all", None) is None
