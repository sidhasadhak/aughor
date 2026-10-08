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

describe("what the daily readings found", () => {
  it("says a raw dataset's health, a move's segment, unanswered questions and new values", () => {
    const ds: DatasetSchema = {
      ...stage,
      program: {
        held: null, reopened: { at: "", reason: "revenue moved -12% — most of it country = US" }, last_run: null,
        watch: { day: { through: "2026-10-07", read_at: "", measured: 2, moved: [{ name: "revenue", rel: -0.12 }],
                        explained: [{ metric: "revenue", name: "revenue", dimension: "country", group: "US", change: -4200, share: false }] } },
        failures: 0, unanswered: 2,
        health: { read_at: "2026-10-08T00:00:00Z", notes: ["events: no new rows since the last reading (40)"] },
        news: ["a new value in orders.status: 'returned'"],
      },
    };
    render(<SchemaProgram connId="wh" ds={ds} view={view} onChanged={() => {}} />);
    const text = screen.getByTestId("schema-program").textContent ?? "";
    expect(text).toContain("revenue -12% (most of it country = US)");
    expect(text).toContain("2 questions it could not answer this week");
    expect(text).toContain("Health: events: no new rows since the last reading (40)");
    expect(text).toContain("New: a new value in orders.status: 'returned'");
  });

  it("names a table's copies and lists the table proposals the accept will set", async () => {
    const { TableProgram } = await import("@/components/DatasetProgram");
    const t = { name: "stg_orders", layer: { set: null, proposed: { layer: "raw", label: "Raw", evidence: ["its name has `stg` as a prefix"] }, effective: "" },
                off: null, maturity, copies: ["public.orders"] };
    render(<TableProgram connId="wh" schema="public" t={t} view={view} schemaOff={false} onChanged={() => {}} />);
    expect(screen.getByTestId("table-copies").textContent).toContain("public.orders");
    const withTable: DatasetsView = { ...view, schemas: [{ ...stage, tables: [t] }] };
    render(<ConnectionProgram connId="wh" view={withTable} onChanged={() => {}} />);
    expect(screen.getByTestId("table-proposals").textContent).toContain("stage_marketing.stg_orders → Raw");
  });
});
