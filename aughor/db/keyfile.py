"""IN-4 — the one resolver for the Fernet key that decrypts every stored DSN.

Before this module the key's path was computed TWICE, in two different modules, from two
different anchors that happened to agree:

    aughor/secretvault.py:20   Path(__file__).parent.parent        / "data" / ".aughor_key"
    aughor/db/registry.py:29   Path(__file__).parent.parent.parent / "data" / ".aughor_key"

Neither had a path override — only the key's VALUE is overridable, through
``AUGHOR_SECRET_KEY``. That is the sharpest hazard in the data-home wave: this file is
gitignored, so it is generated state and must travel with the rest of it, and if state moves
while the key does not, **every connection's DSN becomes undecryptable**. Two copies of a path
also drift; one of them was already reached by a different number of `.parent` hops.

**Why this is not simply `state_dir() / ".aughor_key"`.** Both old anchors are CHECKOUT-relative
and `state_dir()` is CWD-relative, so on a process started from anywhere but the checkout the
two disagree — and disagreeing here does not raise, it silently generates a NEW key and leaves
every stored DSN unreadable. So the resolver prefers a key that already exists, wherever it
exists, and uses the new location only when it is creating one:

    1. ``AUGHOR_SECRET_KEY_FILE`` — an explicit answer always wins.
    2. ``state_dir()/.aughor_key`` if it is already there (the normal case: the API runs from
       the checkout, so this IS the old path).
    3. the legacy checkout-anchored path if THAT is already there — an install started from
       another folder, which used to work by luck.
    4. otherwise ``state_dir()/.aughor_key``, to be created.

A key is never moved by this module and never regenerated over an existing one. `migrate-state`
carries it across with the rest of the state, and until it does, step 3 keeps a deployment
whose CWD wanders reading the key it already has.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Points the key file somewhere else — a mounted secret, a different disk.
KEY_FILE_ENV = "AUGHOR_SECRET_KEY_FILE"

KEY_NAME = ".aughor_key"

#: What `secretvault` and `registry` each computed for themselves. Kept as the fallback so an
#: install whose working directory is not the checkout keeps reading the key it already wrote.
LEGACY_KEY_FILE = Path(__file__).resolve().parents[2] / "data" / KEY_NAME


def key_file() -> Path:
    """Where the Fernet key is, or where a new one belongs. Resolved on CALL."""
    override = os.environ.get(KEY_FILE_ENV)
    if override:
        return Path(override).expanduser()

    from aughor.db.paths import state_dir
    preferred = state_dir() / KEY_NAME
    if preferred.exists():
        return preferred
    if LEGACY_KEY_FILE.exists():
        return LEGACY_KEY_FILE
    return preferred


def read_or_create_key() -> bytes:
    """The key's bytes, creating one at `key_file()` when none exists yet.

    `0o600` on creation, as both call sites did. A `chmod` that fails (a filesystem without
    POSIX modes) must not stop the platform booting — the key is still written."""
    path = key_file()
    if path.exists():
        return path.read_bytes().strip()

    from cryptography.fernet import Fernet
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key
