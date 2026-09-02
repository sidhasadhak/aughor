"use client";

/**
 * VA-12 → DS-1R · authoring is the canvas; these are its two satellites.
 *
 * This file used to render a 340px rail that edited EVERY trigger and step beside the
 * canvas. That rail predates the node faces growing real editors (inline fields, bind
 * chips, guard strips, ports) — by DS-7 it was a second full editor of the same draft,
 * and the user named the cost precisely: "layer after layer… the main workflow is
 * getting out of focus" (2026-09-02). The workflow is now the one primary editor, and
 * what survives of the rail is exactly what the canvas cannot carry:
 *
 * - `DesignControls` — Save · Discard · Dry run · the dirty/incomplete truth, docked in
 *   the HEADER so it never scrolls away and costs no width.
 * - `StepInspector` — the richer widgets (kind selects, "Post as…", agent pickers,
 *   guard editors) for ONE selected node at a time, floating over the canvas edge.
 *   It reads the selection and writes the same draft: the design panel is a lens on
 *   the workflow, never a second author.
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
  ConditionRow, EffectRow, effectsForWire, labelStyle, missingKeys, newCondition,
} from "@/components/automations/AutomationRows";
import {
  createAutomation, dryRunAutomationDraft, getSlackBots, listUserAgents, updateAutomation,
  type Automation, type AutomationGraphData, type AutoCondition, type AutoEffect,
  type NewAutomation, type SlackBotSummary, type UserAgent,
} from "@/lib/api";

/** A pending draft, and whether it differs from what is stored. */
export interface Draft {
  conditions: AutoCondition[];
  effects: AutoEffect[];
}

/** The draft a blank canvas starts from: the trigger node with one schedule, no steps
 *  yet. One condition rather than zero because the model requires it and because an
 *  automation IS "when this, do that" — the when half always exists. */
