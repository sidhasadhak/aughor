from fastapi.testclient import TestClient
from tests.integration.test_insight_stream import _stream_events, _stub_providers


def test_print_wire_sequence(client: TestClient, builtin_conn_id: str, monkeypatch):
    monkeypatch.setenv("AUGHOR_ASK_STREAM_TEXT", "1")
    _stub_providers(monkeypatch)
    events = _stream_events(client, builtin_conn_id, "total value split by group")
    print("\nWIRE SEQUENCE (post-done tail):")
    tail = False
    for e in events:
        if e["type"] == "done":
            tail = True
        if tail:
            extra = e.get("narrative", "")
            print(f"  {e['type']:<18} {str(extra)[:46]}")
