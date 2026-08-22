"""VA-5 — the waterfall's layout maths.

The two properties worth guarding are the two this module got wrong first: model calls
must appear at all (they carry no span id, and the tree that required one excluded 2,506
of them), and the aggregate idle figure must survive concurrency (a sum of per-node gaps
overstated dead time by 75 seconds on a real trace).
"""
from __future__ import annotations

from aughor.obs.trace_tree import build_timeline, flow_edges


def _ev(seq, kind, at, **kw):
    row = {"seq": seq, "kind": kind, "at": at, "name": kw.pop("name", kind)}
    row.update(kw)
    return row


T = "2026-08-22T10:00:{:02d}.000000+00:00"


# ── model calls are first-class, despite carrying no span id ──────────────────────

def test_a_model_call_becomes_a_node_even_though_it_has_no_span_id():
    """The measured gap: 2,506 llm_call rows, every one with a duration, 2,402 with token
    counts, and NOT ONE with a span id. A waterfall that requires a span id omits them
    all — which is to say it omits the model."""
    tl = build_timeline([
        _ev(1, "user_request", T.format(0)),
        _ev(2, "llm_call", T.format(1), duration_ms=900, model="m", provider="p",
            prompt_tokens=100, completion_tokens=20, total_tokens=120),
    ])
    model = [n for n in tl["nodes"] if n["kind"] == "model"]
    assert len(model) == 1
    assert model[0]["usage"] == {"prompt_tokens": 100, "completion_tokens": 20,
                                 "total_tokens": 120}
    assert model[0]["model"] == "m" and model[0]["provider"] == "p"
    assert tl["model_calls"] == 1


def test_usage_totals_roll_up_across_the_run():
    tl = build_timeline([
        _ev(1, "llm_call", T.format(0), duration_ms=10, total_tokens=100, prompt_tokens=90),
        _ev(2, "llm_call", T.format(1), duration_ms=10, total_tokens=50, prompt_tokens=40),
    ])
    assert tl["usage"]["total_tokens"] == 150 and tl["usage"]["prompt_tokens"] == 130


# ── the aggregate must survive concurrency ────────────────────────────────────────

def test_idle_is_the_interval_union_not_a_sum_of_gaps():
    """A LONG call with short ones running inside it — the shape a real trace has.

    The per-node gap compares each node to the one immediately before it, so once a long
    call is still running, every short call after it reports fake dead time. Here the
    naive sum claims 900ms idle while the run is busy end to end. On the real 157-node
    trace this is the whole 75-second discrepancy: 386.5s summed against 311.9s true.

    (An earlier version of this test used two mutually overlapping calls, where the gap
    clamp at zero made both readings agree — it passed against the broken code, which is
    why it is written this way now.)
    """
    tl = build_timeline([
        _ev(1, "llm_call", T.format(0), duration_ms=10000),  # 0 → 10000, still running
        _ev(2, "llm_call", T.format(1), duration_ms=100),    # 1000 → 1100, inside it
        _ev(3, "llm_call", T.format(2), duration_ms=100),    # 2000 → 2100, inside it
    ])
    assert tl["concurrent_nodes"] == 2, "the overlaps must be detected and named"
    assert tl["wall_ms"] == 10000
    assert tl["busy_ms"] == 10000, "the long call covers the whole run"
    assert tl["idle_ms"] == 0, "the run is busy throughout"

    gap_sum = sum(n["gap_ms"] or 0 for n in tl["nodes"])
    assert gap_sum == 900, "the sequential reading sees dead time that is not there"
    assert tl["idle_ms"] != gap_sum, (
        "idle must NOT be a sum of per-node gaps — that is the measure this replaced")


def test_a_fully_sequential_run_has_idle_equal_to_the_gap_sum():
    """The two readings must agree when nothing overlaps — otherwise the union is wrong."""
    tl = build_timeline([
        _ev(1, "llm_call", T.format(0), duration_ms=1000),
        _ev(2, "llm_call", T.format(2), duration_ms=1000),
        _ev(3, "llm_call", T.format(4), duration_ms=1000),
    ])
    assert tl["concurrent_nodes"] == 0
    gap_sum = sum(n["gap_ms"] or 0 for n in tl["nodes"])
    assert tl["idle_ms"] == gap_sum == 2000


