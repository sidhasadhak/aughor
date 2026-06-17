"""Embedding (paraphrase) dedup for explorer findings — the pure clustering logic, which
needs no embed model. The threshold was calibrated on real briefing pairs (paraphrase
dupes cosine 0.87-0.93, distinct-but-related ≤0.78).
"""
from aughor.semantic.finding_dedup import max_cosine, is_paraphrase_duplicate, DEFAULT_THRESHOLD


def test_max_cosine_picks_the_closest():
    assert round(max_cosine([1, 0, 0], [[0, 1, 0], [0.9, 0.1, 0]]), 3) == round(
        max_cosine([1, 0, 0], [[0.9, 0.1, 0]]), 3)


def test_none_vec_is_safe():
    assert max_cosine(None, [[1, 0, 0]]) == 0.0
    assert is_paraphrase_duplicate(None, [[1, 0, 0]]) is False   # embeddings down → never a dup


def test_empty_priors_is_safe():
    assert max_cosine([1, 0, 0], []) == 0.0
    assert is_paraphrase_duplicate([1, 0, 0], []) is False


def test_none_priors_skipped():
    # a prior with no vector (embed failed for it) is skipped, not treated as a match
    assert is_paraphrase_duplicate([1, 0, 0], [None, [1, 0, 0]]) is True
    assert is_paraphrase_duplicate([1, 0, 0], [None, None]) is False


def test_paraphrase_above_threshold_is_dup():
    # near-parallel vectors (cosine well above 0.85) → duplicate
    assert is_paraphrase_duplicate([1.0, 0.05, 0.0], [[1.0, 0.0, 0.0]]) is True


def test_distinct_below_threshold_survives():
    # ~0.78 cosine (distinct-but-related, like SKU-leak vs WRONG_SHADE) → kept
    import math
    ang = math.acos(0.78)
    v = [math.cos(ang), math.sin(ang), 0.0]
    assert is_paraphrase_duplicate(v, [[1.0, 0.0, 0.0]]) is False


def test_threshold_is_conservative():
    assert DEFAULT_THRESHOLD >= 0.8   # suggestions-grade; avoid collapsing distinct findings
