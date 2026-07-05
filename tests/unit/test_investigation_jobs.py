"""Investigations as first-class kernel jobs (T3 completion).

`_investigation_job_streamed` runs the (unchanged) `_stream_investigation`
generator INSIDE a supervised kernel job and bridges its SSE events to the client
over a queue — so a live investigation gets a job.state lifecycle, heartbeat,
kernel cancel, and job-stamped artifacts. Verified live (job PENDING→RUNNING→
SUCCEEDED, and cancel → CANCELLED + reconcile); these lock the mechanics.
"""
import asyncio
import inspect

import aughor.routers.investigations as inv_mod


def test_wrapper_streams_generator_output_and_submits_a_job(monkeypatch):
    async def fake_stream(question, connection_id, request, **kw):
        yield "data: one\n\n"
        yield "data: two\n\n"

    monkeypatch.setattr(inv_mod, "_stream_investigation", fake_stream)

    submitted = {}

    class _FakeKernel:
        async def submit(self, kind, coro_factory, **kw):
            submitted["kind"] = kind
            submitted["kw"] = kw
            asyncio.create_task(coro_factory())   # run the drive coro
            return "job-test"

    import aughor.kernel.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "kernel", lambda: _FakeKernel())

    async def _collect():
        out = []
        async for item in inv_mod._investigation_job_streamed("why?", "conn1", None):
            out.append(item)
        return out

    items = asyncio.run(_collect())

    assert items == ["data: one\n\n", "data: two\n\n"]   # client gets exactly the generator's output
    assert submitted["kind"] == "investigation"          # ran as a kernel job
    assert submitted["kw"]["conn_id"] == "conn1"


def test_wrapper_releases_client_even_when_generator_errors(monkeypatch):
    async def boom_stream(question, connection_id, request, **kw):
        yield "data: partial\n\n"
        raise RuntimeError("node blew up")

    monkeypatch.setattr(inv_mod, "_stream_investigation", boom_stream)

    class _FakeKernel:
        async def submit(self, kind, coro_factory, **kw):
            asyncio.create_task(coro_factory())
            return "job-test"

    import aughor.kernel.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "kernel", lambda: _FakeKernel())

    async def _collect():
        out = []
        async for item in inv_mod._investigation_job_streamed("q", "c", None):
            out.append(item)
        return out

    # The _drive finally must still push the sentinel so the client loop ends
    # (otherwise a failed investigation would hang the SSE response forever).
    items = asyncio.run(asyncio.wait_for(_collect(), timeout=5))
    assert items == ["data: partial\n\n"]


def test_investigate_route_uses_the_job_wrapper():
    """Tripwire: the /investigate route must stream through the job wrapper, not
    the raw generator — otherwise live investigations silently stop being jobs."""
    src = inspect.getsource(inv_mod.investigate)
    assert "_investigation_job_streamed(" in src
    assert "_stream_investigation(" not in src   # raw generator must NOT be the route's stream


def test_cancel_route_maps_investigation_to_its_job(monkeypatch):
    # the inv→job link is read from the journal's job-stamped investigation.created
    events = [{"job_id": "jX", "payload": {"investigation_id": "invA"}},
              {"job_id": "jY", "payload": {"investigation_id": "invB"}}]

    import aughor.kernel.ledger as ledger_mod

    class _L:
        def events(self, **kw):
            assert kw.get("kind") == "investigation.created"
            return events

    monkeypatch.setattr(ledger_mod.Ledger, "default", classmethod(lambda cls: _L()))
    assert inv_mod._job_id_for_investigation("invB") == "jY"
    assert inv_mod._job_id_for_investigation("missing") is None


# ── crash-recovery (Increment B): boot-salvage ────────────────────────────────

def _stub_agent(monkeypatch, checkpoint_values):
    """Make build_graph_generic + open_connection_for return stubs whose checkpoint
    holds `checkpoint_values`, so salvage_orphaned_investigation can run hermetically."""
    from types import SimpleNamespace
    import aughor.agent.graph as graph_mod

    class _DB:
        def close(self): pass

    # Salvage now opens via ExecutionScope.open(), which imports from the canonical source —
    # patch there (not the router re-export) so the stub takes.
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: _DB())
    agent = SimpleNamespace(get_state=lambda cfg: SimpleNamespace(values=checkpoint_values))
    monkeypatch.setattr(graph_mod, "build_graph_generic", lambda db, hitl=False: agent)


def test_salvage_recovers_when_evidence_present(monkeypatch):
    _stub_agent(monkeypatch, {"investigation_phases": [{"phase_id": "baseline"}]})
    salvage_calls, fail_calls = [], []
    monkeypatch.setattr(inv_mod, "_try_salvage",
                        lambda merged, inv_id, q, cid, schema="": salvage_calls.append(inv_id) or "report-sse")
    monkeypatch.setattr(inv_mod, "fail_investigation", lambda *a, **k: fail_calls.append(a))

    asyncio.run(inv_mod.salvage_orphaned_investigation("inv1", "conn1", None, "why?"))

    assert salvage_calls == ["inv1"]   # salvage ran on the gathered evidence
    assert fail_calls == []            # and did NOT blanket-fail (salvage persisted complete)


def test_salvage_fails_cleanly_when_no_evidence(monkeypatch):
    _stub_agent(monkeypatch, {})       # empty checkpoint — nothing to salvage
    fail_calls = []
    monkeypatch.setattr(inv_mod, "_try_salvage", lambda *a, **k: None)
    monkeypatch.setattr(inv_mod, "fail_investigation",
                        lambda inv_id, status="failed": fail_calls.append((inv_id, status)))

    asyncio.run(inv_mod.salvage_orphaned_investigation("inv2", "conn1", None, "q"))

    assert fail_calls == [("inv2", "failed")]   # reaches a terminal status, never orphans


def test_boot_wires_salvage_after_kernel_recovery():
    """Tripwire: salvage jobs must be submitted AFTER kernel boot_recovery sweeps the
    job table, else they'd be failed as orphans themselves."""
    import aughor.api as api_mod
    src = inspect.getsource(api_mod._kernel_boot_recovery)
    assert "_recover_orphaned_investigations()" in src
