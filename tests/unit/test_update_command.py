"""IN-1 — `aughor update` fast-forwards, refuses, and never resets.

Real git repositories in tmp, because the behaviour under test IS git's. The test that
matters most is `test_a_dirty_data_dir_does_not_block`: 102 files under `data/` are tracked
and the running app writes several of them, so a check that refuses on any porcelain output
refuses forever on every install that has been used. Measured on the builder's own checkout
while this was written: `M data/metrics.json` plus six untracked `data/` directories, on an
install whose runbook says never to clean that file.
"""
from __future__ import annotations

import subprocess

import pytest

from aughor import update as up


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def clone(tmp_path):
    """An origin with two commits and a clone sitting on the first — i.e. one behind."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "--quiet", "--initial-branch=main")
    _git(origin, "config", "user.email", "t@example.com")
    _git(origin, "config", "user.name", "t")
    (origin / "README.md").write_text("one\n")
    (origin / "data").mkdir()
    (origin / "data" / "metrics.json").write_text("{}\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "--quiet", "-m", "first")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "--quiet", str(origin), str(work))
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")

    (origin / "README.md").write_text("two\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "--quiet", "-m", "second")
    return work


class TestTheHappyPath:
    def test_a_clean_clone_fast_forwards(self, clone):
        result = up.update(clone)
        assert result.status == "updated", result.reason
        assert result.behind == 1
        assert result.before != result.after
        assert (clone / "README.md").read_text() == "two\n"

    def test_an_up_to_date_clone_is_a_noop_not_an_update(self, clone):
        up.update(clone)
        again = up.update(clone)
        assert again.status == "noop"
        assert again.ok

    def test_a_ref_can_be_pinned(self, clone):
        first = _git(clone, "rev-parse", "HEAD").stdout.strip()
        result = up.update(clone, ref=first)
        assert result.status == "noop", result.reason


class TestItRefuses:
    def test_a_dirty_data_dir_does_not_block(self, clone):
        """THE test. `data/metrics.json` is tracked AND written by the running app — dirty on
        purpose on the builder's own install. Blocking on it would refuse forever."""
        (clone / "data" / "metrics.json").write_text('{"live": true}\n')
        (clone / "data" / "scratch").mkdir()
        (clone / "data" / "scratch" / "x.json").write_text("{}")
        result = up.update(clone)
        assert result.status == "updated", f"a used install could not update: {result.reason}"

    def test_a_tracked_change_outside_data_is_refused_without_fetching(self, clone):
        (clone / "README.md").write_text("local edit\n")
        result = up.update(clone)
        assert result.status == "refused"
        assert any("README.md" in b for b in result.blocking)
        assert (clone / "README.md").read_text() == "local edit\n", "the edit was not preserved"

    def test_an_untracked_file_never_blocks(self, clone):
        """Git refuses a fast-forward that would clobber one, so treating it as dirty is what
        made this check unusable rather than what made it safe."""
        (clone / "IDEAS.md").write_text("notes\n")
        assert up.update(clone).status == "updated"

    def test_a_diverged_checkout_is_refused_and_not_rewound(self, clone):
        (clone / "local.txt").write_text("mine\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "--quiet", "-m", "local work")
        head = _git(clone, "rev-parse", "HEAD").stdout.strip()

        result = up.update(clone)
        assert result.status == "refused"
        assert result.ahead == 1
        assert "diverged" in result.reason
        assert _git(clone, "rev-parse", "HEAD").stdout.strip() == head, "the branch moved"
        assert (clone / "local.txt").exists(), "local work was destroyed"

    def test_a_snapshot_install_is_told_what_to_run(self, tmp_path):
        snapshot = tmp_path / "snapshot"
        (snapshot / "data").mkdir(parents=True)
        result = up.update(snapshot)
        assert result.status == "refused"
        assert "install.sh" in result.reason
        assert "state is not touched" in result.reason


class TestNeverReset:
    def test_no_git_call_can_reset_anything(self):
        """A standing rule on this project, asserted rather than trusted — `git reset --hard`
        has destroyed work here before.

        Read from the AST, not from the text. The first version of this grepped the source and
        failed on the module's own DOCSTRING, which explains the rule using the words it
        forbids — the same "cannot tell code from prose about the code" trap
        `test_sqlite_contention` documents one directory over. This inspects the arguments
        actually passed to git, so the explanation stays and the behaviour is what is checked.
        """
        import ast
        from pathlib import Path

        tree = ast.parse(Path(up.__file__).read_text(encoding="utf-8"))
        passed: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if name not in ("_git", "run"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    passed.append(arg.value)
                elif isinstance(arg, (ast.List, ast.Tuple)):
                    passed += [e.value for e in arg.elts
                               if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        assert passed, "probe failed: no git arguments were found to inspect"
        assert "reset" not in passed, passed
        assert "--hard" not in passed, passed
        assert "checkout" not in passed, passed
