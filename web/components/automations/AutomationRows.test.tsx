// @vitest-environment jsdom
/**
 * W1 — the "Only if" editor.
 *
 * Two of these guard defects this repo has already paid for once:
 *
 * * **A client that cannot SEE a field is a client that DROPS it.** The form rebuilt
 *   each effect as `{kind, config}` and silently lost `alias` — saving a chained
 *   automation unwired its own dataflow. `when` is the same shape of field.
 * * **A binding authored as free text is a step skipped at 09:00.** B1 closed that for
 *   params with a picker over what upstream steps publish; a guard typed by hand would
 *   have re-opened it one field over.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EffectRow, effectsForWire } from "@/components/automations/AutomationRows";
import type { AutoEffect } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getAutomationVocabulary: vi.fn(async () => ({
    kinds: {
      slack_post: { publishes: ["ts", "channel"], bindable: ["message", "thread_ts", "channel"] },
      notify: { publishes: [], bindable: ["message"] },
    },
    guardOps: [
      { op: "truthy", label: "is set", unary: true },
      { op: "gt", label: ">", unary: false },
    ],
  })),
}));

/** The upstream a guard reads. `slack_post` publishes two keys, which is all the
 *  subject picker needs — and it keeps a retired word out of a file with no wire
 *  reason to spell it. */
const opener: AutoEffect = { kind: "slack_post", alias: "numbers",
                             config: { bot_id: "b", channel: "#ops" } };
const post = (over: Partial<AutoEffect> = {}): AutoEffect =>
  ({ kind: "slack_post", config: { bot_id: "b", channel: "#ops" }, ...over });

function renderRow(e: AutoEffect, siblings: AutoEffect[], index: number) {
  const onChange = vi.fn();
  render(<EffectRow e={e} agents={[]} bots={[]} siblings={siblings} index={index}
    onChange={onChange} />);
  return onChange;
}

describe("the Only if editor", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("offers only what EARLIER steps publish — never free text", async () => {
    renderRow(post({ when: [{ left: { $from: "numbers.ts" }, op: "truthy" }] }),
              [opener, post()], 1);
    const subject = await screen.findByLabelText("Only if subject");
    expect([...subject.querySelectorAll("option")].map(o => o.textContent))
      .toEqual(["numbers.ts", "numbers.channel"]);
  });

  it("says 'Only if', never 'When' — the trigger node already owns that word", async () => {
    renderRow(post({ when: [{ left: { $from: "numbers.ts" }, op: "truthy" }] }),
              [opener, post()], 1);
    expect(await screen.findByText("Only if")).toBeInTheDocument();
  });

  it("shows nothing on a FIRST step, which has no upstream to ask about", async () => {
    renderRow(post(), [post()], 0);
    await waitFor(() => expect(screen.getByLabelText("Action kind")).toBeInTheDocument());
    expect(screen.queryByText("Only if")).not.toBeInTheDocument();
  });

  it("writes the clause onto `when`, never into config", async () => {
    const onChange = renderRow(post(), [opener, post()], 1);
    fireEvent.click(await screen.findByText("+ condition"));
    const next = onChange.mock.calls[0][0] as AutoEffect;
    expect(next.when).toEqual([{ left: { $from: "numbers.ts" }, op: "truthy" }]);
    expect(next.config.when).toBeUndefined();
  });

  it("hides the value field for a unary operator rather than asking for one it ignores",
    async () => {
      renderRow(post({ when: [{ left: { $from: "numbers.ts" }, op: "truthy" }] }),
                [opener, post()], 1);
      await screen.findByLabelText("Only if comparison");
      expect(screen.queryByLabelText("Only if value")).not.toBeInTheDocument();
    });

  it("asks for a value once the operator takes one", async () => {
    renderRow(post({ when: [{ left: { $from: "numbers.ts" }, op: "gt", right: 5 }] }),
              [opener, post()], 1);
    expect(await screen.findByLabelText("Only if value")).toHaveValue("5");
  });

  it("keeps a reference the picker can no longer offer, rather than silently re-pointing it",
    async () => {
      // A step renamed or deleted since. Snapping the guard to the first available
      // option would change what it tests with nobody touching it.
      renderRow(post({ when: [{ left: { $from: "gone.answer" }, op: "truthy" }] }),
                [opener, post()], 1);
      const subject = await screen.findByLabelText("Only if subject");
      expect(subject).toHaveValue("gone.answer");
      expect(screen.getByText("gone.answer (missing)")).toBeInTheDocument();
    });
});

