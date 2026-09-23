"""RC-2 on the unattended path — a scheduled Slack post draws its own rows.

The interactive bot got charts in RC-2 (`bots/slack/`, which renders the SVG through
`/charts/svg` and rasterizes at its own edge). The cron path never did: `_dispatch_slack_post`
called `post_as_bot`, which takes `text` and nothing else, so a scheduled run posted prose
while the renderer sat one import away and the bot already held `files:write`.

What these guard, in the order the bugs would bite:

* **Column order, not dict order.** `trusted_query` publishes rows as dicts. Reading them
  with `list(r.values())` looks identical on every fixture whose keys happen to be in
  column order — so the fixture here deliberately is NOT, and that shortcut fails it.
* **Slack's resolved channel id, not the configured name.** `completeUploadExternal` does
  not resolve `#name`. A chain configured with a channel name would fail the third hop on
  every single run, and the message would already have landed — so the failure is invisible
  unless something asserts which id the upload was handed.
* **The chart never costs the send.** A dead node, a slow bundle, a grid with no honest
  chart, a refused upload: the message is the answer and it has already been posted.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from aughor.automations.engine import CHART_GRID_KEY, _attach_chart, chart_grid
from aughor.automations.models import Effect


class _Bot:
    bot_token = "xoxb-test"
    name = "Aughor"
    enabled = True


class _Automation:
    id = "auto-1"
    name = "Top sellers"
    conn_id = ""


def _send(ref: str = "step1.answer") -> Effect:
    return Effect(kind="slack_post",
                  config={"bot_id": "b1", "channel": "#revenue", "message": {"$from": ref}})


# ── the grid the send is a picture of ────────────────────────────────────────────

def test_dict_rows_are_read_in_COLUMN_order_not_key_order():
    """The mutation this exists to kill: `list(r.values())`.

    The keys below are deliberately in a different order from `columns`, which is the
    only arrangement that tells the two implementations apart. A fixture whose dicts
    happened to be column-ordered would pass either way — the guard would look right
    for the wrong reason, and the chart would silently plot the wrong axis.
    """
    context = {"step1": {"columns": ["customer", "amount"],
                         # amount FIRST — key order is the trap
                         "rows": [{"amount": 672, "customer": "1000112"},
                                  {"amount": 519, "customer": "1000134"}]}}
    grid = chart_grid(_send(), context)
    assert grid["columns"] == ["customer", "amount"]
    assert grid["rows"] == [["1000112", 672], ["1000134", 519]]


def test_positional_rows_pass_through():
    context = {"step1": {"columns": ["a", "b"], "rows": [[1, 2], [3, 4]]}}
    assert chart_grid(_send(), context)["rows"] == [[1, 2], [3, 4]]


def test_no_upstream_grid_is_an_empty_verdict():
    """A send bound to a synthesis's prose has no rows of its own — and must not
    borrow the trigger's. Empty means "no picture", which the dispatcher reads as
    "post the message and stop"."""
    assert chart_grid(_send(), {"step1": {"answer": "revenue rose"}}) == {}
    assert chart_grid(_send(), {}) == {}


def test_the_trigger_is_never_the_chart():
    """`departure_basis` skips the trigger alias and so does this: a trigger payload
    can carry `rows`, and charting it would draw the firing condition rather than the
    answer the message is about."""
    ctx = {"trigger": {"columns": ["x"], "rows": [[1]]}}
    assert chart_grid(_send("trigger.rows"), ctx) == {}


def test_first_grid_wins_when_a_send_reads_two():
    """`departure_basis`'s rule, for its reason: two grids are two pictures and no
    answer to which one the message is OF."""
    effect = Effect(kind="slack_post", config={"bot_id": "b1", "channel": "#c",
                                               "message": {"$from": "step1.answer"},
                                               "extra": {"$from": "step2.answer"}})
    ctx = {"step1": {"columns": ["a"], "rows": [[1]]},
           "step2": {"columns": ["b"], "rows": [[2]]}}
    assert chart_grid(effect, ctx)["columns"] == ["a"]


# ── the attach ───────────────────────────────────────────────────────────────────

def _patched(monkeypatch, *, svg: Any = "<svg/>", png: Any = b"PNG", calls: list) -> None:
    import aughor.export.echarts as echarts
    import aughor.slackbots.post as post
    monkeypatch.setattr(echarts, "render_chart_svg", lambda *a, **k: svg)
    monkeypatch.setattr(echarts, "svg_to_png", lambda *a, **k: png)
    monkeypatch.setattr(post, "upload_file",
                        lambda token, channel_id, **kw: (calls.append((channel_id, kw)), (True, {}))[1])


def test_upload_gets_slacks_resolved_id_and_the_posts_thread(monkeypatch):
    """The configured channel is `#revenue`; Slack resolved it to `C123` when the
    message posted. The upload must use `C123` — `completeUploadExternal` will not
    take the name — and must land in the thread the message just opened, so the
    picture sits under its own prose rather than loose in the channel.
    """
    calls: list = []
    _patched(monkeypatch, calls=calls)
    _attach_chart(_grid_effect(), _Automation(), _Bot(),
                  {"channel": "C123", "ts": "170.5"}, "#revenue")
    assert len(calls) == 1
    channel_id, kw = calls[0]
    assert channel_id == "C123", "must not pass the configured '#revenue'"
    assert kw["thread_ts"] == "170.5"
    assert kw["data"] == b"PNG"


def test_no_honest_chart_posts_nothing(monkeypatch):
    """`render_charts_svg` returns None for an un-chartable grid — the same 204 the
    browser reaches for the same rows. That is a verdict, not a fault: no upload."""
    calls: list = []
    _patched(monkeypatch, svg=None, png=None, calls=calls)
    _attach_chart(_grid_effect(), _Automation(), _Bot(),
                  {"channel": "C123", "ts": "170.5"}, "#revenue")
    assert calls == []


def test_an_empty_grid_posts_nothing(monkeypatch):
    calls: list = []
    _patched(monkeypatch, calls=calls)
    effect = Effect(kind="slack_post",
                    config={"bot_id": "b1", "channel": "#c", CHART_GRID_KEY: {}})
    _attach_chart(effect, _Automation(), _Bot(), {"channel": "C1", "ts": "1"}, "#c")
    assert calls == []


def test_a_raising_renderer_never_breaks_the_send(monkeypatch):
    """The message has already posted by the time this runs. An exception here would
    turn a delivered message into a dispatch_error and earn it a retry — a duplicate
    post caused entirely by the decoration."""
    import aughor.export.echarts as echarts

    def _boom(*a, **k):
        raise RuntimeError("node is gone")

    monkeypatch.setattr(echarts, "render_chart_svg", _boom)
    _attach_chart(_grid_effect(), _Automation(), _Bot(),
                  {"channel": "C1", "ts": "1"}, "#c")  # must not raise


def test_a_missing_channel_id_posts_nothing(monkeypatch):
    calls: list = []
    _patched(monkeypatch, calls=calls)
    _attach_chart(_grid_effect(), _Automation(), _Bot(), {"ts": "1"}, "#c")
    assert calls == []


def _grid_effect() -> Effect:
    return Effect(kind="slack_post", config={
        "bot_id": "b1",
        "channel": "#revenue",
        CHART_GRID_KEY: {"columns": ["customer", "amount"],
                         "rows": [["1000112", 672], ["1000134", 519]]}})


# ── the three hops ───────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_upload_is_three_hops_and_the_ticket_hop_is_form_encoded(monkeypatch):
    """Hop 1 rejects an application/json body and answers `invalid_arguments`, which
    says nothing about why. Asserting the content type here is what keeps a future
    tidy-up from making all three hops "consistently JSON" and breaking uploads."""
    import aughor.slackbots.post as post
    seen: list = []

    def _urlopen(req, timeout=None):
        seen.append(req)
        url = req.full_url
        if "getUploadURLExternal" in url:
            return _Resp(json.dumps({"ok": True, "upload_url": "https://files/up",
                                     "file_id": "F1"}).encode())
        if "completeUploadExternal" in url:
            return _Resp(json.dumps({"ok": True}).encode())
        return _Resp(b"")

    monkeypatch.setattr(post.urllib.request, "urlopen", _urlopen)
    ok, info = post.upload_file("xoxb", "C123", data=b"PNG", filename="chart.png",
                                title="Top sellers", thread_ts="170.5")
    assert ok and info["file_id"] == "F1"
    assert len(seen) == 3, "ticket, bytes, complete"
    assert seen[0].headers["Content-type"] == "application/x-www-form-urlencoded"
    assert b"filename=chart.png" in seen[0].data
    assert seen[1].full_url == "https://files/up"
    body = json.loads(seen[2].data.decode())
    assert body["channel_id"] == "C123" and body["thread_ts"] == "170.5"
    assert body["files"] == [{"id": "F1", "title": "Top sellers"}]


def test_a_refused_ticket_stops_before_the_bytes(monkeypatch):
    import aughor.slackbots.post as post
    seen: list = []

    def _urlopen(req, timeout=None):
        seen.append(req)
        return _Resp(json.dumps({"ok": False, "error": "invalid_auth"}).encode())

    monkeypatch.setattr(post.urllib.request, "urlopen", _urlopen)
    ok, info = post.upload_file("xoxb", "C1", data=b"PNG", filename="c.png")
    assert not ok and info["error"] == "invalid_auth"
    assert len(seen) == 1, "no bytes are sent at a URL we were never given"


@pytest.mark.parametrize("kw,err", [
    ({"data": b"", "filename": "c.png"}, "no bytes"),
    ({"data": b"x", "filename": "c.png", "channel_id": ""}, "no channel"),
])
def test_refusals_are_typed_not_silent(kw, err):
    import aughor.slackbots.post as post
    channel = kw.pop("channel_id", "C1")
    ok, info = post.upload_file("xoxb", channel, **kw)
    assert not ok and info["error"] == err


# ── the headless renderer's missing tier ─────────────────────────────────────────

@pytest.mark.parametrize("columns,rows,expected", [
    (["product", "revenue"], [["Nike", 48210], ["Levi", 41775]], True),
    (["product", "revenue"], [["Nike", "48210"]], True),          # BigQuery hands counts back as strings
    (["customer_id", "amount"], [["1000112", 672]], True),        # a numeric-STRING id is a label
    (["month", "revenue"], [[1.5, 48210.0]], False),              # two real measures — a scatter
    (["month", "revenue"], [[1, 48210]], False),                  # both numeric — could be a scatter
    (["product", "region"], [["Nike", "EU"]], False),             # no magnitude to rank
    (["product", "revenue", "units"], [["Nike", 1, 2]], False),   # three columns is another shape
    (["product", "revenue"], [], False),
])
def test_only_one_label_against_one_magnitude_earns_the_fallback(columns, rows, expected):
    """The gate on the bar retry. Tier 1 refuses unknown types precisely because falling
    through to bar drew a `scatter` as a correctly-themed, entirely wrong bar chart — so
    the retry is allowed only for the shape a ranked bar cannot misrepresent."""
    from aughor.automations.engine import _ranked_magnitudes
    assert _ranked_magnitudes(columns, rows) is expected


def test_a_refused_treemap_retries_as_a_ranked_bar(monkeypatch):
    """`auto` sends "top sellers by revenue" to a treemap, which the Vega-only headless
    renderer does not draw. Without this retry the flagship scheduled post — the one
    that prompted the whole feature — silently carries no picture."""
    import aughor.export.echarts as echarts
    import aughor.slackbots.post as post
    asked: list = []
    calls: list = []

    def _render(columns, rows, chart_type, title, **kw):
        asked.append(chart_type)
        return None if chart_type == "auto" else "<svg/>"

    monkeypatch.setattr(echarts, "render_chart_svg", _render)
    monkeypatch.setattr(echarts, "svg_to_png", lambda *a, **k: b"PNG")
    monkeypatch.setattr(post, "upload_file",
                        lambda t, c, **kw: (calls.append(c), (True, {}))[1])
    _attach_chart(_grid_effect(), _Automation(), _Bot(),
                  {"channel": "C1", "ts": "1"}, "#c")
    assert asked == ["auto", "bar"], "auto first, then exactly one honest retry"
    assert calls == ["C1"]


def test_a_refused_scatter_is_not_retried_as_a_bar(monkeypatch):
    """The lie tier 1 exists to prevent. Three columns is not a ranked magnitude, so a
    null stays a null and the post carries no picture rather than a wrong one."""
    import aughor.export.echarts as echarts
    import aughor.slackbots.post as post
    asked: list = []
    calls: list = []
    monkeypatch.setattr(echarts, "render_chart_svg",
                        lambda c, r, ct, t, **kw: (asked.append(ct), None)[1])
    monkeypatch.setattr(echarts, "svg_to_png", lambda *a, **k: b"PNG")
    monkeypatch.setattr(post, "upload_file",
                        lambda t, c, **kw: (calls.append(c), (True, {}))[1])
    effect = Effect(kind="slack_post", config={
        "bot_id": "b1", "channel": "#c",
        CHART_GRID_KEY: {"columns": ["a", "b", "c"], "rows": [[1, 2, 3]]}})
    _attach_chart(effect, _Automation(), _Bot(), {"channel": "C1", "ts": "1"}, "#c")
    assert asked == ["auto"], "no second attempt for a shape bar would misrepresent"
    assert calls == []
