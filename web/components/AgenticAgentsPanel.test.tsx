// @vitest-environment jsdom
/**
 * VA-7 — the configuration history has to be readable as a CHANGE.
 *
 * Before this, a row rendered a truncated copy of the instructions: two revisions
 * differing only in schema scope looked identical, and two differing by one sentence of a
 * long prompt looked identical too. The history could be counted but not read.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentRevision, UserAgent } from "@/lib/api";

const listAgentRevisions = vi.fn();
const restoreAgentRevision = vi.fn();
const getAgentGuardrails = vi.fn();
const setAgentGuardrailsFn = vi.fn();
const getLlmConfigFn = vi.fn();

// One mock for the module. `vi.mock` is hoisted, so a second call for the same specifier
// silently replaces the first — two of them in one file is a trap for whoever adds the
// third and wonders why their stub is ignored.
vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    listAgentRevisions: (...a: unknown[]) => listAgentRevisions(...a),
    restoreAgentRevision: (...a: unknown[]) => restoreAgentRevision(...a),
    getAgentGuardrails: (...a: unknown[]) => getAgentGuardrails(...a),
    setAgentGuardrails: (...a: unknown[]) => setAgentGuardrailsFn(...a),
    getLlmConfig: (...a: unknown[]) => getLlmConfigFn(...a),
  };
});

const { AgentConfigHistory, valueText } = await import("@/components/AgenticAgentsPanel");

const rev = (version: number, over: Partial<AgentRevision> = {}): AgentRevision => ({
  version, at: "2026-08-24T01:00:00", config_rev: `rev${version}`, author: "",
  name: "A", config: { instructions: `v${version}`, schema_scope: "public", doc_ids: [] },
  changed: ["instructions"], ...over,
});

const agent = (over: Partial<UserAgent> = {}) =>
  ({ id: "ua_1", name: "A", config_rev: "rev2", ...over } as UserAgent);

const show = (revisions: AgentRevision[]) => {
  listAgentRevisions.mockResolvedValue({ current_rev: "rev2", eval_basis: "none", revisions });
  return render(
    <AgentConfigHistory agent={agent()} onChanged={() => {}} onError={() => {}} />);
};

beforeEach(() => {
  listAgentRevisions.mockReset();
  restoreAgentRevision.mockReset();
});

describe("valueText", () => {
  it("counts a list and then names it", () => {
    expect(valueText("doc_ids", ["a", "b"])).toBe("2: a, b");
  });

  it("calls an empty binding none rather than showing a blank", () => {
    // An empty `doc_ids` is the RESTRICTIVE case, not an unset one — a blank reads as
    // "no restriction" and means the opposite.
    expect(valueText("doc_ids", [])).toBe("none");
  });

  it("distinguishes empty instructions from an unset field", () => {
    expect(valueText("instructions", "")).toBe("no instructions");
    expect(valueText("schema_scope", "")).toBe("not set");
  });
});

describe("AgentConfigHistory", () => {
  it("shows a single-revision agent instead of hiding until there are two", async () => {
    // Every agent that predated revision tracking had zero or one entry, so a panel that
    // hid below two showed those agents nothing at all.
    show([rev(1, { changed: [], config_rev: "rev2" })]);
    expect(await screen.findByText(/the configuration it started with/i)).toBeInTheDocument();
  });

  it("names the fields an edit moved", async () => {
    show([rev(2, { changed: ["instructions", "schema_scope"] }), rev(1, { changed: [] })]);
    expect(await screen.findByText("Instructions")).toBeInTheDocument();
    expect(screen.getByText("Schema scope")).toBeInTheDocument();
  });

  it("opens to the before and after of each changed field", async () => {
    show([
      rev(2, { changed: ["instructions"], config: { instructions: "after text", doc_ids: [] } }),
      rev(1, { changed: [], config: { instructions: "before text", doc_ids: [] } }),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: /what changed/i }));

    expect(screen.getByText("before text")).toBeInTheDocument();
    expect(screen.getByText("after text")).toBeInTheDocument();
  });

  it("says earlier history is not loaded rather than claiming nothing changed", async () => {
    // `changed: null` means the predecessor fell outside the window. Rendering that as
    // "no change" would tell the reader an edit did nothing.
    show([rev(9, { changed: null })]);
    expect(await screen.findByText(/earlier history not loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(/no governing change/i)).not.toBeInTheDocument();
  });

  it("offers no diff on the revision an agent started with", async () => {
    show([rev(1, { changed: [], config_rev: "rev2" })]);
    await screen.findByText(/the configuration it started with/i);
    expect(screen.queryByRole("button", { name: /what changed/i })).not.toBeInTheDocument();
  });
});

// ── VA-8 · guardrails ─────────────────────────────────────────────────────────

const { AgentGuardrailsSection } = await import("@/components/AgenticAgentsPanel");

const guardrails = (over = {}) => ({
  guardrails: { pii: "redact", max_tokens_per_run: null, ...over },
  is_default: true,
  modes: { pii: ["off", "redact", "block"] },
});

describe("AgentGuardrailsSection", () => {
  beforeEach(() => {
    getAgentGuardrails.mockReset();
    setAgentGuardrailsFn.mockReset();
    setAgentGuardrailsFn.mockResolvedValue({ guardrails: {} });
  });

  const showGuardrails = async (payload: unknown) => {
    getAgentGuardrails.mockResolvedValue(payload);
    render(<AgentGuardrailsSection agent={agent()} onError={() => {}} />);
    return screen.findByText("Guardrails");
  };

  it("offers only the modes this build can enforce", async () => {
    // The list comes from the API, which reads it off the code. A mode nothing enforces
    // appearing here is a promise the platform cannot keep.
    await showGuardrails(guardrails());
    const select = screen.getByRole("combobox");
    expect([...select.querySelectorAll("option")].map(o => o.getAttribute("value")))
      .toEqual(["off", "redact", "block"]);
  });

  it("says what the chosen mode actually does", async () => {
    await showGuardrails(guardrails({ pii: "block" }));
    expect(screen.getByText(/withheld entirely/i)).toBeInTheDocument();
  });

  it("saves a mode change on its own, without the agent's Save button", async () => {
    // A guardrail is a decision ABOUT an agent, not part of its versioned configuration.
    await showGuardrails(guardrails());
    await userEvent.selectOptions(screen.getByRole("combobox"), "block");

    expect(setAgentGuardrailsFn).toHaveBeenCalledWith("ua_1",
      { pii: "block", max_tokens_per_run: null });
  });

  it("reads an empty cap field as no cap rather than as zero", async () => {
    // Zero would arm a budget breached by the first token — an outage wearing a
    // guardrail's name, and a guaranteed 422 from the API.
    await showGuardrails(guardrails({ max_tokens_per_run: 4096 }));
    await userEvent.clear(screen.getByRole("spinbutton"));

    expect(setAgentGuardrailsFn).toHaveBeenLastCalledWith("ua_1",
      { pii: "redact", max_tokens_per_run: null });
  });

  it("says plainly when there is no ceiling", async () => {
    await showGuardrails(guardrails());
    expect(screen.getByText(/No ceiling beyond/i)).toBeInTheDocument();
  });

  it("renders nothing at all when the policy cannot be read", async () => {
    // A guardrail surface that renders defaults it did not fetch would tell an operator
    // this agent is on `redact` when nobody knows what it is on.
    getAgentGuardrails.mockResolvedValue(null);
    const { container } = render(
      <AgentGuardrailsSection agent={agent()} onError={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});

// ── charter model pin — one route for choosing a model (2026-08-25) ───────────
//
// Settings → Models is the only surface that lists models; the roster used to render a
// second, closed dropdown over the same catalogue. These tests pin the replacement: the
// field is free text, the inherited default is the Models-tab bindings and is SHOWN, and
// the paid-OpenRouter consent survives the rewrite.

const { CharterModelPin } = await import("@/components/AgenticAgentsPanel");

const llmConfig = (over: Record<string, unknown> = {}) => ({
  backend: "groq",
  models: { coder: "llama-3.3-70b", narrator: "llama-3.1-8b", fast: "llama-3.1-8b" },
  ...over,
});

describe("CharterModelPin", () => {
  beforeEach(() => {
    getLlmConfigFn.mockReset();
    getLlmConfigFn.mockResolvedValue(llmConfig());
  });

  it("renders no model list — the catalogue lives in Settings → Models alone", async () => {
    render(<CharterModelPin pinned={null} busy={false} onPin={() => {}} />);
    await screen.findByText(/Settings → Models/);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("shows the Models-tab bindings an unpinned agent inherits", async () => {
    render(<CharterModelPin pinned={null} busy={false} onPin={() => {}} />);
    expect(await screen.findByText(/coder → llama-3.3-70b/)).toBeInTheDocument();
  });

  it("pins a pasted model id", async () => {
    const onPin = vi.fn();
    render(<CharterModelPin pinned={null} busy={false} onPin={onPin} />);
    await userEvent.type(await screen.findByRole("textbox"), "my-org/pasted-model");
    await userEvent.click(screen.getByRole("button", { name: "Pin" }));
    expect(onPin).toHaveBeenCalledWith("my-org/pasted-model", false);
  });

  it("asks before pinning a paid OpenRouter model, and passes the consent through", async () => {
    getLlmConfigFn.mockResolvedValue(llmConfig({ backend: "openrouter" }));
    const onPin = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<CharterModelPin pinned={null} busy={false} onPin={onPin} />);
    await screen.findByText(/OpenRouter/);
    await userEvent.type(screen.getByRole("textbox"), "vendor/big-model");
    await userEvent.click(screen.getByRole("button", { name: "Pin" }));
    expect(onPin).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Pin" }));
    expect(onPin).toHaveBeenCalledWith("vendor/big-model", true);
    confirm.mockRestore();
  });

  it("pins a :free OpenRouter model without asking", async () => {
    getLlmConfigFn.mockResolvedValue(llmConfig({ backend: "openrouter" }));
    const onPin = vi.fn();
    const confirm = vi.spyOn(window, "confirm");
    render(<CharterModelPin pinned={null} busy={false} onPin={onPin} />);
    await screen.findByText(/OpenRouter/);
    await userEvent.type(screen.getByRole("textbox"), "vendor/small:free");
    await userEvent.click(screen.getByRole("button", { name: "Pin" }));
    expect(confirm).not.toHaveBeenCalled();
    expect(onPin).toHaveBeenCalledWith("vendor/small:free", false);
    confirm.mockRestore();
  });

  it("clears a pin back to the Models-tab bindings", async () => {
    const onPin = vi.fn();
    render(<CharterModelPin pinned="old-model" busy={false} onPin={onPin} />);
    await userEvent.click(
      await screen.findByRole("button", { name: /use models default/i }));
    expect(onPin).toHaveBeenCalledWith("", false);
  });

  it("clears via an emptied field too", async () => {
    const onPin = vi.fn();
    render(<CharterModelPin pinned="old-model" busy={false} onPin={onPin} />);
    await userEvent.clear(await screen.findByRole("textbox"));
    await userEvent.click(screen.getByRole("button", { name: /clear pin/i }));
    expect(onPin).toHaveBeenCalledWith("", false);
  });

  it("still takes a pasted id when the config cannot be read", async () => {
    // The default line degrades; the override route must not.
    getLlmConfigFn.mockRejectedValue(new Error("403"));
    const onPin = vi.fn();
    render(<CharterModelPin pinned={null} busy={false} onPin={onPin} />);
    await userEvent.type(await screen.findByRole("textbox"), "typed-anyway");
    await userEvent.click(screen.getByRole("button", { name: "Pin" }));
    expect(onPin).toHaveBeenCalledWith("typed-anyway", false);
  });
});
