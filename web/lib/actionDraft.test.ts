/**
 * The action designer's draft (2026-10-09): the business decision in words, the declaration made from it, and a draft
 * that cannot be read yet saying why. The walk-through's form took a free-text type, raw parameter names and an
 * expression typed by hand, and came pre-filled with a refund rule.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEEP_ANALYSIS_EFFECT } from "@/lib/api";
import {
  EMPTY_CALL, conditionMessage, dropAction, emptyAction, keepAction, keptAction, notReady, toActionSpec, type ActionDraft,
} from "@/lib/actionDraft";

const ready: ActionDraft = {
  ...emptyAction("Order", "Order"),
  name: "Escalate to carrier",
  mark: { label: "Escalated to carrier", value: "yes", noteFrom: "reason" },
  conditions: [{ property: "status", label: "Status", negate: false, values: ["Processing"], message: "" }],
};

describe("a new action starts empty of anyone else's rule", () => {
  it("asks for a reason and marks yes — no refund parameter, no criterion, no call", () => {
    const d = emptyAction("Order", "Order");
    expect(d.asks).toEqual([{ label: "Reason", type: "text", required: true }]);
    expect(d.conditions).toEqual([]);
    expect(d.call).toEqual(EMPTY_CALL);
    expect(d.approval).toBe(false);
  });
});

describe("a draft that cannot be read yet says why", () => {
  it.each([
    [{ ...ready, name: "" }, "Name the action."],
    [{ ...ready, entity: "" }, "Choose what the action is about."],
    [{ ...ready, asks: [{ label: "", type: "text", required: true }] }, "Name question 1, or take it off."],
    [{ ...ready, asks: [{ label: "Reason", type: "text", required: true }, { label: "reason", type: "text", required: false }] },
      "Two questions are named alike (reason) — name each differently."],
    [{ ...ready, conditions: [{ ...ready.conditions[0], values: [] }] }, "Choose the status values condition 1 allows, or take it off."],
    [{ ...ready, mark: { ...ready.mark, label: " " } }, "Name the mark a press leaves on an order."],
    [{ ...ready, mark: { ...ready.mark, noteFrom: "why" } }, "The mark's note is kept from a question the action no longer asks."],
    [{ ...ready, does: "call" as const }, "Give the address the call is sent to — it begins https://."],
    [{ ...ready, does: "call" as const, call: { ...EMPTY_CALL, url: "https://x.example", body: "{nope" } }, "The message sent is not valid JSON."],
    [{ ...ready, does: "call" as const, call: { ...EMPTY_CALL, url: "https://x.example" } },
      "Say how to check the call worked — a read that finds a row once it has."],
    [{ ...ready, does: "call" as const, call: { ...EMPTY_CALL, url: "https://x.example", check: "SELECT 1", undo: "action" as const } },
      "Choose the action that takes the call back, or say it cannot be taken back."],
  ])("%#", (draft, why) => {
    expect(notReady(draft as ActionDraft)).toBe(why);
  });

  it("is ready when named, about a type, and its mark complete", () => {
    expect(notReady(ready)).toBe("");
  });
});

describe("the declaration a draft becomes", () => {
  it("is a mark on the object, its conditions as the door's expressions, its words the names a reader sees", () => {
    expect(toActionSpec(ready, ["flag_for_review"])).toEqual({
      id: "escalate_to_carrier",
      spec: {
        display_name: "Escalate to carrier", kind: "annotate", risk: "low", object_type: "Order",
        params: [
          { name: "order", display_name: "Order", kind: "object", object_type: "Order" },
          { name: "reason", display_name: "Reason", kind: "value", data_type: "VARCHAR", required: true },
        ],
        submission_criteria: [{ expr: 'order.status in ["Processing"]',
                                message: "Escalate to carrier is only for an order whose status is Processing." }],
        edits: [{ object: "order", property: "escalated_to_carrier", value: "yes", note: "{reason}" }],
      },
    });
  });

  it("never takes an id already declared, and a person's own refusal is kept as written", () => {
    const negated = { ...ready, approval: true,
      conditions: [{ ...ready.conditions[0], negate: true, values: ["Cancelled", "Returned"], message: "  Not for closed orders. " }] };
    const { id, spec } = toActionSpec(negated, ["escalate_to_carrier"]);
    expect(id).toBe("escalate_to_carrier_2");
    expect(spec.risk).toBe("high");
    expect(spec.submission_criteria).toEqual([{ expr: 'order.status not in ["Cancelled", "Returned"]', message: "Not for closed orders." }]);
    expect(conditionMessage({ ...negated.conditions[0], message: "" }, negated))
      .toBe("Escalate to carrier is only for an order whose status is not Cancelled or Returned.");
  });

  it("is a call with its check and its undo when it calls another system — and no mark", () => {
    const call = { ...ready, does: "call" as const, call: { ...EMPTY_CALL, url: "https://carrier.example/claims",
      body: '{"order": "{order}", "why": "{reason}"}', authHeader: "Authorization", secret: "s3cret",
      check: "SELECT 1 FROM claims WHERE order_id = '{order}'", undo: "action" as const, undoAction: "withdraw_claim", undoHours: "48" } };
    const { spec } = toActionSpec(call);
    expect(spec.kind).toBe("side_effect");
    expect(spec.edits).toBeUndefined();
    expect(spec.side_effects).toEqual([{ kind: "http", config: { method: "POST", url: "https://carrier.example/claims",
      body: { order: "{order}", why: "{reason}" }, auth_header: "Authorization", auth_secret: "s3cret" } }]);
    expect(spec.verification).toEqual({ sql: "SELECT 1 FROM claims WHERE order_id = '{order}'", expects: "rows" });
    expect([spec.reversibility, spec.undo]).toEqual(["compensable", { action_id: "withdraw_claim", window_hours: 48 }]);
    // What the undo asks for is answered from this action's answers, by name — and only those this action has.
    expect(toActionSpec(call, [], ["order", "reason", "claim_id"]).spec.undo?.params).toEqual({ order: "{order}", reason: "{reason}" });
  });

  it("tells a saved destination, or starts a deep analysis — each irreversible, each with no statement to verify it", () => {
    const told = toActionSpec({ ...ready, does: "tell" as const, tell: { destination: "t-desk", message: " Order {order}: {reason} " } }).spec;
    expect([told.kind, told.side_effects, told.reversibility, told.verification, told.edits]).toEqual(
      ["side_effect", [{ kind: "notify", config: { destination: "t-desk", message: "Order {order}: {reason}" } }], "irreversible", undefined, undefined]);
    const asked = toActionSpec({ ...ready, does: "analyse" as const, analysis: { question: "Why is {order} late?" } }).spec;
    expect([asked.side_effects, asked.reversibility]).toEqual([[{ kind: DEEP_ANALYSIS_EFFECT, config: { question: "Why is {order} late?" } }], "irreversible"]);
    expect(notReady({ ...ready, does: "tell" as const })).toBe("Choose who is told — a destination saved in Notifications.");
    expect(notReady({ ...ready, does: "tell" as const, tell: { destination: "t-desk", message: "" } })).toBe("Write the message they get.");
    expect(notReady({ ...ready, does: "analyse" as const })).toBe("Write the question the deep analysis asks.");
  });

  it("names the object after its type, unless a question already holds that name", () => {
    const clash = { ...ready, asks: [{ label: "Order", type: "text" as const, required: false }], mark: { ...ready.mark, noteFrom: "" } };
    expect(toActionSpec(clash).spec.params[0].name).toBe("order_object");
  });
});

describe("a draft kept in this browser", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("is kept and read back — never with its credential", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    });
    const withKey = { ...ready, call: { ...EMPTY_CALL, secret: "s3cret" } };
    expect(keepAction("c1", "s", withKey)).toBe(true);
    expect([...store.values()].join()).not.toContain("s3cret");
    expect(keptAction("c1", "s")).toEqual({ ...withKey, call: { ...withKey.call, secret: "" } });
    dropAction("c1", "s");
    expect(keptAction("c1", "s")).toBeNull();
  });
});
