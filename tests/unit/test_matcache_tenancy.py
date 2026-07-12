"""Result-cache tenancy under the RBAC row policy (Combined platform study, Wave 0 · Rec 1).

`matcache` caches POST-execution (hence post-RLS) result rows, but `routers/query.py` consults it
*before* the connection layer injects a principal's row filters. Keyed on `(conn_id, sql)` alone,
principal A's filtered rows would be served to principal B once `rbac.row_policy` is active. The fix:
`result_cache_tenancy()` fingerprints `(org, roles, resolved filters)` and callers fold it into the key.

These assert: the legacy key is byte-identical when tenancy is off (no behaviour change for anyone today),
distinct principals/policies partition the cache, a policy edit bumps the version, the gate fails CLOSED,
and — end to end — one principal can no longer read another's cached rows.
"""
from __future__ import annotations

import hashlib

import duckdb
import pytest

import aughor.licensing as _lic
import aughor.rbac.resolver as _resolver
import aughor.rbac.row_policy as rp
import aughor.security.authz as _authz
from aughor.db import matcache
from aughor.db.connection import result_cache_tenancy
from aughor.org.context import reset_org_id, reset_user_id, set_org_id, set_user_id
from aughor.platform.contracts.execution import QueryResult

_VIEWER_ORG_POLICY = {"viewer": {"orders": "org_id = '{org_id}'"}}


@pytest.fixture
def mem_cache(monkeypatch):
    """Hermetic in-memory matcache (mirrors test_matcache_evict) so nothing touches data/."""
    conn = duckdb.connect(":memory:")
    conn.execute(matcache._DDL)
    monkeypatch.setattr(matcache, "_conn", conn)
    return conn


def _enable(monkeypatch, *, roles, policies=None):
    """Turn the policy gate fully on and pin the caller's roles — same shape as test_row_policy._enable."""
    monkeypatch.setenv("AUGHOR_RBAC_ROW_POLICY", "1")
    monkeypatch.setattr(_authz, "require_identity_enabled", lambda: True)
    monkeypatch.setattr(_lic, "has_capability", lambda *a, **k: True)
    monkeypatch.setattr(_resolver, "resolve_roles", lambda principal: list(roles))
    monkeypatch.setattr(rp, "ROW_POLICIES", policies if policies is not None else _VIEWER_ORG_POLICY)


def _fingerprint(*, org, user):
    """result_cache_tenancy() evaluated with (org, user) pinned in the request context."""
    ot, ut = set_org_id(org), set_user_id(user)
    try:
        return result_cache_tenancy()
    finally:
        reset_user_id(ut); reset_org_id(ot)


def _result(sql, rows):
    return QueryResult(hypothesis_id="t", sql=sql, columns=["id"], rows=rows, row_count=len(rows))


# ── The key format itself ─────────────────────────────────────────────────────

def test_cache_key_byte_identical_without_tenancy():
    # No tenancy → EXACTLY the historical formula, so pre-existing entries and default-off deployments
    # keep resolving unchanged.
    legacy = hashlib.sha256("c1::SELECT 1".encode()).hexdigest()[:32]
    assert matcache._cache_key("c1", "SELECT 1") == legacy
    assert matcache._cache_key("c1", "SELECT 1", None) == legacy


def test_cache_key_partitions_on_tenancy():
    base = matcache._cache_key("c1", "SELECT 1")
    scoped = matcache._cache_key("c1", "SELECT 1", "rp:abc")
    other = matcache._cache_key("c1", "SELECT 1", "rp:xyz")
    assert base != scoped != other and base != other


# ── result_cache_tenancy(): when it engages ──────────────────────────────────

def test_tenancy_none_when_flag_off(monkeypatch):
    monkeypatch.delenv("AUGHOR_RBAC_ROW_POLICY", raising=False)
    assert _fingerprint(org="o1", user="u1") is None          # legacy key → byte-identical to today


def test_tenancy_none_without_capability(monkeypatch):
    _enable(monkeypatch, roles=["viewer"])
    monkeypatch.setattr(_lic, "has_capability", lambda *a, **k: False)   # RBAC_SSO absent → policy inert
    assert _fingerprint(org="o1", user="u1") is None


def test_tenancy_none_for_internal_query_without_user(monkeypatch):
    _enable(monkeypatch, roles=["viewer"])
    ot = set_org_id("o1")                                      # org set, NO user → internal/background
    try:
        assert result_cache_tenancy() is None
    finally:
        reset_org_id(ot)


