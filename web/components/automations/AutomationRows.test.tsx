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

import { BindingCast, EffectRow, effectsForWire } from "@/components/automations/AutomationRows";
import { getIntegrationConnections, getIntegrationOperations } from "@/lib/api";
import type { AutoEffect } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  // DS-11 — the two SERVED rosters the integration editor reads. Mocked rather than
  // stubbed with a shape of this file's own invention: what is asserted below is that
  // the row renders what the server said, so the fixture has to be the server's shape.
  getIntegrationConnections: vi.fn(async () => [
    { id: "ic_g", provider: "google", user_id: "", scopes: "", account: "sales@example.com",
      token_type: "Bearer", expires_at: null, status: "active",
      created_at: "", updated_at: "" },
    { id: "ic_dead", provider: "slack", user_id: "", scopes: "", account: "Acme",
      token_type: "Bearer", expires_at: null, status: "revoked",
      created_at: "", updated_at: "" },
    { id: "ic_stale", provider: "google", user_id: "", scopes: "", account: "ops@example.com",
      token_type: "Bearer", expires_at: null, status: "needs_reconnect",
      created_at: "", updated_at: "" },
  ]),
  getIntegrationOperations: vi.fn(async () => [
    { id: "gmail.messages.list", provider: "google", label: "Gmail · list messages",
      description: "", writes: false, publishes: ["items", "count"], list_keys: ["items"],
      availability: "ready", reason: "",
      params: [
        { name: "q", label: "Search", type: "string", required: false,
          placeholder: "is:unread", bindable: true },
        { name: "maxResults", label: "Limit", type: "number", required: false,
          placeholder: "", bindable: false },
      ] },
    { id: "gmail.messages.send", provider: "google", label: "Gmail · send",
      description: "", writes: true, publishes: ["id"], list_keys: [],
      availability: "needs_setup",
      reason: "this grant does not carry gmail.send — reconnect google and consent to it",
      params: [] },
  ]),
  // The allowlisted MCP servers with their stored rosters — the server's shape.
  listMcpServers: vi.fn(async () => ({ servers: [
    { id: "srv_jira", name: "Jira", transport: "http", command: "", args: [], env: {}, url: "",
      has_auth: true, enabled: true, created_at: "", updated_at: "", discovered_at: "",
      tool_count: 3, callable_count: 1, granted_count: 1, tools: [
        { server_id: "srv_jira", name: "search_issues", title: "Search issues",
          description: "Find issues by JQL.", disposition: "callable", reason: "",
          read_only_hint: true, destructive_hint: null, discovered_at: "",
          grant_state: "none", grant_reason: "", granted_by: "", granted_at: "", grant_note: "",
          input_schema: { type: "object", required: ["jql"], properties: {
            jql: { type: "string", description: "a JQL query" },
            limit: { type: "integer" } } } },
        { server_id: "srv_jira", name: "create_issue", title: "Create issue", description: "",
          disposition: "refused_mutating", reason: "declares writes", read_only_hint: false,
          destructive_hint: null, discovered_at: "", grant_state: "none", grant_reason: "",
          granted_by: "", granted_at: "", grant_note: "", input_schema: {} },
        { server_id: "srv_jira", name: "add_comment", title: "Add comment", description: "",
          disposition: "refused_mutating", reason: "declares writes", read_only_hint: false,
          destructive_hint: null, discovered_at: "", grant_state: "active", grant_reason: "",
          granted_by: "ops@example.com", granted_at: "", grant_note: "", input_schema: {} },
      ] },
  ] })),
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

  /* The params-erase, fifth of this subsystem's PUT-erase family and the first one
   * INSIDE an effect. An automation loaded for editing arrives with `params` and no
   * `paramsText`; reading that absence as "{}" meant fixing a typo in the NAME wiped the
   * params of every declared-action step in it. */
  it("carries stored params through when the params editor was never opened", () => {
    const untouched: AutoEffect = {
      kind: "kinetic_action",
      config: { action_id: "a1", params: { amount: 5 } },
    };
    const wire = effectsForWire([untouched])[0];
    expect(wire.config.params).toEqual({ amount: 5 });
    expect(wire.config.paramsText).toBeUndefined();
  });

  it("leaves a kind with a generated params form entirely alone", () => {
    /* `integration_call` builds its params from the operation's declared inputs, so they
     * are already a real object. Running it through the TEXT path would stringify a
     * structure that was never a string — which is why it is absent from the table that
     * drives that path, and why this asserts the object survives untouched. */
    const generated: AutoEffect = {
      kind: "integration_call",
      config: { connection_id: "ic_1", operation: "gmail.messages.list",
                params: { q: "is:unread", max_results: 10 } },
    };
    const wire = effectsForWire([generated])[0];
    expect(wire.config.params).toEqual({ q: "is:unread", max_results: 10 });
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

/* ── DS-11 · "Use an integration" ────────────────────────────────────────────────── */

describe("the integration editor", () => {
  const step = (config: Record<string, unknown> = {}): AutoEffect =>
    ({ kind: "integration_call", alias: "inbox", config });

  // `clearAllMocks` clears CALLS, not implementations — a `mockResolvedValue` set by one
  // test outlives it. Re-establishing the default here rather than relying on the factory
  // is what keeps these order-independent; the empty-grants case below overrides it and
  // this puts it back.
  const defaultGrants = vi.mocked(getIntegrationConnections).getMockImplementation()!;
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getIntegrationConnections).mockImplementation(defaultGrants);
  });

  it("says the same sentence the palette does when nothing is connected", async () => {
    vi.mocked(getIntegrationConnections).mockResolvedValue([]);
    render(<EffectRow e={step()} agents={[]} bots={[]} onChange={vi.fn()} />);
    expect(await screen.findByText(/No connected accounts/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Act as")).toBeNull();
  });

  it("offers only grants that can actually be spent", async () => {
    render(<EffectRow e={step()} agents={[]} bots={[]} onChange={vi.fn()} />);
    const picker = await screen.findByLabelText("Act as");
    // A revoked grant is dead and a needs_reconnect one is a refusal the provider has
    // already made — offering either is offering something that cannot work.
    expect([...picker.querySelectorAll("option")].map(o => o.value))
      .toEqual(["", "ic_g"]);
    expect(screen.getByText("google · sales@example.com")).toBeInTheDocument();
  });

  it("fetches the operations for THAT grant, and renders its declared ports", async () => {
    render(<EffectRow e={step({ connection_id: "ic_g", operation: "gmail.messages.list" })}
      agents={[]} bots={[]} onChange={vi.fn()} />);
    await waitFor(() => expect(getIntegrationOperations).toHaveBeenCalledWith("ic_g"));
    expect(await screen.findByLabelText("Search")).toBeInTheDocument();
    expect(screen.getByLabelText("Limit")).toBeInTheDocument();
  });

  it("renders the server's own sentence about a grant that lacks the scope", async () => {
    render(<EffectRow e={step({ connection_id: "ic_g", operation: "gmail.messages.send" })}
      agents={[]} bots={[]} onChange={vi.fn()} />);
    expect(await screen.findByText(/does not carry gmail.send/)).toBeInTheDocument();
  });

  it("keeps a binding as an object rather than stringifying it", async () => {
    // `String({$from: …})` renders "[object Object]" — an editor inviting someone to
    // overwrite the wiring that makes the chain work.
    const onChange = vi.fn();
    render(<EffectRow e={step({ connection_id: "ic_g", operation: "gmail.messages.list",
                                params: { q: { $from: "step1.answer" } } })}
      agents={[]} bots={[]} onChange={onChange} />);
    const field = await screen.findByLabelText("Search");
    expect(field).toHaveValue('{"$from":"step1.answer"}');
    fireEvent.change(field, { target: { value: '{"$from": "step1.q"}' } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      config: expect.objectContaining({ params: { q: { $from: "step1.q" } } }),
    }));
  });

  it("keeps a grant the picker cannot offer, marked missing — never silently cleared", async () => {
    // Revoked since, or someone else's. A `<select>` whose value matches no option
    // renders as the placeholder, so the step would READ as one nobody configured and
    // the next save would make that true.
    render(<EffectRow e={step({ connection_id: "ic_gone", operation: "gmail.messages.list" })}
      agents={[]} bots={[]} onChange={vi.fn()} />);
    const picker = await screen.findByLabelText("Act as");
    expect([...picker.querySelectorAll("option")].map(o => o.textContent))
      .toContain("ic_gone (missing)");
    expect((picker as HTMLSelectElement).value).toBe("ic_gone");
    expect(screen.getByText(/an account you can no longer pick/)).toBeInTheDocument();
  });

  it("still shows an authored step when NOTHING is connected any more", async () => {
    vi.mocked(getIntegrationConnections).mockResolvedValue([]);
    render(<EffectRow e={step({ connection_id: "ic_gone", operation: "gmail.messages.list" })}
      agents={[]} bots={[]} onChange={vi.fn()} />);
    // The "connect one" sentence is for an EMPTY step; on a configured one it would hide
    // what the step actually says and invite a save that drops it.
    expect(await screen.findByLabelText("Act as")).toHaveValue("ic_gone");
    expect(screen.queryByText(/No connected accounts/)).toBeNull();
  });

  it("clears the operation and its params when the grant changes", async () => {
    // Params belong to an operation; carrying them across would send one operation's
    // inputs to another, which the server refuses as undeclared — after the save.
    const onChange = vi.fn();
    render(<EffectRow e={step({ connection_id: "ic_g", operation: "gmail.messages.list",
                                params: { q: "is:unread" } })}
      agents={[]} bots={[]} onChange={onChange} />);
    fireEvent.change(await screen.findByLabelText("Act as"), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      config: expect.objectContaining({ connection_id: "", operation: "", params: {} }),
    }));
  });
});


