"""One vocabulary for guard receipts: the export's words are the web's words.

The web named each guard for the reader in B2 (`GuardReceiptChain.tsx`); the export printed the
raw fields (``extra_filter_replan — replanned_queries — …``) under "Checks" until 2026-10-15. The
Python maps in `aughor/answer/receipts.py` must stay byte-equal to the TSX maps — a guard named on
one surface is named the same on the other — so this reads the TSX and compares.
"""
import re
from pathlib import Path

from aughor.answer.receipts import ACTION_VERB, GUARD_LABEL, receipt_sentence

TSX = Path(__file__).resolve().parents[2] / "web" / "components" / "GuardReceiptChain.tsx"


def _tsx_map(name: str) -> dict[str, str]:
    src = TSX.read_text(encoding="utf-8")
    m = re.search(rf"const {name}: Record<string, string> = \{{(.*?)\n\}};", src, re.S)
    assert m, f"{name} not found in {TSX.name}"
    return dict(re.findall(r'^\s*([a-z_0-9]+):\s*"((?:[^"\\]|\\.)*)",?\s*$', m.group(1), re.M))


def test_the_guard_labels_are_the_webs_labels():
    assert GUARD_LABEL == _tsx_map("GUARD_LABEL")


def test_the_action_verbs_are_the_webs_verbs():
    assert ACTION_VERB == _tsx_map("ACTION_VERB")


def test_every_guard_the_backend_writes_has_a_label():
    """A receipt the routers or the executor write today is named on both surfaces."""
    root = Path(__file__).resolve().parents[2] / "aughor"
    written: set[str] = set()
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        written |= set(re.findall(r'"guard":\s*"([a-z_]+)"', text))
        written |= set(re.findall(r'emit_guard_receipt\(\s*"([a-z_]+)"', text))
        written |= set(re.findall(r'_egr_ef\(\s*"([a-z_]+)"', text))
    missing = sorted(written - set(GUARD_LABEL))
    assert not missing, f"guards without a reader's label: {missing}"


def test_the_sentence_is_the_readers_not_the_fields():
    line = receipt_sentence({"guard": "extra_filter_replan", "action": "replanned_queries",
                             "detail": "Revenue change by platform: is sep = 0; is sep = 1"})
    assert line == ("Queries re-planned around a filter the metric does not declare — sent the plan back "
                    "for correction: Revenue change by platform: is sep = 0; is sep = 1")
    assert "extra_filter_replan" not in line and "replanned_queries" not in line
    # An unknown guard is still visible, spaced, never dropped.
    assert receipt_sentence({"guard": "new_guard", "action": "flagged"}).startswith("new guard — flagged it")
