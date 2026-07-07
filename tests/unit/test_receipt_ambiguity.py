"""I6 — the Trust Receipt surfaces ambiguity handling.

When an answer's question matches a resolution in the Ambiguity Ledger (settled earlier), the
receipt records it, so "this answer followed a previously-resolved reading" is inspectable. Tested
by capturing the artifact payload the receipt writer emits — no dependency on the Ledger read API.
"""
from __future__ import annotations

import pytest

import aughor.routers.investigations as inv


class _Cap:
    def __init__(self):
        self.payloads: list[dict] = []
        self.lineages: list[list] = []

    def artifact_write(self, kind, natural_key, payload, *, conn_id=None, canvas_id=None, lineage=None):
        self.payloads.append(payload)
        self.lineages.append(lineage or [])


@pytest.fixture
def cap_ledger(monkeypatch):
    # Patch only artifact_write/emit on the REAL singleton — leave kv_get intact so
    # flag_enabled (which reads flags through the ledger) still works.
    from aughor.kernel.ledger import Ledger
    cap = _Cap()
    real = Ledger.default()
    monkeypatch.setattr(real, "artifact_write", cap.artifact_write)
    monkeypatch.setattr(real, "emit", lambda *a, **k: None)
    return cap


def test_receipt_surfaces_resolved_ambiguity(cap_ledger, monkeypatch):
    from aughor.semantic.ambiguity_ledger import crystallize_user_choice, purge_connections
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    purge_connections(["rcpt_conn"])
    crystallize_user_choice("rcpt_conn", "top products", "by revenue")
    inv._write_answer_receipt(
        kind="chat_answer", natural_key="chat:rcpt_conn:x",
        question="what are the top products?", sqls=["SELECT 1"], headline="",
        schema="", connection_id="rcpt_conn")
    assert cap_ledger.payloads, "the receipt should have been written"
    payload = cap_ledger.payloads[-1]
    assert "resolved_ambiguities" in payload
    ra = payload["resolved_ambiguities"]
    assert ra and ra[0]["reading"] == "by revenue" and ra[0]["source"] == "user"
    # and the lineage carries an inspectable receipt edge
    assert any(rel == "resolved_ambiguity" for rel, *_ in cap_ledger.lineages[-1])


def test_receipt_omits_field_when_no_resolution(cap_ledger, monkeypatch):
    from aughor.semantic.ambiguity_ledger import purge_connections
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    purge_connections(["rcpt_empty"])
    inv._write_answer_receipt(
        kind="chat_answer", natural_key="chat:rcpt_empty:x",
        question="an unrelated question about suppliers", sqls=["SELECT 1"], headline="",
        schema="", connection_id="rcpt_empty")
    assert "resolved_ambiguities" not in cap_ledger.payloads[-1]


def test_receipt_omits_field_when_flag_off(cap_ledger, monkeypatch):
    from aughor.semantic.ambiguity_ledger import crystallize_user_choice, purge_connections
    monkeypatch.delenv("AUGHOR_CLOSED_LOOP", raising=False)
    purge_connections(["rcpt_off"])
    crystallize_user_choice("rcpt_off", "top products", "by revenue")
    inv._write_answer_receipt(
        kind="chat_answer", natural_key="chat:rcpt_off:x",
        question="what are the top products?", sqls=["SELECT 1"], headline="",
        schema="", connection_id="rcpt_off")
    assert "resolved_ambiguities" not in cap_ledger.payloads[-1]
