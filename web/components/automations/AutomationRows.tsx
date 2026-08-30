"use client";

/**
 * VA-12 · the one editor for a trigger and for an action.
 *
 * These rows lived inside `AutomationsPanel` and were reachable only from its form view.
 * The canvas now authors the same objects, and two editors for one model is how a picture
 * and the thing it edits come to disagree — the same argument `AutomationGraph` makes for
 * letting the SERVER own the graph. So the rows move here and both surfaces render these.
 *
 * **The kind lists are narrower than the model's `Literal`, on purpose.** The server
 * accepts seven effect kinds; two of them — `monitor` and `agent_alert` — are adopted
 * objects that the engine writes when an existing monitor or alert rule is migrated onto
 * it, and the model's own docstring says they are "not authored by hand". Offering them
 * here would invite a reader to hand-write one and get a row that duplicates an object
 * they already have. Posting to Slack IS authorable and is offered — VA-13 added the
 * `GET /slack-bots` client and the picker below.
 */
import React from "react";

import { Button } from "@/components/ui/button";
import {
  AUTOMATION_REQUIRED_KEYS,
  type AutoCondition, type AutoEffect, type ConditionKind, type EffectKind,
  type SlackBotSummary, type UserAgent,
} from "@/lib/api";

export const CONDITION_KINDS: { value: ConditionKind; label: string; desc: string }[] = [
  { value: "schedule",       label: "Schedule",       desc: "Fire on a cron cadence" },
  { value: "metric",         label: "Metric",         desc: "Delegate to an existing monitor by id" },
  { value: "source_change",  label: "Source change",  desc: "A table's rows changed (add / delete / backfill)" },
  { value: "entity_appears", label: "New entity",     desc: "A new key appeared in a table" },
];

export const EFFECT_KINDS: { value: EffectKind; label: string; desc: string }[] = [
  { value: "notify",         label: "Notify",         desc: "Send through a Notifications trigger" },
  { value: "investigate",    label: "Investigate",    desc: "Run the Agent" },
  { value: "brief",          label: "Deliver briefing", desc: "Deliver a briefing subscription" },
  { value: "kinetic_action", label: "Declared action",
    desc: "Run a declared, governed action — through its approval gate" },
  { value: "slack_post", label: "Post to Slack",
    desc: "Post into a channel as one of your bots — mentionable, and repliable in thread" },
];

export const CRON_PRESETS = [
  { label: "Hourly",  cron: "0 * * * *" },
  { label: "Daily",   cron: "0 9 * * *" },
  { label: "Weekly",  cron: "0 9 * * 1" },
  { label: "Custom",  cron: "" },
];

export const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: "var(--r3)",
  border: "1px solid var(--b1)", background: "var(--bg-1, var(--bg-2))", color: "var(--t1)",
};

export const labelStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: "var(--t3)", marginBottom: 5, display: "block",
  textTransform: "uppercase",
};

export const ghostBtn: React.CSSProperties = {
  background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 11,
};

/**
 * A new trigger / a new action, with the config key its kind REQUIRES already present.
 *
 * Shared because the defaults are part of the contract, not a convenience: the server
 * validates required config keys at CONSTRUCTION, so a default that omits one produces a
 * 422 the moment it is saved. Two call sites inventing their own defaults is two chances
 * to get that wrong, and only one of them would be caught by a test.
 */
export function newCondition(): AutoCondition {
  return { kind: "schedule", config: { cron: "0 9 * * *" } };
}

export function newEffect(): AutoEffect {
  return { kind: "notify", config: { trigger_id: "" } };
}

/** What is still missing before the server would accept this row. Empty = valid.
 *
 *  Checked while the row is on screen rather than discovered from a failed save: the
 *  server's error names a config key, and a key says nothing about WHICH of five steps
 *  is carrying it. The requirements themselves live at the wire boundary
 *  (`AUTOMATION_REQUIRED_KEYS`) and are asserted against the Python source. */
export function missingKeys(row: AutoCondition | AutoEffect): string[] {
  return (AUTOMATION_REQUIRED_KEYS[row.kind] ?? [])
    .filter(k => !String(row.config[k] ?? "").trim());
}

