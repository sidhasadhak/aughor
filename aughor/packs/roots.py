"""Where packs live — one place that knows, instead of three that agreed.

The path `<repo>/packs` was written out three times (`cli`, `routers.packs`, `intake`), each
computed from a different `__file__`. They agreed, which is why nothing had gone wrong yet;
they were also the reason a second location could not simply be added.

There are now two roots and they hold different KINDS of thing:

**authored** — `<repo>/packs`, tracked. Packs someone here wrote: entities, metric recipes,
goldens, a declared stance. These steer plans.

**imported** — untracked, `data/packs` by default. Third-party skill prose brought in by
`aughor skills import`. It is deliberately outside version control: the repo is public, and
redistributing a few dozen third-party documents inside it is a decision to take
deliberately rather than as a side effect of running an importer. Nothing here is lost by
that — an imported pack is a copy of a file that already exists in its own repository.

**Authored wins a collision.** A skill library will eventually contain a `retention` or a
`cohorts`, and an import must never shadow a reviewed pack that someone here maintains. The
imported copy stays on disk and is simply not the one that resolves, so the collision is
recoverable by renaming rather than by re-importing.
"""
from __future__ import annotations

from pathlib import Path

from aughor.db.paths import state_dir
from aughor.db.sqlite_util import resolve_db_path

#: Overrides, both honouring the `AUGHOR_*` convention every other store path uses.
AUTHORED_ENV = "AUGHOR_PACKS_DIR"
IMPORTED_ENV = "AUGHOR_IMPORTED_PACKS_DIR"

_REPO_PACKS = Path(__file__).resolve().parents[2] / "packs"


def authored_root() -> Path:
    """The tracked pack directory. Resolved on call, so a test can move it."""
    return resolve_db_path(AUTHORED_ENV, _REPO_PACKS)


def imported_root() -> Path:
    """Where `skills import` writes. Untracked; created on first write, not on read."""
    return resolve_db_path(IMPORTED_ENV, state_dir() / "packs")


def pack_roots() -> list[Path]:
    """Both roots, authored first — the priority order a collision is resolved by."""
    return [authored_root(), imported_root()]


def all_pack_ids() -> list[str]:
    """Every pack id across both roots, deduped, authored first.

    Sorted within each root so the order is stable — an unstable roster makes a diff of two
    `list_packs` results unreadable, and this feeds a tool result a model compares.
    """
    from aughor.packs.loader import list_packs

    seen: dict[str, None] = {}
    for root in pack_roots():
        if not root.is_dir():
            continue
        for pid in sorted(list_packs(root)):
            seen.setdefault(pid, None)
    return list(seen)


def pack_dir(pack_id: str) -> Path | None:
    """The directory `pack_id` resolves to, or None. Containment is asserted HERE.

    A pack id reaches this from a route parameter and from a tool call, and `root / pack_id`
    with a traversing id would leave the roots entirely. The check is local rather than
    trusted from a caller, because there are now several callers.
    """
    if not pack_id or pack_id in (".", ".."):
        return None
    for root in pack_roots():
        candidate = root / pack_id
        try:
            inside = candidate.resolve().parent == root.resolve()
        except OSError:
            inside = False
        if inside and (candidate / "pack.yaml").is_file():
            return candidate
    return None
