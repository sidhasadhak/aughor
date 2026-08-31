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
  dryRunAutomationDraft, getSlackBots, listUserAgents, updateAutomation,
  type Automation, type AutomationGraphData, type AutoCondition, type AutoEffect,
  type NewAutomation, type SlackBotSummary, type UserAgent,
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
    // DS-7 — carried like everything above it: the PUT is a full replace, and a
    // payload that omitted this would quietly re-serialise a parallel chain.
    scheduling: a.scheduling,
  };
}

export function AutomationAuthor({ automation, draft, onDraft, onSaved, onPreview }: {
  automation: Automation;
  draft: Draft;
  onDraft: (d: Draft) => void;
  /** Called after a successful save, so the canvas can refetch the SERVER's graph — which
   *  is the authority again the moment there is nothing pending. */
  onSaved: () => void;
  /** B2 — hand the canvas a preview graph to draw. Not stored anywhere, so the canvas
   *  holds it directly rather than refetching by id. */
  onPreview: (g: AutomationGraphData) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
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

  /** B2 — walk the DRAFT, dispatching nothing.
   *
   *  The draft, not the stored record: "try it before you arm it" is worth most on the
   *  edit you have not committed. The payload is `updatePayload`'s, so what is previewed
   *  is exactly what Save would send — a second assembly here could preview a design the
   *  save does not make.
   *
   *  Offered whether or not the draft is dirty, unlike Save/Discard: a design nobody has
   *  touched today is still one nobody has ever seen run. */
  const dryRun = async () => {
    setPreviewing(true);
    setError("");
    try {
      const { graph } = await dryRunAutomationDraft(updatePayload(automation, draft));
      onPreview(graph);
    } catch (e) {
      setError((e as Error).message || "Dry run failed");
    } finally {
      setPreviewing(false);
    }
  };

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
          {/* DS-7 — the header tells the truth about scheduling (edited on the form,
              like `condition_logic` above): "in order" on a parallel chain would teach
              a reader an order the frontier does not keep. */}
          <label style={{ ...labelStyle, marginBottom: 0 }}>
            Then {automation.scheduling === "parallel"
              ? "(in parallel — as the arrows allow)" : "(in order)"}
          </label>
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

      <div style={{ borderTop: "1px solid var(--b1)", padding: "8px 10px",
        display: "flex", flexDirection: "column", gap: 6 }}>
        {(dirty || error) && incomplete.length > 0 && (
          <div className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
            {incomplete.join(" · ")}
          </div>
        )}
        {error && <div className="aug-fs-xs" style={{ color: "var(--red4)" }}>{error}</div>}
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {dirty && (
            <>
              <Button variant="default" size="xs"
                disabled={saving || previewing || incomplete.length > 0}
                onClick={save}>
                {saving ? "Saving…" : "Save design"}
              </Button>
              <Button variant="ghost" size="xs" disabled={saving || previewing}
                onClick={() => { setError(""); onDraft(stored); }}>
                Discard
              </Button>
            </>
          )}
          <Button variant="ghost" size="xs" style={{ marginLeft: dirty ? "auto" : undefined }}
            disabled={saving || previewing || incomplete.length > 0}
            onClick={dryRun}>
            {previewing ? "Walking…" : "Dry run"}
          </Button>
        </div>
      </div>
    </div>
  );
}
