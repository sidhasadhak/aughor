"""IN-1 — `aughor update`: fetch, fast-forward, re-run the install steps. Never reset.

**What "dirty" has to mean here, and why the obvious answer is wrong.** 102 files under
`data/` are git-TRACKED, and the running app writes several of them. Measured on the
builder's own install while this was written:

    M  data/metrics.json
    ?? data/ontology_overrides/8233e4fd/      (and five more)

`data/metrics.json` is dirty ON PURPOSE — it holds metrics scoped to live connection ids —
and the deployment runbook says never to "clean" it. So a check that refuses on any
`git status --porcelain` output refuses FOREVER on every install that has been used, which is
every install worth updating. This is the sharpest reason IN-4 comes before IN-1, sharper than
the atomic-swap one: the update is not merely unsafe without a data home, it is unusable.

So: untracked files never block (git itself refuses a fast-forward that would clobber one),
modifications under `data/` never block, and a tracked modification anywhere ELSE does —
those are real local edits and a person should know before their tree moves.

⚠️ "Never block" is this check's promise, not git's: git still refuses a fast-forward that
would overwrite a MODIFIED tracked file upstream also changed — which #514 did to
`data/metrics.json`. Since the overlay the app no longer writes that file or the tracked file
under `data/ontology_overrides/`, and upstream no longer changes either
(`test_seed_overlay_frozen`), so for THOSE paths the refusal cannot recur. It still can for
the other tracked files the app rewrites — `glossary.yaml`, `context_graph/`,
`ontology_column_config/` — the first time upstream edits one on an install that changed it.
An install already behind #514 with its own rows in it is recovered by hand, API stopped:
copy the file out, `git checkout HEAD -- data/metrics.json` (HEAD — a bare `--` restores from
the index), update, copy it back. Its rows are then read as this install's — including the
unscoped `revenue` and `aov` it shipped with before #514, which then stay global on that
install; delete them if only the `samples` connection should carry them.
And git overwrites an IGNORED file by default, which is where instance data now lives, so the
fast-forward passes `--no-overwrite-ignore`.

**Never reset.** A diverged checkout — local commits the remote does not have — is refused
and named, not rewound. `git reset --hard` has destroyed work on this project before and is
not in this module's vocabulary.

**A snapshot install is not updated in place here.** An install with no `.git` came from a
tarball (`install.sh::download_aughor` falls back to one when Git is unusable — a Mac without
the Command Line Tools counts). Swapping a live directory safely, on Windows too, is its own
wave; pretending to do it badly is worse than saying so, so this reports exactly how to
re-run the installer instead.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: Modifications under here never block an update: this is state the running app writes, and
#: some of it is tracked (see the module docstring).
_STATE_PREFIX = "data/"


@dataclass
class Result:
    """A typed verdict — `refused` and `noop` must not read like `updated`."""
    status: str                       # "updated" | "noop" | "refused" | "failed"
    reason: str = ""
    before: str = ""
    after: str = ""
    behind: int = 0
    ahead: int = 0
    blocking: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("updated", "noop")


def _git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=check, timeout=180)


def is_git_install(root: Path) -> bool:
    return (root / ".git").exists()


def blocking_changes(root: Path) -> list[str]:
    """Tracked modifications that are NOT state. Empty means a fast-forward is safe to try.

    `--untracked-files=no` is deliberate: an untracked file cannot be fast-forwarded over
    without git itself refusing, and treating one as dirty is what made this check unusable."""
    out = _git(root, "status", "--porcelain", "--untracked-files=no")
    if out.returncode != 0:
        return []
    blocking = []
    for line in out.stdout.splitlines():
        path = line[3:].strip()
        if path and not path.startswith(_STATE_PREFIX):
            blocking.append(line.strip())
    return blocking


def update(root: Path, *, ref: str | None = None) -> Result:
    """Fetch and fast-forward `root`, or say precisely why it will not."""
    if not is_git_install(root):
        return Result("refused",
                      "this install came from a snapshot, not a clone, so there is no remote "
                      "to fast-forward from. Re-run the installer to take the newest code: "
                      "curl -LsSf https://raw.githubusercontent.com/sidhasadhak/aughor/main/install.sh | sh "
                      "— your state is not touched by it.")

    before = _git(root, "rev-parse", "HEAD").stdout.strip()

    blocking = blocking_changes(root)
    if blocking:
        return Result("refused",
                      "there are local changes outside data/. Nothing has been fetched, and "
                      "nothing will be reset — commit or stash them, then run this again.",
                      before=before, blocking=blocking)

    fetched = _git(root, "fetch", "--quiet", "origin")
    if fetched.returncode != 0:
        return Result("failed", f"could not reach the remote: {fetched.stderr.strip()}",
                      before=before)

    target = ref or "@{u}"
    counts = _git(root, "rev-list", "--left-right", "--count", f"{target}...HEAD")
    if counts.returncode != 0:
        return Result("failed",
                      f"could not compare against {target}: {counts.stderr.strip()}", before=before)
    behind, ahead = (int(n) for n in counts.stdout.split())

    if ahead:
        return Result("refused",
                      f"this checkout has {ahead} commit(s) the remote does not. It is diverged, "
                      f"and this command never rewinds a branch — merge or rebase yourself.",
                      before=before, behind=behind, ahead=ahead)
    if not behind:
        return Result("noop", "already up to date.", before=before, after=before)

    merged = _git(root, "merge", "--ff-only", "--no-overwrite-ignore", target)
    if merged.returncode != 0:
        return Result("failed",
                      f"the fast-forward did not apply: {merged.stderr.strip()}",
                      before=before, behind=behind)

    after = _git(root, "rev-parse", "HEAD").stdout.strip()
    if after == before:
        # Declared done only when HEAD actually moved — `--ff-only` can exit 0 having done
        # nothing if the ref resolved to where we already were.
        return Result("noop", "already up to date.", before=before, after=after)
    return Result("updated", f"moved {behind} commit(s).", before=before, after=after, behind=behind)
