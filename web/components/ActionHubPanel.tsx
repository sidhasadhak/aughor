"use client";

import { useEffect, useState } from "react";

import { API_BASE as BASE } from "@/lib/config";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Trigger {
  id:         string;
  name:       string;
  type:       "webhook" | "slack" | "jira";
  url:        string;
  headers:    Record<string, string>;
  enabled:    boolean;
  channel?:   string;
  project?:   string;
  issue_type?: string;
}

interface ActionLog {
  id:               string;
  trigger_id:       string;
  trigger_name:     string;
  investigation_id: string;
  rec_index:        number;
  recommendation:   string;
  status:           "ok" | "failed" | "timeout";
  http_status:      number | null;
  error:            string | null;
  fired_at:         string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const TYPE_LABELS: Record<string, string> = {
  webhook:    "Webhook",
  slack:      "Slack",
  jira:       "Jira",
};

// ── TriggerForm ───────────────────────────────────────────────────────────────

function TriggerForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: Trigger;
  onSave: (t: Partial<Trigger>) => Promise<void>;
  onCancel: () => void;
}) {
  const [name,      setName]    = useState(initial?.name      ?? "");
  const [type,      setType]    = useState<"webhook"|"slack"|"jira">(initial?.type ?? "webhook");
  const [url,       setUrl]     = useState(initial?.url       ?? "");
  const [channel,   setChannel] = useState(initial?.channel   ?? "");
  const [project,   setProject] = useState(initial?.project   ?? "");
  const [issueType, setIssue]   = useState(initial?.issue_type ?? "Task");
  const [saving,    setSaving]  = useState(false);
  const [error,     setError]   = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await onSave({ name, type, url, channel: channel || undefined, project: project || undefined, issue_type: issueType || undefined });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 5 }}>Name</div>
        <input value={name} onChange={e => setName(e.target.value)} required placeholder="My Slack Webhook" className="aug-input" />
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 5 }}>Type</div>
        <select value={type} onChange={e => setType(e.target.value as typeof type)} className="aug-input">
          <option value="webhook">Webhook (generic)</option>
          <option value="slack">Slack incoming webhook</option>
          <option value="jira">Jira (create issue)</option>
        </select>
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 5 }}>
          {type === "jira" ? "Jira base URL" : "Webhook URL"}
        </div>
        <input value={url} onChange={e => setUrl(e.target.value)} required
          placeholder={type === "slack" ? "https://hooks.slack.com/services/…" : type === "jira" ? "https://yourorg.atlassian.net/rest/api/3/issue" : "https://…"}
          className="aug-input" style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
        />
      </div>
      {type === "slack" && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 5 }}>Channel (optional)</div>
          <input value={channel} onChange={e => setChannel(e.target.value)} placeholder="#general" className="aug-input" />
        </div>
      )}
      {type === "jira" && (
        <>
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 5 }}>Project key</div>
            <input value={project} onChange={e => setProject(e.target.value)} placeholder="OPS" className="aug-input" />
          </div>
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 5 }}>Issue type</div>
            <input value={issueType} onChange={e => setIssue(e.target.value)} placeholder="Task" className="aug-input" />
          </div>
        </>
      )}
      {error && <div style={{ fontSize: 11, color: "var(--red4)" }}>{error}</div>}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button type="button" onClick={onCancel} className="aug-btn aug-btn-ghost aug-btn-sm">Cancel</button>
        <button type="submit" disabled={saving} className="aug-btn aug-btn-primary aug-btn-sm">
          {saving ? "Saving…" : initial ? "Update" : "Create"}
        </button>
      </div>
    </form>
  );
}

// ── ActionHubPanel ────────────────────────────────────────────────────────────

