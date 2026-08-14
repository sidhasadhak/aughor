"""OA·LF-1 — the rot guard that would have caught the silent death.

The Langfuse backend was configured, reported enabled, and shipped nothing for as
long as the dependency pin allowed a major bump. `telemetry.py` called `lf.trace()`,
`tr.span()` and `tr.generation()`; the installed client was 4.x, where none of those
exist; every call raised; every raise was swallowed at debug level. No test failed,
because every test asserted the *no-op* behaviour (that a call does not crash when
disabled) — which a permanently-broken backend also satisfies.

So these tests assert the opposite thing: not "it doesn't crash", but "the upstream
surface we depend on is still there". Each one fails on the version bump rather than
in production silence.

What we actually depend on, post-LF-1, is small — spans travel over plain OTLP:
  1. `Langfuse.create_trace_id(seed=…)` — deterministic trace ids.
  2. Langfuse's OTel attribute keys — the labels that make a span a generation.
  3. The OTLP/HTTP exporter — Langfuse's endpoint does not speak gRPC.
  4. The ingestion path + auth shape our exporter posts to.
"""
from __future__ import annotations

import base64

import pytest

import aughor.telemetry as tel

langfuse = pytest.importorskip("langfuse", reason="observability extra not installed")


# ── 1. the one SDK function we still call ─────────────────────────────────────

def test_create_trace_id_exists_and_is_deterministic():
    """`_lf_trace_id` derives a trace id from the investigation id. If this moves,
    every span in a sliced run silently lands on its own trace instead of joining
    one — the exact failure mode the memo used to paper over."""
    from langfuse import Langfuse
    assert hasattr(Langfuse, "create_trace_id"), \
        "langfuse dropped create_trace_id — telemetry._lf_trace_id has no seed function"
    a = tel._lf_trace_id("inv-abc")
    b = tel._lf_trace_id("inv-abc")
    assert a == b, "trace-id seeding stopped being deterministic"
    assert a != tel._lf_trace_id("inv-xyz"), "different investigations collided"
    assert a is not None and len(a) == 32 and int(a, 16) >= 0, \
        "trace id must be 32 lowercase hex chars to be a valid OTel trace id"


def test_v2_sdk_surface_is_gone_so_the_old_path_could_not_have_worked():
    """The finding this wave repairs, pinned as a fact rather than a claim: the
    methods the previous implementation called do not exist on the installed client."""
    from langfuse import Langfuse
    for dead in ("trace", "span", "generation"):
        assert not hasattr(Langfuse, dead), (
            f"Langfuse.{dead} exists again — re-check whether the v2 span path in "
            f"telemetry.py was really unreachable")


# ── 2. the attribute keys that label our spans ────────────────────────────────

def test_langfuse_otel_attribute_keys_match_the_constants_we_hardcode():
    """telemetry.py hardcodes these so a span is still labelled when `langfuse` is
    absent. Hardcoding is only safe if something checks the copy — otherwise a
    rename upstream un-labels every span and nothing fails."""
    A = langfuse.LangfuseOtelSpanAttributes
    assert tel._LF_TRACE_NAME == A.TRACE_NAME
    assert tel._LF_TRACE_INPUT == A.TRACE_INPUT
    assert tel._LF_TRACE_OUTPUT == A.TRACE_OUTPUT
    assert tel._LF_SESSION_ID == A.TRACE_SESSION_ID
    assert tel._LF_OBS_TYPE == A.OBSERVATION_TYPE
    assert tel._LF_OBS_INPUT == A.OBSERVATION_INPUT
    assert tel._LF_OBS_OUTPUT == A.OBSERVATION_OUTPUT
    assert tel._LF_OBS_MODEL == A.OBSERVATION_MODEL
    assert tel._LF_AS_ROOT == A.AS_ROOT


# ── 3. the transport ──────────────────────────────────────────────────────────

def test_otlp_http_exporter_is_importable():
    """Langfuse's OTLP endpoint speaks HTTP/protobuf, not gRPC. The historical
    exporter here was the gRPC one; importing the HTTP one is what LF-1 added."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    assert OTLPSpanExporter is not None


# ── 4. the ingestion contract we post to ──────────────────────────────────────

def test_endpoint_and_auth_match_the_sdks_own_span_processor(monkeypatch):
    """We build the endpoint + Basic-auth header ourselves rather than instantiate the
    client. That is only correct while it matches what the SDK's span processor builds
    (`langfuse/_client/span_processor.py`) — assert the shape, so a path change upstream
    surfaces here and not as spans that 404 into a debug log."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://example.langfuse.com")

    endpoint, headers = tel._langfuse_otlp()
    assert endpoint == "https://example.langfuse.com/api/public/otel/v1/traces"
    expected = base64.b64encode(b"pk-lf-test:sk-lf-test").decode("ascii")
    assert headers["Authorization"] == f"Basic {expected}"
    assert headers["x-langfuse-public-key"] == "pk-lf-test"


def test_host_trailing_slash_does_not_double_up(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_HOST", "https://example.langfuse.com/")
    endpoint, _ = tel._langfuse_otlp()
    assert "//api/public" not in endpoint


def test_unconfigured_is_none(monkeypatch):
    """Half-configured is unconfigured — a public key with no secret must not
    produce an exporter that 401s on every export."""
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-only")
    assert tel._langfuse_otlp() is None
