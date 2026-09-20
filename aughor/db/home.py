"""IN-4 — the data home: where generated state lives when it stops living in the checkout.

**Nothing moves because this module exists.** `home()` answers "where would state live",
`in_use()` answers "has a person moved it there", and every resolver keeps its current answer
until `in_use()` is true. That separation is the whole safety property: the live deployment
measured while this was written holds **1.4 GB** under `data/` — a 266 MB `system.db`, 437 MB of
uploads, a 208 MB checkpoint store — and a default that silently relocated would not lose the
files, it would make the connections, the history and the receipts *invisible*, which reads the
same to a person and is worse to debug. The move happens once, when `aughor migrate-state` is
run, with the API stopped, verified before the old copy is left behind.

**Why a home at all** (ROADMAP §3.19, IN-4). State under the checkout means deleting or
re-cloning `~/aughor` deletes the connections and receipts with it, and a process started from
another folder reads a *different* `data/` — the shape behind the one-writer rule in §7, which
`data/system.db` has been corrupted four times by.

**This is a SPLIT, not a move.** `data/` is mixed: 102 of its files are git-tracked
(`glossary.yaml`, `global_rules.md`, `data/ontology_column_config/**`, `data/demo_packs/**`) and
`.gitignore` is a per-file denylist rather than `data/*`. Authored content stays in the
checkout, where it is versioned and readable from the repo during tests; only GENERATED
per-connection state has a home. `aughor.db.paths.state_dir` owns that family and is the one
resolver this module is wired into.

**The name.** `~/.aughor` (POSIX) and `%LOCALAPPDATA%\\aughor` (Windows) are the home;
`~/aughor` — no dot — is the CHECKOUT, which `install.sh` calls `AUGHOR_DIR`, and
`<checkout>/.aughor/` is the installer's own runtime dir for logs and a downloaded Node. Three
similar names, three different things, so each is spelled out here rather than inferred.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: Points the whole home somewhere else — a different disk, a synced folder, a test's tmp dir.
HOME_ENV = "AUGHOR_HOME"

#: Written into the home by `aughor migrate-state` once the copy is verified. Its PRESENCE is
#: what moves the default; a home directory that exists but carries no marker is a home somebody
#: created by hand or a migration that did not finish, and neither should silently take over a
#: running deployment's state.
MARKER = ".aughor-home"

#: Generated state lives under this, so the home can also hold a log or a marker without either
#: ending up inside the directory the stores enumerate.
STATE_SUBDIR = "state"


def default_home() -> Path:
    """The per-user home for this platform, ignoring any override.

    `%LOCALAPPDATA%` on Windows because that is where per-machine, per-user application state
    belongs and it is not roamed; `~/.aughor` elsewhere. `LOCALAPPDATA` can be unset in a bare
    service account, so the POSIX shape is the fallback rather than a crash."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "aughor"
    return Path.home() / ".aughor"


def home() -> Path:
    """Where state WOULD live. Honours ``AUGHOR_HOME``; never creates anything."""
    override = os.environ.get(HOME_ENV)
    return Path(override).expanduser() if override else default_home()


def marker_path() -> Path:
    return home() / MARKER


def state_home() -> Path:
    """The directory the generated-state family would use inside the home."""
    return home() / STATE_SUBDIR


def in_use() -> bool:
    """Whether a verified migration has happened, i.e. whether the home is the live answer.

    Resolved on CALL, never cached: `aughor migrate-state` writes the marker in one process and
    the API reads it in the next, and a test flips it with `monkeypatch.setenv`."""
    try:
        return marker_path().is_file()
    except OSError:
        # An unreadable home is not a home. Failing closed keeps the checkout's `data/` live
        # rather than pointing a running deployment at a directory it cannot stat.
        return False
