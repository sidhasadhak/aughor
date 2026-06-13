"""Platform secret-at-rest manager.

One Fernet key for the whole platform — `AUGHOR_SECRET_KEY` env, else the
auto-generated `data/.aughor_key` (the same key the connection registry uses to
encrypt DSNs). Encrypted values carry a version prefix so a *plaintext* value (from
before a field was encrypted) round-trips unchanged through `decrypt_secret` — making
per-field adoption safe and reversible, with no migration step.

Use for any secret that lands on disk outside the encrypted-DSN column: webhook URLs,
API tokens, etc. Read paths should return `mask_secret(...)` so the raw secret never
leaves the server.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_KEY_FILE = Path(__file__).parent.parent / "data" / ".aughor_key"
_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    key_env = os.getenv("AUGHOR_SECRET_KEY")
    if key_env:
        return Fernet(key_env.encode())
    if _KEY_FILE.exists():
        return Fernet(_KEY_FILE.read_bytes().strip())
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    _KEY_FILE.chmod(0o600)
    return Fernet(key)


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt_secret(plain: str | None) -> str | None:
    """Encrypt `plain` (idempotent — an already-encrypted or empty value is returned
    unchanged, so re-saving a record never double-encrypts)."""
    if not plain or is_encrypted(plain):
        return plain
    return _PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a value. A non-prefixed (legacy plaintext) value round-trips unchanged;
    a value that can't be decrypted (wrong key / corrupt) is returned as-is rather than
    raising, so one bad record can't take down a read path."""
    if not is_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        return value


def is_masked(value: object) -> bool:
    """True if `value` is a masked preview (so an unchanged round-trip from the UI
    isn't mistaken for a new secret)."""
    return isinstance(value, str) and "•" in value  # the bullet used by mask_secret


def mask_secret(value: str | None, keep: int = 4) -> str | None:
    """A non-reversible preview for API responses. Keeps a recognizable head
    (scheme://host) when the secret is a URL; otherwise shows a short prefix —
    everything sensitive becomes bullets."""
    if not value:
        return value
    v = decrypt_secret(value) if is_encrypted(value) else value
    bullets = "•" * 6
    if "://" in v:
        scheme, rest = v.split("://", 1)
        host = rest.split("/", 1)[0]
        return f"{scheme}://{host}/{bullets}"
    return (v[:keep] + bullets) if len(v) > keep else bullets
