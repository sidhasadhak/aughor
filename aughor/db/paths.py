"""The directory per-connection GENERATED state lives in — one resolver, one env var.

`data/` holds two very different kinds of file. Some are **authored** and version-controlled
(`glossary.yaml`, `global_rules.md`; the knowledge base moved into `packs/*/kb/` with IP-1); the rest are **generated per connection**
and derived from a warehouse — exploration findings, business profiles, the briefing cache,
the explore watermark. This module owns the second kind ONLY.

Why it exists: those stores each hard-coded ``Path("data")`` with no override, so the test
suite wrote and DELETED the developer's live files — the same class as the registry incident
(`AUGHOR_REGISTRY_DB`) and the WP-4 episode/memory/actions holes, which were fixed one store
at a time while this family was missed. On 2026-07-21 a suite run destroyed a real
`exploration_workspace.json` (89 findings, unrecoverable — `data/*.json` is gitignored).

One env var covers the whole family so a NEW store in it is isolated by construction:
point `AUGHOR_STATE_DIR` at a temp dir (the test conftest does) and every reader, writer and
**purger** moves together. That last one matters — `db/purge.py` resolved its own
``Path("data")`` and so deleted from the live dir even when a test had redirected the store
it was purging.

Deliberately NOT a global `data/` switch: authored files keep their own resolvers
(`AUGHOR_GLOSSARY_PATH`, …) and stay readable from the repo during tests.
"""
from __future__ import annotations

import os
from pathlib import Path

from aughor.db.sqlite_util import resolve_db_path

#: Env var pointing at the generated-state directory. Unset → `data/` (unchanged behaviour).
STATE_DIR_ENV = "AUGHOR_STATE_DIR"


def state_dir() -> Path:
    """Directory holding per-connection generated state (honours ``AUGHOR_STATE_DIR``).

    Resolved on CALL. Stores that cache it in a module constant (`_DATA_DIR = state_dir()`,
    the convention here so the existing `monkeypatch.setattr(mod, "_DATA_DIR", tmp)` fixtures
    keep working) capture it at IMPORT — which is why the test conftest must set the env in
    its `setdefault` block ahead of every app import.

    Precedence, and the order is the safety property (IN-4):

    1. ``AUGHOR_STATE_DIR`` — an explicit answer always wins. The suite sets it, an operator who
       has pointed state at durable storage keeps it, and a migrated home never overrides it.
    2. The data home, but ONLY once `aughor migrate-state` has verified a copy and written its
       marker (`db.home.in_use`). Existing on disk is not enough.
    3. ``data/``, unchanged — what every install answers until somebody migrates.

    Step 2 is deliberately not "the home exists". The live deployment measured for this wave
    holds 1.4 GB under `data/`; a default that relocated on a directory's mere existence would
    make its connections, history and receipts invisible rather than missing.
    """
    explicit = resolve_db_path(STATE_DIR_ENV, Path("data"))
    if os.environ.get(STATE_DIR_ENV):
        return explicit
    from aughor.db import home as _home
    return _home.state_home() if _home.in_use() else explicit
