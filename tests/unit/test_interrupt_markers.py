"""Recovery markers for interrupted work (Wave 4 / Layer 4.1c).

An exploration slice claims its domain with a lease. When a worker dies, the lease
lapses and the next worker STEALS the claim — and from inside the next prompt that is
invisible: a half-written finding list looks exactly like a complete one. So the model
either repeats work already done or builds on a record nobody finished.

The fix is to tell it. `Ledger.lapsed_claim_owner` is the primitive (`try_claim`
returns a bare bool and cannot distinguish a fresh claim from a steal), and the marker
uses the one shared sentence for interrupted work, so the same fact reads identically
in a job error, in the web client, and here.
"""
from __future__ import annotations

import pytest

from aughor.kernel.jobs import UNCERTAIN_RESULT
from aughor.kernel.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "ledger.db"))


def test_a_fresh_scope_has_no_lapsed_owner(ledger):
    assert ledger.lapsed_claim_owner("explore:c:sales") == ""


def test_a_live_claim_is_not_reported_as_lapsed(ledger):
    assert ledger.try_claim("explore:c:sales", "worker-1", lease_s=300)
    assert ledger.lapsed_claim_owner("explore:c:sales") == "", (
        "a worker still holding its lease has not been interrupted")


def test_a_lapsed_claim_names_the_worker_that_died(ledger):
    """The signal 4.1c needs: someone started this slice and never finished it."""
    assert ledger.try_claim("explore:c:sales", "worker-1", lease_s=-1)   # already expired
    assert ledger.lapsed_claim_owner("explore:c:sales") == "worker-1"


def test_the_steal_still_succeeds_after_detection(ledger):
    """Detection must not consume the claim — the next worker still takes the slice."""
    ledger.try_claim("explore:c:sales", "worker-1", lease_s=-1)
    assert ledger.lapsed_claim_owner("explore:c:sales") == "worker-1"
    assert ledger.try_claim("explore:c:sales", "worker-2", lease_s=300)
    assert ledger.lapsed_claim_owner("explore:c:sales") == "", "the new lease is live"


def test_a_released_claim_is_not_an_interruption(ledger):
    """A worker that finished cleanly released its slice; that is not a gap."""
    ledger.try_claim("explore:c:sales", "worker-1", lease_s=300)
    ledger.release_claim("explore:c:sales", "worker-1")
    assert ledger.lapsed_claim_owner("explore:c:sales") == ""


def test_the_marker_uses_the_one_shared_sentence():
    """A second wording for the same fact is how a vocabulary fragments — the explorer
    marker, the kernel's job error and the web client all say this."""
    import inspect

    from aughor.explorer import agent as A

    src = inspect.getsource(A)
    assert "from aughor.kernel.jobs import UNCERTAIN_RESULT" in src
    assert "previous pass over this domain was interrupted" in src
    assert UNCERTAIN_RESULT == "its result is uncertain and was not replayed"


def test_the_marker_tells_the_model_what_to_DO():
    """A warning the model cannot act on is decoration. It must say to confirm before
    building on a finding, and that the list may be incomplete."""
    import inspect

    from aughor.explorer import agent as A

    src = inspect.getsource(A)
    assert "confirm one before building on it" in src
    assert "do not assume the list" in src
