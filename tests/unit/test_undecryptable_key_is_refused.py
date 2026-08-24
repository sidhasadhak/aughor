"""A key that cannot be DECRYPTED must not be sent to a provider as if it were one.

`secretvault.decrypt_secret` returns an undecryptable value AS-IS, deliberately, "so one bad
record can't take down a read path". That is right for reading configuration and wrong at
the point of use: the ciphertext then travels as the credential, and the provider answers
about the credential.

Measured, driving the real ladder with `AUGHOR_SECRET_KEY` unset: `endpoint_for("gemini")`
returned `enc:…` — 171 characters of Fernet token — the call went to Google, and Google said
`400 Please pass a valid API key`. Which is true of what it received and false about what is
wrong: the stored key was fine, the secret that unlocks it was absent.

That is a costly kind of error message, because it sends a person to rotate a working key.
This project already carries the scar as a note that live calls from a bare script "401
silently" without the secret; this is the mechanism behind it.
"""
from __future__ import annotations

import pytest

from aughor.llm import provider
from aughor.secretvault import is_encrypted


def _ciphertext() -> str:
    """A value the vault itself agrees is encrypted.

    Asserted rather than assumed: the first draft of this file spelled the marker `enc:`
    where the vault uses `enc:v1:`, so `is_encrypted` said no, the guard correctly did not
    fire, and the test failed for a reason that had nothing to do with the behaviour under
    test. A fake that stops matching the predicate it stands in for is a test that
    silently stops testing."""
    value = "enc:v1:gAAAAABo" + "x" * 150
    assert is_encrypted(value), "this fake no longer looks encrypted to the vault"
    return value


def test_an_undecryptable_key_is_refused_and_names_the_real_cause(monkeypatch):
    monkeypatch.setattr(provider, "_active_key", lambda _b: _ciphertext())

    with pytest.raises(RuntimeError) as exc:
        provider.endpoint_for("gemini")

    message = str(exc.value)
    assert "AUGHOR_SECRET_KEY" in message, "the message must name the thing that is missing"
    assert "nothing was sent to the provider" in message
    assert "key itself is probably fine" in message, (
        "a person reading this must not be sent to rotate a working key")


def test_a_decrypted_key_passes_through(monkeypatch):
    monkeypatch.setattr(provider, "_active_key", lambda _b: "AIza-looks-like-a-real-key")

    base_url, key = provider.endpoint_for("gemini")

    assert key == "AIza-looks-like-a-real-key"
    assert base_url.startswith("https://")


def test_a_local_backend_needs_no_key_and_is_not_checked(monkeypatch):
    """Ollama takes no key. Running the ciphertext check against a backend that never has
    one would refuse a perfectly good local setup."""
    monkeypatch.setattr(provider, "_active_key",
                        lambda _b: pytest.fail("a local backend must not resolve a key"))

    base_url, key = provider.endpoint_for("ollama")

    assert key == "" and base_url


def test_an_unknown_backend_is_still_rejected():
    with pytest.raises(ValueError, match="unknown backend"):
        provider.endpoint_for("wishful")


def test_the_embedding_lane_surfaces_the_refusal(monkeypatch):
    """The path that found this. The lane's own "no API key" check passes — the value is
    non-empty — so without the guard one layer down, the first sign of trouble is a
    provider error."""
    from aughor.semantic import embedder

    monkeypatch.setenv("AUGHOR_EMBED_BACKEND", "gemini")
    monkeypatch.setenv("AUGHOR_EMBED_MODEL", "models/some-embedding-model")
    monkeypatch.setattr(provider, "_active_key", lambda _b: _ciphertext())

    with pytest.raises(RuntimeError, match="AUGHOR_SECRET_KEY"):
        embedder.endpoint()
