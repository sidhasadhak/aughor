"use client";

/**
 * VA-12 · authoring on the canvas — Add Trigger, Add Action.
 *
 * The last structural gap against VoltAgent, and smaller than it looked: measured before
 * building, `POST /automations` and `PUT /automations/{id}` already existed, the model
 * already validated every kind at construction, and `AutomationsPanel` already had a form
 * with "+ add condition" / "+ add effect". What was missing was not authoring — it was
 * authoring WHERE THE WORK IS. You looked at the graph in one place and edited it in
 * another, so the picture never answered "what happens if I add a step here".
 *
 * So this is a rail that docks beside the canvas, in the same shape as the run canvas's
 * timeline rail: the thing you are reading on the left, an index you can act on at the
 * right. It renders `ConditionRow` / `EffectRow` — the SAME editors the form uses, moved
 * to `AutomationRows` for exactly this reason. Two editors for one model is how a picture
 * and the thing it edits come to disagree.
 *
 * ── THE PUT TAKES A WHOLE AUTOMATION ─────────────────────────────────────────
 * `CreateAutomationRequest` is the body for both create and update, and its `enabled`
 * defaults to **True**. So a payload carrying only `{conditions, effects}` does not
 * "leave the rest alone" — it RESETS them, and a paused automation would come back
 * enabled with its retry policy and expiry silently cleared. Every field is therefore
 * carried forward from the record explicitly. (This repo has already been bitten once by
 * the sibling of this trap: `POST /automations/{id}/enabled` takes `enabled` as a QUERY
 * param, so a JSON body is ignored and the default wins.)
 */
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  ConditionRow, EffectRow, effectsForWire, labelStyle, missingKeys, newCondition, newEffect,
} from "@/components/automations/AutomationRows";
import {
  getSlackBots, listUserAgents, updateAutomation,
  type Automation, type AutoCondition, type AutoEffect, type NewAutomation,
  type SlackBotSummary, type UserAgent,
} from "@/lib/api";

/** A pending draft, and whether it differs from what is stored. */
export interface Draft {
  conditions: AutoCondition[];
  effects: AutoEffect[];
}

/** Deep-equal enough for a dirty check over two small plain-JSON lists.
 *
 *  Key order matters to `JSON.stringify` and NOT to equality, so the rows are
 *  re-serialised through a sorted replacer — otherwise re-selecting a kind and picking
 *  the same values back would read as dirty forever. */
export function sameDraft(a: Draft, b: Draft): boolean {
  const norm = (v: unknown) => JSON.stringify(v, (_k, val) =>
    val && typeof val === "object" && !Array.isArray(val)
      ? Object.fromEntries(Object.entries(val as Record<string, unknown>).sort(
          ([x], [y]) => x.localeCompare(y)))
      : val);
  return norm(a) === norm(b);
}

/**
 * The full update payload for one automation with a new design.
 *
 * Exported and pure so the carry-forward is asserted directly: whether `enabled` and
 * `paused_until` survive an edit is not something a rendering test can see, and it is the
 * difference between editing an automation and silently re-arming it.
 */
export function updatePayload(a: Automation, draft: Draft): NewAutomation {
  return {
    conn_id: a.conn_id,
    name: a.name,
    description: a.description,
    conditions: draft.conditions,
    condition_logic: a.condition_logic,
    effects: effectsForWire(draft.effects),
    fallback_effect: a.fallback_effect,
    enabled: a.enabled,
    paused_until: a.paused_until,
    expires_at: a.expires_at,
    max_retries: a.max_retries,
    retry_backoff_seconds: a.retry_backoff_seconds,
  };
}