def test_tenancy_live_is_stable_and_scoped(monkeypatch):
    _enable(monkeypatch, roles=["viewer"])
    fp1 = _fingerprint(org="o1", user="u1")
    assert fp1 and fp1.startswith("rp:")
    # Same principal/policy → identical (so same-org same-role users still share the cache legitimately)…
    assert _fingerprint(org="o1", user="u1") == fp1
    assert _fingerprint(org="o1", user="u2") == fp1           # org-scoped policy: user doesn't change filters
    # …different org resolves to a different filter (org_id='o2') → different partition.
    assert _fingerprint(org="o2", user="u1") != fp1


def test_tenancy_partitions_owner_from_viewer(monkeypatch):
    _enable(monkeypatch, roles=["viewer"])
    viewer = _fingerprint(org="o1", user="u1")
    _enable(monkeypatch, roles=["owner"])                     # owner is unfiltered — must NOT share viewer's key
    owner = _fingerprint(org="o1", user="u1")
    assert viewer != owner


def test_tenancy_version_bumps_on_policy_edit(monkeypatch):
    _enable(monkeypatch, roles=["viewer"])
    before = _fingerprint(org="o1", user="u1")
    # Edit the policy predicate → the resolved-filter text (the "version") changes → old entries unreachable.
    monkeypatch.setattr(rp, "ROW_POLICIES", {"viewer": {"orders": "org_id = '{org_id}' AND active"}})
    after = _fingerprint(org="o1", user="u1")
    assert before != after


def test_tenancy_fails_closed_when_resolution_raises(monkeypatch):
    _enable(monkeypatch, roles=["viewer"])

    def _boom(_principal):
        raise RuntimeError("role store unreachable")

    monkeypatch.setattr(_resolver, "resolve_roles", _boom)
    a = _fingerprint(org="o1", user="u1")
    b = _fingerprint(org="o1", user="u1")
    # Not None (never the shared legacy key) and unique per call → a poison partition: never shared, never reused.
    assert a and a.startswith("rp-blocked:")
    assert b and b.startswith("rp-blocked:") and a != b


# ── End to end: the leak is actually closed ───────────────────────────────────

def test_one_principal_cannot_read_anothers_cached_rows(monkeypatch, mem_cache):
    _enable(monkeypatch, roles=["viewer"])
    sql = "SELECT id FROM orders"

    ta = _fingerprint(org="o1", user="u1")
    matcache.put_cache("c1", sql, _result(sql, [["o1-row"]]), tenancy=ta)

    tb = _fingerprint(org="o2", user="u2")               # different org → different filter → different key
    assert matcache.get_cached("c1", sql, tenancy=tb) is None      # principal B: MISS, no leak

    hit = matcache.get_cached("c1", sql, tenancy=ta)     # principal A reads back its own rows
    assert hit is not None and hit.rows == [["o1-row"]]


def test_owner_rows_do_not_leak_to_a_filtered_viewer(monkeypatch, mem_cache):
    sql = "SELECT id FROM orders"
    _enable(monkeypatch, roles=["owner"])                # owner runs first, caches the UNFILTERED set
    t_owner = _fingerprint(org="o1", user="admin")
    matcache.put_cache("c1", sql, _result(sql, [["r1"], ["r2"], ["r3"]]), tenancy=t_owner)

    _enable(monkeypatch, roles=["viewer"])               # a viewer must not be served the owner's full set
    t_viewer = _fingerprint(org="o1", user="u1")
    assert matcache.get_cached("c1", sql, tenancy=t_viewer) is None


def test_flag_off_cache_is_shared_byte_identical(monkeypatch, mem_cache):
    monkeypatch.delenv("AUGHOR_RBAC_ROW_POLICY", raising=False)
    sql = "SELECT id FROM orders"
    # Both principals resolve tenancy=None → legacy shared key → the pre-policy behaviour is unchanged.
    ta = _fingerprint(org="o1", user="u1")
    tb = _fingerprint(org="o2", user="u2")
    assert ta is None and tb is None
    matcache.put_cache("c1", sql, _result(sql, [["shared"]]), tenancy=ta)
    hit = matcache.get_cached("c1", sql, tenancy=tb)
    assert hit is not None and hit.rows == [["shared"]]
