"""Pause-all-explorers-for-a-connection selection — see _shared.explorers_for_connection.
A user investigation must pause the connection explorer AND any canvas explorers on the
same connection (the bug: canvas explorers kept hammering the DB during a run)."""
import aughor.routers._shared as sh


class _Status:
    def __init__(self, paused=False):
        self.paused = paused


class _Explorer:
    def __init__(self, conn, paused=False):
        self.connection_id = conn
        self._status = _Status(paused)


def test_includes_conn_and_matching_canvas(monkeypatch):
    monkeypatch.setattr(sh, "explorers", {"c1": _Explorer("c1")})
    monkeypatch.setattr(sh, "canvas_explorers", {
        "cv1": _Explorer("c1"),   # canvas on the same connection → included
        "cv2": _Explorer("c2"),   # other connection → excluded
    })
    got = sh.explorers_for_connection("c1")
    assert len(got) == 2
    assert all(e.connection_id == "c1" for e in got)


def test_excludes_already_paused(monkeypatch):
    monkeypatch.setattr(sh, "explorers", {"c1": _Explorer("c1", paused=True)})   # user-paused
    monkeypatch.setattr(sh, "canvas_explorers", {"cv1": _Explorer("c1", paused=False)})
    # default: only the running canvas explorer (don't touch the user-paused one)
    assert len(sh.explorers_for_connection("c1")) == 1
    # include_paused: both
    assert len(sh.explorers_for_connection("c1", include_paused=True)) == 2


def test_no_explorers(monkeypatch):
    monkeypatch.setattr(sh, "explorers", {})
    monkeypatch.setattr(sh, "canvas_explorers", {})
    assert sh.explorers_for_connection("c1") == []


def test_canvas_on_other_connection_excluded(monkeypatch):
    monkeypatch.setattr(sh, "explorers", {})
    monkeypatch.setattr(sh, "canvas_explorers", {"cv1": _Explorer("other")})
    assert sh.explorers_for_connection("c1") == []
