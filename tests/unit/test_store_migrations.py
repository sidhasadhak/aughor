"""Arc SV-1 — every store that migrates, found in the code, is copied before it migrates and keeps its rows.

The population is READ FROM THE SOURCE — every ``run_migrations(..., store=...)`` call under ``aughor/`` — never listed
by hand. The test this joins (`test_migrations.py::test_converted_stores_migrate_cleanly`) names 5 of the 17 stores, and
a hand-listed population cannot fail when one is missing; Grist's own migration test missed 4 of its 53 the same way.
How to OPEN a store is per-store knowledge and lives in ``OPENERS``, keyed by module; a module found in the code with no
opener fails here by name, so a new store cannot be forgotten.

Each store is opened fresh (conftest isolates every store), copied to the test's folder so the shared isolated store is
never touched, given one row per table, wound back to its base version and migrated again — which proves at once that
its migrations re-run (the runner's additive + idempotent contract) and that the copy before migrating holds every row.
"""
from __future__ import annotations

import ast
import importlib
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _migrating_stores() -> dict[str, tuple[str, str | None]]:
    """store → (module, the name of the migrations list it passes), from every call in the source."""
    found: dict[str, tuple[str, str | None]] = {}
    for path in sorted((ROOT / "aughor").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "run_migrations":
                continue
            store = next((k.value.value for k in node.keywords
                          if k.arg == "store" and isinstance(k.value, ast.Constant)), None)
            if store is None:
                continue
            migs = node.args[1].id if len(node.args) > 1 and isinstance(node.args[1], ast.Name) else None
            found[store] = (".".join(path.relative_to(ROOT).with_suffix("").parts), migs)
    return found


def _ensured(conn_fn: str, ensure_fn: str | None = None):
    def _open(mod):
        conn = getattr(mod, conn_fn)()
        if ensure_fn:
            getattr(mod, ensure_fn)(conn)
        return conn
    return _open


def _init_then(conn_fn: str):
    def _open(mod):
        mod._init_schema()
        return getattr(mod, conn_fn)()
    return _open


OPENERS = {   # by module: two stores' persisted names carry a retired word (docs/GLOSSARY.md), the modules do not
    "aughor.actions.grants": _ensured("_conn", "_ensure_schema"),
    "aughor.actions.inbox": _ensured("_conn", "_ensure_schema"),
    "aughor.actions.overlay": _ensured("_conn", "_ensure_schema"),
    "aughor.automations.store": _init_then("_connect"),
    "aughor.custom_agents.store": _ensured("_connect"),
    "aughor.db.history": _ensured("_conn", "_ensure_schema"),
    "aughor.db.registry": _ensured("_db"),
    "aughor.evals.store": _ensured("_connect", "_ensure_schema"),
    "aughor.feedback.verdicts": _ensured("_conn", "_ensure_schema"),
    "aughor.kernel.ledger": lambda mod: mod.Ledger.default()._conn,
    "aughor.metastore.store": _ensured("_conn", "_ensure_schema"),
    "aughor.monitors.store": _init_then("_connect"),
    "aughor.obs.agent_alert_store": _init_then("_connect"),
    "aughor.packs.bindings": _ensured("_conn", "_ensure_schema"),
    "aughor.security.audit": _ensured("_connect", "_ensure_schema"),
    "aughor.semantic.ambiguity_ledger": _ensured("_conn", "_ensure_schema"),
    "aughor.workspace.store": _ensured("_conn", "_ensure_schema"),
}
STORES = _migrating_stores()


def test_the_population_is_read_from_the_code():
    assert len(STORES) >= 17, f"found {sorted(STORES)} — the AST walk lost stores"
    modules = {module for module, _ in STORES.values()}
    missing = sorted(modules - set(OPENERS))
    assert not missing, f"these modules migrate a store and the test cannot open it — add them to OPENERS: {missing}"
    stale = sorted(set(OPENERS) - modules)
    assert not stale, f"OPENERS names stores that no longer migrate: {stale}"


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
    virtual = {n for n, sql in rows if (sql or "").upper().startswith("CREATE VIRTUAL")}
    return [n for n, _ in rows if n not in virtual and not any(n.startswith(v + "_") for v in virtual)]


def _value(decl: str):
    t = (decl or "").upper()
    if "INT" in t:
        return 1
    if "REAL" in t or "FLOA" in t or "DOUB" in t or "NUM" in t:
        return 1.0
    if "BLOB" in t:
        return b"x"
    return "x"


def _fill_one_row_per_table(conn: sqlite3.Connection) -> dict[str, int]:
    for t in _tables(conn):
        cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
        names = [c[1] for c in cols if c[4] is None or c[5]]
        values = [_value(c[2]) for c in cols if c[4] is None or c[5]]
        if not names:
            continue
        quoted = ", ".join('"' + n + '"' for n in names)
        try:
            conn.execute(f'INSERT INTO "{t}" ({quoted}) VALUES ({", ".join("?" * len(values))})', values)
        except sqlite3.Error:
            continue                                     # a CHECK or a foreign key this generic row does not meet
    conn.commit()
    return _counts(conn)


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in _tables(conn)}


@pytest.mark.parametrize("store", sorted(STORES))
def test_every_migrating_store_is_copied_before_it_migrates_and_keeps_its_rows(store, tmp_path, monkeypatch):
    from aughor.db import migrations as M
    monkeypatch.setattr(M, "_HELD_BACK", {})
    monkeypatch.setattr(M, "_BACKED_UP", [])
    module_name, migs_name = STORES[store]
    assert migs_name, f"{store} ({module_name}) passes run_migrations something other than a module-level list"
    mod = importlib.import_module(module_name)
    migrations = getattr(mod, migs_name)
    live = OPENERS[module_name](mod)
    if not migrations:                                    # versioned, with nothing migrated yet: nothing to copy
        assert M.run_migrations(live, migrations, store=store) == live.execute("PRAGMA user_version").fetchone()[0]
        assert M.migration_report()["backed_up"] == []
        return
    latest = max(m.version for m in migrations)
    assert live.execute("PRAGMA user_version").fetchone()[0] == latest, f"{store} did not open at its latest version"
    copy = sqlite3.connect(tmp_path / f"{store}.db")
    live.backup(copy)                                     # the shared isolated store is never written by this test
    rows = _fill_one_row_per_table(copy)
    assert sum(rows.values()) > 0, f"{store}: no table took a generic row — nothing to prove a copy keeps"
    copy.execute("PRAGMA user_version = 1")
    copy.commit()

    assert M.run_migrations(copy, migrations, store=store) == latest   # every migration re-runs on a full store
    assert _counts(copy) == rows                                         # …and keeps every row
    baks = sorted((tmp_path / "backups").glob(f"{store}.db.*.v1-before-v{latest}.bak"))
    assert len(baks) == 1, f"{store}: expected one labelled copy, found {[b.name for b in baks]}"
    assert sorted(p.name for p in (tmp_path / "backups").iterdir()) == [baks[0].name], "a copy is one file"
    check = sqlite3.connect(baks[0])
    assert check.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert check.execute("PRAGMA user_version").fetchone()[0] == 1
    assert _counts(check) == rows
    assert M.migration_report()["ok"]