export function ActionHubPanel() {
  const [triggers,  setTriggers]  = useState<Trigger[]>([]);
  const [logs,      setLogs]      = useState<ActionLog[]>([]);
  const [view,      setView]      = useState<"triggers" | "logs">("triggers");
  const [showForm,  setShowForm]  = useState(false);
  const [editing,   setEditing]   = useState<Trigger | undefined>(undefined);
  const [testing,   setTesting]   = useState<string | null>(null);
  const [testResult,setTestResult]= useState<Record<string, string>>({});

  const reload = async () => {
    const [tr, lr] = await Promise.all([
      fetch(`${BASE}/actions/triggers`).then(r => r.json()).catch(() => ({ triggers: [] })),
      fetch(`${BASE}/actions/logs?limit=50`).then(r => r.json()).catch(() => ({ logs: [] })),
    ]);
    setTriggers(tr.triggers ?? []);
    setLogs(lr.logs ?? []);
  };

  useEffect(() => { reload(); }, []);

  const handleSave = async (data: Partial<Trigger>) => {
    const method = editing ? "PUT" : "POST";
    const url    = editing ? `${BASE}/actions/triggers/${editing.id}` : `${BASE}/actions/triggers`;
    const resp   = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail ?? "Save failed");
    setShowForm(false);
    setEditing(undefined);
    reload();
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("Delete this trigger? This cannot be undone.")) return;
    try {
      const resp = await fetch(`${BASE}/actions/triggers/${id}`, { method: "DELETE" });
      if (!resp.ok) throw new Error(`delete failed (${resp.status})`);
    } catch (e) {
      setTestResult(prev => ({ ...prev, [id]: `✗ ${e instanceof Error ? e.message : "delete failed"}` }));
    } finally {
      reload();
    }
  };

  const handleToggle = async (t: Trigger) => {
    try {
      const resp = await fetch(`${BASE}/actions/triggers/${t.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...t, enabled: !t.enabled }),
      });
      if (!resp.ok) throw new Error(`update failed (${resp.status})`);
    } catch (e) {
      setTestResult(prev => ({ ...prev, [t.id]: `✗ ${e instanceof Error ? e.message : "update failed"}` }));
    } finally {
      reload();
    }
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    setTestResult(prev => ({ ...prev, [id]: "…" }));
    try {
      const resp = await fetch(`${BASE}/actions/triggers/${id}/test`, { method: "POST" });
      const data = await resp.json();
      setTestResult(prev => ({
        ...prev,
        [id]: data.status === "ok" ? `✓ ${data.http_status}` : `✗ ${data.error || data.http_status}`,
      }));
    } catch (e) {
      // Without this, a network error left the button wedged on "…" forever.
      setTestResult(prev => ({ ...prev, [id]: `✗ ${e instanceof Error ? e.message : "unreachable"}` }));
    } finally {
      setTesting(null);
    }
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 20px", height: 44, borderBottom: "1px solid var(--b1)", background: "var(--bg-1)", flexShrink: 0 }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
        <span style={{ fontSize: 13, fontWeight: 500 }}>Action Hub</span>
        <div style={{ display: "flex", gap: 4, marginLeft: 12 }}>
          {(["triggers", "logs"] as const).map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              padding: "3px 10px", borderRadius: "var(--r2)", fontSize: 11, cursor: "pointer",
              background: view === v ? "var(--bg-sel)" : "transparent",
              border: `1px solid ${view === v ? "var(--blue2)" : "var(--b1)"}`,
              color: view === v ? "var(--blue5)" : "var(--t3)",
            }}>
              {v.charAt(0).toUpperCase() + v.slice(1)}
              {v === "triggers" && triggers.length > 0 && (
                <span style={{ marginLeft: 5, fontSize: 9, color: "var(--t4)" }}>{triggers.length}</span>
              )}
              {v === "logs" && logs.length > 0 && (
                <span style={{ marginLeft: 5, fontSize: 9, color: "var(--t4)" }}>{logs.length}</span>
              )}
            </button>
          ))}
        </div>
        {view === "triggers" && !showForm && (
          <button
            onClick={() => { setEditing(undefined); setShowForm(true); }}
            className="aug-btn aug-btn-primary aug-btn-sm"
            style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 5 }}
          >
            + New trigger
          </button>
        )}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>

        {/* Create / edit form */}
        {view === "triggers" && showForm && (
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: "var(--r3)", padding: 16, marginBottom: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", marginBottom: 12 }}>
              {editing ? "Edit trigger" : "New trigger"}
            </div>
            <TriggerForm
              initial={editing}
              onSave={handleSave}
              onCancel={() => { setShowForm(false); setEditing(undefined); }}
            />
          </div>
        )}

        {/* Triggers list */}
        {view === "triggers" && (
          triggers.length === 0 && !showForm ? (
            <div style={{ padding: "48px 0", textAlign: "center" }}>
              <div style={{ fontSize: 12, color: "var(--t3)", marginBottom: 8 }}>No action triggers configured.</div>
              <div style={{ fontSize: 11, color: "var(--t4)", lineHeight: 1.6, maxWidth: 340, margin: "0 auto" }}>
                Create a trigger to fire webhooks, Slack messages, or Jira tickets when you action an investigation recommendation.
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {triggers.map(t => (
                <div key={t.id} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 14px",
                  background: "var(--bg-2)", border: "1px solid var(--b1)",
                  borderRadius: "var(--r2)", opacity: t.enabled ? 1 : 0.5,
                }}>
                  {/* Type badge */}
                  <span style={{
                    padding: "2px 7px", borderRadius: 2, fontSize: 10, fontWeight: 600,
                    background: t.type === "slack" ? "var(--grn1)" : t.type === "jira" ? "var(--blue1)" : "var(--bg-3)",
                    border: `1px solid ${t.type === "slack" ? "var(--grn2)" : t.type === "jira" ? "var(--blue2)" : "var(--b2)"}`,
                    color: t.type === "slack" ? "var(--grn5)" : t.type === "jira" ? "var(--blue5)" : "var(--t2)",
                  }}>
                    {TYPE_LABELS[t.type] ?? t.type}
                  </span>
                  {/* Name + URL */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)" }}>{t.name}</div>
                    <div style={{ fontSize: 10, color: "var(--t4)", fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t.url.slice(0, 60)}{t.url.length > 60 ? "…" : ""}
                    </div>
                  </div>
                  {/* Test result */}
                  {testResult[t.id] && (
                    <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: testResult[t.id].startsWith("✓") ? "var(--grn4)" : "var(--red4)" }}>
                      {testResult[t.id]}
                    </span>
                  )}
                  {/* Actions */}
                  <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                    <button
                      onClick={() => handleTest(t.id)}
                      disabled={testing === t.id}
                      className="aug-btn aug-btn-ghost aug-btn-sm"
                      title="Test fire"
                    >
                      {testing === t.id ? "…" : "Test"}
                    </button>
                    <button
                      onClick={() => handleToggle(t)}
                      className="aug-btn aug-btn-ghost aug-btn-sm"
                      title={t.enabled ? "Disable" : "Enable"}
                    >
                      {t.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                      onClick={() => { setEditing(t); setShowForm(true); }}
                      className="aug-btn aug-btn-ghost aug-btn-sm"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(t.id)}
                      className="aug-btn aug-btn-ghost aug-btn-sm"
                      style={{ color: "var(--red4)" }}
                    >
                      ✕
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )
        )}

        {/* Logs list */}
        {view === "logs" && (
          logs.length === 0 ? (
            <div style={{ padding: "48px 0", textAlign: "center", fontSize: 12, color: "var(--t3)" }}>
              No action logs yet — fire a trigger to see activity here.
            </div>
          ) : (
            <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", overflow: "hidden" }}>
              <table className="aug-dt" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Trigger</th>
                    <th>Recommendation</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {[...logs].reverse().map(l => (
                    <tr key={l.id}>
                      <td style={{ color: "var(--t3)", whiteSpace: "nowrap" }}>{timeAgo(l.fired_at)}</td>
                      <td style={{ fontWeight: 500, color: "var(--t1)" }}>{l.trigger_name}</td>
                      <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--t2)" }}>
                        {l.recommendation}
                      </td>
                      <td>
                        {l.status === "ok"
                          ? <span className="aug-tag aug-tag-green">ok {l.http_status}</span>
                          : l.status === "timeout"
                          ? <span className="aug-tag aug-tag-amber">timeout</span>
                          : <span className="aug-tag aug-tag-red" title={l.error ?? ""}>{l.http_status ? `${l.http_status}` : "failed"}</span>
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>
    </div>
  );
}
