"""Wave G6 — governance disclosure on the answer.

The carrying tests are the redaction battery: :func:`run_as_identity` is one careless
f-string away from printing a connection password into an answer, a receipt, a log and an
exported artifact simultaneously, so it is tested against every DSN shape in the tree plus
the ones that are trying to smuggle a secret through.
"""
from __future__ import annotations

import pytest

from aughor.govern.disclosure import (
    GovernanceDisclosure,
    build,
    run_as_identity,
    standing_grants_for,
)


# ── the redaction rule ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("conn_type,dsn,expected", [
    ("postgresql", "postgresql://analytics:s3cret@db.internal:5432/warehouse", "analytics"),
    ("mysql", "mysql://svc_bi:hunter2@10.0.0.4/sales", "svc_bi"),
    ("snowflake", "snowflake://ACME_SVC:pw@acct/db", "ACME_SVC"),
])
def test_a_url_dsn_yields_only_the_username(conn_type, dsn, expected):
    assert run_as_identity(conn_type, dsn) == expected


@pytest.mark.parametrize("conn_type,dsn", [
    ("postgresql", "postgresql://analytics:s3cret@db.internal:5432/warehouse"),
    ("mysql", "mysql://svc_bi:hunter2@10.0.0.4/sales"),
    ("odbc", "DRIVER={x};SERVER=db;UID=analytics;PWD=hunter2"),
    ("postgresql", "user=analytics password=s3cret host=db"),
])
def test_no_secret_or_host_ever_survives(conn_type, dsn):
    """The whole risk of this feature in one assertion."""
    out = run_as_identity(conn_type, dsn)
    for forbidden in ("s3cret", "hunter2", "PWD", "password", "db.internal", "10.0.0.4",
                      "5432", "warehouse"):
        assert forbidden not in out


def test_a_key_value_dsn_yields_the_user():
    assert run_as_identity("postgresql", "user=analytics password=s3cret host=db") == \
        "analytics"


def test_an_odbc_uid_is_recognised():
    assert run_as_identity("odbc", "DRIVER={x};SERVER=db;UID=analytics;PWD=hunter2") == \
        "analytics"


def test_a_password_containing_an_at_sign_cannot_shift_the_capture():
    """Parsed with urlsplit rather than a regex over the whole string, so an '@' inside
    the password does not move where the username is read from."""
    out = run_as_identity("postgresql", "postgresql://analytics:p@ss@db.internal/w")
    assert "db.internal" not in out and "p@ss" not in out


@pytest.mark.parametrize("conn_type", ["duckdb", "local_upload", "aughor_ops", "sqlite"])
def test_file_backed_connections_report_local_not_an_os_user(conn_type):
    """Naming the OS account would be both wrong and more disclosure than asked for."""
    out = run_as_identity(conn_type, "/data/whatever.db")
    assert out.startswith("local (")


def test_an_unrecognised_dsn_is_unknown_rather_than_guessed():
    """Failing closed is the correct direction when the alternative is printing a
    secret."""
    assert run_as_identity("weird", "totally::opaque::blob") == "unknown"


def test_an_identity_with_unsafe_characters_is_refused():
    """The allowlist is what may be SHOWN — anything not matching is not displayed."""
    assert run_as_identity("postgresql", "user=an;alytics<script> host=db") in (
        "unknown", "an")


def test_run_as_for_an_unknown_connection_degrades_rather_than_raising():
    from aughor.govern.disclosure import run_as_for

    assert run_as_for("no-such-connection-at-all") == "unknown"


# ── standing grants ─────────────────────────────────────────────────────────────────

def test_standing_grants_filter_to_the_ones_that_applied(monkeypatch):
    """An answer needs the grant that auto-approved THIS, not an inventory."""
    import aughor.govern.disclosure as D

    monkeypatch.setattr(
        "aughor.govern.actions.list_allowlist",
        lambda: [{"action": "connection.delete", "scope": "c1", "actor": "alice"},
                 {"action": "ontology.override", "scope": "c2", "actor": "bob"}])
    applied = D.standing_grants_for([("connection.delete", "c1")])
    assert [g["action"] for g in applied] == ["connection.delete"]


def test_no_filter_lists_them_all(monkeypatch):
    """The 'list them' half of J2 — a grant nobody can see is a grant nobody revokes."""
    monkeypatch.setattr("aughor.govern.actions.list_allowlist",
                        lambda: [{"action": "a", "scope": "s"}])
    assert len(standing_grants_for()) == 1


def test_an_unreadable_allowlist_degrades_to_empty(monkeypatch):
    def _boom():
        raise RuntimeError("store down")

    monkeypatch.setattr("aughor.govern.actions.list_allowlist", _boom)
    assert standing_grants_for() == []


# ── the disclosure ──────────────────────────────────────────────────────────────────

def test_an_empty_disclosure_says_nothing():
    d = GovernanceDisclosure()
    assert d.is_empty and d.lines() == []


def test_a_standing_grant_line_names_how_to_revoke_it():
    d = GovernanceDisclosure(standing_grants=[
        {"action": "connection.delete", "scope": "c1", "actor": "alice", "at": "2026-07-28"}])
    line = d.lines()[0]
    assert "connection.delete" in line and "alice" in line and "revoke" in line


def test_the_clearance_notice_rides_the_disclosure():
    d = GovernanceDisclosure(clearance_trimmed=True,
                             clearance_notice="[1 item withheld by data governance]")
    assert any("withheld" in ln for ln in d.lines())


def test_build_never_raises_on_a_bad_connection():
    d = build("no-such-connection", clearance_notice="[1 item withheld]")
    assert d.run_as == "unknown" and d.clearance_trimmed


def test_disclosure_serializes_with_its_lines():
    d = build("", clearance_notice="[1 item withheld by data governance]")
    out = d.to_dict()
    assert out["clearance_trimmed"] is True and out["lines"]
