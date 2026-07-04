"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getMyAccess, getRoleCatalogue, getRoleAssignments, assignRole, revokeRole,
  type MyAccess, type RoleInfo, type RoleAssignment,
} from "@/lib/api";

const ROLE_TINT: Record<string, string> = {
  owner: "var(--blue4)",
  analyst: "var(--t2)",
  viewer: "var(--t3)",
};

function Chip({ label, tint }: { label: string; tint?: string }) {
  return (
    <span style={{
      fontSize: 10, fontFamily: "var(--font-mono, monospace)", padding: "2px 7px",
      borderRadius: "var(--r2)", background: "var(--bg-2)",
      border: `1px solid var(--b1)`, color: tint || "var(--t2)", whiteSpace: "nowrap",
    }}>{label}</span>
  );
}

export function RolesPanel() {
  const [me, setMe] = useState<MyAccess | null>(null);
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [assignments, setAssignments] = useState<RoleAssignment[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [newUser, setNewUser] = useState("");
  const [newRole, setNewRole] = useState("viewer");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canManage = !!me?.permissions.includes("admin.manage_roles");

  const load = useCallback(async () => {
    const [m, cat] = await Promise.all([getMyAccess(), getRoleCatalogue()]);
    setMe(m);
    setRoles(cat);
    setAssignments(m?.permissions.includes("admin.manage_roles") ? await getRoleAssignments() : null);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const refreshRoster = useCallback(async () => {
    setAssignments(await getRoleAssignments());
  }, []);

  const onAssign = async () => {
    const u = newUser.trim();
    if (!u) return;
    setBusy(true); setErr(null);
    const res = await assignRole(u, newRole);
    if (!res) setErr("Could not assign role — check that you have permission.");
    else { setNewUser(""); await refreshRoster(); }
    setBusy(false);
  };

  const onRevoke = async (userId: string, role: string) => {
    setBusy(true); setErr(null);
    await revokeRole(userId, role);
    await refreshRoster();
    setBusy(false);
  };

  if (loading) return <div style={{ fontSize: 12, color: "var(--t3)" }}>Loading…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 620 }}>

      {/* Your access */}
      <div>
        <div className="aug-label" style={{ marginBottom: 10 }}>Your access</div>
        <div style={{
          padding: "12px 14px", borderRadius: "var(--r3)", background: "var(--bg-2)",
          border: "1px solid var(--b1)", display: "flex", flexDirection: "column", gap: 8,
        }}>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 11, color: "var(--t3)" }}>
            <span>User&nbsp;<span style={{ color: "var(--t1)" }}>{me?.user_id ?? "— (local)"}</span></span>
            <span>Org&nbsp;<span style={{ color: "var(--t1)", fontFamily: "var(--font-mono, monospace)" }}>{me?.org_id}</span></span>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 11, color: "var(--t3)" }}>Roles</span>
            {(me?.roles ?? []).map(r => <Chip key={r} label={r} tint={ROLE_TINT[r]} />)}
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "flex-start", flexWrap: "wrap" }}>
            <span style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>Permissions</span>
            {(me?.permissions ?? []).map(p => <Chip key={p} label={p} />)}
          </div>
        </div>
      </div>

      {/* Role catalogue */}
      <div>
        <div className="aug-label" style={{ marginBottom: 10 }}>Roles</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {roles.map(r => (
            <div key={r.name} style={{
              padding: "10px 14px", borderRadius: "var(--r3)", background: "var(--bg-2)",
              border: "1px solid var(--b1)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <Chip label={r.name} tint={ROLE_TINT[r.name]} />
                <span style={{ fontSize: 11, color: "var(--t3)" }}>{r.description}</span>
              </div>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 6 }}>
                {r.permissions.map(p => <Chip key={p} label={p} />)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Roster management (only when the caller can manage roles) */}
      <div>
        <div className="aug-label" style={{ marginBottom: 10 }}>Members &amp; role assignments</div>
        {!canManage ? (
          <div style={{ fontSize: 11, color: "var(--t3)", lineHeight: 1.5 }}>
            You don&apos;t have permission to manage roles in this org. Ask an owner to grant
            you the <Chip label="admin.manage_roles" /> permission.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {/* Add a member */}
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                className="aug-input"
                placeholder="user id (e.g. alice@acme.com)"
                value={newUser}
                onChange={e => setNewUser(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") onAssign(); }}
                style={{ flex: 1 }}
              />
              <select className="aug-input" value={newRole} onChange={e => setNewRole(e.target.value)} style={{ cursor: "pointer", width: 120 }}>
                {roles.map(r => <option key={r.name} value={r.name}>{r.name}</option>)}
              </select>
              <button className="aug-btn aug-btn-primary" onClick={onAssign} disabled={busy || !newUser.trim()}>
                Assign
              </button>
            </div>
            {err && <div style={{ fontSize: 11, color: "var(--red3, #e5484d)" }}>{err}</div>}

            {/* Roster */}
            {(assignments && assignments.length > 0) ? (
              <div style={{ borderRadius: "var(--r3)", border: "1px solid var(--b1)", overflow: "hidden" }}>
                {assignments.map((a, i) => (
                  <div key={`${a.user_id}:${a.role}`} style={{
                    display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
                    background: "var(--bg-2)",
                    borderTop: i === 0 ? "none" : "1px solid var(--b1)",
                  }}>
                    <span style={{ flex: 1, fontSize: 12, color: "var(--t1)" }}>{a.user_id}</span>
                    <Chip label={a.role} tint={ROLE_TINT[a.role]} />
                    <button
                      className="aug-btn aug-btn-sm aug-btn-ghost"
                      onClick={() => onRevoke(a.user_id, a.role)}
                      disabled={busy}
                      title="Revoke this role"
                    >Revoke</button>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 11, color: "var(--t3)" }}>
                No explicit assignments yet — the org&apos;s first identified user becomes owner automatically.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
