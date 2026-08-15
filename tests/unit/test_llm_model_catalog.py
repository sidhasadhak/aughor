"""The model catalogue — OpenRouter as a provider, and the picker's list of values.

Rewritten 2026-08-15, when every hardcoded model id was removed from the product
(operator decision). What this file used to assert — that a curated floor exists, that
the shipped defaults are free-tier, that each agent carries a recommendation — is now
the opposite of the contract, so those tests are gone and their inverse is pinned here
instead, plus a rot guard (:func:`test_no_model_id_ships_in_the_product`) so the lists
cannot creep back one convenient id at a time.

The contract now:
  * the picker shows what the PROVIDER serves, plus what the operator kept — nothing else;
  * a failed live fetch yields an EMPTY picker and says why, rather than a stale floor
    presented with the same authority as the real thing;
  * no role, backend, agent or tier carries a built-in model id;
  * asking for a binding that was never configured raises, loudly.

Live fetches are disabled here (``AUGHOR_LLM_MODEL_FETCH=0``) so the suite never depends
on a remote host being up.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from aughor.llm import models as M
from aughor.llm import provider as P

#: A binding for the tests that need one. Arbitrary and meaningless on purpose — the
#: point of the change is that the product no longer knows any real ids, so a test must
#: supply its own rather than lean on one that ships.
_TEST_MODELS = {"coder": "test/coder", "narrator": "test/narrator", "fast": "test/fast"}


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Point the inference config at a tmp file — it holds encrypted API keys, so
    a test must never touch the real one."""
    cfg = tmp_path / "llm_config.json"
    cfg.write_text(json.dumps({"backend": "openrouter", "models": dict(_TEST_MODELS)}))
    original = P._CONFIG_PATH
    P._CONFIG_PATH = cfg          # restored below, NOT via monkeypatch: the reload
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "0")   # in teardown must happen AFTER
    P.load_config()               # the path is put back, or the module keeps the tmp
    M.clear_cache()               # config cached and later tests see this backend.
    yield
    P._CONFIG_PATH = original
    P.load_config()
    M.clear_cache()


# ── OpenRouter is a first-class provider ──────────────────────────────────────

def test_openrouter_is_registered():
    assert "openrouter" in P.BACKENDS
    assert "openrouter" in P.NEEDS_KEY               # it takes a key
    assert P._DEFAULT_BASE_URLS["openrouter"] == "https://openrouter.ai/api/v1"
    assert P._KEY_ENV["openrouter"] == "OPENROUTER_API_KEY"


def test_openrouter_is_not_treated_as_a_local_backend():
    assert "openrouter" not in P.LOCAL_BACKENDS      # its base URL is fixed


# ── nothing ships a model ─────────────────────────────────────────────────────

def test_no_backend_ships_a_default_model():
    for backend in P.BACKENDS:
        assert P.default_models(backend) == {}, f"{backend} still ships a default model"


def test_the_picker_is_empty_without_a_live_catalogue():
    """The inverse of the old `test_known_models_are_the_offline_floor`. An empty
    picker that says why beats a curated one that has gone stale: this repo shipped
    two OpenRouter ids that never existed and two Ollama ids that stopped working,
    and in every case the list still looked authoritative."""
    out = M.list_models("openrouter")
    assert out["live"] is False
    assert out["models"] == []
    assert out["defaults"] == {}


def test_no_backend_has_a_built_in_floor():
    for backend in P.BACKENDS:
        assert M.list_models(backend)["models"] == [], f"{backend} still has a floor"


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError):
        M.list_models("not-a-backend")


def test_asking_for_an_unconfigured_binding_raises():
    P.write_config({"backend": "openrouter"})        # a backend, but no models
    with pytest.raises(P.NoModelConfigured) as exc:
        P.require_model("openrouter", "coder")
    # The message has to be actionable — this is the whole benefit of removing the
    # default, and a bare KeyError would have been a worse outcome than the guess.
    assert "coder" in str(exc.value)
    assert "Settings" in str(exc.value)