// ── §3.8a · the cast picker ──────────────────────────────────────────────────────────

describe("BindingCast", () => {
  const cast = () => screen.queryByLabelText("convert the bound value");

  it("renders NOTHING for a plain value", () => {
    // The reason it can live beside a free-text field at all. A control on every field
    // would be clutter on the majority that will never hold a binding.
    render(<BindingCast value="just a sentence" onChange={() => {}} />);
    expect(cast()).toBeNull();
  });

  it("renders nothing for an array, which is a value and not wiring", () => {
    render(<BindingCast value={["a", "b"]} onChange={() => {}} />);
    expect(cast()).toBeNull();
  });

  it("appears when the field holds a binding", () => {
    render(<BindingCast value={{ $from: "step1.answer" }} onChange={() => {}} />);
    expect(cast()).not.toBeNull();
  });

  it("shows the cast already declared", () => {
    render(<BindingCast value={{ $from: "s.count", $as: "text" }} onChange={() => {}} />);
    expect((cast() as HTMLSelectElement).value).toBe("text");
  });

  it("writes $as without disturbing the reference", () => {
    const seen: unknown[] = [];
    render(<BindingCast value={{ $from: "s.count" }} onChange={v => seen.push(v)} />);
    fireEvent.change(cast()!, { target: { value: "text" } });
    expect(seen[0]).toEqual({ $from: "s.count", $as: "text" });
  });

  it("DELETES $as when cleared, rather than setting an empty string", () => {
    // The design decision. `CASTS` has no empty member and `wearsMarker` accepts `$from`
    // plus at most `$as`, so `$as: ""` would be a third state — read as wiring by the
    // client and refused as a conversion by the server.
    const seen: Record<string, unknown>[] = [];
    render(<BindingCast value={{ $from: "s.count", $as: "text" }}
                       onChange={v => seen.push(v as Record<string, unknown>)} />);
    fireEvent.change(cast()!, { target: { value: "" } });
    expect(seen[0]).toEqual({ $from: "s.count" });
    expect("$as" in seen[0]).toBe(false);
  });

  it("works on a $from_any join too", () => {
    render(<BindingCast value={{ $from_any: ["a.x", "b.x"] }} onChange={() => {}} />);
    expect(cast()).not.toBeNull();
  });
});

