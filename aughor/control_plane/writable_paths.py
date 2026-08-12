"""Where the stores that write files should write, on a read-only deployment.

A serverless bundle is read-only apart from `/tmp`, and four stores still resolved
to the bundle's own `data/`. Every write failed, loudly, on every boot — measured
over one 30-minute window in production: 43 boots, each logging a failed playbook
seed, plus 14 `doctree: persist failed` and 12 `column-config save is best-effort`.
The LLM runtime config was the one with a user-visible symptom: a model chosen in
Settings reverted on the next cold start, so the app half-worked depending on which
instance answered.

Redirecting loses nothing. `.vercelignore` excludes `/data/*` apart from five named
files, so these paths ship EMPTY — the writes were failing against a directory that
is not in the bundle at all, with no content to preserve.

`/tmp` is per-INSTANCE. This makes the stores work within an instance and stops the
noise; it is not durability. Anything that must survive a cold start needs a real
store — for the LLM binding that means the env vars (`AUGHOR_CODER_MODEL` and
friends) every instance reads identically, rather than a runtime config file whose
edit reaches only the instance that served the request.

Deliberately free of aughor imports: it is called at the very top of `api.py`,
before anything else is wired, and a test must be able to reach it without dragging
in the application.
"""
from __future__ import annotations

from pathlib import Path

#: env var → its filename under the state dir. The var names are the stores' own
#: existing overrides; `AUGHOR_PLAYBOOK_PATH` was added because the playbook alone
#: had none, and a store with no override cannot be relocated at all.
WRITABLE_STORES: dict[str, str] = {
    "AUGHOR_LLM_CONFIG_PATH": "llm_config.json",
    "AUGHOR_ONTOLOGY_DOCS_DIR": "ontology_docs",
    "AUGHOR_COLUMN_CONFIG_ROOT": "ontology_column_config",
    "AUGHOR_PLAYBOOK_PATH": "playbook.json",
}


def writable_store_paths(state_dir: str | Path) -> dict[str, str]:
    """``{env var: path under state_dir}`` for every store that writes files.

    Returns what SHOULD be set; the caller applies it with `setdefault` so an
    operator who has pointed a store at durable storage keeps their value.
    """
    root = Path(state_dir)
    return {var: str(root / name) for var, name in WRITABLE_STORES.items()}