def test_an_unconfigured_provider_constructs_and_refuses_at_dispatch(monkeypatch):
    """CONSTRUCTING is not USING, and conflating them broke a fail-soft path.

    The raise started life in `LLMProvider.__init__`. `SqlWriter.__init__` builds a
    provider eagerly and its callers treat a failed fix as "drop this angle, continue"
    — so an unconfigured role crashed an exploration that was designed to degrade
    (tests/integration/test_fault_injection.py caught it). The client needs no model to
    exist; the id rides on each request. So it builds, and `complete()` refuses.
    """
    monkeypatch.setattr(P, "_active_key", lambda b: "test-key")
    P.write_config({"backend": "openrouter"})        # a backend, but no models

    prov = P.LLMProvider("openrouter", "coder")      # must NOT raise
    assert prov._model == ""

    with pytest.raises(P.NoModelConfigured) as exc:
        prov.complete(system="s", user="u", response_model=dict)
    assert "coder" in str(exc.value)


# ── custom entries persist ────────────────────────────────────────────────────

def test_add_custom_model_persists_and_is_idempotent():
    M.add_custom_model("openrouter", "acme/private-v3")
    assert M.custom_models("openrouter") == ["acme/private-v3"]

    M.add_custom_model("openrouter", "acme/private-v3")          # again
    assert M.custom_models("openrouter") == ["acme/private-v3"]

    # survives a config reload — the point of persisting it
    P.load_config()
    assert M.custom_models("openrouter") == ["acme/private-v3"]

    out = M.list_models("openrouter")
    entry = next(m for m in out["models"] if m["id"] == "acme/private-v3")
    assert entry["source"] == "custom"
    assert out["custom"] == ["acme/private-v3"]


def test_custom_models_are_per_backend():
    M.add_custom_model("openrouter", "acme/one")
    M.add_custom_model("anthropic", "acme/two")
    assert M.custom_models("openrouter") == ["acme/one"]
    assert M.custom_models("anthropic") == ["acme/two"]
    assert "acme/two" not in {m["id"] for m in M.list_models("openrouter")["models"]}


def test_remove_custom_model():
    M.add_custom_model("openrouter", "acme/a")
    M.add_custom_model("openrouter", "acme/b")
    assert M.remove_custom_model("openrouter", "acme/a") == ["acme/b"]
    P.load_config()
    assert M.custom_models("openrouter") == ["acme/b"]


def test_a_live_entry_is_not_removable(monkeypatch):
    """Hiding a model the backend actually serves would make the picker disagree
    with reality — removal is for entries the user added."""
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "1")
    monkeypatch.setattr(M, "fetch_live_models",
                        lambda backend, timeout=6.0: ([{"id": "vendor/served", "source": "live"}], ""))
    M.clear_cache()
    assert "vendor/served" in {m["id"] for m in M.list_models("openrouter")["models"]}
    with pytest.raises(ValueError, match="not a custom entry"):
        M.remove_custom_model("openrouter", "vendor/served")


def test_add_rejects_blank_and_unknown_backend():
    with pytest.raises(ValueError):
        M.add_custom_model("openrouter", "   ")
    with pytest.raises(ValueError):
        M.add_custom_model("nope", "x")


def test_custom_entry_wins_when_it_also_appears_live(monkeypatch):
    """A live model the user also kept stays removable — the custom marking is
    what the UI keys its remove affordance on."""
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "1")
    monkeypatch.setattr(M, "fetch_live_models",
                        lambda backend, timeout=6.0: ([{"id": "vendor/m", "source": "live"}], ""))
    M.clear_cache()
    M.add_custom_model("openrouter", "vendor/m")

    entry = next(m for m in M.list_models("openrouter")["models"] if m["id"] == "vendor/m")
    assert entry["source"] == "custom"


def test_live_failure_surfaces_the_reason_and_shows_nothing(monkeypatch):
    """A failed fetch must be stated, not hidden behind a fallback that then poses as
    the real catalogue. It used to still show the floor; now there is nothing to show,
    which is the honest answer to "what does this provider serve?" when we could not ask."""
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "1")
    monkeypatch.setattr(M, "fetch_live_models",
                        lambda backend, timeout=6.0: ([], "ConnectError: refused"))
    M.clear_cache()

    out = M.list_models("openrouter")
    assert out["live"] is False
    assert "refused" in out["error"]
    assert out["models"] == []


def test_live_results_are_cached(monkeypatch):
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "1")
    calls = {"n": 0}

    def _fetch(backend, timeout=6.0):
        calls["n"] += 1
        return [{"id": "vendor/m", "source": "live"}], ""

    monkeypatch.setattr(M, "fetch_live_models", _fetch)
    M.clear_cache()
    M.list_models("openrouter")
    M.list_models("openrouter")
    assert calls["n"] == 1, "the catalogue moves in days; do not refetch per render"

    M.list_models("openrouter", refresh=True)
    assert calls["n"] == 2, "an explicit refresh must bypass the cache"


