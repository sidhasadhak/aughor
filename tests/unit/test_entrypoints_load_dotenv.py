"""Every process entrypoint reads `.env`, or its configuration silently does not apply.

This closes the loose-end ledger's last unexplained item: **a stray `data/qdrant/` that
appeared in a working tree whose `.env` pinned a Qdrant SERVER.** The ledger had recorded
one suspect, tested it, and cleared it; the cause stayed unfound.

The chain, proven statically:

1. `.env` is read in exactly two places — `aughor/api.py` and `semantic/kb_retriever.py`.
   Nothing on the general import path reads it.
2. `aughor/cli.py` is the installed entrypoint (`[project.scripts] aughor = …`) and read
   none of it. A process starting there therefore never saw `AUGHOR_QDRANT_URL`.
3. Without that pin, `vector_store._client()` takes the embedded branch at
   `_embedded_path()` → `state_dir() / "qdrant"` → **`data/qdrant`**.
4. `aughor investigate` imports `agent.bootstrap`, which calls `delete_by_filter` and
   `match_filter` — real operations, and this store writes when USED.

🔑 **The fix belongs at the entrypoint, not in the library modules.** `kb_retriever` had
already patched itself the same way, which is precisely why the gap survived: patching one
call site fixes one path, and the next path in does not go through it. A new entrypoint is
the recurring shape here — so this test guards the CLASS, not the one file.

**Where in the entrypoint matters too**, and the repo already had an opinion:
`test_env_isolation` refuses a module-level load outside its guarded list, because
importing such a module from a test puts the developer's environment into the process. So
the CLI loads inside its `click.group()` callback — which every command passes through, and
which a test that merely imports the module never runs. This file asserts the load EXISTS;
that one asserts it is not at import. Neither is redundant: a load could satisfy one and
fail the other, and the pair is what pins "at the entrypoint, on invocation".
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

#: Every module a PROCESS can start at. A file listed here is one whose first statement
#: runs in a fresh interpreter, with only the real environment — no `.env` unless it says
#: so itself.
ENTRYPOINTS = {
    "aughor/api.py": "the ASGI app (uvicorn, Vercel)",
    "aughor/cli.py": "the installed console script (`aughor …`)",
}


def _loads_dotenv(path: Path) -> bool:
    """Does this module call `load_dotenv` ANYWHERE — at import or inside a function?

    Anywhere, deliberately: `test_env_isolation` owns the question of WHERE, and answers
    it in the opposite direction (not at import, unless allowlisted). This one only asks
    whether the entrypoint reads its configuration at all.

    Parsed rather than grepped so a mention inside a docstring or a comment — of which
    this repo has several, explaining the very trap — cannot pass for the call itself.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "load_dotenv"
        for node in ast.walk(tree)
    )


def test_every_entrypoint_loads_dotenv():
    """The load-bearing claim. An entrypoint that skips this reads none of `.env`, so every
    pin in it — the Qdrant URL, the secret key, the model bindings — silently does not
    apply, and the process quietly builds its own local state instead."""
    missing = [f"{p} ({why})" for p, why in ENTRYPOINTS.items()
               if not _loads_dotenv(_ROOT / p)]
    assert not missing, (
        "entrypoint(s) that never read .env: " + "; ".join(missing) +
        ". A process starting there sees no AUGHOR_QDRANT_URL, so the semantic index "
        "falls through to embedded mode and creates state_dir()/qdrant — which is the "
        "stray data/qdrant/ this test exists because of. Copy the guarded load from "
        "aughor/api.py."
    )


def test_every_entrypoint_honours_the_clean_environment_flag():
    """`AUGHOR_SKIP_DOTENV` is how the test suite declares a clean environment — conftest
    sets it before any app import, because a developer's `.env` leaking into the suite
    makes a laptop run a different suite from CI. An entrypoint that loaded
    unconditionally would re-pollute it."""
    for p in ENTRYPOINTS:
        src = (_ROOT / p).read_text(encoding="utf-8")
        assert "AUGHOR_SKIP_DOTENV" in src, (
            f"{p} loads .env without honouring AUGHOR_SKIP_DOTENV — the suite's declared "
            f"clean environment would be re-polluted by whatever is in the developer's "
            f".env, which is how a laptop starts running a different suite from CI")


def test_the_console_script_target_is_covered():
    """Guards the LIST, not just the files in it. `[project.scripts]` naming a module this
    test does not know about is exactly how the next entrypoint slips through — which is
    how this one did."""
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'aughor = "aughor.cli:cli"' in pyproject, (
        "the console script moved; ENTRYPOINTS in this test names aughor/cli.py and must "
        "be updated to whatever module now starts a process")


def test_the_dotenv_readers_are_the_ones_we_think():
    """A canary on the premise, not on the fix.

    The whole diagnosis rested on `.env` being read in only a couple of places, so a
    process that started elsewhere saw none of it. If that stops being true — if the load
    moves onto the general import path, say — this assertion fails and the reasoning above
    should be re-derived rather than trusted.
    """
    readers = sorted(
        str(p.relative_to(_ROOT))
        for p in (_ROOT / "aughor").rglob("*.py")
        if _loads_dotenv(p)
    )
    assert readers == ["aughor/api.py", "aughor/cli.py",
                       "aughor/semantic/kb_retriever.py"], (
        f"the set of .env readers changed: {readers}. That is not necessarily wrong, but "
        f"the stray-data/qdrant diagnosis assumed this set — re-check it before trusting "
        f"the comment in aughor/cli.py")
