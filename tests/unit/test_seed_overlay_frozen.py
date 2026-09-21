"""The paths an install writes are frozen upstream — the rule the whole overlay rests on.

The code that performs a fast-forward is the `update.py` ALREADY on each install, so no release
can repair the fast-forward that delivers it. The only way a used install keeps updating is for
upstream never again to add, change or delete a tracked path the app writes. These guards read
the git INDEX, not the working tree, so they hold on a developer's checkout whose
`data/metrics.json` is modified on purpose.
"""
from __future__ import annotations

import ast
import hashlib
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

#: What the two frozen paths shipped as when the overlay landed. Changing either value is
#: changing the file — which strands every install that has written to it. Don't.
FROZEN = {
    "data/metrics.json": "fc3781790057a89ace5bb0acd79831e533dd6fa3",
    "data/ontology_overrides/workspace/default/action/refund_orders.yaml":
        "20032b54217162c033699aa04ea680b789f1c907",
}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout


pytestmark = pytest.mark.skipif(not (REPO / ".git").exists(), reason="not a git checkout")


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def test_G1_the_paths_an_install_writes_never_change_upstream():
    staged = {}
    for line in _git("ls-files", "-s", *FROZEN).splitlines():     # "<mode> <blob> <stage>\t<path>"
        meta, path = line.split("\t", 1)
        staged[path] = meta.split()[1]
    assert staged == FROZEN, (
        "a frozen path changed. Every install that has written to it will refuse the fast-forward "
        "that delivers this commit, and cannot receive the fix either. Ship the change in "
        "data/shipped/ instead.")


def test_G1_nothing_new_is_tracked_where_the_app_writes():
    tracked = set(_git("ls-files", "data/ontology_overrides").split())
    assert tracked == {p for p in FROZEN if p.startswith("data/ontology_overrides/")}, (
        "a file was added under data/ontology_overrides/, which is this install's own tree: a "
        "fast-forward that adds a path an install already wrote untracked is refused. Ship it in "
        "data/shipped/ontology_overrides/.")
    assert not _git("ls-files", "data/metrics.instance.json").strip()


def test_G1_the_baseline_is_a_byte_copy_of_what_the_legacy_file_shipped_as():
    """`derive` judges an install's rows against this file; if it drifted from the frozen legacy
    file, every fresh install would read the whole shipped catalogue as its own."""
    base = (REPO / "data" / "shipped" / "metrics.legacy.json").read_bytes()
    assert _blob(base) == FROZEN["data/metrics.json"]


def test_G5_nothing_reads_the_catalogue_file_but_the_store():
    """schema_linker read `data/metrics.json` directly — past the test isolation and, after the
    overlay, past every row an install writes. A path literal outside the store is that bypass."""
    allowed = {REPO / "aughor" / "semantic" / "metrics.py",
               REPO / "aughor" / "db" / "home.py"}          # an entry NAME in AUTHORED_ENTRIES
    offenders = []
    for py in sorted((REPO / "aughor").rglob("*.py")):
        if py in allowed:
            continue
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and node.value.rstrip("/").endswith(("metrics.json", "metrics.instance.json")) \
                    and len(node.value) < 60:
                offenders.append(f"{py.relative_to(REPO)}:{node.lineno} {node.value!r}")
    assert offenders == [], offenders
