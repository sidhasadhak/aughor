"""`aughor up` must refuse a BUSY port, and only a busy one.

The refusal is deliberate and good: `_check_port_free` never kills the owner, because the
owner may be someone else's live server. What it must not do is refuse a port that is
free — and it did, on the single most common path there is.

When a TCP connection is closed by the side that owns the LISTENING address, that address
sits in TIME_WAIT for about a minute. `_port_in_use` bound without `SO_REUSEADDR`, so it
saw EADDRINUSE while nothing was listening at all: `./start.sh --stop && ./start.sh`
answered "Port 8000 is already in use" and quit. The workaround was to wait and retry,
which teaches people the tool is flaky rather than that it has a rule.

The old code told on itself. The refusal printed no "owned by …" clause, because
`_port_owner` filters to `-sTCP:LISTEN` and found nobody. Two checks disagreed about the
same port and the pessimistic one won without saying so.
"""
from __future__ import annotations

import socket

import pytest

from aughor.cli import _port_in_use, _port_owner


@pytest.fixture
def timewait_port():
    """A port whose LISTENING address is in TIME_WAIT and has no listener.

    Produced the way it happens in production rather than simulated: accept a connection
    and close the SERVER side first, which is the side that enters TIME_WAIT, then drop
    the listener. This is what a server shutting down leaves behind.
    """
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)
    cli = socket.create_connection(("127.0.0.1", port))
    conn, _ = srv.accept()
    conn.close()            # server side closes first → TIME_WAIT on the listening addr
    cli.close()
    srv.close()
    return port


def test_a_port_whose_server_just_stopped_is_FREE(timewait_port):
    """The regression, reproduced rather than described. Without SO_REUSEADDR this bind
    raises EADDRINUSE and the CLI refuses to start on a port nobody holds."""
    assert _port_in_use(timewait_port) is False, (
        "the CLI would refuse to start on a port with no listener — this is the "
        "'Port 8000 is already in use' that appears right after stopping the server")


def test_the_two_checks_agree_about_a_free_port(timewait_port):
    """The tell that something was wrong: `_port_owner` filters to LISTEN and found
    nobody, while `_port_in_use` said busy. A refusal that cannot name an owner is a
    refusal that should not have fired."""
    assert _port_owner(timewait_port) == ""
    assert _port_in_use(timewait_port) is False


def test_a_port_with_a_LIVE_listener_is_still_busy():
    """The half that must not regress. SO_REUSEADDR does not permit binding over an
    active listener on BSD/macOS — that needs SO_REUSEPORT — so the refusal still fires
    for the case it exists for: someone else's running server."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)
    try:
        assert _port_in_use(port) is True, \
            "a port with a live listener must stay busy — never kill someone else's server"
    finally:
        srv.close()


def test_an_unbound_port_is_free():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert _port_in_use(port) is False


def test_the_probe_binds_the_way_the_server_does():
    """Pinned as a fact, not a comment. The probe exists to answer 'can uvicorn take this
    port', and uvicorn sets SO_REUSEADDR (`uvicorn/config.py`). A probe stricter than the
    process it protects will keep inventing refusals."""
    import socket as _s

    # Written first as `"SO_REUSEADDR" in inspect.getsource(...)`, which passed with the
    # setsockopt call DELETED — the docstring says the words. A probe that cannot fail is
    # not a probe. So watch the option actually being set on the socket.
    seen: list = []
    real = _s.socket

    class _Watched(real):                       # type: ignore[misc,valid-type]
        def setsockopt(self, level, optname, value, *a):
            seen.append((level, optname, value))
            return super().setsockopt(level, optname, value, *a)

    import aughor.cli as cli
    orig = cli.socket.socket
    cli.socket.socket = _Watched
    try:
        _port_in_use(0)
    finally:
        cli.socket.socket = orig

    assert (_s.SOL_SOCKET, _s.SO_REUSEADDR, 1) in seen, (
        "the port probe did not set SO_REUSEADDR, so it is stricter than the server it "
        f"protects and will refuse ports uvicorn could have taken. saw: {seen}")