def test_a_live_context_window_is_recorded_for_the_tier(monkeypatch):
    """What replaced the hardcoded capability table: the provider's own declared
    context window, captured when the catalogue is fetched and read back by
    `profile.tier_for`. Without this the derived tier has nothing to derive from."""
    from aughor.llm.profile import declared_context

    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "1")
    monkeypatch.delenv("AUGHOR_MODEL_CONTEXT_TOKENS", raising=False)
    monkeypatch.setattr(M, "fetch_live_models", lambda backend, timeout=6.0: (
        [{"id": "vendor/wide", "source": "live", "context": 200_000}], ""))
    M.clear_cache()
    M.list_models("openrouter")
    assert declared_context("vendor/wide") == 200_000


# ── the API surface ───────────────────────────────────────────────────────────

def test_model_routes(client):
    listed = client.get("/llm/models", params={"backend": "openrouter"})
    assert listed.status_code == 200
    assert listed.json()["backend"] == "openrouter"

    added = client.post("/llm/models", json={"backend": "openrouter", "model": "acme/x"})
    assert added.status_code == 200
    assert added.json()["custom"] == ["acme/x"]

    removed = client.delete("/llm/models", params={"backend": "openrouter", "model": "acme/x"})
    assert removed.status_code == 200
    assert removed.json()["custom"] == []


def test_removing_a_model_that_is_not_custom_is_a_400(client):
    r = client.delete("/llm/models", params={"backend": "openrouter", "model": "acme/never-added"})
    assert r.status_code == 400


def test_config_exposes_openrouter_to_the_ui(client):
    body = client.get("/llm/config").json()
    assert "openrouter" in body["backends"]
    assert "openrouter" in body["needs_key"]
    # The key survives for payload stability; what it must never do again is carry a
    # model id the UI then presents as a suggestion.
    assert body["default_models"]["openrouter"] == {}


# ── the rot guard ─────────────────────────────────────────────────────────────

#: A model id, in the two shapes this repo ever shipped: ``vendor/model`` and a
#: ``:free`` / ``:cloud`` suffix. Kept narrow deliberately — this must fire on a
#: returning list, not on every string containing a slash.
_MODEL_ID = re.compile(
    r'"[A-Za-z0-9._-]+:(?:free|cloud)"'
    r'|"(?:nvidia|google|openai|anthropic|meta-llama|deepseek|moonshotai|z-ai|qwen'
    r'|cohere|poolside|mistralai|together)/[A-Za-z0-9._:-]+"'
)


def test_no_model_id_ships_in_the_product():
    """The lists came back before as one convenient id at a time; this is the ratchet.

    Every hardcoded model id was removed on 2026-08-15 — the picker's curated floor,
    the per-backend/role defaults, the vouched matrix, the capability families and the
    per-agent pins. A model id in shipped code is a claim about another vendor's
    catalogue that this repo has no way to keep true, and every one of them went stale
    silently: retired mid-life, quietly made subscription-only, or never real at all.

    Tests may name ids (they need something concrete to assert on); `aughor/` may not.
    """
    root = pathlib.Path(__file__).resolve().parents[2] / "aughor"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if _MODEL_ID.search(line):
                rel = path.relative_to(root.parent).as_posix()
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "a hardcoded model id is back in the product:\n  " + "\n  ".join(offenders)
        + "\n\nThe catalogue comes from the provider's own /models; a binding comes from "
          "the operator. If you need one for a test, put it in the test."
    )


def test_no_charter_recommends_a_model():
    """`recommended_models` and POST /agents/apply-recommended-models are gone: the
    feature's entire content was six hardcoded ids."""
    from aughor.kernel.agents import AGENTS

    for charter in AGENTS:
        assert not hasattr(charter, "recommended_models"), \
            f"{charter.id} carries a model recommendation again"


def test_the_apply_recommended_route_is_gone(client):
    assert client.post("/agents/apply-recommended-models", json={}).status_code in (404, 405)


def test_the_vouched_matrix_module_is_gone():
    with pytest.raises(ImportError):
        import aughor.llm.matrix  # noqa: F401


# ── every registered backend must actually be constructible ───────────────────

