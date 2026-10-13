"use client";
/**
 * Notifications — redone to `aughor-v2/CLARITY.md` (2026-10-13): three figures (triggers, delivered, failed among the
 * latest sends), then what needs a person — a live trigger whose last send failed — then the triggers as rows, and the
 * delivery log folded to one row per trigger and outcome. A trigger's form opens only on New trigger or Edit; the
 * whole error of a folded row is behind its Details, with any webhook path cut (`lib/notificationLog.ts`).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Loading, ReadFailed } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import {
  CARD, Chip, Dot, Empty, Figure, Figures, Label, MUTED, NeedsRow, NeedsYou, NUM, ONE_LINE, Page, ROW, RULE, type Tone,
} from "@/components/clarity/kit";
import { getApiBase } from "@/lib/config";
import { formatCount, formatDateTime, relTime } from "@/lib/format";
import { dayMonth } from "@/lib/monitorSummary";
import {
  failingStreak, foldDeliveries, hostOf, latestByTrigger, OUTCOME_WORD, redactError, shortError, sourceWords,
  type DeliveryGroup, type DeliveryLog, type DeliveryStatus,
} from "@/lib/notificationLog";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Trigger {
  id:         string;
  name:       string;
  type:       "webhook" | "slack" | "jira";
  /** Masked by the API to `scheme://host/••••••` — the secret never leaves the server. */
  url:        string;
  headers:    Record<string, string>;
  enabled:    boolean;
  channel?:   string;
  project?:   string;
  issue_type?: string;
}

/** The latest sends the log reads — the API keeps more; this screen folds these. */
const LOG_LIMIT = 50;

const TYPE_LABELS: Record<string, string> = { webhook: "Webhook", slack: "Slack", jira: "Jira" };

const OUTCOME_HUE: Record<DeliveryStatus, "green" | "red" | "amber" | "grey"> = {
  ok: "green", failed: "red", timeout: "amber", skipped: "grey",
};
const OUTCOME_TONE: Record<DeliveryStatus, Tone> = { ok: "up", failed: "down", timeout: "amber", skipped: "plain" };

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

/** "4m ago" this week, "31 Aug" before it. */
function when(iso: string): string {
  if (!iso) return "—";
  const age = Date.now() - Date.parse(iso);
  return age < 7 * 86_400_000 ? `${relTime(iso)} ago` : dayMonth(iso);
}

/** Where a trigger sends, said without its secret: the channel or project, and the host. */
function whereWords(t: Trigger): string {
  const host = hostOf(t.url);
  if (t.type === "slack") return [t.channel, host].filter(Boolean).join(" on ");
  if (t.type === "jira") return [[t.project, t.issue_type].filter(Boolean).join(" · "), host].filter(Boolean).join(" on ");
  return host;
}

/** A read that says when it failed — a failed read is never shown as "nothing configured". */
async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${getApiBase()}${path}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ── TriggerForm ───────────────────────────────────────────────────────────────

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <div className="aug-fs-xs" style={{ ...MUTED, marginBottom: 4 }}>{children}</div>;
}

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
    <form onSubmit={handleSubmit} data-testid="trigger-form"
      style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, padding: "10px 0 12px" }}>
      <div>
        <FieldLabel>Name</FieldLabel>
        <Input value={name} onChange={e => setName(e.target.value)} required placeholder="My Slack Webhook" />
      </div>
      <div>
        <FieldLabel>Sends to</FieldLabel>
        <SelectField value={type} onChange={e => setType(e.target.value as typeof type)}>
          <option value="webhook">Webhook (generic)</option>
          <option value="slack">Slack incoming webhook</option>
          <option value="jira">Jira (create issue)</option>
        </SelectField>
      </div>
      <div>
        <FieldLabel>{type === "jira" ? "Jira base URL" : "Webhook URL"}</FieldLabel>
        <Input value={url} onChange={e => setUrl(e.target.value)} required
          placeholder={type === "slack" ? "https://hooks.slack.com/services/…" : type === "jira" ? "https://yourorg.atlassian.net/rest/api/3/issue" : "https://…"}
        />
      </div>
      {type === "slack" && (
        <div>
          <FieldLabel>Channel (optional)</FieldLabel>
          <Input value={channel} onChange={e => setChannel(e.target.value)} placeholder="#general" />
        </div>
      )}
      {type === "jira" && (
        <>
          <div>
            <FieldLabel>Project key</FieldLabel>
            <Input value={project} onChange={e => setProject(e.target.value)} placeholder="OPS" />
          </div>
          <div>
            <FieldLabel>Issue type</FieldLabel>
            <Input value={issueType} onChange={e => setIssue(e.target.value)} placeholder="Task" />
          </div>
        </>
      )}
      <div style={{ ...ROW, gridColumn: "1 / -1" }}>
        <Button type="submit" disabled={saving} variant="default" size="xs">
          {saving ? "Saving…" : initial ? "Update" : "Create"}
        </Button>
        <Button type="button" onClick={onCancel} variant="ghost" size="xs">Cancel</Button>
        {initial && <span className="aug-fs-xs" style={MUTED}>The stored URL is kept unless you replace it.</span>}
        {error && <span role="alert" className="aug-fs-xs" style={{ color: "var(--red4)" }}>{error}</span>}
      </div>
    </form>
  );
}

