// @vitest-environment jsdom
/**
 * VA-12 — what canvas authoring PUTs, and when it thinks it has something to PUT.
 *
 * Both assertions are on pure functions rather than on a rendered rail, because both
 * defects they guard are invisible on screen: an automation that comes back enabled after
 * an edit looks exactly like one that was already enabled, and a draft that reads dirty
 * forever looks exactly like one you have genuinely changed.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  blankDraft, createPayload, DesignControls, incompleteOf, sameDraft, StepInspector,
  updatePayload,
} from "@/components/automations/AutomationAuthor";
import type { Automation, AutoCondition, AutoEffect } from "@/lib/api";

const cond = (over: Partial<AutoCondition> = {}): AutoCondition =>
  ({ kind: "schedule", config: { cron: "0 9 * * *" }, ...over });

const eff = (over: Partial<AutoEffect> = {}): AutoEffect =>
  ({ kind: "notify", config: { trigger_id: "t1" }, ...over });

/** The governed-write kind, named once. */
const DECLARED: AutoEffect["kind"] = "kinetic_action";

const automation = (over: Partial<Automation> = {}): Automation => ({
  id: "a1", conn_id: "warehouse", name: "Refund spike watch", description: "d",
  conditions: [cond()], condition_logic: "any", effects: [eff()],
  fallback_effect: null,
  // The three that a partial payload would quietly reset.
  enabled: false, paused_until: "2026-09-01T00:00:00Z", expires_at: "2026-12-01T00:00:00Z",
  max_retries: 4, retry_backoff_seconds: 90,
  // DS-7 — the fourth: a parallel chain must not come back ordered from a rename.
  scheduling: "parallel",
  created_at: "", updated_at: "", last_run_at: null, last_status: null,
  ...over,
} as Automation);

describe("the update payload", () => {
  it("carries EVERY stored field forward, not just the design", () => {
    // `CreateAutomationRequest` is the body for update as well as create, and its
    // `enabled` defaults to True. A payload of `{conditions, effects}` therefore does not
    // leave the rest alone — it re-arms a paused automation, drops its expiry and resets
    // its retry policy, all silently and all at 03:00.
    const a = automation();
    const p = updatePayload(a, { conditions: a.conditions, effects: a.effects });

    expect(p.enabled).toBe(false);
    expect(p.paused_until).toBe("2026-09-01T00:00:00Z");
    expect(p.expires_at).toBe("2026-12-01T00:00:00Z");
    expect(p.max_retries).toBe(4);
    expect(p.retry_backoff_seconds).toBe(90);
    expect(p.condition_logic).toBe("any");
    expect(p.scheduling).toBe("parallel");
    expect(p.conn_id).toBe("warehouse");
    expect(p.name).toBe("Refund spike watch");
  });

  it("sends the draft's design, not the stored one", () => {
    const a = automation();
    const p = updatePayload(a, {
      conditions: [cond({ kind: "metric", config: { monitor_id: "m9" } })],
      effects: [eff(), eff({ config: { trigger_id: "t2" } })],
    });
    expect(p.conditions).toHaveLength(1);
    expect(p.conditions[0].kind).toBe("metric");
    expect(p.effects).toHaveLength(2);
  });

  it("parses a declared action's params and keeps its alias", () => {
    // `alias` is what VA-4a's `{"$from": "step1.ts"}` bindings point AT. The version of
    // this that lived in the form rebuilt each effect as `{kind, config}` and so dropped
    // it — saving a chained automation would have unwired its own dataflow.
    const a = automation();
    const p = updatePayload(a, {
      conditions: a.conditions,
      effects: [{ kind: DECLARED, alias: "refund",
                  config: { action_id: "issue_refund", paramsText: '{"amount": 500}' } }],
    });
    expect(p.effects[0].alias).toBe("refund");
    expect(p.effects[0].config.params).toEqual({ amount: 500 });
    expect(p.effects[0].config.paramsText).toBeUndefined();
  });

  it("refuses unparseable params rather than PUTting a broken step", () => {
    const a = automation();
    expect(() => updatePayload(a, {
      conditions: a.conditions,
      effects: [{ kind: DECLARED, config: { action_id: "x", paramsText: "{oops" } }],
    })).toThrow(/valid JSON/);
  });
});

