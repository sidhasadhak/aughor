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


class TestTheOverlayKeepsAUsedInstallUpdatable:
    """The overlay's premise, against real git: the release that ships it fast-forwards on the OLD
    updater, and an ignored instance file is never overwritten."""

    def _used(self, clone):
        (clone / "data" / "metrics.json").write_text('[{"name": "mine"}]\n')
        (clone / "data" / "ontology_overrides" / "c1").mkdir(parents=True)
        (clone / "data" / "ontology_overrides" / "c1" / "x.yaml").write_text("mine\n")

    def _upstream(self, clone, rel, text):
        origin = clone.parent / "origin"
        (origin / rel).parent.mkdir(parents=True, exist_ok=True)
        (origin / rel).write_text(text)
        _git(origin, "add", "-A")
        _git(origin, "commit", "--quiet", "-m", f"upstream touches {rel}")

    def test_U1_a_release_that_ships_only_under_data_shipped_reaches_a_used_install(self, clone):
        self._used(clone)
        self._upstream(clone, "data/shipped/metrics.json", "[]\n")
        result = up.update(clone)
        assert result.status == "updated", result.reason
        assert (clone / "data" / "metrics.json").read_text() == '[{"name": "mine"}]\n'
        assert (clone / "data" / "ontology_overrides" / "c1" / "x.yaml").read_text() == "mine\n"

    def test_U1_the_control_an_upstream_edit_of_a_written_path_strands_it(self, clone):
        """Why `test_seed_overlay_frozen` exists: this is #514's shape, and no update can fix it."""
        self._used(clone)
        self._upstream(clone, "data/metrics.json", "[]\n")
        result = up.update(clone)
        assert result.status == "failed"
        assert (clone / "data" / "metrics.json").read_text() == '[{"name": "mine"}]\n'

    def test_U2_an_ignored_instance_file_is_never_overwritten(self, clone):
        """Git overwrites an IGNORED file by default when upstream starts tracking its path — which
        is where instance data now lives. Kills: dropping `--no-overwrite-ignore`."""
        self._upstream(clone, ".gitignore", "data/*.json\n")
        assert up.update(clone).status == "updated"
        (clone / "data" / "metrics.instance.json").write_text('{"rows": ["mine"]}\n')
        origin = clone.parent / "origin"
        (origin / "data" / "metrics.instance.json").write_text("{}\n")
        _git(origin, "add", "-f", "data/metrics.instance.json")      # ignored: only -f tracks it
        _git(origin, "commit", "--quiet", "-m", "upstream tracks an instance path")
        result = up.update(clone)
        assert result.status == "failed", result.reason
        assert (clone / "data" / "metrics.instance.json").read_text() == '{"rows": ["mine"]}\n'


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


# ── re-running the installer updates an existing clone ────────────────────────

@pytest.mark.parametrize("status", ["updated", "noop", "refused", "failed", "raises"])
def test_the_installer_updates_a_clone_and_never_fails_on_a_refusal(tmp_path, monkeypatch,
                                                                    capsys, status):
    """A re-run used to reuse an existing checkout exactly as it was — re-syncing the old code's
    dependencies and never pulling. It now fast-forwards first, through the same function
    `aughor update` uses. What must NOT change is that an install finishes: a refusal (local
    changes, a diverged branch) or an error is one line, never an abort."""
    from aughor import installer

    (tmp_path / ".git").mkdir()
    calls = []

    def fake_update(root, ref=None):
        calls.append(root)
        if status == "raises":
            raise RuntimeError("network down")
        return up.Result(status, "local changes outside data/",
                         before="a" * 40, after="b" * 40) if status != "noop" else \
            up.Result("noop", "already current", before="a" * 40, after="a" * 40)

    monkeypatch.setattr(up, "update", fake_update)
    installer.update_checkout(tmp_path, installer.Steps())  # must not raise, whatever the status
    assert calls == [tmp_path]
    out = capsys.readouterr().out
    if status in ("refused", "failed"):
        assert "Not updating the code" in out
    if status == "raises":
        assert "installing what is here" in out


def test_a_snapshot_install_is_not_asked_to_update_itself(tmp_path, monkeypatch):
    """No `.git`: the installer that is running IS how a snapshot updates, so `update` — whose
    snapshot answer is "re-run the installer" — must not be called from inside it."""
    from aughor import installer
    monkeypatch.setattr(up, "update", lambda *a, **k: pytest.fail("update called on a snapshot"))
    installer.update_checkout(tmp_path, installer.Steps())
