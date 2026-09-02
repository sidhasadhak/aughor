"""Dump the FastAPI OpenAPI spec to a file WITHOUT a running server.

Feeds the typed-TS-client codegen (`web: npm run gen:api`) and the CI
codegen-drift gate, so `web/lib/api.gen.ts` can never silently fall behind the
route surface again (it was missing the /rbac, /jobs, /packs and /verify
families when the gate was added).

Hermetic: every store honours an env override — `AUGHOR_*_DB` for the SQLite ones
(REC-04) and a path var for the directory/file ones — so we point them all at a
temp dir BEFORE importing the app. A spec dump must never touch live data/.

⚠️ The second half of that sentence was missing until DS-17, and so was the code:
only the `_DB` names were isolated, so a store keyed on a DIRECTORY had no pin here
at all. Measured before adding one: no directory store writes during a spec dump
today (the dump imports and calls `app.openapi()`, and these stores write when they
are USED) — so this closes a latent hole rather than a bleeding one, and the stray
`data/qdrant/` seen on 2026-09-02 was NOT this script (reproduced with the old
shape; it did not appear). Adding a store means adding it HERE and in
`tests/conftest.py` — the two lists are siblings.

Usage: uv run python scripts/dump_openapi.py [out.json]   (default: stdout)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile


def _isolate_stores() -> None:
    tmp = tempfile.mkdtemp(prefix="aughor-openapi-")
    os.environ.setdefault("AUGHOR_SYSTEM_DB", os.path.join(tmp, "system.db"))
    os.environ.setdefault("AUGHOR_REGISTRY_DB", os.path.join(tmp, "connections.db"))
    for name in (
        "HISTORY", "METASTORE", "WORKSPACES", "AUDIT", "CANVAS", "ARTIFACTS",
        "EVIDENCE", "MONITORS", "ORGSETTINGS", "SAVEDQUERY", "VOLUMES",
        "VERDICTS", "PACK_DELTAS", "PACK_BINDINGS", "CHECKPOINTS",
        "IDEMPOTENCY", "RBAC", "AUTOMATIONS", "KINETIC_INBOX", "KINETIC_GRANTS",
    ):
        os.environ.setdefault(f"AUGHOR_{name}_DB", os.path.join(tmp, f"{name.lower()}.db"))
    os.environ.setdefault("AUGHOR_BRIEFS_FILE", os.path.join(tmp, "briefs.json"))

    # DS-17 — the DIRECTORY stores, which this dump did not isolate at all. The docstring
    # above says "every store honours its AUGHOR_*_DB override", and that sentence was the
    # bug: a store whose env is a PATH rather than a `_DB` fell straight through and wrote
    # into the developer's live `data/` on every `npm run gen:api`. `tests/conftest.py`
    # already isolates exactly this family for exactly this reason — the two lists are
    # siblings, and a new store belongs in both.
    for _dir_env in ("AUGHOR_EPISODES_DIR", "AUGHOR_MEMORY_DIR", "AUGHOR_ACTIONS_DIR",
                     "AUGHOR_SLACKBOTS_DIR", "AUGHOR_STATE_DIR", "AUGHOR_INTEGRATIONS_DIR",
                     "AUGHOR_AUTOMATIONS_DIR"):
        os.environ.setdefault(_dir_env, tmp)
    # A DIRECTORY too, and one that takes an EXCLUSIVE lock in local mode — so an unpinned
    # default here does not merely dirty `data/`, it contends with a running API.
    os.environ.setdefault("AUGHOR_QDRANT_PATH", os.path.join(tmp, "qdrant"))


def main() -> None:
    _isolate_stores()
    from aughor.api import app  # import AFTER isolation

    spec = app.openapi()
    out = json.dumps(spec, indent=1, sort_keys=True)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as fh:
            fh.write(out)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
