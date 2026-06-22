"""Column-feasibility gate (#1) — the explorer must not pursue a coverage angle
whose required column class is absent from the domain, or the generator stubs the
missing dimension with a constant literal (the `'Unknown' AS signup_source` channel
hallucination). See feasibility.angle_feasible and the Phase-8 column-feasibility gate.

Parallels the temporal-feasibility gate (feasibility.is_temporal_angle): same idea,
but for categorical column requirements instead of a date/timestamp.
"""
from aughor.explorer.feasibility import angle_feasible as _angle_feasible


def test_channel_angle_needs_a_channel_column():
    # No channel/source column anywhere → infeasible (this is the repro shape).
    assert _angle_feasible("channel_mix", {"customer_id", "order_id", "total_amount"}) is False
    # A signup_source / channel column present → feasible.
    assert _angle_feasible("channel_mix", {"order_id", "signup_source", "total"}) is True
    assert _angle_feasible("attribution", {"order_id", "touchpoint_type"}) is True


def test_payment_and_refund_angles_need_their_columns():
    assert _angle_feasible("payment_behavior", {"order_id", "status", "amount"}) is False
    assert _angle_feasible("payment_behavior", {"order_id", "payment_method"}) is True
    assert _angle_feasible("refund_rate", {"order_id", "amount"}) is False
    assert _angle_feasible("refund_rate", {"order_id", "refund_amount"}) is True


def test_generic_angles_are_always_feasible():
    # Angles with no specific column requirement must never be dropped.
    for angle in ("volume", "value", "revenue", "margins", "patterns", "anomalies", "seasonality"):
        assert _angle_feasible(angle, {"x"}) is True


def test_operations_angles_match_their_columns():
    assert _angle_feasible("supplier_performance", {"po_id", "supplier_id", "delay_days"}) is True
    assert _angle_feasible("inventory_health", {"sku_id", "on_hand_qty"}) is True
    assert _angle_feasible("lead_times", {"expected_delivery_date", "actual_delivery_date"}) is True
    assert _angle_feasible("inventory_health", {"customer_id", "order_total"}) is False


def test_unknown_angle_and_empty_columns():
    assert _angle_feasible("totally_made_up_angle", {"x"}) is True   # not in map → feasible
    assert _angle_feasible("channel_mix", set()) is False            # no columns → infeasible
