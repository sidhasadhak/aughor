// @vitest-environment jsdom
/** "Keep on a dashboard" from a Data Canvas answer (PENDING 54): the answer's question kept as a Question on one of the
 *  person's dashboards, the answer its first — and switched off at once when the dashboard refuses it. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/lib/testing";

const api = vi.hoisted(() => ({
  getSystemFlags: vi.fn(), listDashboards: vi.fn(), getDashboard: vi.fn(), keepDashboard: vi.fn(),
  setAutomationEnabled: vi.fn(), keepQuestion: vi.fn(), readQuestionCost: vi.fn(),
}));
vi.mock("@/lib/api", async original => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
const { KeepOnDashboard } = await import("@/components/dashboards/KeepOnDashboard");

/** The dashboard every rules test starts from. */
const SPEC = JSON.parse(readFileSync(resolve(process.cwd(), "lib/dashboards/premise.fixture.json"), "utf8")) as
  { elements: Record<string, { type: string; props: Record<string, unknown> }> };

beforeEach(() => {
  Object.values(api).forEach(f => f.mockReset());
  api.getSystemFlags.mockResolvedValue({ "dashboard.questions": { value: true }, "dashboard.composed": { value: true } });
  api.listDashboards.mockResolvedValue({ person: "default", cockpits: [{ cockpit_id: "revenue-watch-1", title: "Revenue watch", retired: false }],
    shared_cards: 0, own_cards: 0, from_canvases: [] });
  api.getDashboard.mockResolvedValue({ cockpit: { spec: SPEC } });
  api.readQuestionCost.mockResolvedValue({ kind: "", from: "", tokens: null, minutes: 6.4, n: 5, usd_floor: null,
    usd_n: 0, unpriced_calls: 0, ceiling: {} });
  api.keepQuestion.mockResolvedValue({ automation_id: "aut-1a2b3c4d", session: "question:x", first: "d4039693", rhythm: "weekly" });
  api.setAutomationEnabled.mockResolvedValue({});
});

const open = async () => {
  render(<KeepOnDashboard connectionId="8233e4fd" question="Why did revenue change last month?" runId="d4039693" />);
  fireEvent.click(await screen.findByTestId("keep-on-dashboard"));
  fireEvent.click(await screen.findByTestId("question-keep"));
};

describe("keeping a Data Canvas answer's question on a dashboard", () => {
  it("places it on the dashboard chosen, the answer its first", async () => {
    api.keepDashboard.mockResolvedValue({ status: "kept", kept: true, version: 2, artifact_id: "a", sentences: [] });
    await open();
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1));
    const [conn, id, spec] = api.keepDashboard.mock.calls[0];
    expect([conn, id]).toEqual(["8233e4fd", "revenue-watch-1"]);
    const placed = Object.values((spec as typeof SPEC).elements).find(e => e.type === "Question");
    expect(placed).toMatchObject({ props: { automation: "aut-1a2b3c4d", first: "d4039693" } });
    expect(api.keepQuestion.mock.calls[0][1]).toMatchObject({ question: "Why did revenue change last month?", rhythm: "weekly", first_run: "d4039693" });
    expect(await screen.findByTestId("keep-on-dashboard-said")).toHaveTextContent("Kept on “Revenue watch”.");
    expect(api.setAutomationEnabled).not.toHaveBeenCalled();
  });

  it("switches the question off at once when the dashboard refuses it, and says why", async () => {
    api.keepDashboard.mockResolvedValue({ status: "refused", kept: false, version: null, artifact_id: "",
      sentences: ["The dashboard holds a question — question — and questions on a dashboard are off on this install."] });
    await open();
    await waitFor(() => expect(api.setAutomationEnabled).toHaveBeenCalledWith("aut-1a2b3c4d", false));
    expect(await screen.findByTestId("keep-on-dashboard-said")).toHaveTextContent("Not kept on “Revenue watch”: The dashboard holds a question");
  });

  it("is not offered while questions are off", async () => {
    api.getSystemFlags.mockResolvedValue({ "dashboard.questions": { value: false }, "dashboard.composed": { value: true } });
    render(<KeepOnDashboard connectionId="8233e4fd" question="q" runId="d4039693" />);
    await waitFor(() => expect(api.getSystemFlags).toHaveBeenCalled());
    expect(screen.queryByTestId("keep-on-dashboard")).toBeNull();
  });
});
