"""IN-3 — a download survives a flaky network, and names a TLS-inspecting proxy.

Before this every network operation in the installer was a single attempt: the git clone, the
snapshot download, the Node.js download. One dropped connection ended an install with "check
your internet connection", which is true of nothing a person can act on.

The certificate case is separate on purpose. It is not transient — retrying it three times
wastes a minute to print the same failure — and Python's own message names the certificate
rather than the cause, so a person behind a corporate proxy is told verification failed and
nothing about `SSL_CERT_FILE` or `NODE_EXTRA_CA_CERTS`.
"""
from __future__ import annotations

import ssl
import urllib.error

import pytest

from aughor import installer


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    monkeypatch.setattr(installer.time, "sleep", lambda _s: None)


class TestRetries:
    def test_a_transient_failure_is_retried_and_can_succeed(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("connection reset")
            return b"payload"

        assert installer._with_retries("downloading x", flaky) == b"payload"
        assert calls["n"] == 3

    def test_it_gives_up_after_three_and_says_so(self):
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise urllib.error.URLError("connection reset")

        with pytest.raises(installer.InstallError) as caught:
            installer._with_retries("downloading x", always_fails)
        assert calls["n"] == installer._NET_ATTEMPTS == 3
        assert "3 attempts" in str(caught.value)
        assert "Nothing was installed" in caught.value.hint

    def test_a_successful_call_is_not_retried(self):
        calls = {"n": 0}

        def fine():
            calls["n"] += 1
            return b"ok"

        installer._with_retries("downloading x", fine)
        assert calls["n"] == 1


class TestTheCertificateCase:
    def test_a_wrapped_certificate_error_is_recognised(self):
        """THE case. `urlopen` raises `URLError` with the certificate error as its `reason`,
        so an `isinstance` on the OUTER exception answers False on exactly the failure that
        needs the hint."""
        inner = ssl.SSLCertVerificationError("certificate verify failed")
        outer = urllib.error.URLError(inner)
        assert isinstance(outer, ssl.SSLCertVerificationError) is False, "premise drift"
        assert installer._is_certificate_error(outer) is True

    def test_a_bare_certificate_error_is_recognised(self):
        assert installer._is_certificate_error(
            ssl.SSLCertVerificationError("certificate verify failed")) is True

    def test_an_ordinary_network_error_is_not_a_certificate_error(self):
        assert installer._is_certificate_error(urllib.error.URLError("connection reset")) is False

    def test_it_fails_immediately_rather_than_retrying(self):
        """Retrying an untrusted certificate three times buys a slower identical failure."""
        calls = {"n": 0}

        def cert_failure():
            calls["n"] += 1
            raise urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))

        with pytest.raises(installer.InstallError) as caught:
            installer._with_retries("downloading x", cert_failure)
        assert calls["n"] == 1, "a certificate error was retried"
        assert "certificate" in str(caught.value)

    def test_the_hint_names_both_runtimes(self):
        """Python and Node each need their own pointer at the bundle; naming one is half a fix."""
        assert "SSL_CERT_FILE" in installer._PROXY_HINT
        assert "NODE_EXTRA_CA_CERTS" in installer._PROXY_HINT

    def test_a_chain_without_a_cause_terminates(self):
        """The walk is bounded; a self-referential or plain exception must not spin."""
        assert installer._is_certificate_error(OSError("plain")) is False


class TestTheDownloadsUseIt:
    def test_fetch_retries(self, monkeypatch):
        calls = {"n": 0}

        def flaky_urlopen(*_a, **_k):
            calls["n"] += 1
            raise urllib.error.URLError("reset")

        monkeypatch.setattr(installer.urllib.request, "urlopen", flaky_urlopen)
        with pytest.raises(installer.InstallError):
            installer._fetch("https://example.invalid/x.json")
        assert calls["n"] == 3

    def test_download_retries(self, monkeypatch, tmp_path):
        calls = {"n": 0}

        def flaky(*_a, **_k):
            calls["n"] += 1
            raise urllib.error.URLError("reset")

        monkeypatch.setattr(installer, "_download_once", flaky)
        with pytest.raises(installer.InstallError):
            installer._download("https://example.invalid/node.tar.gz", tmp_path / "n", lambda *_: None)
        assert calls["n"] == 3