describe("the dirty check", () => {
  it("is clean against the stored design", () => {
    const a = automation();
    expect(sameDraft({ conditions: a.conditions, effects: a.effects },
                     { conditions: a.conditions, effects: a.effects })).toBe(true);
  });

  it("ignores key ORDER, which the editors reshuffle on every kind change", () => {
    // Picking a different kind and picking the original back rebuilds `config` with its
    // keys in a new order. Comparing raw JSON would call that an edit, the Save button
    // would never go away, and every "unsaved" badge on the surface would be noise.
    const one = { conditions: [cond({ config: { cron: "0 9 * * *", tz: "UTC" } })], effects: [eff()] };
    const two = { conditions: [cond({ config: { tz: "UTC", cron: "0 9 * * *" } })], effects: [eff()] };
    expect(sameDraft(one, two)).toBe(true);
  });

  it("sees a real edit", () => {
    const a = automation();
    expect(sameDraft(
      { conditions: a.conditions, effects: a.effects },
      { conditions: a.conditions, effects: [...a.effects, eff({ config: { trigger_id: "t2" } })] },
    )).toBe(false);

    expect(sameDraft(
      { conditions: a.conditions, effects: a.effects },
      { conditions: [cond({ config: { cron: "0 * * * *" } })], effects: a.effects },
    )).toBe(false);
  });
});

/* ── B2 · the dry run ───────────────────────────────────────────────────────── */

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  listUserAgents: vi.fn(async () => []),
  getSlackBots: vi.fn(async () => []),
  getAutomationVocabulary: vi.fn(async () => ({ kinds: {}, guardOps: [] })),
  updateAutomation: vi.fn(async () => ({})),
  createAutomation: vi.fn(async () => ({ id: "new-1", name: "Seeded" })),
  dryRunAutomationDraft: vi.fn(async () => ({ run: {}, graph: { nodes: [], edges: [] } })),
}));

describe("Dry run", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("previews EXACTLY what Save would send", async () => {
    // One payload builder. A second assembly here could preview a design the save does
    // not make — a preview you cannot trust is worse than none, because it is believed.
    const { dryRunAutomationDraft } = await import("@/lib/api");
    const a = automation();
    const draft = { conditions: a.conditions, effects: a.effects };
    render(<DesignControls automation={a} connId={a.conn_id} name={a.name} draft={draft}
      onDraft={() => {}} onSaved={() => {}} onPreview={() => {}} />);

    fireEvent.click(await screen.findByText("Dry run"));
    await waitFor(() => expect(dryRunAutomationDraft).toHaveBeenCalled());
    expect(vi.mocked(dryRunAutomationDraft).mock.calls[0][0])
      .toEqual(updatePayload(a, draft));
  });

  it("is offered on a design nobody has edited today", async () => {
    // Save and Discard are for a dirty draft; a preview is not. An untouched design is
    // still one nobody has ever seen run, which is the whole question.
    const a = automation();
    render(<DesignControls automation={a} connId={a.conn_id} name={a.name}
      draft={{ conditions: a.conditions, effects: a.effects }}
      onDraft={() => {}} onSaved={() => {}} onPreview={() => {}} />);
    expect(await screen.findByText("Dry run")).toBeInTheDocument();
    expect(screen.queryByText("Save design")).not.toBeInTheDocument();
  });

  it("hands the graph up rather than storing it — a preview has no id to refetch by", async () => {
    const seen: unknown[] = [];
    const a = automation();
    render(<DesignControls automation={a} connId={a.conn_id} name={a.name}
      draft={{ conditions: a.conditions, effects: a.effects }}
      onDraft={() => {}} onSaved={() => {}} onPreview={(g) => seen.push(g)} />);
    fireEvent.click(await screen.findByText("Dry run"));
    await waitFor(() => expect(seen).toHaveLength(1));
  });
});

