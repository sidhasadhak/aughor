"""Secret-at-rest vault + action-trigger URL encryption.

Pins: encrypt/decrypt round-trip, legacy-plaintext back-compat (round-trips unchanged),
idempotent re-encrypt, masking, and that a saved trigger's URL is ciphertext on disk
but plaintext when loaded for the executor.
"""
from aughor.secretvault import (
    encrypt_secret, decrypt_secret, is_encrypted, is_masked, mask_secret,
)


class TestVault:
    def test_round_trip(self):
        c = encrypt_secret("https://hooks.slack.com/services/T0/B0/xoxb-supersecret")
        assert is_encrypted(c) and c.startswith("enc:v1:")
        assert decrypt_secret(c) == "https://hooks.slack.com/services/T0/B0/xoxb-supersecret"

    def test_legacy_plaintext_round_trips_unchanged(self):
        # a pre-encryption value (no prefix) must decrypt to itself — no migration needed
        assert decrypt_secret("https://old.example.com/hook") == "https://old.example.com/hook"
        assert is_encrypted("https://old.example.com/hook") is False

    def test_encrypt_is_idempotent(self):
        c = encrypt_secret("tok")
        assert encrypt_secret(c) == c            # already encrypted → unchanged
        assert decrypt_secret(c) == "tok"

    def test_empty_passthrough(self):
        assert encrypt_secret("") == "" and encrypt_secret(None) is None
        assert decrypt_secret("") == "" and decrypt_secret(None) is None

    def test_ciphertext_differs_from_plaintext(self):
        plain = "super-secret-token"
        assert plain not in encrypt_secret(plain)   # not stored in the clear

    def test_mask_url_keeps_host_hides_secret(self):
        m = mask_secret("https://hooks.slack.com/services/T0/B0/xoxb-supersecret")
        assert m.startswith("https://hooks.slack.com/")
        assert "xoxb-supersecret" not in m and "•" in m

    def test_mask_non_url(self):
        m = mask_secret("xoxb-abcdef123456")
        assert m.startswith("xoxb") and "•" in m and "123456" not in m

    def test_is_masked(self):
        assert is_masked(mask_secret("https://x.io/abc/secret")) is True
        assert is_masked("https://x.io/abc/secret") is False


class TestActionTriggerStore:
    def test_url_encrypted_at_rest_plaintext_on_load(self, tmp_path, monkeypatch):
        from aughor.util.json_store import JsonListStore
        import aughor.actions.store as store
        from aughor.actions.models import ActionTrigger
        # isolate the store to a temp file
        monkeypatch.setattr(store, "_triggers", JsonListStore(tmp_path / "triggers.json"))

        url = "https://hooks.slack.com/services/T1/B1/zzz-secret"
        saved = store.save_trigger(ActionTrigger(id="", name="t", type="slack", url=url))

        # on disk: ciphertext, not the plaintext URL
        raw = store._triggers.get(saved.id)
        assert is_encrypted(raw["url"]) and "zzz-secret" not in raw["url"]
        # loaded for the executor: plaintext URL restored
        assert store.get_trigger(saved.id).url == url

    def test_legacy_plaintext_trigger_still_loads(self, tmp_path, monkeypatch):
        from aughor.util.json_store import JsonListStore
        import aughor.actions.store as store
        s = JsonListStore(tmp_path / "triggers.json")
        s.upsert({"id": "leg", "name": "old", "type": "webhook",
                  "url": "https://old.example.com/hook", "headers": {}, "enabled": True})
        monkeypatch.setattr(store, "_triggers", s)
        assert store.get_trigger("leg").url == "https://old.example.com/hook"
