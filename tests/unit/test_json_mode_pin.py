"""An operator can pin a model to JSON structured output — deliberately (2026-09-07).

`ToolsDeclarationError` refuses a model that advertises tool calling and then does not
do it, because working around a false declaration silently leaves a model that
misreports itself in place. That refusal is right, and it leaves an operator who KNOWS
their model cannot do tool calling with no way to use it.

This is that way, and the difference is consent: the pin is a thing a person set, once,
in config. The two must compose — a pinned model goes to JSON mode and therefore never
reaches the accusation at all.
"""
from __future__ import annotations

import instructor
import pytest

from aughor.llm import provider as P


@pytest.fixture
def _isolated_config(monkeypatch):
    """A stubbed in-memory config for the MODE tests.

    Deliberately NOT autouse: it replaces `_cfg` wholesale, so applying it to the
    config-write tests below made `current_config()` read an empty dict and every one
    of them fail. Two different isolations for two different subjects.
    """
    cfg: dict = {}
    monkeypatch.setattr(P, "_cfg", lambda: cfg)
    return cfg


def test_a_pinned_model_is_built_in_json_mode(_isolated_config, monkeypatch):
    monkeypatch.setattr(P, "model_supports_tools", lambda m: True)   # it CLAIMS tools
    _isolated_config["json_mode"] = {"ollama": ["m:1"]}

    pinned = P._build_ollama_client("m:1", "http://localhost:11434")
    assert pinned.mode == instructor.Mode.JSON

    other = P._build_ollama_client("m:2", "http://localhost:11434")
    assert other.mode == instructor.Mode.TOOLS       # the pin is per model


def test_the_pin_is_scoped_to_its_backend(_isolated_config, monkeypatch):
    monkeypatch.setattr(P, "model_supports_tools", lambda m: True)
    _isolated_config["json_mode"] = {"lmstudio": ["m:1"]}
    assert P.forces_json_mode("lmstudio", "m:1") is True
    assert P.forces_json_mode("ollama", "m:1") is False
    assert P._build_ollama_client("m:1", "http://localhost:11434").mode == instructor.Mode.TOOLS


def test_a_pinned_model_never_reaches_the_accusation(_isolated_config, monkeypatch):
    """The two features compose: consent short-circuits the refusal."""
    monkeypatch.setattr(P, "model_supports_tools", lambda m: True)
    _isolated_config["json_mode"] = {"ollama": ["m:1"]}
    client = P._build_ollama_client("m:1", "http://localhost:11434")

    class InstructorRetryException(Exception):
        pass
    from types import SimpleNamespace
    exc = InstructorRetryException("validation failed")
    exc.last_completion = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content="{}", tool_calls=None))])

    # JSON mode -> not a TOOLS call -> nothing to accuse the model of.
    P._raise_if_tools_declaration_false(client, "ollama", "m:1", exc)


def test_an_unpinned_model_is_unaffected(_isolated_config):
    assert P.forces_json_mode("ollama", "anything") is False


# ── the config write path, driven through the REAL set_config ─────────────────
#
# An earlier draft reimplemented the merge rules here and asserted against its own
# copy — a guard supplied by the same hand, which cannot fail. These call `set_config`
# and read the result back off disk.

@pytest.fixture
def clean_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_CONFIG_PATH", tmp_path / "llm_config.json")
    monkeypatch.setattr(P, "_runtime", None)
    P._providers.clear()
    P._cache_version = -1
    P.load_config()
    yield


def _pins() -> dict:
    return P.current_config()["json_mode"]


def test_a_pin_round_trips_through_the_config(clean_cfg):
    P.set_config({"json_mode": {"ollama": ["qwen2.5-coder:14b"]}})
    assert _pins() == {"ollama": ["qwen2.5-coder:14b"]}
    assert P.forces_json_mode("ollama", "qwen2.5-coder:14b") is True


def test_a_backends_list_is_replaced_not_merged(clean_cfg):
    """"Off" has to be expressible — merge-only semantics can add a pin, never remove
    one."""
    P.set_config({"json_mode": {"ollama": ["a", "b"]}})
    P.set_config({"json_mode": {"ollama": ["a"]}})
    assert _pins() == {"ollama": ["a"]}


def test_an_empty_list_clears_that_backend_only(clean_cfg):
    P.set_config({"json_mode": {"ollama": ["a"], "lmstudio": ["z"]}})
    P.set_config({"json_mode": {"ollama": []}})
    assert _pins() == {"lmstudio": ["z"]}
    assert P.forces_json_mode("ollama", "a") is False


def test_entries_are_deduplicated_and_blanks_dropped(clean_cfg):
    P.set_config({"json_mode": {"ollama": ["a", "a", "  ", "b"]}})
    assert _pins() == {"ollama": ["a", "b"]}


def test_an_unknown_backend_is_refused(clean_cfg):
    with pytest.raises(ValueError, match="unknown backend"):
        P.set_config({"json_mode": {"not-a-backend": ["a"]}})
    assert _pins() == {}


def test_other_config_is_untouched_by_a_pin(clean_cfg):
    """A patch must not clobber neighbours — the schema is shared."""
    P.set_config({"base_urls": {"ollama": "http://elsewhere:11434"}})
    P.set_config({"json_mode": {"ollama": ["a"]}})
    c = P.current_config()
    assert c["json_mode"] == {"ollama": ["a"]}
    assert c["base_urls"]["ollama"] == "http://elsewhere:11434"


def test_the_ui_is_told_where_the_pin_actually_works(clean_cfg):
    """A control offered where it has no effect is worse than no control."""
    from aughor.llm.provider import JSON_MODE_PINNABLE
    vended = P.current_config()["json_mode_backends"]
    assert vended == list(JSON_MODE_PINNABLE)
    assert "ollama" in vended
    # lmstudio already builds in JSON_SCHEMA mode; nothing consults the pin there.
    assert "lmstudio" not in vended
