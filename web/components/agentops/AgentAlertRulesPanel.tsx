"use client";

/**
 * VA-6 — the rules behind the alerts.
 *
 * The engine that decides whether the agents are misbehaving shipped complete and unreachable:
 * nothing stored a rule, so nothing could ever evaluate one. This is the surface that
 * stores them. It sits inside Attention rather than beside Monitors because the person
 * who sets these thresholds is the person reading what is waiting on them.
 *
 * Two things it refuses to do:
 *
 * The metric list comes from the SERVER, never from a constant here. A picker offering a
 * metric the backend cannot measure is a control that silently does nothing — the same
 * rule `/activity` follows for event kinds.
 *
 * Test reports the number AND the population, including when nothing fired. "It did not
 * cross" is not an answer on its own; "it did not cross — 0.12 over 41 runs" is.
 */
import { useCallback, useEffect, useState } from "react";

import { StatusChip } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import {
  deleteAgentAlertRule, getAgentAlertVocabulary, listAgentAlertRules, listUserAgents,
  testAgentAlertRule, upsertAgentAlertRule, type AgentAlertRule, type UserAgent,
} from "@/lib/api";

const COMPARATOR_LABEL: Record<string, string> = {
  gt: "is above", gte: "is at or above", lt: "is below", lte: "is at or below",
};

/** Metric names as a person says them. Anything the server adds and this map has not
 *  caught up with falls back to the raw name rather than disappearing. */
const METRIC_LABEL: Record<string, string> = {
  error_rate: "Error rate", failed_runs: "Failed runs", runs_started: "Runs started",
  p95_duration_ms: "p95 duration (ms)", tokens: "Tokens", cost_usd: "Cost (USD)",
  unmetered_runs: "Runs with no spend recorded",
};

type Comparator = AgentAlertRule["comparator"];

const BLANK = {
  name: "", metric: "error_rate", comparator: "gt" as Comparator, threshold: 0.25,
  window_minutes: 15, debounce_minutes: 30, check_cron: "*/5 * * * *",
  severity: "warning" as const, channel: "", enabled: true,
  // AO-4 — the scope the engine always honoured and the form never offered: "" is the
  // whole fleet, an id narrows the rule to one custom agent.
  agent_id: "",
};

function Field({ label, children, width }: {
  label: string; children: React.ReactNode; width?: number;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, width }}>
      <label className="aug-label" style={{ color: "var(--t3)", textTransform: "uppercase",
        letterSpacing: "0.05em" }}>{label}</label>
      {children}
    </div>
  );
}