/**
 * DS-19 — the Trusted query step's two authoring modes.
 *
 * The property that matters is EXCLUSIVITY on the wire. A step carrying both a picked id
 * and typed SQL has two answers to "what runs", and the server refuses it — so a switch
 * that leaves the other side's keys behind produces a 422 the author cannot see the cause
 * of, from a control that looked like it worked.
 */
describe("the Trusted query editor", () => {
  const tq = (config: Record<string, unknown> = {}): AutoEffect =>
    ({ kind: "trusted_query", config });

  it("opens on PICK for a step that names a query", () => {
    render(<EffectRow e={tq({ query_id: "tq_vetted" })} agents={[]} bots={[]}
      onChange={vi.fn()} />);
    expect(screen.getByPlaceholderText("trusted query id")).toHaveValue("tq_vetted");
    expect(screen.queryByPlaceholderText("SELECT …")).not.toBeInTheDocument();
  });

  it("opens on WRITE for a step whose query was authored here", () => {
    // `authored_query_id` is what the save path hands back, so re-opening the rail lands
    // on the mode the author last used rather than on an id they never typed.
    render(<EffectRow e={tq({ query_id: "tq_x", authored_query_id: "tq_x" })}
      agents={[]} bots={[]} onChange={vi.fn()} />);
    expect(screen.getByPlaceholderText("SELECT …")).toBeInTheDocument();
  });

  it("switching to Write SQL CLEARS the picked id, and back again clears the SQL", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <EffectRow e={tq({ query_id: "tq_vetted" })} agents={[]} bots={[]}
        onChange={onChange} />);

    fireEvent.click(screen.getByText("Write SQL"));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      config: expect.objectContaining({ query_id: undefined }),
    }));

    rerender(<EffectRow e={tq({ sql: "SELECT 1", question: "q" })} agents={[]} bots={[]}
      onChange={onChange} />);
    fireEvent.click(screen.getByText("Pick a query"));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      config: expect.objectContaining({ sql: undefined, question: undefined }),
    }));
  });

  it("says what saving will DO, and who will see it, before the save", () => {
    // Both facts belong in front of the person while they type: finding out afterwards
    // is how a governance step reads as an obstacle rather than a guarantee.
    render(<EffectRow e={tq({ sql: "SELECT 1", question: "q" })} agents={[]} bots={[]}
      onChange={vi.fn()} />);
    expect(screen.getByText(/runs this once to verify it/i)).toBeInTheDocument();
    expect(screen.getByText(/private to this automation until you promote it/i))
      .toBeInTheDocument();
  });
});