# ── layout ────────────────────────────────────────────────────────────────────────

def test_offsets_are_relative_to_the_first_event():
    tl = build_timeline([
        _ev(1, "user_request", T.format(0)),
        _ev(2, "llm_call", T.format(3), duration_ms=100),
    ])
    assert tl["nodes"][0]["offset_ms"] == 0
    assert tl["nodes"][1]["offset_ms"] == 3000


def test_a_tool_call_and_its_result_are_ONE_node():
    tl = build_timeline([
        _ev(1, "tool_call", T.format(0), span_id="s1", name="run_sql"),
        _ev(2, "tool_call_result", T.format(1), span_id="s1", duration_ms=1200,
            ok=True, row_count=7),
    ])
    assert tl["span_count"] == 1
    node = tl["nodes"][0]
    assert node["name"] == "run_sql" and node["ok"] is True
    assert node["duration_ms"] == 1200 and node["row_count"] == 7


def test_depth_comes_from_real_parentage_and_is_never_invented():
    tl = build_timeline([
        _ev(1, "tool_call", T.format(0), span_id="p"),
        _ev(2, "tool_call", T.format(1), span_id="c", parent_span_id="p"),
        _ev(3, "llm_call", T.format(2), duration_ms=10),          # no parent at all
    ])
    by = {n["id"]: n for n in tl["nodes"]}
    assert by["p"]["depth"] == 0 and by["c"]["depth"] == 1
    assert [n for n in tl["nodes"] if n["kind"] == "model"][0]["depth"] == 0


def test_a_parent_cycle_cannot_hang_the_layout():
    tl = build_timeline([
        _ev(1, "tool_call", T.format(0), span_id="a", parent_span_id="b"),
        _ev(2, "tool_call", T.format(1), span_id="b", parent_span_id="a"),
    ])
    assert all(isinstance(n["depth"], int) for n in tl["nodes"])


def test_the_slowest_node_is_marked_and_only_one_is():
    tl = build_timeline([
        _ev(1, "llm_call", T.format(0), duration_ms=100),
        _ev(2, "llm_call", T.format(1), duration_ms=9000, name="slow"),
    ])
    crit = [n for n in tl["nodes"] if n["critical"]]
    assert len(crit) == 1 and crit[0]["name"] == "slow"


def test_flow_edges_carry_the_latency_between_nodes():
    """The reference renders that number ON the edge; it is what turns boxes-and-arrows
    into a reading of where the time went."""
    tl = build_timeline([
        _ev(1, "llm_call", T.format(0), duration_ms=1000),
        _ev(2, "llm_call", T.format(3), duration_ms=500),
    ])
    edges = flow_edges(tl)
    assert len(edges) == 1 and edges[0]["latency_ms"] == 2000


# ── degenerate input ──────────────────────────────────────────────────────────────

def test_an_empty_trace_returns_an_empty_layout_rather_than_raising():
    tl = build_timeline([])
    assert tl["nodes"] == [] and tl["span_count"] == 0


def test_events_without_timestamps_do_not_break_the_layout():
    tl = build_timeline([_ev(1, "llm_call", None, duration_ms=10),
                         _ev(2, "llm_call", T.format(0), duration_ms=10)])
    assert tl["span_count"] == 2


def test_a_space_separated_timestamp_is_parsed_not_compared():
    """SQLite's datetime('now') writes a space where these rows use a `T`; comparing them
    as strings is the trap this repo has hit before."""
    tl = build_timeline([
        _ev(1, "llm_call", "2026-08-22 10:00:00.000000+00:00", duration_ms=10),
        _ev(2, "llm_call", "2026-08-22T10:00:02.000000+00:00", duration_ms=10),
    ])
    assert tl["nodes"][1]["offset_ms"] == 2000
