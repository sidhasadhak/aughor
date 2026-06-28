"""Value index — fast approximate matching over a column's value domain (CHESS-style).

CHESS (Talaei et al., ICML 2025) scales filter-literal correction to industrial databases by indexing
unique cell values with LSH and retrieving near-matches in ~5s instead of ~5min of brute-force edit
distance over every value. This is the dependency-free analog: a character-trigram inverted index
(shingle blocking) that gathers only the candidate values sharing trigrams with the needle, then
re-ranks those survivors by string similarity. Same shape as LSH — block on shingles, rerank the
short-list — without pulling in an external MinHash dependency.

It exists to extend filter-literal binding (aughor/sql/join_guard.py) to HIGH-CARDINALITY columns
(names, SKUs, cities) that the ≤50-distinct enumeration path deliberately skips: build the index over
a bounded sample of the column's distinct values, look a guessed literal up, and bind it to its
nearest real value when the literal itself matches no row. Pure and deterministic — unit-testable
offline, and grounded in real values rather than a model opinion.
"""
from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher


def _trigrams(s: str) -> set[str]:
    """Character trigrams of a value, padded so short strings and edges still yield shingles."""
    s = s.lower().strip()
    if not s:
        return set()
    padded = f"  {s} "
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


class ValueIndex:
    """Trigram-blocked fuzzy index over a fixed set of string values (case-insensitive, deduped)."""

    def __init__(self, values, max_candidates: int = 200):
        self._values: list[str] = []
        self._postings: dict[str, list[int]] = defaultdict(list)
        self._max_candidates = max_candidates
        seen: set[str] = set()
        for v in values:
            if v is None:
                continue
            sv = str(v)
            key = sv.lower()
            if key in seen:
                continue
            seen.add(key)
            idx = len(self._values)
            self._values.append(sv)
            for tg in _trigrams(sv):
                self._postings[tg].append(idx)

    def __len__(self) -> int:
        return len(self._values)

    def query(self, needle: str, k: int = 5, cutoff: float = 0.82) -> list[tuple[str, float]]:
        """Up to k (value, similarity) pairs with similarity >= cutoff, best first.

        Blocks candidates by shared trigrams (so we never score the whole domain), then re-ranks the
        most-overlapping candidates with the full string-similarity ratio."""
        if not needle or not self._values:
            return []
        tgs = _trigrams(needle)
        if not tgs:
            return []
        counts: dict[int, int] = defaultdict(int)
        for tg in tgs:
            for idx in self._postings.get(tg, ()):
                counts[idx] += 1
        if not counts:
            return []
        candidates = sorted(counts, key=lambda i: counts[i], reverse=True)[:self._max_candidates]
        nl = needle.lower()
        scored = [(self._values[i], SequenceMatcher(None, nl, self._values[i].lower()).ratio())
                  for i in candidates]
        scored = [vs for vs in scored if vs[1] >= cutoff]
        scored.sort(key=lambda vs: vs[1], reverse=True)
        return scored[:k]

    def best_match(self, needle: str, cutoff: float = 0.82) -> str | None:
        """The single nearest value at or above cutoff, or None."""
        hits = self.query(needle, k=1, cutoff=cutoff)
        return hits[0][0] if hits else None
