"""Wave V4 — freeze: live by default, snapshot by choice, gone data errors loudly.

Pre-registered gate:
* a frozen artifact whose pin cannot be honoured **errors with a named reason** instead of
  rendering (``test_gate_gone_data_errors_loudly``);
* a connection that cannot be pinned **refuses the freeze up front**
  (``test_gate_unpinnable_connection_refuses_the_freeze``);
* unfreezing restores live following (``test_gate_unfreeze_restores_live``).

Gate amended during the build — see ``test_detect_only_never_claims_reproducibility``: the
plan said refuse any freeze on a connector without AS-OF support, which would make freeze
unavailable to every plain-DuckDB user. Shipped instead: two *named* modes, with refusal
reserved for "nothing can be pinned at all". The safety property the gate existed to protect
— never accept a promise you cannot keep — is asserted directly.
"""
from __future__ import annotations

import pytest

from aughor.kernel import freeze as fz
from aughor.kernel.freeze import FreezeRefused, FrozenDataGoneError

KIND, NK = "savedquery", "savedquery:q1"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(fz, "_store",
                        KeyedJsonStore(tmp_path / "freeze_state.json", max_entries=50))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))


class _Conn:
    def close(self):
        pass


def _storage(monkeypatch, *, token, as_of=False):
    """Stand in for the connector: what data_version/as_of_supported report."""
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda c: _Conn())
    monkeypatch.setattr("aughor.db.snapshot.data_version", lambda conn, tables: token)
    monkeypatch.setattr("aughor.db.snapshot.as_of_supported", lambda conn: as_of)


def _saved(body=None):
    from aughor.kernel.lifecycle import save_draft

    return save_draft(KIND, NK, body or {"sql": "SELECT 1"})


# ── The flag contract ─────────────────────────────────────────────────────────

def test_gate_unpinnable_connection_refuses_the_freeze(monkeypatch):
    """No data version ⇒ nothing to pin ⇒ refuse NOW, with the reason. A lock icon that
    guarantees nothing is worse than no lock."""
    _storage(monkeypatch, token=None)
    with pytest.raises(FreezeRefused, match="cannot compute a data version"):
        fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])
    assert fz.frozen(KIND, NK) is None, "a refused freeze must leave the artifact live"


def test_gate_unopenable_connection_refuses_the_freeze(monkeypatch):
    def boom(_):
        raise RuntimeError("no such connection")

    monkeypatch.setattr("aughor.db.connection.open_connection_for", boom)
    with pytest.raises(FreezeRefused, match="cannot open connection"):
        fz.freeze(KIND, NK, version=1, connection_id="nope")


def test_gate_gone_data_errors_loudly(monkeypatch):
    """Frozen to a replayable snapshot, then the storage loses AS-OF: reading must raise,
    naming the as-of stamp — never quietly serve live numbers under a frozen label."""
    _saved()
    _storage(monkeypatch, token="dl:cat:7", as_of=True)
    pin = fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])
    assert pin.is_reproducible

    _storage(monkeypatch, token="dl:cat:9", as_of=False)      # time travel gone
    status, reason = fz.verify(KIND, NK)
    assert status == "gone" and "no longer supports AS-OF" in reason

    with pytest.raises(FrozenDataGoneError) as ei:
        fz.read_frozen(KIND, NK)
    assert ei.value.as_of == pin.as_of
    assert "can no longer be honoured" in str(ei.value)
    assert "Unfreeze it" in str(ei.value)


def test_gate_unfreeze_restores_live(monkeypatch):
    _storage(monkeypatch, token="fp:abc")
    fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])
    assert fz.frozen(KIND, NK) is not None
    assert fz.unfreeze(KIND, NK) is True
    assert fz.frozen(KIND, NK) is None
    assert fz.unfreeze(KIND, NK) is False, "unfreezing a live artifact is a no-op"


# ── The two modes ─────────────────────────────────────────────────────────────

def test_detect_only_never_claims_reproducibility(monkeypatch):
    """The amended gate's safety property: a pin that cannot replay must not say it can."""
    _storage(monkeypatch, token="fp:abc", as_of=False)
    pin = fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])
    assert pin.mode == "detect_only"
    assert pin.is_reproducible is False
    assert "detect-only" in pin.describe()