describe("the MCP call editor", () => {
  it("offers the tools a step may call, and writes server, tool and typed arguments", async () => {
    // Before this the step could be placed and configured nowhere: no form set its server
    // or its tool. A refused (mutating) tool is not offered; one a person granted is.
    const onChange = vi.fn();
    const { rerender } = render(<EffectRow e={{ kind: "mcp_call", config: {} }} agents={[]}
      bots={[]} onChange={onChange} />);
    fireEvent.change(await screen.findByLabelText("MCP server"), { target: { value: "srv_jira" } });
    const picked = onChange.mock.lastCall![0] as AutoEffect;
    expect(picked.config).toEqual({ server_id: "srv_jira", tool: "", arguments: {} });

    rerender(<EffectRow e={picked} agents={[]} bots={[]} onChange={onChange} />);
    const tools = await screen.findByLabelText("MCP tool");
    expect([...tools.querySelectorAll("option")].map(o => o.textContent))
      .toEqual(["Which tool…", "Search issues", "Add comment (granted)"]);
    fireEvent.change(tools, { target: { value: "search_issues" } });
    const withTool = onChange.mock.lastCall![0] as AutoEffect;

    rerender(<EffectRow e={withTool} agents={[]} bots={[]} onChange={onChange} />);
    fireEvent.change(await screen.findByLabelText("limit"), { target: { value: "25" } });
    expect((onChange.mock.lastCall![0] as AutoEffect).config).toEqual(
      { server_id: "srv_jira", tool: "search_issues", arguments: { limit: 25 } });
    expect(screen.getByLabelText("jql")).toHaveAttribute("placeholder", "jql — a JQL query");
  });
});
