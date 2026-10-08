// @vitest-environment jsdom
/**
 * The exploration principles in the Catalog (2026-10-08): maturity as three vertical bars and a number
 * — a reading that does not apply drawn faint and said, never 0% — the proposed layer with its evidence
 * and one click to set it, and an off switch that asks why before it turns a dataset off.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@/lib/testing";
import type { DatasetSchema, DatasetsView, Maturity } from "@/lib/api";

const setDatasetLayer = vi.fn();
const setDatasetOff = vi.fn();
const acceptDatasetLayers = vi.fn();
vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  setDatasetLayer: (...a: unknown[]) => setDatasetLayer(...a),
  setDatasetOff: (...a: unknown[]) => setDatasetOff(...a),
  acceptDatasetLayers: (...a: unknown[]) => acceptDatasetLayers(...a),
  getConnectionSettings: async () => ({ ontology_refresh_hours: null, exploration_monthly_tokens: 50000 }),
}));

const { MaturityBars, SchemaProgram, ConnectionProgram } = await import("@/components/DatasetProgram");

const maturity: Maturity = {
  structure: { share: 1, note: "structure learned" },
  questions: { share: null, note: "not explored — raw" },
  time: { share: 0.25, note: "1 of 2 metrics dated · newest day not read yet" },
  percent: 63, stage: "learning",
};

const stage: DatasetSchema = {
  name: "stage_marketing", key: "wh__stage_marketing",
  layer: { set: null, proposed: { layer: "raw", label: "Raw", evidence: ["the schema's name has the word `stage`"] },
           effective: "", policy: "structure only — its questions wait for a person to set its layer", jobs: ["structure"] },
  off: null, maturity,
  program: { held: null, reopened: null, last_run: null, watch: {}, failures: 0 },
  tables: [],
};

const view: DatasetsView = {
  connection_id: "wh", schemas: [stage],
  budget: { organisation: { limit: null, spent: null }, connection: { limit: 50000, spent: 60000 }, remaining: -10000,
            held_by: "connection", spent_out: true, sentence: "the connection's monthly exploration budget of 50,000 tokens is spent" },
  layers: [{ id: "business", label: "Business", policy: "" }, { id: "raw", label: "Raw", policy: "" }],
  exclusion_reasons: ["out_of_domain", "sensitive"],
};

beforeEach(() => { setDatasetLayer.mockReset(); setDatasetOff.mockReset(); acceptDatasetLayers.mockReset(); });

describe("MaturityBars", () => {
  it("draws three bars and the number, a reading that does not apply faint and said", () => {
    render(<MaturityBars m={maturity} />);
    const bars = screen.getByTestId("maturity-bars");
    expect(bars.querySelectorAll("[data-bar]")).toHaveLength(3);
    expect(bars.textContent).toContain("63%");
    const questions = bars.querySelector('[data-bar="questions"]') as HTMLElement;
    expect(questions.style.opacity).toBe("0.4");
    expect(bars.getAttribute("title")).toContain("Questions — — not explored — raw");
  });
});

describe("SchemaProgram", () => {
  it("shows the proposal with its evidence and sets it in one click", async () => {
    setDatasetLayer.mockResolvedValue({ layer: "raw", set_by: "amit", set_at: "", started: null });
    const changed = vi.fn();
    render(<SchemaProgram connId="wh" ds={stage} view={view} onChanged={changed} />);
    expect(screen.getByTestId("layer-evidence").textContent).toContain("the word `stage`");
    fireEvent.click(screen.getByTestId("accept-layer"));
    await waitFor(() => expect(setDatasetLayer).toHaveBeenCalledWith("wh", "stage_marketing", "raw", ""));
    await waitFor(() => expect(changed).toHaveBeenCalled());
  });

  it("asks why before it turns a dataset off", async () => {
    setDatasetOff.mockResolvedValue({ ok: true, off: null });
    render(<SchemaProgram connId="wh" ds={stage} view={view} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("switch"));
    expect(setDatasetOff).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("confirm-off"));
    await waitFor(() => expect(setDatasetOff).toHaveBeenCalledWith("wh", "stage_marketing", true,
      { table: undefined, reason: "out_of_domain" }));
  });
});

describe("ConnectionProgram", () => {
  it("lists the datasets waiting for a layer and says the budget is spent", async () => {
    acceptDatasetLayers.mockResolvedValue({ accepted: [], started: {} });
    render(<ConnectionProgram connId="wh" view={view} onChanged={() => {}} />);
    expect(screen.getByTestId("connection-program").textContent).toContain("stage_marketing → Raw");
    expect(screen.getByTestId("budget-sentence").textContent).toContain("50,000 tokens is spent");
    fireEvent.click(screen.getByTestId("accept-all-layers"));
    await waitFor(() => expect(acceptDatasetLayers).toHaveBeenCalledWith("wh"));
  });
});