/** A `message` is either a sentence or a `{"$from": …}` binding. Rendered as the text a
 *  person typed either way, so the field round-trips: showing `[object Object]` for a
 *  binding would invite someone to overwrite the one thing that makes the chain work. */
function messageText(e: AutoEffect): string {
  const m = e.config.message;
  if (m == null) return "";
  return typeof m === "string" ? m : JSON.stringify(m);
}

/** Text back to a value. A well-formed binding object becomes one; anything else stays
 *  the string it is — including half-typed JSON, which must not be swallowed mid-keystroke. */
function parseMessage(text: string): unknown {
  const t = text.trim();
  if (!t.startsWith("{")) return text;
  try {
    const parsed = JSON.parse(t);
    return parsed && typeof parsed === "object" && "$from" in parsed ? parsed : text;
  } catch {
    return text;
  }
}

export function ConditionRow({ c, onChange, onRemove }: {
  c: AutoCondition; onChange: (c: AutoCondition) => void; onRemove?: () => void;
}) {
  const set = (patch: Record<string, unknown>) => onChange({ ...c, config: { ...c.config, ...patch } });
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 8 }}>
      <select value={c.kind} onChange={e => onChange({ kind: e.target.value as ConditionKind, config: {} })}
        aria-label="Trigger kind"
        style={{ ...inputStyle, width: 150 }}>
        {CONDITION_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
      </select>
      <div style={{ flex: 1 }}>
        {c.kind === "schedule" && (
          <div style={{ display: "flex", gap: 6 }}>
            <select value={CRON_PRESETS.find(p => p.cron === c.config.cron)?.cron ?? ""}
              aria-label="Cron preset"
              onChange={e => e.target.value && set({ cron: e.target.value })}
              style={{ ...inputStyle, width: 110 }}>
              {CRON_PRESETS.map(p => <option key={p.label} value={p.cron}>{p.label}</option>)}
            </select>
            <input style={inputStyle} value={String(c.config.cron ?? "")} onChange={e => set({ cron: e.target.value })} placeholder="cron e.g. 0 9 * * *" />
          </div>
        )}
        {c.kind === "metric" && (
          <input style={inputStyle} value={String(c.config.monitor_id ?? "")} onChange={e => set({ monitor_id: e.target.value })} placeholder="monitor id" />
        )}
        {(c.kind === "source_change" || c.kind === "entity_appears") && (
          <input style={inputStyle} value={String(c.config.table ?? "")} onChange={e => set({ table: e.target.value })} placeholder="table (schema.table)" />
        )}
      </div>
      {onRemove && <Button variant="ghost" onClick={onRemove} className="h-auto font-normal" aria-label="Remove trigger" style={{ ...ghostBtn, color: "var(--red3)", padding: "6px 4px" }}>✕</Button>}
    </div>
  );
}

