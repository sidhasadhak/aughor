"""F3 — render_profile_annotations classifies high-null columns: dead (100%),
structural-sparse (a real attribute for a subset, ≥2 distinct), or noise (1 value
sprinkled across a few rows). Uses null_rate + distinct_count — no extra scan."""
from aughor.tools.profiler import ColumnProfile, TableProfile, render_profile_annotations


def _render(col, null_rate, distinct):
    tp = {"products": TableProfile(table="products", row_count=150)}
    cps = {f"products.{col}": ColumnProfile(table="products", column=col, dtype="VARCHAR",
                                            semantic_type="dimension", null_rate=null_rate,
                                            distinct_count=distinct)}
    line = next(l for l in render_profile_annotations(tp, cps).splitlines() if col in l)
    return line


def test_structural_sparse_column():
    line = _render("shade", 0.80, 6)            # shade: only Makeup has it, 6 shades
    assert "STRUCTURAL" in line and "NOISE" not in line


def test_noise_column():
    line = _render("gift_message", 0.95, 1)     # one value in a few rows
    assert "NOISE" in line


def test_dead_column():
    line = _render("middle_name", 1.0, 0)       # 100% null
    assert "dead column" in line


def test_normal_low_null_unchanged():
    line = _render("country", 0.03, 9)          # ordinary low-null dimension
    assert "3% null" in line and "NOISE" not in line and "STRUCTURAL" not in line
