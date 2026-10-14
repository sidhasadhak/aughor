"""Evidence peer layer — scope-recent claims query (backlog #8).

The ledger keys only by investigation_id, so the scope-level layer resolves a
connection/canvas to its investigation IDs (history) and filters claims to them.
This covers the evidence-store half (the IN-filter + ordering + limit).
See aughor/evidence/store.py::get_recent_claims_for_investigations.
"""
import aughor.evidence.store as store
from aughor.evidence.models import EvidenceClaim


def _claim(inv, text, created_at, conf=0.7):
    return EvidenceClaim(investigation_id=inv, claim_text=text, confidence=conf,
                         created_at=created_at, sql_source="SELECT 1")


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "ev.db")


def test_recent_claims_scoped_to_investigation_ids(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    store.append_claim(_claim("invA", "claim a1", "2026-06-01T00:00:00Z"))
    store.append_claim(_claim("invA", "claim a2", "2026-06-03T00:00:00Z"))
    store.append_claim(_claim("invB", "claim b1", "2026-06-02T00:00:00Z"))
    store.append_claim(_claim("invC", "claim c1", "2026-06-09T00:00:00Z"))  # out of scope

    out = store.get_recent_claims_for_investigations(["invA", "invB"], limit=50)
    texts = [c.claim_text for c in out]
    assert "claim c1" not in texts                       # invC excluded
    # newest-first across the in-scope investigations
    assert texts == ["claim a2", "claim b1", "claim a1"]


def test_recent_claims_respects_limit(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for i in range(5):
        store.append_claim(_claim("invA", f"c{i}", f"2026-06-0{i+1}T00:00:00Z"))
    out = store.get_recent_claims_for_investigations(["invA"], limit=2)
    assert len(out) == 2
    assert [c.claim_text for c in out] == ["c4", "c3"]   # the 2 newest


def test_recent_claims_empty_scope_returns_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    store.append_claim(_claim("invA", "a", "2026-06-01T00:00:00Z"))
    assert store.get_recent_claims_for_investigations([], limit=50) == []


def test_recent_claims_unknown_ids_returns_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    store.append_claim(_claim("invA", "a", "2026-06-01T00:00:00Z"))
    assert store.get_recent_claims_for_investigations(["ghost"], limit=50) == []


# ── an investigation's own notes are not claims (2026-10-14: 134 of theLook's last 500) ──────────

def test_the_spec_and_a_skipped_phase_are_not_claims():
    from aughor.evidence.linker import extract_claims_from_ada_phases
    phases = [
        {"phase_id": "intake", "findings": [
            {"finding_id": "intake_spec", "title": "Investigation Specification", "sql": "",
             "interpretation": "Investigating Revenue in last month.", "error": None}]},
        {"phase_id": "decomposition", "findings": [
            {"finding_id": "decomposition_skip", "title": "Skipped", "sql": "",
             "interpretation": "structured output empty: the model returned no content.", "error": None},
            {"finding_id": "d1", "title": "Revenue by country", "sql": "SELECT 1",
             "interpretation": "China leads. The rest follow.", "error": None}]},
    ]
    claims = extract_claims_from_ada_phases(investigation_id="inv1", phases=phases)
    assert [c.claim_text for c in claims] == ["Revenue by country: China leads."]


def test_a_stored_spec_or_skip_is_not_read_as_a_claim(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    store.append_claim(_claim("invA", "Revenue by country: China leads.", "2026-06-01T00:00:00Z"))
    for text in ("Investigation Specification: Investigating Revenue.", "Skipped: structured output empty."):
        store.append_claim(EvidenceClaim(investigation_id="invA", claim_text=text, created_at="2026-06-02T00:00:00Z"))
    assert [c.claim_text for c in store.get_recent_claims_for_investigations(["invA"])] == [
        "Revenue by country: China leads."]
    assert [c.claim_text for c in store.get_claims_for_investigation("invA")] == ["Revenue by country: China leads."]