export function AgentAlertRulesPanel({ agentId = "", agentName = "" }: {
  /** AO-4 — scoped to ONE custom agent (its Alerts tab): the list shows its rules and a
   *  new rule is born bound to it. Unscoped (Attention), the form offers the scope. */
  agentId?: string;
  agentName?: string;
} = {}) {
  const [rules, setRules] = useState<AgentAlertRule[]>([]);
  const [metrics, setMetrics] = useState<string[]>([]);
  const [comparators, setComparators] = useState<string[]>([]);
  const [agents, setAgents] = useState<UserAgent[]>([]);
  const [draft, setDraft] = useState({ ...BLANK, agent_id: agentId });
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    listAgentAlertRules()
      .then(all => setRules(agentId ? all.filter(r => r.agent_id === agentId) : all))
      .catch(e => setError(String(e?.message || e)));
    if (!agentId) listUserAgents().then(setAgents).catch(() => setAgents([]));
  }, [agentId]);
  const agentLabel = (id: string) =>
    id === agentId && agentName ? agentName : (agents.find(a => a.id === id)?.name ?? id);

  useEffect(() => {
    load();
    getAgentAlertVocabulary()
      .then(v => { setMetrics(v.metrics); setComparators(v.comparators); })
      .catch(e => setError(String(e?.message || e)));
  }, [load]);

  const save = async () => {
    setBusy("save");
    try {
      await upsertAgentAlertRule(draft);
      setDraft({ ...BLANK, agent_id: agentId });
      setOpen(false);
      setError(null);
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (rule: AgentAlertRule) => {
    setBusy(rule.id);
    try {
      await upsertAgentAlertRule({ ...rule, enabled: !rule.enabled });
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const remove = async (rule: AgentAlertRule) => {
    setBusy(rule.id);
    try {
      await deleteAgentAlertRule(rule.id);
      load();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  const test = async (rule: AgentAlertRule) => {
    setBusy(rule.id);
    try {
      const { verdict } = await testAgentAlertRule(rule.id);
      setVerdicts(v => ({ ...v, [rule.id]: verdict.reason }));
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ marginBottom: 16, background: "var(--bg-2)", border: "1px solid var(--b1)",
      borderRadius: "var(--r3)", padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div className="aug-fs-ui" style={{ flex: 1, color: "var(--t1)" }}>
          Alert rules{agentId ? ` for ${agentName || agentId}` : ""}
          <span className="aug-fs-sm" style={{ color: "var(--t3)", marginLeft: 8 }}>
            {rules.length === 0
              ? (agentId ? "none yet — nothing about this agent is being watched"
                         : "none yet — nothing about the agents is being watched")
              : `${rules.filter(r => r.enabled).length} of ${rules.length} enabled`}
          </span>
        </div>
        <Button variant="secondary" size="xs" onClick={() => setOpen(o => !o)}>
          {open ? "Cancel" : "New rule"}
        </Button>
      </div>

      {error && (
        <div className="aug-fs-sm" style={{ color: "var(--red4)", marginTop: 8 }}>{error}</div>
      )}

      {open && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12,
          paddingTop: 12, borderTop: "1px solid var(--b1)" }}>
          <Field label="Name" width={200}>
            <input className="aug-input" value={draft.name} placeholder="Error rate across agents"
              onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} />
          </Field>
          <Field label="Metric" width={190}>
            <select className="aug-input" value={draft.metric}
              onChange={e => setDraft(d => ({ ...d, metric: e.target.value }))}>
              {metrics.map(m => (
                <option key={m} value={m}>{METRIC_LABEL[m] ?? m}</option>
              ))}
            </select>
          </Field>
          <Field label="Condition" width={140}>
            <select className="aug-input" value={draft.comparator}
              onChange={e => setDraft(d => ({ ...d, comparator: e.target.value as Comparator }))}>
              {comparators.map(c => (
                <option key={c} value={c}>{COMPARATOR_LABEL[c] ?? c}</option>
              ))}
            </select>
          </Field>
          <Field label="Threshold" width={100}>
            <input className="aug-input" type="number" step="any" value={draft.threshold}
              onChange={e => setDraft(d => ({ ...d, threshold: Number(e.target.value) }))} />
          </Field>
          <Field label="Window (min)" width={100}>
            <input className="aug-input" type="number" min={1} value={draft.window_minutes}
              onChange={e => setDraft(d => ({ ...d, window_minutes: Number(e.target.value) }))} />
          </Field>
          <Field label="Quiet period (min)" width={120}>
            <input className="aug-input" type="number" min={0} value={draft.debounce_minutes}
              onChange={e => setDraft(d => ({ ...d, debounce_minutes: Number(e.target.value) }))} />
          </Field>
          <Field label="Severity" width={110}>
            <select className="aug-input" value={draft.severity}
              onChange={e => setDraft(d => ({ ...d, severity: e.target.value as typeof BLANK.severity }))}>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="critical">critical</option>
            </select>
          </Field>
          <Field label="Channel (trigger id)" width={170}>
            <input className="aug-input" value={draft.channel} placeholder="in-app only"
              onChange={e => setDraft(d => ({ ...d, channel: e.target.value }))} />
          </Field>
          <Field label="Scope" width={200}>
            {agentId ? (
              <span className="aug-fs-sm" style={{ color: "var(--t2)", lineHeight: "28px" }}
                title={`This rule watches only ${agentName || agentId}`}>
                {agentName || agentId}
              </span>
            ) : (
              <select className="aug-input" value={draft.agent_id}
                onChange={e => setDraft(d => ({ ...d, agent_id: e.target.value }))}>
                <option value="">the whole fleet</option>
                {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            )}
          </Field>
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <Button variant="default" size="xs" disabled={!draft.name || busy === "save"}
              onClick={save}>Save rule</Button>
          </div>
        </div>
      )}

      {rules.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
          {rules.map(rule => (
            <div key={rule.id} style={{ display: "flex", alignItems: "center", gap: 10,
              paddingTop: 8, borderTop: "1px solid var(--b1)" }}>
              <StatusChip hue={rule.enabled ? "accent" : "muted"} strength="soft">
                {rule.severity}
              </StatusChip>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="aug-fs-ui" style={{ overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{rule.name}</div>
                <div className="aug-fs-sm" style={{ color: "var(--t2)", marginTop: 2 }}>
                  {METRIC_LABEL[rule.metric] ?? rule.metric}{" "}
                  {COMPARATOR_LABEL[rule.comparator] ?? rule.comparator} {rule.threshold}
                  {" · "}over {rule.window_minutes}m
                  {" · "}checked {rule.check_cron}
                  {" · "}quiet {rule.debounce_minutes}m
                  {rule.channel ? ` · via ${rule.channel}` : " · in-app"}
                  {rule.agent_id ? ` · only ${agentLabel(rule.agent_id)}`
                    : rule.charter_id ? ` · only ${rule.charter_id}` : " · whole fleet"}
                </div>
                {verdicts[rule.id] && (
                  <div className="aug-fs-sm" style={{ color: "var(--t3)", marginTop: 2 }}>
                    {verdicts[rule.id]}
                  </div>
                )}
              </div>
              <Button variant="ghost" size="xs" disabled={busy === rule.id}
                onClick={() => test(rule)}>Test</Button>
              <Button variant="ghost" size="xs" disabled={busy === rule.id}
                onClick={() => toggle(rule)}>{rule.enabled ? "Disable" : "Enable"}</Button>
              <Button variant="ghost" size="xs" disabled={busy === rule.id}
                onClick={() => remove(rule)}>Delete</Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
