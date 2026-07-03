"""K4 contract ratchets — silent failure and boundary erosion can only go DOWN.

The K0 recon measured 271 except-blocks whose entire body is ``pass`` /
``continue`` (failure eaten, no trail) and 70 cross-module imports of private
``_underscore`` names (boundary erosion). Fixing them all at once isn't
realistic; letting NEW ones in silently is how the number got to 271. So:
ratchets. Each test pins the current count — adding a new offence fails CI
with directions; reducing the count means lowering the baseline here.

The only legal exception swallow in kernel-managed code is
``aughor.kernel.errors.tolerate`` (logs the reason + counts + journals).
"""
import ast
import glob
from pathlib import Path

# Lower these as offences are converted — never raise them.
# 2026-06-27: converted 38 best-effort store/cache/registry/scheduler swallows to
# tolerate() (AUDIT_2026-06-27.md #3), ratcheting 302 → 265.
# 2026-07-03: fail-closed SQL safety gate (REC-01) converted the 2 security-path
# `except: pass` in db/connection.py to tolerate(), ratcheting 265 → 263.
SILENT_SWALLOW_BASELINE = 263
PRIVATE_IMPORT_BASELINE = 22

REPO = Path(__file__).parent.parent.parent


def _py_files():
    return [f for f in glob.glob(str(REPO / "aughor/**/*.py"), recursive=True)
            if "__pycache__" not in f]


def _silent_swallows(path):
    """except-blocks whose entire body is pass/continue — failure with no trail."""
    out = []
    try:
        tree = ast.parse(open(path).read())
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Continue)):
                out.append(node.lineno)
    return out


def _private_imports(path):
    """`from aughor.x import _private` — reaching into another module's internals."""
    out = []
    try:
        tree = ast.parse(open(path).read())
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("aughor"):
            out.extend(node.lineno for a in node.names if a.name.startswith("_"))
    return out


class TestRatchets:
    def test_no_new_silent_swallows(self):
        hits = {f: _silent_swallows(f) for f in _py_files()}
        total = sum(len(v) for v in hits.values())
        assert total <= SILENT_SWALLOW_BASELINE, (
            f"{total} silent except-pass/continue blocks (baseline "
            f"{SILENT_SWALLOW_BASELINE}). A swallowed failure must go through "
            f"aughor.kernel.errors.tolerate(exc, reason, counter=...) — it keeps the "
            f"resilience but logs the reason, counts it, and journals it. "
            f"Newest offenders: "
            + ", ".join(f"{Path(f).name}:{ls}" for f, ls in hits.items() if ls)[-400:]
        )
        if total < SILENT_SWALLOW_BASELINE:
            # Not a failure — a nudge visible in -v output to ratchet down.
            print(f"\n[ratchet] silent swallows now {total} — lower "
                  f"SILENT_SWALLOW_BASELINE in {__file__}")

    def test_no_new_private_cross_imports(self):
        total = sum(len(_private_imports(f)) for f in _py_files())
        assert total <= PRIVATE_IMPORT_BASELINE, (
            f"{total} cross-module private imports (baseline {PRIVATE_IMPORT_BASELINE}). "
            f"Import the module's public interface instead of its _internals."
        )


class TestTolerate:
    def test_tolerate_logs_counts_and_journals(self, tmp_path, monkeypatch, caplog):
        import logging
        monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "sys.db"))
        from aughor.kernel.ledger import Ledger
        Ledger._instances.clear()
        from aughor.kernel.errors import tolerate
        from aughor.stats import stats

        (stats.snapshot() if hasattr(stats, "snapshot") else {})
        with caplog.at_level(logging.WARNING):
            tolerate(ValueError("boom"), "test reason", counter="unit.test", conn_id="c1")
        assert any("test reason" in r.message for r in caplog.records)
        evs = Ledger.default().events(kind="error.tolerated")
        assert evs and evs[0]["payload"]["reason"] == "test reason"
        assert evs[0]["conn_id"] == "c1"

    def test_tolerate_never_raises(self, monkeypatch):
        # Even with the journal disabled and stats broken, tolerate must not raise.
        monkeypatch.setenv("AUGHOR_KERNEL_EVENTS", "0")
        from aughor.kernel.errors import tolerate
        tolerate(RuntimeError("x"), "reason")
