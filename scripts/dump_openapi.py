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
`tests/conftest.py` — the two lists are siblings, and
`tests/unit/test_store_hermeticity.py` fails when they drift apart.

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
    # The registry's sibling file: builtin connection settings, including which builtins a
    # person has hidden.
    os.environ.setdefault("AUGHOR_CONNECTION_SETTINGS", os.path.join(tmp, "connection_settings.json"))
    # This helper is also the isolation for LIVE DRIVES (scratch API servers started to
    # verify a change) and for the SP-M recorder, so a store missing here is one the drive
    # writes: a drive that created agents once wrote them into the running deployment's
    # data/agents.db. The comment here used to say this list was "kept equal to
    # tests/conftest.py's allowlist BY MEASUREMENT". On 2026-09-17 it was 22 stores short of
    # the suite's — a scratch API created data/org_llm.db in a worktree, which from the main
    # checkout is the live org model config — and it pinned ORGSETTINGS, a name no code has
    # ever read. The measurement is a test now: tests/unit/test_store_hermeticity.py runs this
    # function and the conftest in fresh interpreters and fails on any store the suite
    # isolates that this does not.
    for name in (
        "HISTORY", "METASTORE", "WORKSPACES", "AUDIT", "CANVAS", "ARTIFACTS",
        "EVIDENCE", "MONITORS", "SAVEDQUERY", "VOLUMES",
        "VERDICTS", "PACK_DELTAS", "PACK_BINDINGS", "CHECKPOINTS",
        "IDEMPOTENCY", "RBAC", "AUTOMATIONS", "KINETIC_INBOX", "KINETIC_GRANTS",
        "LEARNING", "INTAKE", "USER_PREFS", "DEPARTURES", "HUB_LINKS",
        "AGENTS", "AGENT_ALERTS", "EVALS", "MATCACHE", "ORGS", "DECISIONS",
        "ORG_LLM", "AMBIGUITY_LEDGER", "OVERLAY_LEDGER", "GOVERN_TAGS", "GOVERN_CAPS",
        "QUALITY", "IDENTITY", "OVERVIEW_DRILLS", "POPULARITY", "DASHBOARD",
    ):
        os.environ.setdefault(f"AUGHOR_{name}_DB", os.path.join(tmp, f"{name.lower()}.db"))
    # The runtime LLM config (a model chosen in Settings, and its encrypted keys). Isolated
    # with ORG_LLM above, so a drive that needs a model binds it from the environment, never
    # from — or into — the deployment's own choice.
    os.environ.setdefault("AUGHOR_LLM_CONFIG_PATH", os.path.join(tmp, "llm_config.json"))
    # The demo warehouse. "Explore the demo" writes it when it is absent, so a scratch
    # deployment starts without one; a drive that wants it calls
    # `aughor.demo.setup.ensure_fixture_db()`, which seeds the deterministic scenario here.
    os.environ.setdefault("AUGHOR_FIXTURE_DB", os.path.join(tmp, "aughor.duckdb"))
    # NOT isolated, on purpose: the authored package tree (AUGHOR_PACKS_DIR) and the samples
    # warehouse (AUGHOR_SAMPLES_DB), which a drive reads from the checkout. The suite isolates
    # both; that test holds the reasons and fails when either stops being true.
    os.environ.setdefault("AUGHOR_BRIEFS_FILE", os.path.join(tmp, "briefs.json"))
    os.environ.setdefault("AUGHOR_INSTRUCTIONS_FILE", os.path.join(tmp, "instructions.json"))
    os.environ.setdefault("AUGHOR_CANVAS_INSTRUCTIONS_FILE",
                          os.path.join(tmp, "canvas_instructions.json"))
    # Upload storage and the playbook. Neither resolves through `resolve_db_path`, so
    # neither appeared in any isolation list — including the conftest's, until a full
    # suite run wrote both into a fresh checkout's `data/` on 2026-09-11. Registered in
    # both places at once, which is the rule this file's sibling comment below states.
    os.environ.setdefault("AUGHOR_UPLOAD_DIR", os.path.join(tmp, "uploads"))
    os.environ.setdefault("AUGHOR_PLAYBOOK_PATH", os.path.join(tmp, "playbook.json"))
    # IP-2 — the industries chosen at install: a live drive that changes the choice must not narrow the
    # running deployment's.
    os.environ.setdefault("AUGHOR_INDUSTRIES_FILE", os.path.join(tmp, "industries.json"))
    # The metrics catalog and glossary are TRACKED repo files (data/metrics.json,
    # data/glossary.yaml) — the one store family whose pollution lands in git status,
    # not just in a live database. Found the hard way TWICE: a live-drive scratch
    # server wrote both (memory, pre-2026-09), and SP-M's recorder re-seeded
    # metrics.json on 2026-09-16 because this list still lacked them.
    os.environ.setdefault("AUGHOR_METRICS_PATH", os.path.join(tmp, "metrics.json"))
    os.environ.setdefault("AUGHOR_GLOSSARY_PATH", os.path.join(tmp, "glossary.yaml"))
    # …and the vetted-query store beside them, which saving a query writes.
    os.environ.setdefault("AUGHOR_TRUSTED_QUERIES_PATH", os.path.join(tmp, "trusted_queries.json"))
    # File trees and registries outside the directory family below, each written when used:
    # saved synonyms, `skills import`, the per-column config (whose default tree is TRACKED
    # under data/), and the documents registry with the uploaded bytes it indexes (a delete
    # rmtree()s the latter).
    os.environ.setdefault("AUGHOR_VOCABULARY_ROOT", os.path.join(tmp, "vocabulary"))
    os.environ.setdefault("AUGHOR_IMPORTED_PACKS_DIR", os.path.join(tmp, "packs-imported"))
    os.environ.setdefault("AUGHOR_COLUMN_CONFIG_ROOT", os.path.join(tmp, "ontology_column_config"))
    os.environ.setdefault("AUGHOR_DOCUMENTS_REGISTRY", os.path.join(tmp, "documents.json"))
    os.environ.setdefault("AUGHOR_DOCUMENTS_DIR", os.path.join(tmp, "documents"))

    # The DIRECTORY stores, which this dump never isolated: the docstring above said
    # "every store honours its AUGHOR_*_DB override", and that sentence was the gap — a
    # store keyed on a path had no pin here at all. Latent rather than bleeding (these
    # write when USED, and a spec dump only imports and calls `app.openapi()`), but an
    # unpinned MCP allowlist is the wrong one to leave latent: it is a list of outbound
    # destinations. `tests/conftest.py` isolates exactly this family; the two are siblings
    # and a new store belongs in BOTH.
    #
    # DS-17 added AUGHOR_AUTOMATIONS_DIR here and VA-9d added AUGHOR_MCPSERVERS_DIR; this
    # is the union, which is what the merge of the two waves means.
    for _dir_env in ("AUGHOR_EPISODES_DIR", "AUGHOR_MEMORY_DIR", "AUGHOR_ACTIONS_DIR",
                     "AUGHOR_SLACKBOTS_DIR", "AUGHOR_STATE_DIR", "AUGHOR_INTEGRATIONS_DIR",
                     "AUGHOR_AUTOMATIONS_DIR", "AUGHOR_MCPSERVERS_DIR",
                     # MI-3's snapshot bytes — the directory half of the same store.
                     "AUGHOR_DATASETS_DIR"):
        os.environ.setdefault(_dir_env, tmp)
    # A DIRECTORY too, and one that takes an EXCLUSIVE lock in local mode — so an unpinned
    # default here does not merely dirty `data/`, it contends with a running API.
    os.environ.setdefault("AUGHOR_QDRANT_PATH", os.path.join(tmp, "qdrant"))
    # ON-1b — the ontology's file trees: human overrides (a measure WRITES verdicts back into it), the export beside it,
    # the engine's recommendations, (ON-7b) the explorer's draft record, and (R8) the compiled doc tree. Isolated in
    # tests/conftest.py too.
    for _tree in ("OVERRIDES", "EXPORT", "RECOMMENDATIONS", "DRAFTS", "DOCS"):
        os.environ.setdefault(f"AUGHOR_ONTOLOGY_{_tree}_DIR", os.path.join(tmp, f"ontology_{_tree.lower()}"))


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
