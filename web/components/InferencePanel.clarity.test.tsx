// @vitest-environment jsdom
/**
 * Settings ▸ Models, redone to CLARITY (2026-10-12). Pinned: the figures read the SAVED binding (provider, roles
 * bound, fallback, keys); "Needs you" holds a provider with no key, a role with no model, a fallback that would be
 * skipped, and a bound model the ledger saw with no price — each with what resolves it — and says so when the
 * prices could not be checked. Three roles describing the same model say it once.
 */
import { render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getLlmConfig: vi.fn(), setLlmConfig: vi.fn(), getLlmModels: vi.fn(), getUsageReport: vi.fn(),
  testLlmConfig: vi.fn(), cacheProbe: vi.fn(), addLlmModel: vi.fn(), removeLlmModel: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { InferencePanel } from "./InferencePanel";

const CAP = { cache_mode: "explicit_breakpoint", tooling: "native_tools", structured_output: "native",
  token_accounting: "exact", max_context: 32768, privacy_class: "public_api", cost: "per_token" };
const BOUND = { coder: "claude-sonnet-5-5", narrator: "claude-haiku-5-5", fast: "claude-haiku-5-5" };

function config(over: Record<string, unknown> = {}) {
  return {
    backend: "anthropic", models: BOUND, models_set: BOUND, base_urls: {}, base_urls_set: {},
    keys_set: { anthropic: true, openrouter: true }, keys_state: { anthropic: "set", openrouter: "set" },
    capabilities: { coder: CAP, narrator: CAP, fast: CAP },
    backends: ["anthropic", "openrouter", "ollama"], needs_key: ["anthropic", "openrouter"], local_backends: ["ollama"],
    default_models: {}, json_mode: {}, json_mode_backends: [],
    fallback: { backend: "openrouter", model: "deepseek/deepseek-v4.1-flash", chain: ["openrouter"], active: false, env_pinned: false },
    ...over,
  };
}
const usage = (rows: Array<Record<string, unknown>> = []) => ({ axes: ["provider", "model"], total_calls: 10, rows });

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.getLlmConfig.mockResolvedValue(config());
  api.getLlmModels.mockResolvedValue({ backend: "anthropic", models: [], custom: [], live: true, live_count: 0, error: "", defaults: {} });
  api.getUsageReport.mockResolvedValue(usage([
    { provider: "anthropic", model: "claude-sonnet-5-5", calls: 5, unpriced_calls: 0 },
  ]));
});

const value = (id: string) => screen.getByTestId(`${id}-value`);

describe("Settings ▸ Models", () => {
  it("opens on what is in force: the provider, the roles bound, the fallback, the keys", async () => {
    render(<InferencePanel />);
    await waitFor(() => expect(value("fig-provider")).toHaveTextContent("Anthropic"));
    expect(screen.getByTestId("fig-provider")).toHaveTextContent("prompts leave this machine");
    expect(value("fig-roles")).toHaveTextContent("3 of 3");
    expect(screen.getByTestId("fig-roles")).toHaveTextContent("claude-sonnet-5-5 · claude-haiku-5-5");
    expect(value("fig-fallback")).toHaveTextContent("OpenRouter");
    expect(screen.getByTestId("fig-fallback")).toHaveTextContent("deepseek/deepseek-v4.1-flash");
    expect(value("fig-keys")).toHaveTextContent("2 of 2");
  });

  it("says nothing needs you when every role has a model and the provider a key", async () => {
    render(<InferencePanel />);
    await waitFor(() => expect(screen.getByTestId("models-needs")).toHaveTextContent(
      "Nothing needs you · every role has a model and the provider a key"));
    expect(screen.getByTestId("models-needs")).toHaveAttribute("data-waiting", "false");
  });

  it("needs you for a provider with no key, a role with no model and a fallback with none", async () => {
    api.getLlmConfig.mockResolvedValue(config({
      keys_set: { anthropic: false, openrouter: true }, keys_state: { anthropic: "unset", openrouter: "set" },
      models: { ...BOUND, narrator: "" }, models_set: { ...BOUND, narrator: "" },
      fallback: { backend: "openrouter", model: "", chain: ["openrouter"], active: false, env_pinned: false },
    }));
    render(<InferencePanel />);
    const key = await screen.findByTestId("needs-key");
    expect(key).toHaveTextContent("Anthropic has no API key");
    expect(within(key).getByRole("button", { name: "Paste a key" })).toBeInTheDocument();
    expect(screen.getByTestId("needs-roles")).toHaveTextContent("1 role has no model · Narrator");
    expect(screen.getByTestId("needs-fallback-model")).toHaveTextContent("The fallback, OpenRouter, has no model");
    expect(screen.getByTestId("fig-provider")).toHaveTextContent("no key");
    expect(value("fig-roles")).toHaveTextContent("2 of 3");
  });

  it("needs you for a bound model the ledger saw with no price — its spend is unknown, not zero", async () => {
    api.getUsageReport.mockResolvedValue(usage([
      { provider: "anthropic", model: "claude-haiku-5-5", calls: 40, unpriced_calls: 12 },
      { provider: "openrouter", model: "someone/else", calls: 9, unpriced_calls: 9 },   // not bound: Spend's business
    ]));
    render(<InferencePanel />);
    const row = await screen.findByTestId("needs-price");
    expect(row).toHaveTextContent("claude-haiku-5-5 has no price");
    expect(row).toHaveTextContent("12 calls unpriced");
    expect(row).not.toHaveTextContent("someone/else");
    expect(within(row).getByRole("button", { name: "Open Spend" })).toBeInTheDocument();
  });

  it("says the prices were not checked when the ledger cannot be read", async () => {
    api.getUsageReport.mockRejectedValue(new Error("Failed to fetch usage report"));
    render(<InferencePanel />);
    await waitFor(() => expect(screen.getByTestId("models-needs")).toHaveTextContent("prices not checked"));
  });

  it("says once what three roles bound to the same kind of model share", async () => {
    render(<InferencePanel />);
    await screen.findByTestId("models-figures");
    expect(await screen.findByText("Every role:")).toBeInTheDocument();
    expect(screen.getAllByText("33k ctx")).toHaveLength(1);
  });
});
