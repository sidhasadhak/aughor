"use client";

/**
 * Settings ▸ Access, redone to `aughor-v2/CLARITY.md` (2026-10-12): four figures first — who you are here, the role
 * assignments, the function groups, how much of the call ledger carries a person — then what needs one (calls nobody
 * is attributed to, a function group with no members), then the roles beside the groups and the assignments beside the
 * measured users. Each role's permissions sit behind its *Details*; the built-in groups fold into one line.
 */
import { useCallback, useEffect, useState } from "react";
import {
  getAdminUsers, getMyAccess, getRoleCatalogue, getRoleAssignments, assignRole, revokeRole,
  getGroups, saveGroup, deleteGroup, getGroupMembers, addGroupMember, removeGroupMember,
  getLevelGrants, addLevelGrant, removeLevelGrant, getActionTriggers,
  type AdminUsers, type MyAccess, type RoleInfo, type RoleAssignment,
  type GroupsCatalogue, type LevelGrant, type ActionTrigger,
} from "@/lib/api";
import { Card, Chip, Empty, Figure, Figures, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, ROW, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Loading, ReadFailed } from "@/components/ui/states";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { formatCount, pct } from "@/lib/format";

import { Details, Pair, Stack, goTo, plural } from "./settings/parts";

/** The catalogue carries each role's display name (`label`) beside its id; the client type predates it. */
type Role = RoleInfo & { label?: string };

/** An id, a permission, a principal — set in mono, as a chip. */
function Code({ children, title }: { children: string; title?: string }) {
  return <Chip title={title}><span style={{ fontFamily: "var(--font-mono)" }}>{children}</span></Chip>;
}

/** The server's own reason for a refused write (`api.ts` `refused`) — never a guessed one. */
function refusal(e: unknown): string {
  return e instanceof Error ? e.message : "The change was refused";
}

/** A refused write's reason, in the card whose write it was. */
function Refused({ text }: { text: string | null }) {
  if (!text) return null;
  return <div role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", margin: "4px 0 8px" }}>{text}</div>;
}

const LIST_ROW = { ...ROW, gap: 10, padding: "7px 0", ...RULE, flexWrap: "nowrap" as const };

