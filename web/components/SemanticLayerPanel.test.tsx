// @vitest-environment jsdom
/**
 * The Semantic Layer's frame, redone to CLARITY (2026-10-12): one row of tabs with the scope at its end — the table
 * picker only where a tab reads one — and a read that failed said as a failure, never as an empty list.
 */
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/MetricsPanel", () => ({ MetricsPanel: () => <div data-testid="metrics-stub" /> }));
vi.mock("@/components/intake/IntakePanel", () => ({ IntakePanel: () => <div data-testid="intake-stub" /> }));
// One object, as the shared cache hands out: a new one per render would loop the panel's mirroring effect.
const SCHEMA = { schema: { tables: [{ name: "orders" }, { name: "customers" }] }, loading: false };
vi.mock("@/lib/schema-context", () => ({ useRichSchema: () => SCHEMA }));

import { SemanticLayerPanel } from "@/components/SemanticLayerPanel";

const view = (ui: ReactElement) => render(<Theme>{ui}</Theme>);
const CONNS = [{ id: "c1", name: "theLook" }];

function serve(answer: (url: string) => Response) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => answer(String(url))));
}

beforeEach(() => window.history.replaceState(null, "", "/"));
afterEach(() => vi.unstubAllGlobals());

describe("the frame", () => {
  it("lands on Metrics, with the connection in scope and no table picker", () => {
    view(<SemanticLayerPanel connectionId="c1" connections={CONNS} />);
    expect(screen.getByTestId("metrics-stub")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Connection" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Table" })).not.toBeInTheDocument();
  });

  it("opens the tab its link names, and offers the table picker on Annotations", async () => {
    serve(() => new Response("{}"));
    window.history.replaceState(null, "", "/?semtab=annotations");
    view(<SemanticLayerPanel connectionId="c1" connections={CONNS} />);
    expect(await screen.findByText("No annotations yet.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Table" })).toBeInTheDocument();
  });
});

describe("a read that failed says so", () => {
  it.each([
    ["annotations", "Could not read the annotations", "No annotations yet."],
    ["knowledge", "Could not read the knowledge entries", "No knowledge entries yet."],
    ["benchmarks", "Could not read the benchmark questions", "No questions yet."],
  ])("%s: the failure with Retry, never the empty line", async (tab, said, never) => {
    serve(() => new Response("down", { status: 503 }));
    window.history.replaceState(null, "", `/?semtab=${tab}`);
    view(<SemanticLayerPanel connectionId="c1" connections={CONNS} />);
    expect(await screen.findByText(new RegExp(said))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText(never)).not.toBeInTheDocument();
  });
});
