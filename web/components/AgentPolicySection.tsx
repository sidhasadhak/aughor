"use client";

/**
 * AgentPolicySection — Settings ▸ Organization: what an outside agent (an MCP client) may do here (DE-2b,
 * ROADMAP §3.51). Three levels — read looks things up, run starts analyses that spend model calls, act
 * changes things (cancel a job, run an automation, Spotlight's acts) — and two allowlists.
 *
 * The section shows three things apart and says which is which: the policy a person SAVED (or that nobody
 * did, so the default `run` stands), what the ENVIRONMENT pins on the server (it can only narrow), and the
 * EFFECTIVE result the API enforces. `act` is given only by a named person: the server refuses an agent that
 * tries, and this form is disabled without `admin.manage_org`, saying so.
 *
 * A card (CLARITY, 2026-10-12): the policy in force at the label's right end, one line on what it governs, the three
 * levels side by side, the two allowlists, one Save.
 */
import { useCallback, useEffect, useState } from "react";
import { clearAgentPolicy, getAgentPolicy, getMyAccess, updateAgentPolicy, type AgentPolicyView } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { Card } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Radio } from "@/components/ui/checkbox";

import { FIELDS, Field, Note, SaveLine } from "./settings/parts";

type Level = "read" | "run" | "act";

const LEVELS: Array<{ key: Level; label: string; hint: string }> = [
  { key: "read", label: "Read", hint: "look things up — connections, findings, metrics, the knowledge graph" },
  { key: "run", label: "Run", hint: "also ask questions and start explorations, which spend model calls" },
  { key: "act", label: "Act", hint: "also cancel jobs, run automations and Spotlight's staged acts" },
];

/** A comma list as typed → the list the API takes; blank means "all". */
export function parseAllowlist(text: string): string[] | null {
  const items = text.split(",").map(t => t.trim()).filter(Boolean);
  return items.length ? items : null;
}

/** The effective policy, as one sentence. */
export function describeEffective(view: AgentPolicyView): string {
  const e = view.effective;
  const who = view.saved
    ? `set by ${view.saved.set_by || "a person"}${view.saved.updated_at ? ` on ${formatTimestamp(view.saved.updated_at, "short")}` : ""}`
    : "the default — set by nobody";
  const narrowed = e.source === "narrowed" && e.narrowed_by.length
    ? `; the environment narrowed the ${e.narrowed_by.join(" and ")}`
    : "";
  return `${e.level} · ${who}${narrowed}`;
}

export function AgentPolicySection() {
  const [view, setView] = useState<AgentPolicyView | null>(null);
  const [level, setLevel] = useState<Level>("run");
  const [connections, setConnections] = useState("");
  const [tools, setTools] = useState("");
  const [canManage, setCanManage] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const take = useCallback((v: AgentPolicyView) => {
    setView(v);
    const base = v.saved ?? v.effective;
    setLevel(base.level);
    setConnections((base.connections ?? []).join(", "));
    setTools((base.tools ?? []).join(", "));
  }, []);

  const load = useCallback(async () => {
    setError("");
    try {
      take(await getAgentPolicy());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the agent policy");
    }
    try {
      // No identity (localhost mode) answers null: the server then decides, and this form stays open.
      const me = await getMyAccess();
      setCanManage(me === null || me.permissions.includes("admin.manage_org"));
    } catch {
      setCanManage(true);
    }
  }, [take]);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    setSaving(true); setError(""); setSaved(false);
    try {
      take(await updateAgentPolicy({ level, connections: parseAllowlist(connections), tools: parseAllowlist(tools) }));
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the agent policy");
    } finally {
      setSaving(false);
    }
  };

  const clear = async () => {
    setSaving(true); setError(""); setSaved(false);
    try {
      take(await clearAgentPolicy());
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not clear the agent policy");
    } finally {
      setSaving(false);
    }
  };

  const env = view?.environment;
  const envPins = env && (env.level || env.connections || env.tools);

  return (
    <Card label="Outside agents (MCP)" testId="agent-policy-section"
      right={view && (
        <span className="aug-fs-xs" data-testid="agent-policy-effective" style={{ color: "var(--t2)" }}>
          In force: <strong>{describeEffective(view)}</strong>
        </span>
      )}>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 10 }}>
        What an MCP client acting for this organisation may do; every call is checked and audited.
      </div>
      {envPins && (
        <div className="aug-fs-xs" data-testid="agent-policy-environment" style={{ color: "var(--amb4)", marginBottom: 10 }}>
          The server's environment pins {[
            env.level ? `the level at ${env.level}` : "",
            env.connections ? `${env.connections.length} connection${env.connections.length === 1 ? "" : "s"}` : "",
            env.tools ? `${env.tools.length} tool${env.tools.length === 1 ? "" : "s"}` : "",
          ].filter(Boolean).join(", ")} — a saved policy can only be narrower than that, never wider.
        </div>
      )}

      <div role="radiogroup" aria-label="Agent level" style={{ display: "grid", gap: 10, marginBottom: 12,
        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))" }}>
        {LEVELS.map(l => (
          <label key={l.key} className="aug-fs-sm" style={{ display: "flex", alignItems: "flex-start", gap: 8, color: "var(--t2)", cursor: canManage ? "pointer" : "default" }}>
            <Radio name="agent-level" value={l.key} checked={level === l.key}
              disabled={!canManage || saving} onChange={() => setLevel(l.key)} />
            <span>
              <strong style={{ color: "var(--t1)" }}>{l.label}</strong>{" "}
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>— {l.hint}</span>
            </span>
          </label>
        ))}
      </div>

      <div style={FIELDS}>
        <Field label="Connections the agent may touch" htmlFor="agent-policy-connections">
          <Input id="agent-policy-connections" value={connections} disabled={!canManage || saving}
            onChange={e => setConnections(e.target.value)} placeholder="all — or connection ids, comma-separated" />
        </Field>
        <Field label="Tools the agent may call" htmlFor="agent-policy-tools">
          <Input id="agent-policy-tools" value={tools} disabled={!canManage || saving}
            onChange={e => setTools(e.target.value)} placeholder="all — or tool names, comma-separated" />
        </Field>
      </div>

      {!canManage && (
        <Note testId="agent-policy-locked">
          Changing this needs the <code>admin.manage_org</code> permission; the policy in force is shown above.
        </Note>
      )}
      <SaveLine saved={saved && !saving} error={error} errorTestId="agent-policy-error">
        <Button variant="secondary" size="sm" onClick={save} disabled={!canManage || saving} data-testid="agent-policy-save">
          {saving ? "Saving…" : "Save agent policy"}
        </Button>
        {view?.saved && (
          <Button variant="ghost" size="sm" onClick={clear} disabled={!canManage || saving} data-testid="agent-policy-clear">
            Return to the default (run)
          </Button>
        )}
      </SaveLine>
    </Card>
  );
}
