"""Platform secret-at-rest manager.

One Fernet key for the whole platform — `AUGHOR_SECRET_KEY` env, else the
auto-generated key file `aughor.db.keyfile` resolves (the same key the connection
registry uses to encrypt DSNs — one resolver owns that path since IN-4). Encrypted values carry a version prefix so a *plaintext* value (from
before a field was encrypted) round-trips unchanged through `decrypt_secret` — making
per-field adoption safe and reversible, with no migration step.

Use for any secret that lands on disk outside the encrypted-DSN column: webhook URLs,
API tokens, etc. Read paths should return `mask_secret(...)` so the raw secret never
leaves the server.
"""
from __future__ import annotations

import logging
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    key_env = os.getenv("AUGHOR_SECRET_KEY")
    if key_env:
        return Fernet(key_env.encode())
    # IN-4 — `aughor.db.keyfile` owns this path now. It was computed here AND in
    # `db/registry.py`, from anchors a different number of `.parent` hops apart, and neither
    # had an override; the key is gitignored generated state, so it has to follow the state.
    from aughor.db import keyfile
    return Fernet(keyfile.read_or_create_key())


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt_secret(plain: str | None) -> str | None:
    """Encrypt `plain` (idempotent — an already-encrypted or empty value is returned
    unchanged, so re-saving a record never double-encrypts)."""
    if not plain or is_encrypted(plain):
        return plain
    return _PREFIX + _fernet().encrypt(plain.encode()).decode()


#: Stored secrets this process could not decrypt — the deployment's key (`AUGHOR_SECRET_KEY`, or
#: the key file) changed since they were saved, or a value is corrupt. Counted for `/health` and
#: said once in the log, because every caller sees only an empty credential.
_unreadable = 0
_unreadable_said = False
_unreadable_lock = threading.Lock()


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a value. A non-prefixed (legacy plaintext) value round-trips unchanged.

    A value that cannot be decrypted (wrong key / corrupt) comes back EMPTY rather than
    raising, so one bad record cannot take down a read path — and never as the ciphertext,
    which it used to be: the `enc:…` token then travelled on as the credential itself (a Slack
    or Teams token, a Jira header, an MCP server's key) and the far side refused a "bad
    credential" while the stored one was fine and the deployment's key was what changed. Each
    is counted (`unreadable_count`, on `/health`) and the first is logged with that cause;
    `readable` asks the question without decrypting into a caller's hands."""
    if not is_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        _note_unreadable()
        return ""


def readable(value: object) -> bool:
    """False only for an encrypted value this deployment's key cannot decrypt — for a caller
    that must say "unreadable" rather than "unset" (the key-state views, the model doors)."""
    if not is_encrypted(value):
        return True
    try:
        _fernet().decrypt(str(value)[len(_PREFIX):].encode())
    except InvalidToken:
        return False
    return True


def unreadable_count() -> int:
    """How many stored secrets this process has failed to decrypt since it started."""
    return _unreadable


def _note_unreadable() -> None:
    global _unreadable, _unreadable_said
    with _unreadable_lock:
        _unreadable += 1
        first, _unreadable_said = not _unreadable_said, True
    if first:
        logging.getLogger(__name__).error(
            "a stored secret cannot be decrypted with this deployment's key — AUGHOR_SECRET_KEY "
            "or the key file changed since it was saved. The credential it guards reads as "
            "empty until it is entered again; GET /health counts them.")


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