export function EffectRow({ e, agents, bots = [], onChange, onRemove }: {
  e: AutoEffect; agents: UserAgent[];
  /** The bots a "Post to Slack" step may post AS. Empty ⇒ the row says so rather than
   *  offering an empty picker, because "no bots configured" and "pick a bot" call for
   *  different actions and only one of them is something the reader can do here. */
  bots?: SlackBotSummary[];
  onChange: (e: AutoEffect) => void; onRemove?: () => void;
}) {
  const set = (patch: Record<string, unknown>) => onChange({ ...e, config: { ...e.config, ...patch } });
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 8 }}>
      <select value={e.kind} onChange={ev => onChange({ kind: ev.target.value as EffectKind, config: {} })}
        aria-label="Action kind"
        style={{ ...inputStyle, width: 150 }}>
        {EFFECT_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
      </select>
      <div style={{ flex: 1 }}>
        {e.kind === "notify" && (
          <input style={inputStyle} value={String(e.config.trigger_id ?? "")} onChange={ev => set({ trigger_id: ev.target.value })} placeholder="Notifications trigger id" />
        )}
        {e.kind === "investigate" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <input style={inputStyle} value={String(e.config.question ?? "")} onChange={ev => set({ question: ev.target.value })} placeholder="Agent question" />
            {agents.length > 0 && (
              <select style={inputStyle} value={String(e.config.agent_id ?? "")}
                aria-label="Run as agent"
                onChange={ev => set({ agent_id: ev.target.value })}>
                <option value="">Run unbound (no agent)</option>
                {agents.filter(a => a.enabled).map(a => (
                  <option key={a.id} value={a.id}>Run as {a.name}</option>
                ))}
              </select>
            )}
          </div>
        )}
        {e.kind === "brief" && (
          <input style={inputStyle} value={String(e.config.subscription_id ?? "")} onChange={ev => set({ subscription_id: ev.target.value })} placeholder="briefing subscription id" />
        )}
        {e.kind === "slack_post" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {bots.length === 0 ? (
              <div className="aug-fs-xs" style={{ color: "var(--amb4)", padding: "6px 0" }}>
                No Slack bots configured — create one first, then this step can post as it.
              </div>
            ) : (
              <select style={inputStyle} value={String(e.config.bot_id ?? "")}
                aria-label="Post as bot"
                onChange={ev => set({ bot_id: ev.target.value })}>
                <option value="">Post as…</option>
                {bots.filter(b => b.enabled).map(b => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            )}
            <input style={inputStyle} value={String(e.config.channel ?? "")}
              onChange={ev => set({ channel: ev.target.value })}
              placeholder="channel — e.g. #aughor-canvas or C0…" />
            {/* Left as free text on purpose: a step whose message is
                `{"$from": "step1.answer"}` is the whole reason the chain exists, and a
                plain input is the only editor that can hold either that or a sentence. */}
            <input style={inputStyle} value={messageText(e)}
              onChange={ev => set({ message: parseMessage(ev.target.value) })}
              placeholder={'message, or {"$from": "step1.answer"} to post an earlier step'} />
          </div>
        )}
        {e.kind === "kinetic_action" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <input style={inputStyle} value={String(e.config.action_id ?? "")} onChange={ev => set({ action_id: ev.target.value })} placeholder="declared action id" />
            <input style={inputStyle} value={String((e.config as { paramsText?: string }).paramsText ?? "")} onChange={ev => set({ paramsText: ev.target.value })} placeholder='params JSON e.g. {"amount": 500}' />
          </div>
        )}
      </div>
      {onRemove && <Button variant="ghost" onClick={onRemove} className="h-auto font-normal" aria-label="Remove action" style={{ ...ghostBtn, color: "var(--red3)", padding: "6px 4px" }}>✕</Button>}
    </div>
  );
}

/**
 * The wire shape of an effect list, with the one field the editor keeps out of band.
 *
 * Declared-action params are edited as TEXT (`paramsText`) because a half-typed JSON
 * object is not a JSON object, and parsing on every keystroke would fight the typist.
 * The parse therefore happens once, here, at save — and both surfaces call this rather
 * than each remembering to strip the field. Throws with a readable message; the caller
 * decides how to show it.
 */
export function effectsForWire(effects: AutoEffect[]): AutoEffect[] {
  return effects.map(e => {
    if (e.kind !== "kinetic_action") return e;
    const cfg = e.config as Record<string, unknown> & { paramsText?: string };
    const raw = String(cfg.paramsText ?? "").trim() || "{}";
    const { paramsText: _omit, ...rest } = cfg;
    void _omit;
    let params: unknown;
    try {
      params = JSON.parse(raw);
    } catch {
      throw new Error("Declared-action params must be valid JSON");
    }
    // SPREAD, not a fresh literal. The version of this that lived in the form rebuilt
    // the effect as `{kind, config}` — which silently dropped `alias`, the key VA-4a's
    // `{"$from": "step1.ts"}` bindings point at. Saving a chained automation through the
    // form would have quietly unwired its own dataflow. Spreading keeps every field the
    // server sent, including ones this client has no opinion about.
    return { ...e, config: { ...rest, params } };
  });
}
