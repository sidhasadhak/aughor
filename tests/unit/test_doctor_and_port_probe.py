"""IN-1 — `aughor doctor`, and the port probe it exposed as broken.

The probe bug is the reason this file leads with it. `_port_in_use` bound `127.0.0.1` with
`SO_REUSEADDR` and its docstring claimed that could not succeed over a live listener on
BSD/macOS. That holds only for the SAME address: a server on the wildcard `0.0.0.0` — exactly
how the deployment runbook starts this API — does not stop a bind of the specific
`127.0.0.1`. Measured 2026-09-20 on a live machine: `lsof` named a listener on `*:8000` and
one on `*:3000`, and the probe answered "free" for both, so `aughor up`'s guard had never
fired there.
"""
from __future__ import annotations

import socket

from aughor import doctor
from aughor.netprobe import port_in_use


def _wildcard_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 0))          # the wildcard, as uvicorn --host 0.0.0.0 does
    s.listen(1)
    return s, s.getsockname()[1]


class TestThePortProbe:
    def test_a_wildcard_listener_is_seen_as_busy(self):
        """THE regression. Before the connect probe this returned False."""
        sock, port = _wildcard_listener()
        try:
            assert port_in_use(port) is True
        finally:
            sock.close()

    def test_a_loopback_listener_is_seen_as_busy(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        try:
            assert port_in_use(s.getsockname()[1]) is True
        finally:
            s.close()

    def test_a_port_with_no_listener_is_free(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                    # nothing listening now
        assert port_in_use(port) is False


class TestTheVerdictIsTyped:
    def test_a_check_distinguishes_could_not_tell_from_fine(self):
        """`X or {}` erases the difference; these are four distinct statuses."""
        assert doctor.OK != doctor.UNKNOWN != doctor.FAIL != doctor.WARN
        assert doctor.Check("x", doctor.UNKNOWN).ok is False
        assert doctor.Check("x", doctor.WARN).ok is False
        assert doctor.Check("x", doctor.OK).ok is True

    def test_worst_reports_the_most_serious_status(self):
        mk = doctor.Check
        assert doctor.worst([mk("a", doctor.OK), mk("b", doctor.WARN)]) == doctor.WARN
        assert doctor.worst([mk("a", doctor.WARN), mk("b", doctor.FAIL)]) == doctor.FAIL
        assert doctor.worst([mk("a", doctor.OK)]) == doctor.OK
        assert doctor.worst([mk("a", doctor.UNKNOWN), mk("b", doctor.OK)]) == doctor.UNKNOWN

    def test_a_failing_check_always_says_what_to_do(self):
        from pathlib import Path
        checks = doctor.run(Path("."), api_port=0, web_port=0)
        for c in checks:
            if not c.ok:
                assert c.fix, f"{c.name} reports a problem with no fix"

    def test_a_busy_port_names_its_own_flag(self, monkeypatch):
        """The owner is forced, because `lsof` on a listener owned by the pytest process is
        not deterministic — and without an owner `_port` takes the UNKNOWN branch, whose fix
        is a different sentence. Aiming at the branch under test rather than hoping for it."""
        monkeypatch.setattr("aughor.netprobe.port_in_use", lambda _p: True)
        monkeypatch.setattr("aughor.netprobe.port_owner", lambda _p: "uvicorn (pid 1)")
        api = doctor._port("api", 8000, "--api-port")
        web = doctor._port("web", 3000, "--web-port")
        assert api.status == doctor.WARN, api
        assert "--api-port" in api.fix and "--web-port" not in api.fix
        assert "--web-port" in web.fix

    def test_a_busy_port_with_no_owner_is_unknown_not_a_failure(self, monkeypatch):
        """`_port_owner` shells out to `lsof`, which is POSIX-only. No answer is not "nobody",
        and reporting it as a failure sends a person to fix something that is fine."""
        monkeypatch.setattr("aughor.netprobe.port_in_use", lambda _p: True)
        monkeypatch.setattr("aughor.netprobe.port_owner", lambda _p: "")
        assert doctor._port("api", 8000, "--api-port").status == doctor.UNKNOWN


class TestTheModelCheckTouchesNoStore:
    def test_it_reads_the_config_file_not_the_database(self, monkeypatch, tmp_path):
        """The obvious route (`provider.resolve_binding` → `org_config._conn`) issues
        `CREATE TABLE … ; commit` against `org_llm.db`, making a diagnostic a SECOND WRITER on
        `data/` — the shape behind four `system.db` corruptions."""
        cfg = tmp_path / "llm_config.json"
        cfg.write_text('{"backend": "anthropic"}')
        monkeypatch.setattr("aughor.llm.provider._CONFIG_PATH", cfg)

        def explode(*_a, **_k):
            raise AssertionError("doctor opened a store")
        monkeypatch.setattr("aughor.db.backend.connect_store", explode, raising=False)

        check = doctor._model()
        assert check.ok and "anthropic" in check.found

    def test_no_backend_anywhere_is_a_failure_with_a_fix(self, monkeypatch, tmp_path):
        monkeypatch.setattr("aughor.llm.provider._CONFIG_PATH", tmp_path / "absent.json")
        monkeypatch.delenv("AUGHOR_BACKEND", raising=False)
        check = doctor._model()
        assert check.status == doctor.FAIL and check.fix

    def test_an_unreadable_config_is_unknown_not_a_failure(self, monkeypatch, tmp_path):
        bad = tmp_path / "llm_config.json"
        bad.write_text("{not json")
        monkeypatch.setattr("aughor.llm.provider._CONFIG_PATH", bad)
        assert doctor._model().status == doctor.UNKNOWN

    def test_the_environment_answers_when_the_file_does_not(self, monkeypatch, tmp_path):
        monkeypatch.setattr("aughor.llm.provider._CONFIG_PATH", tmp_path / "absent.json")
        monkeypatch.setenv("AUGHOR_BACKEND", "ollama")
        check = doctor._model()
        assert check.ok and "ollama" in check.found
