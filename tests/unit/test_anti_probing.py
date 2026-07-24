"""Wave R4 — the anti-probing rule, as a ratchet.

T2.4 verbatim: *guard-suppressed data must be indistinguishable from absence in the
model's view; the suppression count surfaces to the user out-of-band.*

Auditing the paths found Aughor already correct — the PII scanner's redacted count goes to
the audit log, the row-budget truncation is silent, the RBAC row policy filters inside the
SQL (so the model simply sees fewer rows), and ``format_result_for_llm`` renders neither
``caveats`` nor ``annotations``. Nothing needed fixing.

That is exactly why this file exists. A property that holds only because nobody has yet
added the obvious-looking line ("tell the model 3 rows were hidden so it doesn't
over-claim") is one refactor from being false, and the failure is silent: a model that can
see a suppression COUNT can binary-search the hidden set by varying its filters. These
tests make the property load-bearing instead of incidental.
"""
from __future__ import annotations

import inspect

import pytest

from aughor.platform.contracts.execution import QueryResult
from aughor.tools.executor import format_result_for_llm

SUPPRESSION_WORDS = ("suppress", "redact", "hidden", "withheld", "filtered out",
                     "row policy", "row-level", "masked")


def _result(**kw) -> QueryResult:
    base = dict(hypothesis_id="H1", sql="SELECT region, revenue FROM sales",
                columns=["region", "revenue"], rows=[["eu", 10], ["us", 20]], row_count=2)
    base.update(kw)
    return QueryResult(**base)


def test_caveats_never_reach_the_model_facing_render():
    """`caveats` is the channel guard findings ride on. It is user-facing — the trust
    receipt and the dashboard read it — and it must stay that way."""
    out = format_result_for_llm(_result(caveats=[
        "3 rows were suppressed by the row-level access policy",
        "PII redacted in 7 cells",
        "join is on value-disjoint keys",
    ]))
    lowered = out.lower()
    assert not any(w in lowered for w in SUPPRESSION_WORDS), out


def test_human_overlay_annotations_do_not_leak_through_this_channel():
    """K3 overlay edits are a separate, deliberate surface. If they are ever to reach the
    model it must be a decision someone makes, not a side effect of a render helper."""
    out = format_result_for_llm(_result(annotations=[
        {"target": "eu", "kind": "correction", "body": "known launch-day spike",
         "source": "human"}]))
    assert "known launch-day spike" not in out


def test_the_true_row_count_is_still_reported():
    """The complement, and the line this rule must NOT be read as crossing: honest
    coverage is not a suppression signal. A model told 'Rows returned: 5000' while shown
    1000 knows its sample is partial — that prevents an over-claim. What it must not learn
    is that a GUARD removed something."""
    out = format_result_for_llm(_result(row_count=5000))
    assert "Rows returned: 5000" in out


def test_the_pii_scanner_reports_its_count_out_of_band_only():
    """`_security_post` redacts in place and sends `redacted_count` to the AuditLogger.
    The count must not be threaded onto the result, where a render could pick it up."""
    src = inspect.getsource(__import__("aughor.db.connection", fromlist=["_security_post"])._security_post)
    # The count is computed and passed to the audit log…
    assert "pii_redacted=pii_count" in src
    # …and the QueryResult rebuilds carry only rows/columns, never the count.
    for rebuild in src.split("QueryResult(")[1:]:
        head = rebuild.split(")")[0]
        assert "pii" not in head.lower() and "redact" not in head.lower(), head


def test_a_blocked_query_says_so_rather_than_returning_an_empty_result():
    """The one place the rule inverts. A row policy that could not be applied FAILS CLOSED,
    and that must be a visible error — silently returning zero rows would make a
    permissions failure look like a finding of absence, which is a wrong answer, not a
    protected one."""
    from aughor.db import connection as C

    src = inspect.getsource(C.enforce_row_policy)
    assert "fail" in src.lower() and "ROW POLICY" in src
    assert 'error="[ROW POLICY]' in src


@pytest.mark.parametrize("field", ["caveats", "annotations"])
def test_the_render_helper_does_not_read_the_sidecar_fields(field):
    """A structural check to go with the behavioural ones above: the model-facing renderer
    must not so much as reference these fields. This is the line a future 'just mention it
    to the model' change would have to cross deliberately."""
    src = inspect.getsource(format_result_for_llm)
    assert field not in src, f"format_result_for_llm now reads `{field}` — see the anti-probing rule"