export function blankDraft(): Draft {
  return { conditions: [newCondition()], effects: [] };
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

/** The payload a canvas-born automation is created with. The defaults are the model's
 *  own (enabled, ordered, one retry) — a blank canvas must not invent a policy. */
export function createPayload(connId: string, name: string, draft: Draft): NewAutomation {
  return {
    conn_id: connId,
    name,
    description: "",
    conditions: draft.conditions,
    condition_logic: "all",
    effects: effectsForWire(draft.effects),
    fallback_effect: null,
    enabled: true,
    paused_until: null,
    expires_at: null,
    max_retries: 1,
    retry_backoff_seconds: 30,
    scheduling: "ordered",
  };
}

/** Every row the server would reject, named by position — checked here rather than
 *  discovered from a 422, because the error names a config key and a key says nothing
 *  about which of five steps is carrying it. A stepless draft is named too: the model
 *  requires at least one action, and a blank canvas should say so before Save does. */
export function incompleteOf(draft: Draft): string[] {
  const out: string[] = [];
  draft.conditions.forEach((c, i) => {
    const m = missingKeys(c);
    if (m.length) out.push(`Trigger ${i + 1} needs ${m.join(", ")}`);
  });
  draft.effects.forEach((e, i) => {
    const m = missingKeys(e);
    if (m.length) out.push(`Action ${i + 1} needs ${m.join(", ")}`);
  });
  if (draft.effects.length === 0) out.push("add at least one action");
  return out;
}

/**
 * Save · Discard · Dry run — the design's verbs, docked in the canvas header.
 *
 * `automation` is null while the canvas is authoring something that does not exist yet
 * (canvas-first creation): Save then POSTs `createPayload` and hands the new record up,
 * and Dry run walks the same unsaved payload — `POST /automations/dry-run` has taken an
 * unsaved chain since B2, which is what made "try it before it exists" free here.
 */
export function DesignControls({ automation, connId, name, draft, onDraft, onSaved, onPreview }: {
  automation: Automation | null;
  /** Create mode: the connection the new automation belongs to. */
  connId: string;
  /** Create mode: the name the header input currently holds. */
  name: string;
  draft: Draft;
  onDraft: (d: Draft) => void;
  /** After a successful save. Create mode passes the NEW record so the caller can leave
   *  create mode and let the server's copy become the authority. */
  onSaved: (created?: Automation) => void;
  /** B2 — hand the canvas a preview graph to draw. Not stored anywhere, so the canvas
   *  holds it directly rather than refetching by id. */
  onPreview: (g: AutomationGraphData) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");

  const stored: Draft | null = useMemo(
    () => automation
      ? { conditions: automation.conditions, effects: automation.effects }
      : null,
    [automation]);
  const dirty = stored ? !sameDraft(draft, stored) : true;
  const incomplete = useMemo(() => incompleteOf(draft), [draft]);

  const payload = (): NewAutomation =>
    automation ? updatePayload(automation, draft)
               : createPayload(connId, name.trim() || "Untitled automation", draft);

  /** B2 — walk the DRAFT, dispatching nothing. The payload is exactly what Save would
   *  send — a second assembly here could preview a design the save does not make.
   *  Offered whether or not the draft is dirty: a design nobody has touched today is
   *  still one nobody has ever seen run. */
  const dryRun = async () => {
    setPreviewing(true);
    setError("");
    try {
      const { graph } = await dryRunAutomationDraft(payload());
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
      if (automation) {
        await updateAutomation(automation.id, payload());
        onSaved();
      } else {
        onSaved(await createAutomation(payload()));
      }
    } catch (e) {
      setError((e as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}
         data-testid="design-controls">
      {/* The blocking truth rides the row, compact; the full list is on the button's
          tooltip. An empty draft's "add at least one action" is a starting state, not
          an error — it shows dimmer. */}
      {(error || (dirty && incomplete.length > 0)) && (
        <span className="aug-fs-xs"
          title={incomplete.join(" · ")}
          style={{ color: error ? "var(--red4)" : "var(--amb4)",
                   overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                   maxWidth: 260 }}>
          {error || incomplete[0]}{!error && incomplete.length > 1 ? ` · +${incomplete.length - 1}` : ""}
        </span>
      )}
      {dirty && !automation && null /* create mode is always "dirty"; no chip needed */}
      {dirty && automation && (
        <span className="aug-fs-xs" style={{ color: "var(--amb4)" }}>unsaved</span>
      )}
      {dirty && automation && (
        <Button variant="ghost" size="xs" disabled={saving || previewing}
          onClick={() => { setError(""); if (stored) onDraft(stored); }}>
          Discard
        </Button>
      )}
      <Button variant="ghost" size="xs"
        disabled={saving || previewing || incomplete.length > 0}
        title={incomplete.length ? incomplete.join(" · ") : "Walk the chain — inert, nothing is sent"}
        onClick={dryRun}>
        {previewing ? "Walking…" : "Dry run"}
      </Button>
      {(dirty || !automation) && (
        <Button variant="default" size="xs"
          disabled={saving || previewing || incomplete.length > 0}
          title={incomplete.length ? incomplete.join(" · ") : undefined}
          onClick={save}>
          {saving ? "Saving…" : automation ? "Save design" : "Create automation"}
        </Button>
      )}
    </div>
  );
}

/**
 * The selected node's editor, floating at the canvas edge — the design panel as a LENS.
 *
 * Shows exactly one thing: the trigger node's conditions, or one step's full widget set
 * (kind select, "Post as…", agent picker, guards, for-each). It reads the canvas's
 * selection and writes the canvas's draft; deselecting closes it. This is the half of
 * the old rail the node faces genuinely cannot carry — selects and pickers need more
 * room than a node row — scoped to the one node being asked about.
 */
export function StepInspector({ draft, onDraft, selection, logicLabel, onClose }: {
  draft: Draft;
  onDraft: (d: Draft) => void;
  /** "__trigger" or a step alias (`step3`, or an explicit alias). */
  selection: string;
  /** "all match" / "any match" — the automation's own words for the trigger header. */
  logicLabel: string;
  onClose: () => void;
}) {
  const [agents, setAgents] = useState<UserAgent[]>([]);
  const [bots, setBots] = useState<SlackBotSummary[]>([]);
  useEffect(() => { listUserAgents().then(setAgents).catch(() => setAgents([])); }, []);
  useEffect(() => { getSlackBots().then(setBots).catch(() => setBots([])); }, []);

  const aliasAt = (e: AutoEffect, i: number) => (e.alias?.trim() ? e.alias.trim() : `step${i + 1}`);
  const index = selection === "__trigger"
    ? -1
    : draft.effects.findIndex((e, i) => aliasAt(e, i) === selection);
  if (selection !== "__trigger" && index < 0) return null;

  const setCond = (i: number, c: AutoCondition) =>
    onDraft({ ...draft, conditions: draft.conditions.map((x, j) => (j === i ? c : x)) });
  const setEff = (i: number, e: AutoEffect) =>
    onDraft({ ...draft, effects: draft.effects.map((x, j) => (j === i ? e : x)) });

  return (
    <div
      data-testid="step-inspector"
      style={{
        position: "absolute", top: 8, right: 8, bottom: 8, width: 312, zIndex: 5,
        display: "flex", flexDirection: "column",
        border: "1px solid var(--border)", borderRadius: "var(--r3)",
        background: "var(--bg-1)", boxShadow: "var(--shadow-md)", overflow: "hidden",
      }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
        padding: "8px 10px", borderBottom: "1px solid var(--b1)" }}>
        <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500 }}>
          {selection === "__trigger" ? `When (${logicLabel})` : selection}
        </span>
        <Button variant="ghost" size="icon-xs" aria-label="Close the inspector"
          style={{ marginLeft: "auto" }} onClick={onClose}>
          <Icon name="close" size={12} />
        </Button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "10px 10px 6px" }}>
        {selection === "__trigger" ? (
          <>
            {draft.conditions.map((c, i) => (
              <ConditionRow key={i} c={c} onChange={cc => setCond(i, cc)}
                // The model requires at least one, so the last row has no remove
                // control at all rather than one that fails at save.
                onRemove={draft.conditions.length > 1
                  ? () => onDraft({ ...draft,
                      conditions: draft.conditions.filter((_, j) => j !== i) })
                  : undefined} />
            ))}
            <Button variant="ghost" size="xs" className="aug-fs-xs"
              style={{ color: "var(--blue4)" }}
              onClick={() => onDraft({ ...draft, conditions: [...draft.conditions, newCondition()] })}>
              <Icon name="plus" size={11} /> Add Trigger
            </Button>
          </>
        ) : (
          <>
            <label style={{ ...labelStyle }}>everything this step takes</label>
            <EffectRow e={draft.effects[index]} agents={agents} bots={bots}
              siblings={draft.effects} index={index}
              onChange={ee => setEff(index, ee)}
              onRemove={undefined /* removal lives on the node face — one door */} />
          </>
        )}
      </div>
    </div>
  );
}
