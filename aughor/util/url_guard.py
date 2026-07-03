"""SSRF guard for user-supplied outbound URLs (webhook / Slack / Jira triggers).

An action trigger's ``url`` is caller-controlled and gets POSTed server-side
(``actions/executor._post``). Without a guard, a caller with ACTION_HUB (on by
default) can point it at ``http://169.254.169.254/`` (cloud metadata),
``http://localhost:...`` (internal services), or a ``file://`` scheme (SEC-04).

``is_safe_webhook_url`` fails CLOSED — any parse/resolution error → unsafe. It
resolves the host and checks EVERY returned IP (not just the literal), which
defeats ``localhost`` aliases and DNS tricks. On-prem operators who genuinely
need internal targets set ``AUGHOR_ALLOW_PRIVATE_WEBHOOKS=1`` (scheme + host are
still required; only the private-IP block is relaxed).
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("http", "https")


def _allow_private() -> bool:
    return os.environ.get("AUGHOR_ALLOW_PRIVATE_WEBHOOKS", "") == "1"


def is_safe_webhook_url(url: str) -> bool:
    """True iff ``url`` is an http(s) URL whose host resolves only to public IPs.

    Fails closed on any error. Honours ``AUGHOR_ALLOW_PRIVATE_WEBHOOKS=1`` to
    permit private/loopback targets on-prem (scheme + host still required).
    """
    try:
        u = urlparse(url)
        if u.scheme not in _ALLOWED_SCHEMES or not u.hostname:
            return False
        if _allow_private():
            return True
        for _fam, _type, _proto, _canon, sockaddr in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if (ip.is_private or ip.is_loopback or ip.is_reserved
                    or ip.is_link_local or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False
