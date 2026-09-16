"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getAdminUsers, getMyAccess, getRoleCatalogue, getRoleAssignments, assignRole, revokeRole,
  getGroups, saveGroup, deleteGroup, getGroupMembers, addGroupMember, removeGroupMember,
  getLevelGrants, addLevelGrant, removeLevelGrant, getActionTriggers,
  type AdminUsers, type MyAccess, type RoleInfo, type RoleAssignment,
  type GroupsCatalogue, type LevelGrant, type ActionTrigger,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

const ROLE_TINT: Record<string, string> = {
  owner: "var(--blue4)",
  analyst: "var(--t2)",
  viewer: "var(--t3)",
};

function Chip({ label, tint }: { label: string; tint?: string }) {
  return (
    <span style={{
      fontSize: 11, fontFamily: "var(--font-mono, monospace)", padding: "2px 7px",
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
  // VA-10 — the measured view: who the ledger and the role table know, with usage.
  const [adminUsers, setAdminUsers] = useState<AdminUsers | null>(null);
  // HB-1 — groups, members and grants-by-securable (the routing half).
  const [catalogue, setCatalogue] = useState<GroupsCatalogue | null>(null);
  const [triggers, setTriggers] = useState<ActionTrigger[]>([]);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [members, setMembers] = useState<string[] | null>(null);
  const [grants, setGrants] = useState<LevelGrant[] | null>(null);
  const [newGroupId, setNewGroupId] = useState("");
  const [newGroupChannel, setNewGroupChannel] = useState("");
  const [newMember, setNewMember] = useState("");
  const [newSecurable, setNewSecurable] = useState("");
  const [newLevel, setNewLevel] = useState("subscribe");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canManage = !!me?.permissions.includes("admin.manage_roles");

  const load = useCallback(async () => {
    const [m, cat, au, gc, trg] = await Promise.all([
      getMyAccess(), getRoleCatalogue(), getAdminUsers(), getGroups(), getActionTriggers(),
    ]);
    setMe(m);
    setRoles(cat);
    setAdminUsers(au);
    setCatalogue(gc);
    setTriggers(trg);
    setAssignments(m?.permissions.includes("admin.manage_roles") ? await getRoleAssignments() : null);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const refreshGroups = useCallback(async () => {
    setCatalogue(await getGroups());
  }, []);

  const openGroupDetails = useCallback(async (groupId: string) => {
    setOpenGroup(groupId);
    const [m, g] = await Promise.all([
      getGroupMembers(groupId),
      getLevelGrants({ principal: `group:${groupId}` }),
    ]);
    setMembers(m);
    setGrants(g);
  }, []);

  const onCreateGroup = async () => {
    const id = newGroupId.trim().toLowerCase();
    if (!id) return;
    setBusy(true); setErr(null);
    const g = await saveGroup({ id, channel_trigger_id: newGroupChannel });
    if (!g) setErr("Could not create the group — a group id is a lowercase slug, and creating one needs role administration.");
    else { setNewGroupId(""); setNewGroupChannel(""); await refreshGroups(); }
    setBusy(false);
  };

  const onAddMember = async () => {
    if (!openGroup) return;
    const p = newMember.trim();
    if (!p) return;
    setBusy(true); setErr(null);
    const res = await addGroupMember(openGroup, p);
    if (!res) setErr("Could not add the member — it must be a user:… or agent:… principal.");
    else { setNewMember(""); setMembers(res); }
    setBusy(false);
  };

  const onAddGrant = async () => {
    if (!openGroup) return;
    const s = newSecurable.trim();
    if (!s) return;
    setBusy(true); setErr(null);
    const res = await addLevelGrant(`group:${openGroup}`, s, newLevel);
    if (!res) setErr("Could not add the grant — a securable is kind:id (e.g. domain:supply-chain).");
    else { setNewSecurable(""); setGrants(await getLevelGrants({ principal: `group:${openGroup}` })); }
    setBusy(false);
  };

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

      {/* HB-1 — groups: the built-in defaults, and the org's function groups with
          members (people AND agents), a channel, and grants by securable. */}
      {catalogue && (
        <div>
          <div className="aug-label" style={{ marginBottom: 10 }}>Groups</div>

          {/* Built-in groups — a default level per securable kind, never stored */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
            {catalogue.builtin_groups.map(g => (
              <span key={g.id} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Chip label={g.name} tint={ROLE_TINT[g.id]} />
                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                  {g.levels?.["*"] ?? "—"} on everything
                </span>
              </span>
            ))}
          </div>

          {/* Function groups */}
          {catalogue.groups.length > 0 && (
            <div style={{ borderRadius: "var(--r3)", border: "1px solid var(--b1)", overflow: "hidden", marginBottom: 10 }}>
              {catalogue.groups.map((g, i) => (
                <div key={g.id} style={{ background: "var(--bg-2)", borderTop: i === 0 ? "none" : "1px solid var(--b1)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px" }}>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openGroup === g.id ? setOpenGroup(null) : openGroupDetails(g.id)}
                      style={{ flex: 1, justifyContent: "flex-start", color: "var(--t1)" }}
                      title={openGroup === g.id ? "Collapse" : "Members and grants"}
                    >
                      {g.name}&nbsp;<span className="aug-fs-xs" style={{ color: "var(--t3)" }}>group:{g.id}</span>
                    </Button>
                    <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                      {g.channel_trigger_id
                        ? `→ ${triggers.find(t => t.id === g.channel_trigger_id)?.name ?? g.channel_trigger_id}`
                        : "no channel"}
                    </span>
                    {canManage && (
                      <Button variant="ghost" size="xs" disabled={busy}
                        onClick={async () => { setBusy(true); await deleteGroup(g.id); if (openGroup === g.id) setOpenGroup(null); await refreshGroups(); setBusy(false); }}
                        title="Delete this group, its memberships and its grants"
                      >Delete</Button>
                    )}
                  </div>

                  {openGroup === g.id && (
                    <div style={{ padding: "0 12px 10px", display: "flex", flexDirection: "column", gap: 8 }}>
                      {/* Members */}
                      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Members</span>
                        {members === null
                          ? <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>visible to role administrators</span>
                          : members.length === 0
                            ? <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>none yet</span>
                            : members.map(m => (
                              <span key={m} style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
                                <Chip label={m} />
                                {canManage && (
                                  <Button variant="ghost" size="xs" disabled={busy}
                                    onClick={async () => { setBusy(true); await removeGroupMember(g.id, m); setMembers(await getGroupMembers(g.id)); setBusy(false); }}
                                    title="Remove from the group"
                                  >×</Button>
                                )}
                              </span>
                            ))}
                      </div>
                      {canManage && (
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <input className="aug-input" placeholder="user:alice@acme.com or agent:ua_…"
                            value={newMember} onChange={e => setNewMember(e.target.value)}
                            onKeyDown={e => { if (e.key === "Enter") onAddMember(); }} style={{ flex: 1 }} />
                          <Button variant="default" size="sm" onClick={onAddMember} disabled={busy || !newMember.trim()}>Add member</Button>
                        </div>
                      )}

                      {/* Grants by securable */}
                      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Grants</span>
                        {grants === null
                          ? <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>visible to role administrators</span>
                          : grants.length === 0
                            ? <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>none yet</span>
                            : grants.map(gr => (
                              <span key={`${gr.securable}:${gr.level}`} style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
                                <Chip label={`${gr.level} · ${gr.securable}`} />
                                {canManage && (
                                  <Button variant="ghost" size="xs" disabled={busy}
                                    onClick={async () => { setBusy(true); await removeLevelGrant(gr.principal, gr.securable, gr.level); setGrants(await getLevelGrants({ principal: `group:${g.id}` })); setBusy(false); }}
                                    title="Revoke this grant"
                                  >×</Button>
                                )}
                              </span>
                            ))}
                      </div>
                      {canManage && (
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <input className="aug-input" placeholder="securable (e.g. domain:supply-chain, promise:dispatch-24h)"
                            value={newSecurable} onChange={e => setNewSecurable(e.target.value)}
                            onKeyDown={e => { if (e.key === "Enter") onAddGrant(); }} style={{ flex: 1 }} />
                          <select className="aug-input" value={newLevel} onChange={e => setNewLevel(e.target.value)} style={{ cursor: "pointer", width: 120 }}>
                            {catalogue.ladder.map(l => <option key={l} value={l}>{l}</option>)}
                          </select>
                          <Button variant="default" size="sm" onClick={onAddGrant} disabled={busy || !newSecurable.trim()}>Grant</Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Create a function group */}
          {canManage && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input className="aug-input" placeholder="new group id (e.g. supply-chain)"
                value={newGroupId} onChange={e => setNewGroupId(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") onCreateGroup(); }} style={{ flex: 1 }} />
              <select className="aug-input" value={newGroupChannel} onChange={e => setNewGroupChannel(e.target.value)} style={{ cursor: "pointer", width: 180 }}>
                <option value="">no channel yet</option>
                {triggers.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <Button variant="default" size="sm" onClick={onCreateGroup} disabled={busy || !newGroupId.trim()}>Create group</Button>
            </div>
          )}
          {catalogue.groups.length === 0 && !canManage && (
            <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
              No function groups yet — an owner creates them, and each carries members, a channel and its grants.
            </div>
          )}
        </div>
      )}

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
              <Button variant="default" size="sm" onClick={onAssign} disabled={busy || !newUser.trim()}>
                Assign
              </Button>
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
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => onRevoke(a.user_id, a.role)}
                      disabled={busy}
                      title="Revoke this role"
                    >Revoke</Button>
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

      {/* VA-10 — users, measured. Metadata only by design (§6.4): counts and costs
          answer "is this deployment healthy"; reading anyone's prompts stays behind
          the audited break-glass and has no door here. */}
      {adminUsers && (
        <div>
          <div className="aug-label" style={{ marginBottom: 10 }}>Users · measured</div>
          {adminUsers.total_calls > 0 && adminUsers.coverage === 0 && (
            <div className="aug-fs-xs" style={{ color: "var(--amb4, #f59e0b)", marginBottom: 8, lineHeight: 1.5 }}>
              None of the {adminUsers.total_calls} recorded calls carry a user —{" "}
              {adminUsers.oidc_configured
                ? "identity is configured but nothing authenticated yet."
                : "identity attribution starts once OIDC is configured and callers present tokens."}
            </div>
          )}
          {adminUsers.users.length === 0 ? (
            <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
              No identified users yet — the ledger and the role table are both empty of names.
            </div>
          ) : (
            <div style={{ borderRadius: "var(--r3)", border: "1px solid var(--b1)", overflow: "hidden" }}>
              {adminUsers.users.map((u, i) => (
                <div key={u.user_id} style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
                  background: "var(--bg-2)",
                  borderTop: i === 0 ? "none" : "1px solid var(--b1)",
                }}>
                  <span className="aug-fs-sm" style={{ flex: 1, color: "var(--t1)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.user_id}</span>
                  {u.roles.map(r => <Chip key={r} label={r} tint={ROLE_TINT[r]} />)}
                  <span className="aug-fs-xs" style={{ color: "var(--t2)", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
                    {u.calls} calls{u.cost_usd > 0 && <> · ${u.cost_usd.toFixed(2)}{!u.cost_is_complete && "+"}</>}
                  </span>
                </div>
              ))}
            </div>
          )}
          {adminUsers.total_calls > 0 && adminUsers.coverage > 0 && (
            <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 6 }}>
              {Math.round(adminUsers.coverage * 100)}% of {adminUsers.total_calls} calls attributed
              {adminUsers.unattributed_calls > 0 && <> · {adminUsers.unattributed_calls} carry no user and are not shown as a blank cohort</>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
