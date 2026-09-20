"""IN-4 — the Fernet key has one resolver, and an existing key is never abandoned.

This file is the sharpest hazard in the data-home wave. `data/.aughor_key` is gitignored, so
it is generated state and must travel with the rest of it — and it decrypts every stored DSN.
Before this, its path was computed twice, in two modules, from anchors a different number of
`.parent` hops apart, with no override on either:

    aughor/secretvault.py:20   Path(__file__).parent.parent        / "data" / ".aughor_key"
    aughor/db/registry.py:29   Path(__file__).parent.parent.parent / "data" / ".aughor_key"

The failure mode is silent. Resolving to a path where no key exists does not raise — it
GENERATES one, and every connection's DSN becomes undecryptable with no error until somebody
opens a connection. So the resolver prefers a key that already exists, wherever it is.
"""
from __future__ import annotations

import pytest

from aughor.db import keyfile


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """A state dir and a legacy anchor, both empty, both under tmp. The legacy anchor is
    monkeypatched because the real one exists in a developer's checkout — which is exactly
    what made the first hand-probe of this resolver misleading."""
    state = tmp_path / "state"
    state.mkdir()
    legacy = tmp_path / "checkout-data" / ".aughor_key"
    legacy.parent.mkdir()
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(state))
    monkeypatch.delenv(keyfile.KEY_FILE_ENV, raising=False)
    monkeypatch.setattr(keyfile, "LEGACY_KEY_FILE", legacy)
    return state, legacy


class TestAnExistingKeyIsNeverAbandoned:
    def test_a_legacy_key_is_used_even_though_the_state_dir_is_elsewhere(self, isolated):
        """THE test. The old anchors are checkout-relative and `state_dir()` is CWD-relative,
        so on a process started from another folder they disagree — and disagreeing here means
        a new key and unreadable DSNs."""
        state, legacy = isolated
        legacy.write_bytes(b"legacy-key-bytes")
        assert keyfile.key_file() == legacy
        assert keyfile.read_or_create_key() == b"legacy-key-bytes"
        assert not (state / keyfile.KEY_NAME).exists(), "a second key was created beside it"

    def test_the_state_dir_key_wins_when_both_exist(self, isolated):
        state, legacy = isolated
        legacy.write_bytes(b"legacy")
        (state / keyfile.KEY_NAME).write_bytes(b"migrated")
        assert keyfile.read_or_create_key() == b"migrated"

    def test_reading_twice_does_not_regenerate(self, isolated):
        first = keyfile.read_or_create_key()
        assert keyfile.read_or_create_key() == first

    def test_surrounding_whitespace_is_stripped(self, isolated):
        state, _legacy = isolated
        (state / keyfile.KEY_NAME).write_bytes(b"  padded-key\n")
        assert keyfile.read_or_create_key() == b"padded-key"


class TestCreation:
    def test_a_new_key_lands_in_the_state_dir_not_the_legacy_path(self, isolated):
        state, legacy = isolated
        keyfile.read_or_create_key()
        assert (state / keyfile.KEY_NAME).exists()
        assert not legacy.exists()

    def test_a_new_key_is_owner_only(self, isolated):
        state, _legacy = isolated
        keyfile.read_or_create_key()
        assert (state / keyfile.KEY_NAME).stat().st_mode & 0o777 == 0o600

    def test_a_chmod_that_cannot_work_does_not_stop_the_boot(self, isolated, monkeypatch):
        """A filesystem without POSIX modes must still get a key written."""
        def no_chmod(_self, _mode):
            raise OSError("not supported")
        monkeypatch.setattr(keyfile.Path, "chmod", no_chmod)
        assert keyfile.read_or_create_key()


class TestTheOverride:
    def test_an_explicit_path_beats_both(self, isolated, monkeypatch, tmp_path):
        state, legacy = isolated
        legacy.write_bytes(b"legacy")
        (state / keyfile.KEY_NAME).write_bytes(b"migrated")
        explicit = tmp_path / "mounted" / "secret"
        explicit.parent.mkdir()
        explicit.write_bytes(b"explicit")
        monkeypatch.setenv(keyfile.KEY_FILE_ENV, str(explicit))
        assert keyfile.read_or_create_key() == b"explicit"


class TestBothModulesShareIt:
    def test_secretvault_encrypts_what_the_registry_can_decrypt(self, isolated):
        """The integration guarantee. Two modules computed this path separately; if they ever
        resolve differently, a DSN written by one is unreadable by the other."""
        from aughor import secretvault
        from aughor.db import registry

        token = secretvault.encrypt_secret("postgres://u:p@h/db")
        assert token and token.startswith("enc:v1:")
        raw = registry._get_fernet().decrypt(token[len("enc:v1:"):].encode()).decode()
        assert raw == "postgres://u:p@h/db"

    def test_the_registry_no_longer_publishes_a_path_of_its_own(self):
        """`registry.KEY_FILE` is gone rather than re-pointed. Written after the first attempt
        kept it: bound at import, it snapshotted an anchor the resolver re-decides per call, so
        it disagreed with `keyfile.key_file()` as soon as a test moved the anchor — a name that
        lies is worse than no name. Nothing read it once `_get_fernet` moved to the resolver."""
        from aughor.db import registry
        assert not hasattr(registry, "KEY_FILE")
