"""Wave V6 — the lifecycle serving surface.

Decision gate: every route 404s with its flag off (the default surface is byte-identical);
with the flags on, history exposes save≠publish as two distinct versions, a refused freeze is
a **409 carrying the reason**, and an unhonourable pin is a **410 carrying the as-of stamp** —
never a silent fall-back to live data.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

KIND, NK = "savedquery", "savedquery:q1"


@pytest.fixture
def client():
    from aughor.api import app

    return TestClient(app)


@pytest.fixture
def _pub(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_LIFECYCLE_PUBLISH", "1")
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))


@pytest.fixture
def _frz(monkeypatch, tmp_path):
    from aughor.kernel import freeze as fz
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setenv("AUGHOR_LIFECYCLE_FREEZE", "1")
    monkeypatch.setenv("AUGHOR_LIFECYCLE_PUBLISH", "1")
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    monkeypatch.setattr(fz, "_store",
                        KeyedJsonStore(tmp_path / "freeze.json", max_entries=50))


class _Conn:
    def close(self):
        pass


def _storage(monkeypatch, *, token, as_of=False):
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda c: _Conn())
    monkeypatch.setattr("aughor.db.snapshot.data_version", lambda conn, tables: token)
    monkeypatch.setattr("aughor.db.snapshot.as_of_supported", lambda conn: as_of)


# ── Flags off: the default surface is unchanged ────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("get", f"/lifecycle/{KIND}/history"),
    ("get", f"/lifecycle/{KIND}/diff"),
    ("post", f"/lifecycle/{KIND}/publish"),
    ("post", f"/lifecycle/{KIND}/revert"),
    ("get", f"/lifecycle/{KIND}/freeze"),
    ("delete", f"/lifecycle/{KIND}/freeze"),
    ("get", f"/lifecycle/{KIND}/frozen-content"),
])
def test_every_route_404s_when_its_flag_is_off(client, method, path):
    r = getattr(client, method)(
        path, params={"natural_key": NK, "from_version": 1, "to_version": 2, "to_version_": 1},
    )
    assert r.status_code == 404, (path, r.status_code, r.text)
    assert "disabled" in r.text


# ── History exposes save≠publish ──────────────────────────────────────────────

def test_history_reports_published_and_editor_versions_separately(client, _pub):
    from aughor.kernel.lifecycle import publish, save_draft

    save_draft(KIND, NK, {"t": "v1"})
    publish(KIND, NK)
    save_draft(KIND, NK, {"t": "WIP"})

    r = client.get(f"/lifecycle/{KIND}/history", params={"natural_key": NK})
    assert r.status_code == 200
    body = r.json()
    assert body["editor_version"] > body["published_version"], body
    assert len(body["revisions"]) == 3
    assert body["revisions"][0]["state"] == "draft"


def test_history_of_an_unknown_artifact_is_empty_not_an_error(client, _pub):
    r = client.get(f"/lifecycle/{KIND}/history", params={"natural_key": "savedquery:none"})
    assert r.status_code == 200
    assert r.json()["revisions"] == [] and r.json()["published_version"] is None


def test_diff_route_reports_a_move_as_a_move(client, _pub):
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"cards": ["a", "b", "c"]})
    save_draft(KIND, NK, {"cards": ["c", "a", "b"]})

    r = client.get(f"/lifecycle/{KIND}/diff",
                   params={"natural_key": NK, "from_version": 1, "to_version": 2})
    assert r.status_code == 200
    kinds = {c["kind"] for c in r.json()["changes"]}
    assert kinds == {"move"}, r.json()
    assert all("moved" in c["describe"] for c in r.json()["changes"])


def test_diff_route_404s_on_a_missing_version(client, _pub):
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"a": 1})
    r = client.get(f"/lifecycle/{KIND}/diff",
                   params={"natural_key": NK, "from_version": 1, "to_version": 99})
    assert r.status_code == 404


def test_publish_then_revert_round_trip(client, _pub):
    from aughor.kernel.lifecycle import resolve, save_draft

    save_draft(KIND, NK, {"t": "original"})
    assert client.post(f"/lifecycle/{KIND}/publish",
                       params={"natural_key": NK}).status_code == 200
    save_draft(KIND, NK, {"t": "broken"})

    r = client.post(f"/lifecycle/{KIND}/revert",
                    params={"natural_key": NK, "to_version": 1, "publish_now": True})
    assert r.status_code == 200
    assert resolve(KIND, NK, audience="viewer").body == {"t": "original"}


def test_publish_with_nothing_saved_404s(client, _pub):
    r = client.post(f"/lifecycle/{KIND}/publish", params={"natural_key": "savedquery:nope"})
    assert r.status_code == 404


def test_revert_to_a_missing_version_404s(client, _pub):
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"a": 1})
    r = client.post(f"/lifecycle/{KIND}/revert",
                    params={"natural_key": NK, "to_version": 42})
    assert r.status_code == 404


# ── Freeze: refusal and gone-data are errors WITH reasons ──────────────────────

def test_freeze_route_returns_the_pin_and_its_mode(client, _frz, monkeypatch):
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"a": 1})
    _storage(monkeypatch, token="dl:cat:3", as_of=True)

    r = client.post(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK},
                    json={"connection_id": "c", "version": 1, "tables": ["t"]})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "reproducible" and r.json()["frozen"] is True

    got = client.get(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK}).json()
    assert got["status"] == "ok" and got["as_of"]


def test_refused_freeze_is_a_409_carrying_the_reason(client, _frz, monkeypatch):
    """Accepting a pin that cannot be honoured would put a lock on a guarantee that does not
    exist, so the refusal travels to the caller."""
    _storage(monkeypatch, token=None)
    r = client.post(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK},
                    json={"connection_id": "c", "version": 1, "tables": ["t"]})
    assert r.status_code == 409
    assert "cannot compute a data version" in r.json()["detail"]


def test_unfrozen_artifact_reports_frozen_false(client, _frz):
    r = client.get(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK})
    assert r.status_code == 200 and r.json()["frozen"] is False


def test_unfreeze_returns_to_live(client, _frz, monkeypatch):
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"a": 1})
    _storage(monkeypatch, token="fp:x")
    client.post(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK},
                json={"connection_id": "c", "version": 1, "tables": ["t"]})

    r = client.delete(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK})
    assert r.status_code == 200 and r.json()["frozen"] is False
    assert client.get(f"/lifecycle/{KIND}/freeze",
                      params={"natural_key": NK}).json()["frozen"] is False


def test_drifted_detect_only_pin_is_reported_as_drifted(client, _frz, monkeypatch):
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"a": 1})
    _storage(monkeypatch, token="fp:before")
    client.post(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK},
                json={"connection_id": "c", "version": 1, "tables": ["t"]})

    _storage(monkeypatch, token="fp:after")
    got = client.get(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK}).json()
    assert got["status"] == "drifted"
    assert "cannot reconstruct" in got["reason"]


def test_frozen_content_returns_the_pinned_body(client, _frz, monkeypatch):
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"t": "pinned"})
    _storage(monkeypatch, token="fp:x")
    client.post(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK},
                json={"connection_id": "c", "version": 1, "tables": ["t"]})
    save_draft(KIND, NK, {"t": "newer"})

    r = client.get(f"/lifecycle/{KIND}/frozen-content", params={"natural_key": NK})
    assert r.status_code == 200
    assert r.json()["body"] == {"t": "pinned"}


def test_gone_pin_is_a_410_carrying_the_as_of(client, _frz, monkeypatch):
    """The route has no live fall-back on purpose — a frozen label over live numbers is
    worse than an error, because the reader cannot tell."""
    from aughor.kernel.lifecycle import save_draft

    save_draft(KIND, NK, {"t": "pinned"})
    _storage(monkeypatch, token="dl:cat:3", as_of=True)
    client.post(f"/lifecycle/{KIND}/freeze", params={"natural_key": NK},
                json={"connection_id": "c", "version": 1, "tables": ["t"]})

    _storage(monkeypatch, token="dl:cat:9", as_of=False)   # time travel gone
    r = client.get(f"/lifecycle/{KIND}/frozen-content", params={"natural_key": NK})
    assert r.status_code == 410, r.text
    detail = r.json()["detail"]
    assert detail["as_of"] and "no longer supports AS-OF" in detail["reason"]
