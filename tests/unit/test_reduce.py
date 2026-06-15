"""Unit tests for the hierarchical map-reduce primitive (aughor/llm/reduce).

The primitive is pure — it takes ``summarize``/``combine`` callables and never touches an LLM — so
these pass plain functions and assert the batching, recursion, depth bound, and partition-isolation.
"""
from __future__ import annotations

from aughor.llm.reduce import hierarchical_reduce, partitioned_reduce


def test_empty_is_empty_string():
    assert hierarchical_reduce([], summarize=lambda b: "x", combine=lambda s: "y") == ""


def test_single_batch_one_summarize_call():
    calls = []
    out = hierarchical_reduce(
        [1, 2, 3],
        summarize=lambda b: (calls.append(("sum", list(b))), ",".join(map(str, b)))[1],
        combine=lambda s: (calls.append(("comb", list(s))), "|".join(s))[1],
        fanout=8,
    )
    assert out == "1,2,3"
    assert [c[0] for c in calls] == ["sum"]          # no combine — fit in one batch


def test_multi_batch_maps_then_combines():
    summarized, combined = [], []
    out = hierarchical_reduce(
        list(range(20)),
        summarize=lambda b: (summarized.append(list(b)), f"<{len(b)}>")[1],
        combine=lambda s: (combined.append(list(s)), "+".join(s))[1],
        fanout=8,
    )
    # 20 items / fanout 8 → batches of 8, 8, 4
    assert [len(b) for b in summarized] == [8, 8, 4]
    assert combined == [["<8>", "<8>", "<4>"]]        # one combine over the 3 batch summaries
    assert out == "<8>+<8>+<4>"


def test_deep_recursion_folds_in_levels():
    # 100 items, fanout 4 → 25 leaf summaries → fold 25 → 7 → 2 → 1
    combine_batch_sizes = []
    hierarchical_reduce(
        list(range(100)),
        summarize=lambda b: "s",
        combine=lambda s: (combine_batch_sizes.append(len(s)), "c")[1],
        fanout=4,
        max_depth=6,
    )
    # at least two fold levels happened (25 summaries can't combine in one fanout-4 batch)
    assert len(combine_batch_sizes) > 1


def test_max_depth_forces_a_single_combine():
    combined = []
    hierarchical_reduce(
        list(range(40)),
        summarize=lambda b: "s",
        combine=lambda s: (combined.append(len(s)), "c")[1],
        fanout=4,
        max_depth=1,            # no recursion past the first fold
    )
    # 40/4 = 10 leaf summaries → one combine over all 10 (depth bound hit)
    assert combined == [10]


def test_partitioned_reduce_never_blends_groups():
    seen = {}
    out = partitioned_reduce(
        {"sales": [1, 2, 3], "support": [4, 5]},
        summarize_group=lambda k, v: (seen.__setitem__(k, list(v)), f"{k}={sum(v)}")[1],
        combine=lambda s: " / ".join(s),
    )
    assert seen == {"sales": [1, 2, 3], "support": [4, 5]}   # each group got ONLY its own items
    assert out == "sales=6 / support=9"


def test_partitioned_reduce_skips_empty_groups():
    out = partitioned_reduce(
        {"a": [1], "b": [], "c": [2]},
        summarize_group=lambda k, v: k,
        combine=lambda s: ",".join(s),
    )
    assert out == "a,c"


def test_partitioned_reduce_all_empty_is_empty():
    out = partitioned_reduce({"a": [], "b": []}, summarize_group=lambda k, v: k, combine=lambda s: "x")
    assert out == ""