describe("what the editor sends", () => {
  it("carries `when` through to the wire — a field a client drops is a chain it unwires",
    () => {
      const guarded = post({ when: [{ left: { $from: "numbers.ts" }, op: "truthy" }],
                             when_logic: "any" });
      expect(effectsForWire([guarded])[0].when).toEqual(guarded.when);
      expect(effectsForWire([guarded])[0].when_logic).toBe("any");
    });

  it("keeps it on the declared-action kind too — the one branch that rebuilds config", () => {
    const act: AutoEffect = {
      kind: "kinetic_action",
      config: { action_id: "a1", paramsText: '{"amount": 5}' },
      when: [{ left: { $from: "numbers.ts" }, op: "truthy" }],
    };
    const wire = effectsForWire([act])[0];
    expect(wire.when).toEqual(act.when);
    expect(wire.config.params).toEqual({ amount: 5 });
  });

  /* VA-11 — the params-erase, fifth of this subsystem's PUT-erase family and the first
   * one INSIDE an effect. An automation loaded for editing arrives with `params` and no
   * `paramsText`; reading that absence as "{}" meant fixing a typo in the NAME wiped the
   * params of every step in it. Both kinds whose params are authored as text are pinned,
   * because the shape is the table's, not either kind's. */
  it("carries stored params through when the params editor was never opened", () => {
    for (const kind of ["kinetic_action", "connection_call"] as const) {
      const untouched: AutoEffect = {
        kind,
        config: kind === "kinetic_action"
          ? { action_id: "a1", params: { amount: 5 } }
          : { grant_id: "ic_1", operation: "google.gmail.messages.list",
              params: { q: "is:unread" } },
      };
      const wire = effectsForWire([untouched])[0];
      expect(wire.config.params).toEqual(untouched.config.params);
      expect(wire.config.paramsText).toBeUndefined();
    }
  });

  it("still parses the operation params a person did type, and blames the right kind", () => {
    const call: AutoEffect = {
      kind: "connection_call",
      config: { grant_id: "ic_1", operation: "google.gmail.messages.get",
                paramsText: '{"message_id": {"$from": "inbox.id"}}' },
    };
    // A binding survives the round trip — it is the only way to author the fanned read.
    expect(effectsForWire([call])[0].config.params)
      .toEqual({ message_id: { $from: "inbox.id" } });

    const broken = { ...call, config: { ...call.config, paramsText: "{oops" } };
    // Named for ITSELF: "Declared-action params…" on a Gmail step sends the reader
    // hunting for a declared action they never wrote.
    expect(() => effectsForWire([broken])).toThrow(/Operation params/);
  });
});

/* ── DS-6 · the Otherwise editor ────────────────────────────────────────────────── */

describe("the Otherwise editor", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  /** A step the route may target: earlier, guarded, unfanned. */
  const guarded: AutoEffect = { kind: "slack_post", alias: "alerts",
    config: { bot_id: "b", channel: "#alerts" },
    when: [{ left: { $from: "numbers.ts" }, op: "truthy" }] };

  it("offers only steps this one may be the otherwise OF — earlier, guarded, unfanned", async () => {
    renderRow(post(), [opener, guarded, post()], 2);
    const picker = await screen.findByLabelText("Otherwise of");
    const options = [...picker.querySelectorAll("option")].map(o => o.value);
    // `numbers` (no guard) must not be offered; `alerts` must.
    expect(options).toEqual(["", "alerts"]);
  });

  it("does not render at all when no earlier step qualifies", () => {
    renderRow(post(), [opener, post()], 1);
    expect(screen.queryByLabelText("Otherwise of")).toBeNull();
  });

  it("writes else_of on pick, and clears it back to undefined", async () => {
    const onChange = renderRow(post(), [opener, guarded, post()], 2);
    const picker = await screen.findByLabelText("Otherwise of");
    fireEvent.change(picker, { target: { value: "alerts" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ else_of: "alerts" }));
    fireEvent.change(picker, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ else_of: undefined }));
  });

  it("keeps a target the picker cannot offer, marked missing — never silently cleared", async () => {
    // The target was deleted or lost its guard since. Re-pointing or clearing would
    // change WHEN this step runs without anyone touching it.
    renderRow(post({ else_of: "ghost" }), [opener, post()], 1);
    const picker = await screen.findByLabelText("Otherwise of");
    expect([...picker.querySelectorAll("option")].map(o => o.textContent))
      .toContain("ghost (missing)");
    expect((picker as HTMLSelectElement).value).toBe("ghost");
  });
});
