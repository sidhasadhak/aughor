"""Cardinality/overlap sketches — MinHash Jaccard + containment, and the HLL
inclusion–exclusion math used to estimate join overlap on huge tables. Pure + hermetic."""
from __future__ import annotations

from aughor.sql.sketches import (
    minhash_signature, jaccard, containment, overlap_from_hll,
)


# ── MinHash ──────────────────────────────────────────────────────────────────────

def test_minhash_jaccard_approximates_true_similarity():
    a = set(range(0, 1000))
    b = set(range(500, 1500))           # true Jaccard = 500 / 1500 ≈ 0.333
    sa = minhash_signature(a, num_perm=256)
    sb = minhash_signature(b, num_perm=256)
    est = jaccard(sa, sb)
    assert abs(est - 1 / 3) < 0.08      # within MinHash sampling error


def test_minhash_identical_sets_are_jaccard_one():
    s = minhash_signature(["x", "y", "z", "x"], num_perm=64)
    assert jaccard(s, s) == 1.0


def test_minhash_disjoint_sets_are_near_zero():
    sa = minhash_signature([f"a{i}" for i in range(500)], num_perm=128)
    sb = minhash_signature([f"b{i}" for i in range(500)], num_perm=128)
    assert jaccard(sa, sb) < 0.05


def test_minhash_is_process_stable():
    # deterministic coefficients + stable hash → identical signature every call
    assert minhash_signature(["alpha", "beta"], 32) == minhash_signature(["beta", "alpha", None], 32)


def test_minhash_empty_and_mismatched_lengths():
    assert minhash_signature([], 16) == ()
    assert jaccard((), (1, 2)) == 0.0
    assert jaccard((1, 2, 3), (1, 2)) == 0.0     # different lengths → incomparable


def test_containment_from_jaccard_and_sizes():
    # A ⊂ B: |A|=100, |B|=1000, A fully contained → |A∩B|=100, |A∪B|=1000, J=0.1
    # containment_A = 100/100 = 1.0
    assert abs(containment(0.1, 100, 1000) - 1.0) < 1e-9
    assert containment(0.0, 100, 1000) == 0.0
    assert containment(0.5, 0, 10) == 0.0        # empty A


# ── HLL inclusion–exclusion ──────────────────────────────────────────────────────

def test_overlap_from_hll_real_fk():
    # FK side fully contained in PK: |A|=1000 distinct, |B|=5000, union=5000 → inter=1000
    inter, cont_a, cont_b = overlap_from_hll(1000, 5000, 5000)
    assert inter == 1000
    assert cont_a == 1.0                 # every FK value is present in PK
    assert abs(cont_b - 0.2) < 1e-9


def test_overlap_from_hll_disjoint():
    # disjoint: union == |A|+|B| → intersection 0
    inter, cont_a, cont_b = overlap_from_hll(1000, 2000, 3000)
    assert inter == 0 and cont_a == 0.0 and cont_b == 0.0


def test_overlap_from_hll_clamps_noise():
    # HLL noise: union estimated smaller than max(|A|,|B|) would push inter past min — clamp it
    inter, cont_a, _ = overlap_from_hll(1000, 800, 900)   # raw inter = 900, min=800
    assert inter == 800 and cont_a == 0.8
    # empty A → no intersection: containment_a is None, containment_b is 0.0
    assert overlap_from_hll(0, 100, 100) == (0, None, 0.0)
