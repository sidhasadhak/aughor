"""Cardinality + set-overlap sketches — estimate join overlap on huge tables without a
full anti-join / IN-set scan.

Two techniques, both for the same goal (is ``a.fk`` actually contained in ``b.pk``?):

  * **MinHash** — a fixed-size signature (k minimum hash values) that estimates the
    Jaccard similarity of two sets in O(k) *from the signatures alone*. Precompute one
    signature per key column and join-verification becomes signature-vs-signature — no
    table scan, and the signatures are small enough to persist.
  * **HLL inclusion–exclusion** — DuckDB's built-in ``approx_count_distinct`` (a
    HyperLogLog) gives |A|, |B| and |A∪B| in one cheap pass each; then
    |A∩B| ≈ |A|+|B|−|A∪B| and containment A⊆B ≈ |A∩B|/|A|. No anti-join, no IN-set —
    the warehouse does it in a single aggregate. :func:`overlap_from_hll` is the math; the
    SQL lives with the prober in ``sql/join_guard.py``.

Pure + dependency-free. MinHash uses a stable 64-bit hash (blake2b, not Python's salted
``hash``) so signatures are reproducible across processes — safe to persist and compare.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Iterable, Optional

_MERSENNE = (1 << 61) - 1     # a Mersenne prime modulus for universal hashing
_DEFAULT_PERM = 64


def _stable_hash(value) -> int:
    """A process-stable 64-bit hash of a value's string form (blake2b)."""
    return int.from_bytes(hashlib.blake2b(str(value).encode("utf-8"), digest_size=8).digest(), "big")


@lru_cache(maxsize=8)
def _coeffs(num_perm: int) -> tuple:
    """Deterministic (a, b) universal-hash coefficients per permutation — derived from a
    stable hash of the index, so two processes build identical signatures."""
    out = []
    for i in range(num_perm):
        a = (_stable_hash(f"minhash:a:{i}") % (_MERSENNE - 1)) + 1   # a ∈ [1, p-1]
        b = _stable_hash(f"minhash:b:{i}") % _MERSENNE               # b ∈ [0, p-1]
        out.append((a, b))
    return tuple(out)


def minhash_signature(values: Iterable, num_perm: int = _DEFAULT_PERM) -> tuple:
    """A MinHash signature for ``values`` (NULLs skipped). Returns a length-``num_perm``
    tuple of minima, or an empty tuple if the set was empty. Two signatures of the same
    length estimate Jaccard via :func:`jaccard`."""
    coeffs = _coeffs(num_perm)
    sig = [_MERSENNE] * num_perm
    seen = False
    for v in values:
        if v is None:
            continue
        seen = True
        hx = _stable_hash(v)
        for i, (a, b) in enumerate(coeffs):
            hv = (a * hx + b) % _MERSENNE
            if hv < sig[i]:
                sig[i] = hv
    return tuple(sig) if seen else tuple()


def jaccard(sig_a: tuple, sig_b: tuple) -> float:
    """Estimated Jaccard |A∩B|/|A∪B| from two equal-length MinHash signatures. 0.0 when
    either is empty or the lengths differ (incomparable)."""
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return 0.0
    same = sum(1 for x, y in zip(sig_a, sig_b) if x == y)
    return same / len(sig_a)


def containment(jac: float, n_a: int, n_b: int) -> float:
    """Containment of A in B (|A∩B|/|A|) from a Jaccard estimate + the two set sizes.
    From J = |A∩B|/|A∪B| and |A∪B| = |A|+|B|−|A∩B|: |A∩B| = J·(|A|+|B|)/(1+J)."""
    if jac <= 0 or n_a <= 0:
        return 0.0
    inter = jac * (n_a + n_b) / (1.0 + jac)
    return max(0.0, min(1.0, inter / n_a))


def overlap_from_hll(a_distinct, b_distinct, union_distinct) -> tuple:
    """Inclusion–exclusion on three HLL distinct-counts → ``(intersection, containment_a,
    containment_b)``. |A∩B| = |A|+|B|−|A∪B|, clamped to ``[0, min(|A|,|B|)]`` (HLL noise can
    push the raw estimate slightly out of range). ``containment_*`` is ``None`` when that
    side is empty."""
    a = max(0, int(a_distinct or 0))
    b = max(0, int(b_distinct or 0))
    u = max(0, int(union_distinct or 0))
    inter = max(0, min(a + b - u, min(a, b)))
    cont_a = (inter / a) if a > 0 else None
    cont_b = (inter / b) if b > 0 else None
    return inter, cont_a, cont_b