def test_every_backend_builds_a_client(monkeypatch):
    """The bug this exists for: openrouter was added to BACKENDS, NEEDS_KEY,
    _KEY_ENV and base URLs — but not to the client-builder dispatch. Selecting it
    raised "Unknown backend: 'openrouter'. Use one of ..., openrouter" — an error
    that lists the backend it just refused, because the message interpolates
    BACKENDS while the branch had no arm for it.

    Registering metadata is not wiring. This asserts the whole set. The model is
    passed explicitly now: with no defaults, resolution would raise before the
    dispatch this test is about is ever reached.
    """
    from aughor.llm.provider import LLMProvider

    for backend in P.BACKENDS:
        # every keyed backend gets a dummy so the builders do not bail on a missing key
        monkeypatch.setattr(P, "_active_key", lambda b: "test-key")
        try:
            LLMProvider(backend, "coder", model="test/model")
        except ValueError as exc:                     # the dispatch has no arm
            pytest.fail(f"{backend} is registered but has no client builder: {exc}")
        except Exception:
            pass    # a network/SDK failure is fine here — dispatch is what we assert


def test_openrouter_uses_the_openai_compatible_client(monkeypatch):
    monkeypatch.setattr(P, "_active_key", lambda b: "test-key")
    built: list = []
    monkeypatch.setattr(P, "_build_openai_compat",
                        lambda url, key: built.append((url, key)) or object())

    from aughor.llm.provider import LLMProvider
    LLMProvider("openrouter", "coder", model="test/model")

    assert built, "openrouter did not route to the OpenAI-compatible builder"
    assert built[0][0] == P._DEFAULT_BASE_URLS["openrouter"]


# ── connection test coverage ──────────────────────────────────────────────────

def test_connection_test_covers_every_role_not_just_coder(monkeypatch):
    """The bug: test_provider hardcoded role "coder" in three places and the UI
    passed models.coder, so exactly ONE completion ran. A green result said
    nothing about the narrator or fast bindings, which can be different models
    with their own ids and quotas — visible as a single call in the provider's
    own request log."""
    pinged: list = []
    monkeypatch.setattr(P, "_ping",
                        lambda b, m, role="coder": pinged.append((m, role)) or
                        {"model": m, "ok": True, "ms": 1.0})

    out = P.test_provider(backend="openrouter")

    tested = {m for m, _ in pinged}
    assert tested == set(_TEST_MODELS.values()), f"only tested {tested}"
    assert out["tested"] == len(tested)
    assert out["ok"] is True


def test_a_non_active_backend_has_nothing_to_test(monkeypatch):
    """It used to be probed against its built-in defaults. With none shipped there is
    nothing to probe until the operator configures it — and reporting a pass built on
    a guess is exactly what this change exists to stop."""
    monkeypatch.setattr(P, "_ping",
                        lambda b, m, role="coder": {"model": m, "ok": True, "ms": 1.0})
    out = P.test_provider(backend="anthropic")       # active backend is openrouter
    assert out["results"] == []
    assert out["ok"] is False, "an untested backend must never report as a pass"
    assert "no model configured" in out["error"]


def test_identical_role_models_are_pinged_once(monkeypatch):
    """Most setups point several roles at one model; three identical pings would
    be three times the cost for one fact."""
    pinged: list = []
    monkeypatch.setattr(P, "_ping",
                        lambda b, m, role="coder": pinged.append(m) or
                        {"model": m, "ok": True, "ms": 1.0})
    monkeypatch.setattr(P, "_active_model", lambda b, role: "one/model")
    monkeypatch.setattr(P, "_active_backend", lambda: "openrouter")

    out = P.test_provider(backend="openrouter")
    assert pinged == ["one/model"]
    assert out["results"][0]["used_by"] == ["coder", "narrator", "fast"]


def test_one_broken_binding_fails_the_whole_test(monkeypatch):
    """A narrator model that 404s must not be hidden behind a working coder."""
    def _ping(b, m, role="coder"):
        ok = "narrator" not in m
        return {"model": m, "ok": ok, "ms": 1.0, **({} if ok else {"error": "404 no such model"})}

    monkeypatch.setattr(P, "_ping", _ping)
    out = P.test_provider(backend="openrouter")

    assert out["ok"] is False
    assert out["failed"] == 1
    assert "narrator" in out["error"]
    assert [r for r in out["results"] if r["ok"]], "the working ones still report ok"


