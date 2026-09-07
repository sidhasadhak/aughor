// @vitest-environment jsdom
/**
 * The deliberate JSON-mode pin (2026-09-07).
 *
 * A model that advertises tool calling and then does not do it makes its binding fail
 * as `tools_unsupported` — the platform refuses rather than quietly answering another
 * way. This control is how an operator who KNOWS their model cannot do tool calling
 * says "use it anyway". The difference is consent, so the consent has to be visible,
 * per model, and it has to reach the server.
 *
 * Pinned here:
 *   * the control appears only where the SERVER says the pin is honoured — offering it
 *     elsewhere would be a switch wired to nothing;
 *   * ticking it sends `json_mode` for that backend;
 *   * an existing pin loads back in as ticked.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { InferencePanel } from "@/components/InferencePanel";

const api = vi.hoisted(() => ({
  getLlmConfig: vi.fn(), setLlmConfig: vi.fn(), getLlmModels: vi.fn(),
  testLlmConfig: vi.fn(), cacheProbe: vi.fn(), addLlmModel: vi.fn(), removeLlmModel: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const MODEL = "qwen2.5-coder:14b";

function config(over: Record<string, unknown> = {}) {
  return {
    backend: "ollama",
    models: { coder: MODEL, narrator: MODEL, fast: MODEL },
    models_set: { coder: MODEL, narrator: MODEL, fast: MODEL },
    base_urls: { ollama: "http://localhost:11434" },
    base_urls_set: {},
    keys_set: {}, keys_state: {}, capabilities: {},
    backends: ["ollama", "openrouter"], needs_key: ["openrouter"],
    local_backends: ["ollama"], default_models: {},
    json_mode: {}, json_mode_backends: ["ollama"],
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getLlmModels.mockResolvedValue({ models: [], source: "live" });
  api.getLlmConfig.mockResolvedValue(config());
  api.setLlmConfig.mockImplementation(async () => config());
});

it("offers the pin where the server says it is honoured", async () => {
  render(<InferencePanel />);
  const label = await screen.findByText(/Use JSON structured output for/i);
  expect(label).toBeTruthy();
  expect(screen.getByText(MODEL)).toBeTruthy();     // named, not generic
});

it("does NOT offer it where the server says it does nothing", async () => {
  api.getLlmConfig.mockResolvedValue(config({ json_mode_backends: [] }));
  render(<InferencePanel />);
  await screen.findByText(/Structured output/i).catch(() => null);
  await waitFor(() => expect(api.getLlmConfig).toHaveBeenCalled());
  expect(screen.queryByText(/Use JSON structured output for/i)).toBeNull();
});

it("ticking it sends the pin for this backend", async () => {
  render(<InferencePanel />);
  const box = await screen.findByRole("checkbox");
  fireEvent.click(box);
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

  await waitFor(() => expect(api.setLlmConfig).toHaveBeenCalled());
  const patch = api.setLlmConfig.mock.calls[0][0];
  expect(patch.json_mode).toEqual({ ollama: [MODEL] });
});

it("an existing pin comes back ticked", async () => {
  api.getLlmConfig.mockResolvedValue(config({ json_mode: { ollama: [MODEL] } }));
  render(<InferencePanel />);
  const box = await screen.findByRole("checkbox");
  await waitFor(() => expect((box as HTMLInputElement).checked).toBe(true));
});

it("unticking a saved pin sends an empty list, which is how it is cleared", async () => {
  api.getLlmConfig.mockResolvedValue(config({ json_mode: { ollama: [MODEL] } }));
  render(<InferencePanel />);
  const box = await screen.findByRole("checkbox");
  await waitFor(() => expect((box as HTMLInputElement).checked).toBe(true));
  fireEvent.click(box);
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

  await waitFor(() => expect(api.setLlmConfig).toHaveBeenCalled());
  expect(api.setLlmConfig.mock.calls[0][0].json_mode).toEqual({ ollama: [] });
});