export function AutomationAuthor({ automation, draft, onDraft, onSaved }: {
  automation: Automation;
  draft: Draft;
  onDraft: (d: Draft) => void;
  /** Called after a successful save, so the canvas can refetch the SERVER's graph — which
   *  is the authority again the moment there is nothing pending. */
  onSaved: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [agents, setAgents] = useState<UserAgent[]>([]);
  const [bots, setBots] = useState<SlackBotSummary[]>([]);
  useEffect(() => { listUserAgents().then(setAgents).catch(() => setAgents([])); }, []);
  useEffect(() => { getSlackBots().then(setBots).catch(() => setBots([])); }, []);

  const stored: Draft = useMemo(
    () => ({ conditions: automation.conditions, effects: automation.effects }), [automation]);
  const dirty = !sameDraft(draft, stored);

  /** Every row the server would reject, named by position. Checked HERE rather than
   *  discovered from a 422: the error names a config key, and a key says nothing about
   *  which of five steps is carrying it. */
  const incomplete = useMemo(() => {
    const out: string[] = [];
    draft.conditions.forEach((c, i) => {
      const m = missingKeys(c);
      if (m.length) out.push(`Trigger ${i + 1} needs ${m.join(", ")}`);
    });
    draft.effects.forEach((e, i) => {
      const m = missingKeys(e);
      if (m.length) out.push(`Action ${i + 1} needs ${m.join(", ")}`);
    });
    return out;
  }, [draft]);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await updateAutomation(automation.id, updatePayload(automation, draft));
      onSaved();
    } catch (e) {
      setError((e as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const setCond = (i: number, c: AutoCondition) =>
    onDraft({ ...draft, conditions: draft.conditions.map((x, j) => (j === i ? c : x)) });
  const setEff = (i: number, e: AutoEffect) =>
    onDraft({ ...draft, effects: draft.effects.map((x, j) => (j === i ? e : x)) });

  return (
    <div style={{
      width: 340, flexShrink: 0, display: "flex", flexDirection: "column",
      border: "1px solid var(--border)", borderRadius: "var(--r-chip)",
      background: "var(--bg-1)", overflow: "hidden",
    }}>
      <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--b1)",
        display: "flex", alignItems: "center", gap: 6 }}>
        <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500 }}>Design</span>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          {draft.conditions.length} triggers · {draft.effects.length} actions
        </span>
        {dirty && (
          <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--amb4)" }}>
            unsaved
          </span>
        )}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "10px 10px 4px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
          <label style={{ ...labelStyle, marginBottom: 0 }}>
            When {automation.condition_logic === "all" ? "(all match)" : "(any match)"}
          </label>
          <Button variant="ghost" size="xs" className="aug-fs-xs"
            style={{ marginLeft: "auto", color: "var(--blue4)" }}
            onClick={() => onDraft({ ...draft, conditions: [...draft.conditions, newCondition()] })}>
            <Icon name="plus" size={11} /> Add Trigger
          </Button>
        </div>
        {draft.conditions.map((c, i) => (
          <ConditionRow key={i} c={c} onChange={cc => setCond(i, cc)}
            // The model requires at least one of each, so the last row has no remove
            // control at all rather than one that fails at save. A disabled affordance
            // still teaches that the action exists.
            onRemove={draft.conditions.length > 1
              ? () => onDraft({ ...draft,
                  conditions: draft.conditions.filter((_, j) => j !== i) })
              : undefined} />
        ))}

        <div style={{ display: "flex", alignItems: "center", gap: 6, margin: "14px 0 6px" }}>
          <label style={{ ...labelStyle, marginBottom: 0 }}>Then (in order)</label>
          <Button variant="ghost" size="xs" className="aug-fs-xs"
            style={{ marginLeft: "auto", color: "var(--blue4)" }}
            onClick={() => onDraft({ ...draft, effects: [...draft.effects, newEffect()] })}>
            <Icon name="plus" size={11} /> Add Action
          </Button>
        </div>
        {draft.effects.map((e, i) => (
          <EffectRow key={i} e={e} agents={agents} bots={bots} siblings={draft.effects} index={i}
            onChange={ee => setEff(i, ee)}
            onRemove={draft.effects.length > 1
              ? () => onDraft({ ...draft, effects: draft.effects.filter((_, j) => j !== i) })
              : undefined} />
        ))}
      </div>

      {(dirty || error) && (
        <div style={{ borderTop: "1px solid var(--b1)", padding: "8px 10px",
          display: "flex", flexDirection: "column", gap: 6 }}>
          {incomplete.length > 0 && (
            <div className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
              {incomplete.join(" · ")}
            </div>
          )}
          {error && <div className="aug-fs-xs" style={{ color: "var(--red4)" }}>{error}</div>}
          <div style={{ display: "flex", gap: 6 }}>
            <Button variant="default" size="xs"
              disabled={saving || incomplete.length > 0}
              onClick={save}>
              {saving ? "Saving…" : "Save design"}
            </Button>
            <Button variant="ghost" size="xs" disabled={saving}
              onClick={() => { setError(""); onDraft(stored); }}>
              Discard
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