export function RolesPanel() {
  const [me, setMe] = useState<MyAccess | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
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
  // How many members each function group has — read for the figures and "Needs you"; null where the reader may not
  // see them (members are visible to role administrators only).
  const [memberCounts, setMemberCounts] = useState<Record<string, number | null>>({});
  const [newGroupId, setNewGroupId] = useState("");
  const [newGroupChannel, setNewGroupChannel] = useState("");
  const [newMember, setNewMember] = useState("");
  const [newSecurable, setNewSecurable] = useState("");
  const [newLevel, setNewLevel] = useState("subscribe");
  const [busy, setBusy] = useState(false);
  // One reason for the last refused write, shown in the card the write was made from.
  const [err, setErr] = useState<{ at: "groups" | "roster"; text: string } | null>(null);

  const canManage = !!me?.permissions.includes("admin.manage_roles");

  const countMembers = useCallback(async (gc: GroupsCatalogue | null) => {
    if (!gc?.groups.length) { setMemberCounts({}); return; }
    const counts = await Promise.all(gc.groups.map(g => getGroupMembers(g.id).then(m => m === null ? null : m.length)
      .catch(() => null)));
    setMemberCounts(Object.fromEntries(gc.groups.map((g, i) => [g.id, counts[i]])));
  }, []);

  // A failed read of who you are, the roles or the groups used to come back empty: the panel
  // then drew its read-only view — as if you lacked the permission — with no roles and no groups.
  const [loadFailed, setLoadFailed] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoadFailed(null);
    try {
      const [m, cat, au, gc, trg] = await Promise.all([
        getMyAccess(), getRoleCatalogue(), getAdminUsers(), getGroups(), getActionTriggers(),
      ]);
      setMe(m);
      setRoles(cat);
      setAdminUsers(au);
      setCatalogue(gc);
      setTriggers(trg);
      setAssignments(m?.permissions.includes("admin.manage_roles") ? await getRoleAssignments() : null);
      void countMembers(gc);
    } catch (e) {
      setLoadFailed(refusal(e));
    }
    setLoading(false);
  }, [countMembers]);

  useEffect(() => { load(); }, [load]);

  const refreshGroups = useCallback(async () => {
    try {
      const gc = await getGroups();
      setCatalogue(gc);
      void countMembers(gc);
    } catch (e) { setErr({ at: "groups", text: refusal(e) }); }
  }, [countMembers]);

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
    try {
      await saveGroup({ id, channel_trigger_id: newGroupChannel });
      setNewGroupId(""); setNewGroupChannel(""); await refreshGroups();
    } catch (e) { setErr({ at: "groups", text: refusal(e) }); }
    setBusy(false);
  };

  const onAddMember = async () => {
    if (!openGroup) return;
    const p = newMember.trim();
    if (!p) return;
    setBusy(true); setErr(null);
    try {
      const next = await addGroupMember(openGroup, p);
      setMembers(next);
      setMemberCounts(c => ({ ...c, [openGroup]: next.length }));
      setNewMember("");
    } catch (e) { setErr({ at: "groups", text: refusal(e) }); }
    setBusy(false);
  };

  const onAddGrant = async () => {
    if (!openGroup) return;
    const s = newSecurable.trim();
    if (!s) return;
    setBusy(true); setErr(null);
    try {
      await addLevelGrant(`group:${openGroup}`, s, newLevel);
      setNewSecurable(""); setGrants(await getLevelGrants({ principal: `group:${openGroup}` }));
    } catch (e) { setErr({ at: "groups", text: refusal(e) }); }
    setBusy(false);
  };

  const refreshRoster = useCallback(async () => {
    try { setAssignments(await getRoleAssignments()); } catch (e) { setErr({ at: "roster", text: refusal(e) }); }
  }, []);

  const onAssign = async () => {
    const u = newUser.trim();
    if (!u) return;
    setBusy(true); setErr(null);
    try {
      await assignRole(u, newRole);
      setNewUser(""); await refreshRoster();
    } catch (e) { setErr({ at: "roster", text: refusal(e) }); }
    setBusy(false);
  };

  const onRevoke = async (userId: string, role: string) => {
    setBusy(true); setErr(null);
    // A refused revoke used to read as done: the roster re-read, and the role stayed.
    try { await revokeRole(userId, role); } catch (e) { setErr({ at: "roster", text: refusal(e) }); }
    await refreshRoster();
    setBusy(false);
  };

  const onDeleteGroup = async (groupId: string) => {
    setBusy(true); setErr(null);
    try { await deleteGroup(groupId); if (openGroup === groupId) setOpenGroup(null); }
    catch (e) { setErr({ at: "groups", text: refusal(e) }); }
    await refreshGroups();
    setBusy(false);
  };

  const onRemoveMember = async (groupId: string, m: string) => {
    setBusy(true); setErr(null);
    try { await removeGroupMember(groupId, m); } catch (e) { setErr({ at: "groups", text: refusal(e) }); }
    const next = await getGroupMembers(groupId);
    setMembers(next);
    setMemberCounts(c => ({ ...c, [groupId]: next === null ? null : next.length }));
    setBusy(false);
  };

  const onRevokeGrant = async (groupId: string, gr: LevelGrant) => {
    setBusy(true); setErr(null);
    try { await removeLevelGrant(gr.principal, gr.securable, gr.level); } catch (e) { setErr({ at: "groups", text: refusal(e) }); }
    setGrants(await getLevelGrants({ principal: `group:${groupId}` }));
    setBusy(false);
  };

  if (loading) return <Loading what="roles" />;
  if (loadFailed !== null) return <ReadFailed what="the roles and groups" error={loadFailed} onRetry={load} />;

  // ── The figures and what needs a person ───────────────────────────────────────────────────────────────────────
  const roleName = (id: string) => roles.find(r => r.name === id)?.label
    ?? catalogue?.builtin_groups.find(g => g.id === id)?.name ?? id;
  const heldBy = (id: string) => (assignments ?? []).filter(a => a.role === id).length;
  const groups = catalogue?.groups ?? [];
  const empty = groups.filter(g => memberCounts[g.id] === 0);
  const triggerName = (id: string) => triggers.find(t => t.id === id)?.name ?? id;
  const au = adminUsers;
  const noOneAttributed = !!au && au.total_calls > 0 && au.coverage === 0;
  const byRole = assignments
    ? Object.entries(assignments.reduce<Record<string, number>>((n, a) => ({ ...n, [a.role]: (n[a.role] ?? 0) + 1 }), {}))
    : [];

  const openFromNeeds = (groupId: string) => {
    void openGroupDetails(groupId);
    goTo("access-groups");
  };

  return (
    <Stack testId="access-panel">
      <Figures testId="access-figures">
        <Figure label="You" testId="fig-you"
          value={(me?.roles ?? []).map(roleName).join(" · ") || "No role"}
          sub={<span style={ONE_LINE} title={`Recorded as ${me?.actor ?? "—"} · org ${me?.org_id ?? "—"}`}>
            {me?.user_id ?? me?.actor ?? "— (local)"}{me && !me.signed_in ? " · not signed in" : ""} · org {me?.org_id}
          </span>} />
        <Figure label="Role assignments" testId="fig-assignments"
          value={assignments ? formatCount(assignments.length) : "—"}
          sub={!assignments ? "visible to role administrators"
            : byRole.length ? byRole.map(([r, n]) => `${n} ${roleName(r)}`).join(" · ") : "the first identified user becomes Owner"} />
        <Figure label="Function groups" testId="fig-groups" value={formatCount(groups.length)}
          sub={`plus ${plural(catalogue?.builtin_groups.length ?? 0, "built-in group")}`} />
        <Figure label="Calls attributed" testId="fig-attributed"
          value={au && au.total_calls > 0 ? pct(au.coverage) : "—"} tone={noOneAttributed ? "amber" : undefined}
          sub={!au ? "not measured" : au.total_calls > 0 ? `of ${formatCount(au.total_calls)} recorded calls` : "no calls recorded yet"} />
      </Figures>

      <NeedsYou testId="access-needs" empty="Nothing needs you · every call carries a person and every group has members">
        {[
          noOneAttributed && (
            <NeedsRow key="attribution" testId="needs-attribution"
              title="No recorded call carries a user"
              detail={au!.oidc_configured
                ? "Identity is configured, but nothing has authenticated yet."
                : "Attribution starts once OIDC is configured and callers present tokens."} />
          ),
          ...empty.map(g => (
            <NeedsRow key={`empty-${g.id}`} testId="needs-empty-group"
              title={`${g.name} has no members`}
              actions={<Button size="xs" variant="secondary" onClick={() => openFromNeeds(g.id)}>Add members</Button>} />
          )),
        ]}
      </NeedsYou>

      <Pair>
        <Card label="Roles" testId="access-roles">
          {roles.map((r, i) => (
            <div key={r.name} style={{ padding: "7px 0", ...(i ? RULE : {}) }}>
              <div style={{ ...ROW, gap: 10, flexWrap: "nowrap" }}>
                <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500, minWidth: 64 }}>{roleName(r.name)}</span>
                {me?.roles.includes(r.name) && <Chip tone="accent">you</Chip>}
                <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, flex: 1 }} title={r.description}>{r.description}</span>
                {assignments && <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>held by {heldBy(r.name)}</span>}
              </div>
              <Details label={plural(r.permissions.length, "permission")}>
                <div style={{ ...ROW, gap: 5 }}>{r.permissions.map(p => <Code key={p}>{p}</Code>)}</div>
              </Details>
            </div>
          ))}
          {me && (
            <div style={{ ...RULE, paddingTop: 7 }}>
              <Details label={`Your permissions · ${me.permissions.length}`} testId="your-permissions">
                <div style={{ ...ROW, gap: 5 }}>
                  {me.permissions.length ? me.permissions.map(p => <Code key={p}>{p}</Code>) : <span>none</span>}
                </div>
              </Details>
            </div>
          )}
        </Card>

        <div id="access-groups" style={{ minWidth: 0 }}>
          <Card label="Groups">
            <Refused text={err?.at === "groups" ? err.text : null} />
            {/* Built-in groups — a default level per securable kind, never stored */}
            <div className="aug-fs-xs" style={{ ...ROW, gap: 6, ...MUTED, marginBottom: 6 }}>
              <span>Built-in, on everything:</span>
              {(catalogue?.builtin_groups ?? []).map(g => (
                <Chip key={g.id} title={g.description}>{g.name} · {g.levels?.["*"] ?? "—"}</Chip>
              ))}
            </div>

            {/* Function groups */}
            {groups.map(g => (
              <div key={g.id} style={{ ...RULE, padding: "7px 0" }}>
                <div style={{ ...ROW, gap: 10, flexWrap: "nowrap" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500 }}>{g.name}</div>
                    <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>
                      <span style={{ fontFamily: "var(--font-mono)" }}>group:{g.id}</span>
                      {" · "}{g.channel_trigger_id ? `→ ${triggerName(g.channel_trigger_id)}` : "no channel"}
                      {memberCounts[g.id] != null && <> · {plural(memberCounts[g.id]!, "member")}</>}
                    </div>
                  </div>
                  <Button variant="ghost" size="xs" aria-expanded={openGroup === g.id}
                    onClick={() => openGroup === g.id ? setOpenGroup(null) : openGroupDetails(g.id)}
                    title={openGroup === g.id ? "Collapse" : "Members and grants"}>
                    {openGroup === g.id ? "Close" : "Open"}
                  </Button>
                  {canManage && (
                    <Button variant="ghost" size="xs" disabled={busy} onClick={() => void onDeleteGroup(g.id)}
                      title="Delete this group, its memberships and its grants">Delete</Button>
                  )}
                </div>

                {openGroup === g.id && (
                  <div style={{ padding: "8px 0 2px", display: "flex", flexDirection: "column", gap: 8 }}>
                    {/* Members */}
                    <div style={{ ...ROW, gap: 6 }}>
                      <span className="aug-fs-xs" style={MUTED}>Members</span>
                      {members === null
                        ? <span className="aug-fs-xs" style={MUTED}>visible to role administrators</span>
                        : members.length === 0
                          ? <span className="aug-fs-xs" style={MUTED}>none yet</span>
                          : members.map(m => (
                            <span key={m} style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
                              <Code>{m}</Code>
                              {canManage && (
                                <Button variant="ghost" size="xs" disabled={busy} onClick={() => void onRemoveMember(g.id, m)}
                                  title="Remove from the group" aria-label={`Remove ${m}`}>×</Button>
                              )}
                            </span>
                          ))}
                    </div>
                    {canManage && (
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <Input placeholder="user:alice@acme.com or agent:ua_…" aria-label={`Add a member to ${g.name}`}
                          value={newMember} onChange={e => setNewMember(e.target.value)}
                          onKeyDown={e => { if (e.key === "Enter") onAddMember(); }} style={{ flex: 1 }} />
                        <Button variant="default" size="sm" onClick={onAddMember} disabled={busy || !newMember.trim()}>Add member</Button>
                      </div>
                    )}

                    {/* Grants by securable */}
                    <div style={{ ...ROW, gap: 6 }}>
                      <span className="aug-fs-xs" style={MUTED}>Grants</span>
                      {grants === null
                        ? <span className="aug-fs-xs" style={MUTED}>visible to role administrators</span>
                        : grants.length === 0
                          ? <span className="aug-fs-xs" style={MUTED}>none yet</span>
                          : grants.map(gr => (
                            <span key={`${gr.securable}:${gr.level}`} style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
                              <Code>{`${gr.level} · ${gr.securable}`}</Code>
                              {canManage && (
                                <Button variant="ghost" size="xs" disabled={busy} onClick={() => void onRevokeGrant(g.id, gr)}
                                  title="Revoke this grant" aria-label={`Revoke ${gr.level} on ${gr.securable}`}>×</Button>
                              )}
                            </span>
                          ))}
                    </div>
                    {canManage && (
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <Input placeholder="securable (e.g. domain:supply-chain, promise:dispatch-24h)"
                          value={newSecurable} onChange={e => setNewSecurable(e.target.value)}
                          onKeyDown={e => { if (e.key === "Enter") onAddGrant(); }} style={{ flex: 1 }} />
                        <SelectField value={newLevel} onChange={e => setNewLevel(e.target.value)} style={{ cursor: "pointer", width: 120 }}>
                          {(catalogue?.ladder ?? []).map(l => <option key={l} value={l}>{l}</option>)}
                        </SelectField>
                        <Button variant="default" size="sm" onClick={onAddGrant} disabled={busy || !newSecurable.trim()}>Grant</Button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {groups.length === 0 && !canManage && (
              <Empty>No function groups yet — an owner creates them, and each carries members, a channel and its grants.</Empty>
            )}

            {/* Create a function group */}
            {canManage && (
              <div style={{ display: "flex", gap: 8, alignItems: "center", ...RULE, paddingTop: 10 }}>
                <Input placeholder="new group id (e.g. supply-chain)"
                  value={newGroupId} onChange={e => setNewGroupId(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") onCreateGroup(); }} style={{ flex: 1 }} />
                <SelectField value={newGroupChannel} onChange={e => setNewGroupChannel(e.target.value)} style={{ cursor: "pointer", width: 160 }}>
                  <option value="">no channel yet</option>
                  {triggers.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                </SelectField>
                <Button variant="default" size="sm" onClick={onCreateGroup} disabled={busy || !newGroupId.trim()}>Create group</Button>
              </div>
            )}
          </Card>
        </div>
      </Pair>

      <Pair>
        {/* Roster management (only when the caller can manage roles) */}
        <Card label="Role assignments">
          {!canManage ? (
            <Empty>
              Managing roles needs the <Code>admin.manage_roles</Code> permission — ask an Owner to grant it.
            </Empty>
          ) : (
            <>
              <Refused text={err?.at === "roster" ? err.text : null} />
              {/* Add a member */}
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                <Input
                  placeholder="user id (e.g. alice@acme.com)"
                  value={newUser}
                  onChange={e => setNewUser(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") onAssign(); }}
                  style={{ flex: 1 }}
                />
                <SelectField value={newRole} onChange={e => setNewRole(e.target.value)} style={{ cursor: "pointer", width: 120 }}>
                  {roles.map(r => <option key={r.name} value={r.name}>{roleName(r.name)}</option>)}
                </SelectField>
                <Button variant="default" size="sm" onClick={onAssign} disabled={busy || !newUser.trim()}>
                  Assign
                </Button>
              </div>
              {/* Roster */}
              {(assignments && assignments.length > 0) ? (
                assignments.map(a => (
                  <div key={`${a.user_id}:${a.role}`} style={LIST_ROW}>
                    <span className="aug-fs-sm" style={{ flex: 1, color: "var(--t1)", ...ONE_LINE }}>{a.user_id}</span>
                    <Chip>{roleName(a.role)}</Chip>
                    <Button variant="ghost" size="xs" onClick={() => onRevoke(a.user_id, a.role)} disabled={busy}
                      title="Revoke this role">Revoke</Button>
                  </div>
                ))
              ) : (
                <Empty>No explicit assignments yet — the org&apos;s first identified user becomes Owner automatically.</Empty>
              )}
            </>
          )}
        </Card>

        {/* VA-10 — users, measured. Metadata only by design (§6.4): counts and costs
            answer "is this deployment healthy"; reading anyone's prompts stays behind
            the audited break-glass and has no door here. */}
        {au && (
          <Card label="Users · measured" right={plural(au.users.length, "user")}>
            {au.users.length === 0 ? (
              <Empty>No identified users yet — the ledger and the role table are both empty of names.</Empty>
            ) : (
              au.users.map(u => (
                <div key={u.user_id} style={LIST_ROW}>
                  <span className="aug-fs-sm" style={{ flex: 1, color: "var(--t1)", ...ONE_LINE }}>{u.user_id}</span>
                  {u.roles.map(r => <Chip key={r}>{roleName(r)}</Chip>)}
                  <span className="aug-fs-xs" style={{ color: "var(--t2)", ...NUM, whiteSpace: "nowrap" }}>
                    {plural(u.calls, "call")}{u.cost_usd > 0 && <> · ${u.cost_usd.toFixed(2)}{!u.cost_is_complete && "+"}</>}
                  </span>
                </div>
              ))
            )}
            {au.total_calls > 0 && au.coverage > 0 && (
              <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 6 }}>
                {Math.round(au.coverage * 100)}% of {formatCount(au.total_calls)} calls attributed
                {au.unattributed_calls > 0 && <> · {formatCount(au.unattributed_calls)} carry no user and are not shown as a blank cohort</>}
              </div>
            )}
          </Card>
        )}
      </Pair>
    </Stack>
  );
}
