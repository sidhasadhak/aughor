// @vitest-environment jsdom
/**
 * VA-12 — what canvas authoring PUTs, and when it thinks it has something to PUT.
 *
 * Both assertions are on pure functions rather than on a rendered rail, because both
 * defects they guard are invisible on screen: an automation that comes back enabled after
 * an edit looks exactly like one that was already enabled, and a draft that reads dirty
 * forever looks exactly like one you have genuinely changed.
 */
import { describe, expect, it } from "vitest";

import { sameDraft, updatePayload } from "@/components/automations/AutomationAuthor";
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