// ── ActionHubPanel ────────────────────────────────────────────────────────────

/** A test, toggle or delete's answer, shown on its trigger's row. */
type RowNote = { tone: Tone; text: string };

export function ActionHubPanel() {
  const [triggers,  setTriggers]  = useState<Trigger[]>([]);
  const [logs,      setLogs]      = useState<DeliveryLog[]>([]);
  const [loaded,    setLoaded]    = useState(false);
  const [readFailed, setReadFailed] = useState<{ triggers?: string; logs?: string }>({});
  /** "new" while the New trigger form is open, a trigger's id while its Edit form is. One at a time. */
  const [formFor,   setFormFor]   = useState<string | null>(null);
  const [testing,   setTesting]   = useState<string | null>(null);
  const [notes,     setNotes]     = useState<Record<string, RowNote>>({});
  const [openRows,  setOpenRows]  = useState<ReadonlySet<string>>(new Set());

  const reload = useCallback(async () => {
    const [tr, lr] = await Promise.allSettled([
      getJson<{ triggers?: Trigger[] }>("/actions/triggers"),
      getJson<{ logs?: DeliveryLog[] }>(`/actions/logs?limit=${LOG_LIMIT}`),
    ]);
    setTriggers(tr.status === "fulfilled" ? tr.value.triggers ?? [] : []);
    setLogs(lr.status === "fulfilled" ? lr.value.logs ?? [] : []);
    setReadFailed({
      triggers: tr.status === "rejected" ? String((tr.reason as Error)?.message ?? tr.reason) : undefined,
      logs: lr.status === "rejected" ? String((lr.reason as Error)?.message ?? lr.reason) : undefined,
    });
    setLoaded(true);
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const note = (id: string, n: RowNote) => setNotes(prev => ({ ...prev, [id]: n }));

  const handleSave = async (data: Partial<Trigger>) => {
    const editing = formFor && formFor !== "new" ? formFor : null;
    const method = editing ? "PUT" : "POST";
    const url    = editing ? `${getApiBase()}/actions/triggers/${editing}` : `${getApiBase()}/actions/triggers`;
    const resp   = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail ?? "Save failed");
    setFormFor(null);
    void reload();
  };

  const handleDelete = async (t: Trigger) => {
    if (!window.confirm(`Delete the trigger “${t.name}”? This cannot be undone.`)) return;
    try {
      const resp = await fetch(`${getApiBase()}/actions/triggers/${t.id}`, { method: "DELETE" });
      if (!resp.ok) throw new Error(`delete failed (${resp.status})`);
    } catch (e) {
      note(t.id, { tone: "down", text: e instanceof Error ? e.message : "delete failed" });
    } finally {
      void reload();
    }
  };

  const handleToggle = async (t: Trigger) => {
    try {
      const resp = await fetch(`${getApiBase()}/actions/triggers/${t.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...t, enabled: !t.enabled }),
      });
      if (!resp.ok) throw new Error(`update failed (${resp.status})`);
    } catch (e) {
      note(t.id, { tone: "down", text: e instanceof Error ? e.message : "update failed" });
    } finally {
      void reload();
    }
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const resp = await fetch(`${getApiBase()}/actions/triggers/${id}/test`, { method: "POST" });
      const data = await resp.json();
      note(id, data.status === "ok" ? { tone: "up", text: `test sent${data.http_status ? ` · HTTP ${data.http_status}` : ""}` }
        : data.status === "skipped" ? { tone: "plain", text: `test skipped: ${data.error || "the trigger is off"}` }
        : { tone: "down", text: `test failed: ${shortError({ error: data.error, status: data.status, http_status: data.http_status }) || "no reason given"}` });
    } catch (e) {
      // Without this, a network error left the button wedged forever.
      note(id, { tone: "down", text: `test failed: ${e instanceof Error ? e.message : "unreachable"}` });
    } finally {
      setTesting(null);
      void reload();
    }
  };

  const liveIds = useMemo(() => new Set(triggers.map(t => t.id)), [triggers]);
  /** Whether "since removed" can be said at all: with the triggers unread, no send's trigger is known to be gone. */
  const triggersKnown = !readFailed.triggers;
  const groups = useMemo(() => foldDeliveries(logs, liveIds).map(g => (triggersKnown ? g : { ...g, removed: false })),
    [logs, liveIds, triggersKnown]);
  const latest = useMemo(() => latestByTrigger(logs), [logs]);

  const sent = logs.filter(l => l.status === "ok").length;
  const skipped = logs.filter(l => l.status === "skipped").length;
  const failedLogs = logs.filter(l => l.status === "failed" || l.status === "timeout");
  const failedLive = failedLogs.filter(l => liveIds.has(l.trigger_id));
  const removedTriggers = new Set(failedLogs.filter(l => !liveIds.has(l.trigger_id)).map(l => l.trigger_id));
  const on = triggers.filter(t => t.enabled).length;
  const windowFull = logs.length >= LOG_LIMIT;

  /** A trigger that is on and whose newest send failed: the one thing on this screen a person must act on. */
  const failing = triggers.filter(t => t.enabled && ["failed", "timeout"].includes(latest.get(t.id)?.status ?? ""));

  const failedSub = failedLogs.length === 0 ? (logs.length ? "none failed" : "nothing sent yet")
    : !triggersKnown ? `from ${plural(new Set(failedLogs.map(l => l.trigger_id)).size, "trigger")}`
    : failedLive.length === 0 ? `all from ${plural(removedTriggers.size, "trigger")} since removed`
    : removedTriggers.size ? `${formatCount(failedLive.length)} from live triggers · the rest from removed ones`
    : `from ${plural(new Set(failedLive.map(l => l.trigger_id)).size, "trigger")}`;

  return (
    <Page testId="notifications">
      {!loaded && <Loading what="notifications" />}
      {loaded && (
        <>
          <Figures testId="notification-figures">
            <Figure label="Triggers" value={readFailed.triggers ? "—" : formatCount(triggers.length)} testId="fig-triggers"
              sub={readFailed.triggers ? "could not be read" : triggers.length === 0 ? "none set up"
                : on === triggers.length ? "all on" : `${on} on · ${triggers.length - on} off`} />
            <Figure label="Delivered" value={readFailed.logs ? "—" : formatCount(sent)} testId="fig-delivered"
              sub={readFailed.logs ? "could not be read" : logs.length === 0 ? "nothing sent yet"
                : `of the latest ${plural(logs.length, "send")}${skipped ? ` · ${formatCount(skipped)} skipped` : ""}`} />
            <Figure label="Failed" value={readFailed.logs ? "—" : formatCount(failedLogs.length)} testId="fig-failed"
              tone={failedLive.length ? "red" : undefined} sub={readFailed.logs ? "could not be read" : failedSub} />
          </Figures>

          <NeedsYou testId="notification-needs"
            empty={triggers.length === 0 ? "Nothing needs you" : "Nothing needs you · no live trigger is failing"}>
            {failing.map(t => {
              const last = latest.get(t.id)!;
              const streak = failingStreak(logs, t.id);
              return (
                <NeedsRow key={t.id} testId="needs-failing"
                  title={`${t.name} · ${streak > 1 ? `its last ${streak} sends failed` : "its last send failed"}`}
                  detail={[shortError(last), when(last.fired_at), `sent by ${sourceWords(last)}`].filter(Boolean).join(" · ")}
                  actions={<>
                    <Button size="xs" variant="secondary" disabled={testing === t.id} onClick={() => void handleTest(t.id)}>
                      {testing === t.id ? "Testing…" : "Test"}
                    </Button>
                    <Button size="xs" variant="ghost" onClick={() => setFormFor(t.id)}>Edit</Button>
                  </>} />
              );
            })}
          </NeedsYou>

          <section aria-label="Triggers" data-testid="trigger-list" style={CARD}>
            <Label right={
              <Button size="xs" variant="ghost" disabled={formFor === "new"} onClick={() => setFormFor("new")}>
                <Icon name="plus" size={12} />New trigger
              </Button>
            }>Triggers</Label>
            {formFor === "new" && (
              <TriggerForm onSave={handleSave} onCancel={() => setFormFor(null)} />
            )}
            {readFailed.triggers ? <ReadFailed what="the triggers" error={readFailed.triggers} onRetry={() => void reload()} />
              : triggers.length === 0 ? (
                formFor !== "new" && (
                  <Empty>A trigger sends to Slack, a webhook or Jira when a recommendation, a monitor or an automation fires it.</Empty>
                )
              ) : triggers.map((t, i) => (
                <TriggerRow key={t.id} t={t} first={i === 0 && formFor !== "new"} last={latest.get(t.id)}
                  sources={[...new Set(logs.filter(l => l.trigger_id === t.id).map(sourceWords))]}
                  windowFull={windowFull} note={notes[t.id]} testing={testing === t.id} editing={formFor === t.id}
                  onTest={() => void handleTest(t.id)} onToggle={() => void handleToggle(t)}
                  onEdit={() => setFormFor(formFor === t.id ? null : t.id)} onDelete={() => void handleDelete(t)}
                  form={formFor === t.id
                    ? <TriggerForm initial={t} onSave={handleSave} onCancel={() => setFormFor(null)} /> : null} />
              ))}
          </section>

          <section aria-label="Delivery log" data-testid="delivery-log" style={CARD}>
            {/* How many sends were read is the Delivered figure's line, and the newest row says when — the label says
                neither again. */}
            <Label>Delivery log</Label>
            {readFailed.logs ? <ReadFailed what="the delivery log" error={readFailed.logs} onRetry={() => void reload()} />
              : groups.length === 0 ? <Empty>A trigger&apos;s sends show here, a test fire among them.</Empty>
              : groups.map((g, i) => (
                <DeliveryRow key={g.key} g={g} first={i === 0} open={openRows.has(g.key)}
                  onToggle={() => setOpenRows(p => { const n = new Set(p); if (n.has(g.key)) n.delete(g.key); else n.add(g.key); return n; })} />
              ))}
          </section>
        </>
      )}
    </Page>
  );
}

// ── A trigger, one row ────────────────────────────────────────────────────────

function TriggerRow({ t, first, last, sources, windowFull, note, testing, editing, onTest, onToggle, onEdit, onDelete, form }: {
  t: Trigger;
  first: boolean;
  last?: DeliveryLog;
  sources: string[];
  windowFull: boolean;
  note?: RowNote;
  testing: boolean;
  editing: boolean;
  onTest: () => void;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  form: React.ReactNode;
}) {
  const where = whereWords(t);
  const used = sources.length ? `used by ${sources.join(", ")}`
    : windowFull ? `no send in the latest ${LOG_LIMIT}` : "not fired yet";
  const meta = [where, used].filter(Boolean).join(" · ");
  return (
    <div data-testid="trigger-row" style={{ ...(first ? {} : RULE), padding: "9px 2px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr) auto", gap: 12, alignItems: "center" }}>
        <Switch checked={t.enabled} onChange={onToggle} title={t.enabled ? "Turn off" : "Turn on"}
          aria-label={`${t.enabled ? "Turn off" : "Turn on"} ${t.name}`} />
        <div style={{ minWidth: 0 }}>
          <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }}>
            <span className="aug-fs-chrome" title={t.name} style={{ ...ONE_LINE, fontWeight: 600, color: "var(--t1)" }}>{t.name}</span>
            <Chip>{TYPE_LABELS[t.type] ?? t.type}</Chip>
            {last && (
              <Chip tone={OUTCOME_TONE[last.status]} title={last.error ? redactError(last.error) : undefined}>
                {`${OUTCOME_WORD[last.status]} ${when(last.fired_at)}`}
              </Chip>
            )}
            {!t.enabled && <Chip>off</Chip>}
            {note && <Chip tone={note.tone} testId="trigger-note">{note.text}</Chip>}
          </div>
          <div className="aug-fs-xs" title={meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>
        </div>
        <div style={{ ...ROW, flexWrap: "nowrap", gap: 4 }}>
          <Button size="xs" variant="outline" disabled={testing} onClick={onTest} title="Send a test message through this trigger">
            {testing ? "Testing…" : "Test"}
          </Button>
          <Button size="xs" variant="ghost" aria-expanded={editing} onClick={onEdit}>{editing ? "Close" : "Edit"}</Button>
          <Button size="xs" variant="ghost" onClick={onDelete} aria-label={`Delete ${t.name}`} title="Delete"
            style={{ color: "var(--red4)" }}>
            <Icon name="trash" size={12} />
          </Button>
        </div>
      </div>
      {form}
    </div>
  );
}

// ── The delivery log, repeats folded ──────────────────────────────────────────

function DeliveryRow({ g, first, open, onToggle }: { g: DeliveryGroup; first: boolean; open: boolean; onToggle: () => void }) {
  const err = shortError(g.latest);
  const meta = [OUTCOME_WORD[g.outcome], `last ${when(g.last)}`, err].filter(Boolean).join(" · ");
  const full = g.latest.error ? redactError(g.latest.error) : "";
  return (
    <div data-testid="delivery-row" style={{ ...(first ? {} : RULE), padding: "8px 2px", opacity: g.removed ? 0.8 : 1 }}>
      <div style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto auto", gap: 10, alignItems: "center" }}>
        <Dot hue={OUTCOME_HUE[g.outcome]} title={OUTCOME_WORD[g.outcome]} />
        <div style={{ minWidth: 0 }}>
          <div style={{ ...ROW, flexWrap: "nowrap", minWidth: 0 }}>
            <span className="aug-fs-chrome" style={{ ...ONE_LINE, fontWeight: 500, color: "var(--t1)" }}>{g.triggerName}</span>
            {g.removed && <Chip title="This trigger no longer exists — these sends are history">since removed</Chip>}
          </div>
          <div className="aug-fs-xs" title={full || meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>
        </div>
        <span className="aug-fs-chrome" data-testid="delivery-count"
          style={{ color: "var(--t2)", ...NUM, minWidth: 28, textAlign: "right" }}>
          {g.count > 1 ? `×${formatCount(g.count)}` : ""}
        </span>
        <Button size="xs" variant="ghost" aria-expanded={open} onClick={onToggle}>
          Details <Icon name={open ? "chevu" : "chevd"} size={12} />
        </Button>
      </div>
      {open && (
        <div data-testid="delivery-details" style={{ padding: "8px 0 2px 22px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={ROW}>
            <Chip>{g.count === 1 ? formatDateTime(g.last) : `${formatDateTime(g.first)} – ${formatDateTime(g.last)}`}</Chip>
            <Chip>{`sent by ${g.sources.join(", ")}`}</Chip>
            {g.latest.http_status != null && <Chip>{`HTTP ${g.latest.http_status}`}</Chip>}
          </div>
          {g.messages.length > 0 && (
            <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>
              {`${g.messages.length === 1 ? "Message" : "Messages"}: ${g.messages.slice(0, 3).map(m => `“${m.length > 80 ? `${m.slice(0, 79)}…` : m}”`).join(" · ")}`}
              {g.messages.length > 3 ? ` · and ${formatCount(g.messages.length - 3)} more` : ""}
            </div>
          )}
          {full && (
            <pre className="aug-fs-xs" style={{ margin: 0, background: "var(--code-bg)", borderRadius: "var(--r2)", padding: "6px 8px",
              whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "var(--font-code)", color: "var(--t2)" }}>{full}</pre>
          )}
        </div>
      )}
    </div>
  );
}