/* ── DS-1R · canvas-first creation ──────────────────────────────────────────── */

describe("the create payload", () => {
  it("starts from the model's own defaults — a blank canvas must not invent a policy", () => {
    const p = createPayload("warehouse", "Nightly digest",
      { conditions: [cond()], effects: [eff()] });
    expect(p.conn_id).toBe("warehouse");
    expect(p.name).toBe("Nightly digest");
    expect(p.enabled).toBe(true);
    expect(p.scheduling).toBe("ordered");
    expect(p.max_retries).toBe(1);
    expect(p.fallback_effect).toBeNull();
  });

  it("the blank canvas is the trigger node alone", () => {
    const d = blankDraft();
    expect(d.conditions).toHaveLength(1);
    expect(d.effects).toHaveLength(0);
  });
});

describe("what blocks a save", () => {
  it("a stepless draft is named before the server has to refuse it", () => {
    expect(incompleteOf(blankDraft())).toContain("add at least one action");
  });

  it("a filled chain is clean", () => {
    expect(incompleteOf({ conditions: [cond()], effects: [eff()] })).toEqual([]);
  });

  it("create mode offers Create, gated on the same truth", async () => {
    render(<DesignControls automation={null} connId="warehouse" name="New one"
      draft={blankDraft()} onDraft={() => {}} onSaved={() => {}} onPreview={() => {}} />);
    const btn = await screen.findByText("Create automation");
    expect(btn).toBeDisabled();
  });

  it("a seeded create is savable and POSTs createPayload", async () => {
    const { createAutomation } = await import("@/lib/api");
    render(<DesignControls automation={null} connId="warehouse" name="Seeded"
      draft={{ conditions: [cond()], effects: [eff()] }}
      onDraft={() => {}} onSaved={() => {}} onPreview={() => {}} />);
    fireEvent.click(await screen.findByText("Create automation"));
    await waitFor(() => expect(createAutomation).toHaveBeenCalled());
    expect(vi.mocked(createAutomation).mock.calls[0][0].name).toBe("Seeded");
  });
});

/* ── DS-1R · the inspector is a LENS on the selection ───────────────────────── */

describe("StepInspector", () => {
  it("shows exactly the selected step, not the whole chain", async () => {
    const draft = {
      conditions: [cond()],
      effects: [eff({ config: { trigger_id: "t1" } }),
                eff({ alias: "second", config: { trigger_id: "t2" } })],
    };
    render(<StepInspector draft={draft} onDraft={() => {}} selection="second"
      logicLabel="all match" onClose={() => {}} />);
    expect(await screen.findByText("second")).toBeInTheDocument();
    // One EffectRow means one kind <select>; the whole-chain rail rendered one per step.
    expect(screen.getAllByDisplayValue(/Notify/i)).toHaveLength(1);
  });

  it("the trigger selection edits the WHEN half", async () => {
    const draft = { conditions: [cond()], effects: [eff()] };
    render(<StepInspector draft={draft} onDraft={() => {}} selection="__trigger"
      logicLabel="all match" onClose={() => {}} />);
    expect(await screen.findByText("When (all match)")).toBeInTheDocument();
    expect(screen.getByText("Add Trigger")).toBeInTheDocument();
  });

  it("a selection that no longer exists renders nothing rather than someone else's step", () => {
    const draft = { conditions: [cond()], effects: [eff()] };
    const { container } = render(<StepInspector draft={draft} onDraft={() => {}}
      selection="ghost" logicLabel="all match" onClose={() => {}} />);
    expect(container.querySelector("[data-testid=step-inspector]")).toBeNull();
  });
});
