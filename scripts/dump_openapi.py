"""Dump the FastAPI OpenAPI spec to a file WITHOUT a running server.

Feeds the typed-TS-client codegen (`web: npm run gen:api`) and the CI
codegen-drift gate, so `web/lib/api.gen.ts` can never silently fall behind the
route surface again (it was missing the /rbac, /jobs, /packs and /verify
families when the gate was added).

Hermetic: every store honours its AUGHOR_*_DB override (REC-04), so we point
them all at a temp dir BEFORE importing the app — a spec dump must never touch
live data/.

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