def test_reproducible_mode_when_storage_is_version_aware(monkeypatch):
    _storage(monkeypatch, token="dl:cat:7", as_of=True)
    pin = fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])
    assert pin.mode == "reproducible" and pin.is_reproducible
    assert "🔒 v1" in pin.describe()


def test_detect_only_drift_is_reported_not_swallowed(monkeypatch):
    """A detect-only pin's whole value is saying 'this moved'."""
    _saved()
    _storage(monkeypatch, token="fp:before", as_of=False)
    fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])

    _storage(monkeypatch, token="fp:after", as_of=False)
    status, reason = fz.verify(KIND, NK)
    assert status == "drifted"
    assert "cannot reconstruct the original" in reason

    # drifted is still READABLE — but the status travels with the content
    rev, status, reason = fz.read_frozen(KIND, NK)
    assert status == "drifted" and rev.version == 1


def test_detect_only_unfingerprintable_data_is_gone_not_ok(monkeypatch):
    """If drift can no longer be ruled out, the honest answer is 'gone', not 'ok'."""
    _saved()
    _storage(monkeypatch, token="fp:before", as_of=False)
    fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])

    _storage(monkeypatch, token=None, as_of=False)
    status, reason = fz.verify(KIND, NK)
    assert status == "gone" and "drift cannot be ruled out" in reason


def test_reproducible_pin_tolerates_drift_because_it_replays(monkeypatch):
    """Drift is expected on a replayable pin — the read is AT the pinned version."""
    _saved()
    _storage(monkeypatch, token="dl:cat:7", as_of=True)
    fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])

    _storage(monkeypatch, token="dl:cat:99", as_of=True)     # data moved a lot
    status, _ = fz.verify(KIND, NK)
    assert status == "ok"


def test_reproducible_pin_with_a_non_replayable_token_is_gone(monkeypatch):
    """A 'reproducible' pin whose token is not a snapshot id cannot be replayed."""
    _saved()
    _storage(monkeypatch, token="dl:cat:7", as_of=True)
    fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])
    fz._store.put(fz._key(KIND, NK), {**fz._store.get(fz._key(KIND, NK)),
                                      "data_version": "fp:not-a-snapshot"})
    status, reason = fz.verify(KIND, NK)
    assert status == "gone"
    assert "not a replayable snapshot id" in reason


# ── Reading ───────────────────────────────────────────────────────────────────

def test_read_frozen_on_a_live_artifact_raises(monkeypatch):
    with pytest.raises(FrozenDataGoneError, match="is not frozen"):
        fz.read_frozen(KIND, NK)


def test_read_frozen_returns_the_pinned_version_not_the_latest(monkeypatch):
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"sql": "PINNED"})
    _storage(monkeypatch, token="fp:x", as_of=False)
    fz.freeze(KIND, NK, version=1, connection_id="c", tables=["t"])
    save_draft(KIND, NK, {"sql": "NEWER"})

    rev, status, _ = fz.read_frozen(KIND, NK)
    assert rev.body == {"sql": "PINNED"} and status == "ok"


def test_read_frozen_errors_when_the_pinned_version_left_history(monkeypatch):
    _storage(monkeypatch, token="fp:x", as_of=False)
    fz.freeze(KIND, NK, version=99, connection_id="c", tables=["t"])
    with pytest.raises(FrozenDataGoneError, match="no longer in the artifact history"):
        fz.read_frozen(KIND, NK)


def test_verify_on_an_unfrozen_artifact_is_ok_not_an_error():
    assert fz.verify(KIND, NK) == ("ok", "not frozen")


def test_freeze_records_the_as_of_and_tables(monkeypatch):
    _storage(monkeypatch, token="fp:x", as_of=False)
    pin = fz.freeze(KIND, NK, version=2, connection_id="conn-a", tables=["b", "a", "a"])
    assert pin.tables == ["a", "b"] and pin.connection_id == "conn-a"
    assert pin.as_of and pin.version == 2

    reread = fz.frozen(KIND, NK)
    assert reread.data_version == "fp:x" and reread.as_of == pin.as_of
