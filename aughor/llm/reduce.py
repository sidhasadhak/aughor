"""Hierarchical map-reduce over context windows — pack → summarize → recurse.

When synthesizing from MANY items (findings, evidence rows, reviews) that won't fit one prompt well,
this folds them in bounded batches instead of stuffing everything into a single prompt (lossy, and the
model loses the middle) or truncating (silently drops data). A leaf batch is summarized directly; the
batch summaries are then folded recursively until one remains — classic map-reduce, depth-bounded so it
always terminates.

The primitive is PURE: it takes a ``summarize`` (items → text) and a ``combine`` (summaries → text)
callable and never touches an LLM itself, so callers wire in whatever model role they want and tests
pass plain functions. ``partitioned_reduce`` adds partition-awareness — items in different groups
(e.g. different domains) are summarized separately and never blended before the final fold.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TypeVar

T = TypeVar("T")

DEFAULT_FANOUT = 8
DEFAULT_MAX_DEPTH = 4


def hierarchical_reduce(
    items: Sequence[T],
    *,
    summarize: Callable[[list[T]], str],
    combine: Callable[[list[str]], str],
    fanout: int = DEFAULT_FANOUT,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> str:
    """Reduce ``items`` to one summary by recursive batching.

    ``<= fanout`` items → one ``summarize`` call. Otherwise split into ``ceil(n/fanout)`` batches,
    ``summarize`` each (the *map*), then fold the batch summaries with ``combine`` (the *reduce*),
    recursing until one summary remains. ``max_depth`` bounds the fold so it always terminates."""
    items = list(items)
    if not items:
        return ""
    if len(items) <= max(1, fanout):
        return summarize(items)
    summaries = [summarize(items[i:i + fanout]) for i in range(0, len(items), fanout)]
    return _fold(summaries, combine, fanout, max_depth - 1)


def partitioned_reduce(
    groups: Mapping[str, Sequence[T]],
    *,
    summarize_group: Callable[[str, list[T]], str],
    combine: Callable[[list[str]], str],
    fanout: int = DEFAULT_FANOUT,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> str:
    """Summarize each partition independently (never blending groups), then fold the per-group
    digests. Use when items belong to distinct buckets — e.g. findings per domain — that must not be
    conflated before the final synthesis."""
    digests = [summarize_group(k, list(v)) for k, v in groups.items() if v]
    if not digests:
        return ""
    return _fold(digests, combine, fanout, max_depth)


def _fold(summaries: list[str], combine: Callable[[list[str]], str], fanout: int, depth: int) -> str:
    """Fold a list of summaries down to one, batching by ``fanout``, bounded by ``depth``."""
    summaries = [s for s in summaries if s]
    if not summaries:
        return ""
    if len(summaries) == 1:
        return summaries[0]
    if len(summaries) <= max(1, fanout) or depth <= 1:
        return combine(summaries)
    folded = [combine(summaries[i:i + fanout]) for i in range(0, len(summaries), fanout)]
    return _fold(folded, combine, fanout, depth - 1)