def test_agent_pins_are_tested_when_asked(monkeypatch):
    pinged: list = []
    monkeypatch.setattr(P, "_ping",
                        lambda b, m, role="coder": pinged.append(m) or
                        {"model": m, "ok": True, "ms": 1.0})
    monkeypatch.setattr(P, "_active_backend", lambda: "openrouter")
    monkeypatch.setattr("aughor.kernel.agents.effective_governance",
                        lambda aid, ws=None: type("G", (), {"model": "pinned/only-for-agents"})())

    out = P.test_provider(backend="openrouter", include_agents=True)
    assert "pinned/only-for-agents" in pinged
    entry = next(r for r in out["results"] if r["model"] == "pinned/only-for-agents")
    assert any(u.startswith("agent:") for u in entry["used_by"])


def test_explicit_model_still_tests_just_that_one(monkeypatch):
    pinged: list = []
    monkeypatch.setattr(P, "_ping",
                        lambda b, m, role="coder": pinged.append(m) or
                        {"model": m, "ok": True, "ms": 1.0})
    P.test_provider(backend="openrouter", model="just/this-one")
    assert pinged == ["just/this-one"]


def test_an_unconfigured_binding_is_a_400_not_an_internal_error(client, monkeypatch):
    """A loud failure the UI renders as "internal_error" is not loud. The catch-all
    handler hides exception text — correct for internal faults, exactly wrong for the
    one error the operator can actually fix."""
    from aughor.llm.provider import NoModelConfigured

    def _boom(*a, **k):
        raise NoModelConfigured("openrouter", "coder")

    monkeypatch.setattr("aughor.llm.provider.test_provider", _boom)
    r = client.post("/llm/config/test", json={"backend": "openrouter"})
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"] == "no_model_configured"
    assert body["role"] == "coder"
    assert "Settings" in body["detail"]


# ── capabilities are asked for, not matched on the name ───────────────────────

def test_ollama_facts_come_from_api_show(monkeypatch):
    """`/api/show` publishes both facts this codebase used to guess from the model NAME.
    The guess was wrong on the deployment's own binding: a model declaring
    `capabilities: [completion, tools, thinking]` matched no keyword in the tools list,
    so every structured call ran in JSON mode and came back empty."""
    import httpx

    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"capabilities": ["completion", "tools", "thinking"],
                    "model_info": {"deepseek4.context_length": 1_048_576,
                                   "deepseek4.embedding_length": 4096}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _R())
    facts = M.ollama_model_facts("http://localhost:11434/v1", "vendor-x:cloud")
    assert facts == {"tools": True, "context": 1_048_576}


def test_ollama_facts_degrade_to_nothing_when_the_model_is_gone(monkeypatch):
    """A retired id answers nothing; the caller must keep its conservative default
    rather than inherit another model's numbers."""
    import httpx

    def _boom(*a, **k):
        raise RuntimeError("404 model not found")

    monkeypatch.setattr(httpx, "post", _boom)
    assert M.ollama_model_facts("http://localhost:11434/v1", "retired:cloud") == {}


def test_a_declared_tools_capability_selects_TOOLS_mode(monkeypatch):
    """The live defect, pinned: JSON mode on a thinking model returns empty content."""
    import instructor

    monkeypatch.setattr(P, "model_supports_tools", lambda m: m == "declares/tools")
    assert P._build_ollama_client("declares/tools", "http://x/v1").mode is instructor.Mode.TOOLS
    # unknown ⇒ JSON, the conservative mode (and the pre-2026-08-15 default)
    assert P._build_ollama_client("unknown/model", "http://x/v1").mode is instructor.Mode.JSON


def test_tool_support_round_trips_through_the_config(monkeypatch):
    monkeypatch.delenv("AUGHOR_MODEL_TOOLS", raising=False)
    assert P.model_supports_tools("vendor/x") is None      # nobody has asked yet
    M._record_model_facts([{"id": "vendor/x", "tools": True, "context": 200_000}])
    assert P.model_supports_tools("vendor/x") is True
    from aughor.llm.profile import declared_context
    assert declared_context("vendor/x") == 200_000


def test_max_context_is_the_declared_window_not_a_name_match(monkeypatch):
    """The substring table this replaced was wrong in the dangerous direction on a real
    binding: it claimed qwen2.5-coder held 131,072 where Ollama reports 32,768, and its
    own comment says an over-estimate silences the overflow guard."""
    from aughor.control_plane.inference import _DEFAULT_CONTEXT, _max_context

    monkeypatch.setattr("aughor.llm.profile.declared_context",
                        lambda m: 32_768 if m == "qwen2.5-coder:14b" else None)
    assert _max_context("qwen2.5-coder:14b") == 32_768
    assert _max_context("never/asked") == _DEFAULT_CONTEXT
