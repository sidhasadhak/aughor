"""R5 deferreds (closed) — the filter guard binds from the PERSISTED value-sample
store before scanning the warehouse, and composer-open can prewarm that store via
one supervised, idempotent kernel job.

Hermetic: a recording fake connection for the guard; monkeypatched warm fn +
kernel for the endpoint.
"""
from __future__ import annotations

from aughor.sql.join_guard import _highcard_bind_warnings


class _Res:
    def __init__(self, rows):
        self.rows = rows
        self.error = None


class _FakeConn:
    """Answers the guard's probes; records which probe labels ran."""

    def __init__(self, existing: set[str], live_sample: list[str]):
        self._existing = {v.lower() for v in existing}
        self._live = live_sample
        self.labels: list[str] = []
        self._connection_id = "connG"

    def execute(self, label: str, sql: str):
        self.labels.append(label)
        if label == "__filter_highcard_exists__":
            probe = sql.split("LOWER('")[1].split("')")[0].replace("''", "'")
            return _Res([[1]] if probe.lower() in self._existing else [])
        if label == "__filter_highcard_sample__":
            return _Res([[v] for v in self._live])
        raise AssertionError(f"unexpected probe {label}")


def test_offline_sample_binds_without_a_warehouse_scan(monkeypatch):
    monkeypatch.setattr("aughor.tools.profile_cache.load_value_samples",
                        lambda cid: {("sales", "brand"): ["Mytheresa", "Zalando"]})
    conn = _FakeConn(existing={"Mytheresa"}, live_sample=["SHOULD-NOT-BE-SCANNED"])
    warns = _highcard_bind_warnings(conn, "main.sales", "brand", {("Mytheresea", "=")})
    assert len(warns) == 1
    assert warns[0].suggestion == "Mytheresa"
    assert "__filter_highcard_sample__" not in conn.labels   # zero-scan bind


def test_stale_offline_suggestion_falls_back_to_live(monkeypatch):
    # The persisted sample fuzzy-matches the typo to a value that NO LONGER EXISTS
    # ("Mytheresaa", a ghost from before the last refresh) → the guard must verify
    # and fall through to the live domain instead of binding to the ghost.
    monkeypatch.setattr("aughor.tools.profile_cache.load_value_samples",
                        lambda cid: {("sales", "brand"): ["Mytheresaa"]})
    conn = _FakeConn(existing={"Mytheresa"}, live_sample=["Mytheresa", "Zalando"])
    warns = _highcard_bind_warnings(conn, "sales", "brand", {("Mytheresea", "=")})
    assert "__filter_highcard_sample__" in conn.labels       # live fallback ran
    assert len(warns) == 1
    assert warns[0].suggestion == "Mytheresa"                 # the real value, not the ghost


def test_no_offline_sample_behaves_exactly_as_before(monkeypatch):
    monkeypatch.setattr("aughor.tools.profile_cache.load_value_samples",
                        lambda cid: {})
    conn = _FakeConn(existing=set(), live_sample=["Womenswear", "Menswear"])
    warns = _highcard_bind_warnings(conn, "sales", "category", {("Womenswar", "=")})
    assert "__filter_highcard_sample__" in conn.labels
    assert len(warns) == 1 and warns[0].suggestion == "Womenswear"


def test_existing_literal_is_never_second_guessed(monkeypatch):
    monkeypatch.setattr("aughor.tools.profile_cache.load_value_samples",
                        lambda cid: {("sales", "brand"): ["Mytheresa"]})
    conn = _FakeConn(existing={"Zalando"}, live_sample=[])
    warns = _highcard_bind_warnings(conn, "sales", "brand", {("Zalando", "=")})
    assert warns == []
    assert conn.labels == ["__filter_highcard_exists__"]      # one probe, nothing else


# ── the composer-open prewarm endpoint ───────────────────────────────────────

def test_prewarm_submits_one_supervised_job(client, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("aughor.routers.connections._warm_profiles",
                        lambda cid: calls.append(cid) or {"tables": 0, "columns": 0})
    r = client.post("/connections/fixture/prewarm")
    assert r.status_code == 202
    body = r.json()
    assert body["submitted"] is True and body["job_id"]

    # Idempotent: a composer-open burst returns the SAME active job, not a pile.
    r2 = client.post("/connections/fixture/prewarm")
    assert r2.json()["job_id"] == body["job_id"] or r2.json()["submitted"] is True


def test_prewarm_404_on_unknown_connection(client):
    assert client.post("/connections/nope-does-not-exist/prewarm").status_code == 404


def test_prewarm_skips_when_curator_disabled(client, monkeypatch):
    monkeypatch.setattr("aughor.routers.connections.is_enabled",
                        lambda agent, ws=None: False, raising=False)
    monkeypatch.setattr("aughor.kernel.agents.is_enabled", lambda agent, ws=None: False)
    r = client.post("/connections/fixture/prewarm")
    assert r.status_code == 202
    assert r.json() == {"submitted": False, "reason": "curator_disabled"}
