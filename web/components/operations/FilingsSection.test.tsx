// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Filing } from "@/lib/api";

import { FilingsSection, ProbationSection, aboutWords, openFor } from "./FilingsSection";

const api = vi.hoisted(() => ({ listFilings: vi.fn(), closeFiling: vi.fn(), getHubMap: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const filing = (id: string, extra: Partial<Filing> = {}): Filing => ({
  id, ts: "2026-10-01T09:00:00+00:00", object_ref: "promise:order_to_delivery.dispatch", kind: "ticket", ref: "OPS-123",
  url: "", title: "Dispatch breach, carrier X", source: "automation:a1", status: "open", outcome: "", number_recovered: "",
  closed_at: null, closed_by: "", ...extra,
});

beforeEach(() => {
  for (const f of Object.values(api)) f.mockReset();
  try { localStorage.clear(); } catch { /* jsdom */ }
  api.listFilings.mockResolvedValue([filing("f1"), filing("f2", { kind: "doc", title: "", ref: "", object_ref: "finding:late_dispatch", source: "user:ana" })]);
  api.closeFiling.mockResolvedValue(filing("f1", { status: "closed" }));
});

describe("filed and open", () => {
  it("lists every open filing with what it is about, and can be taken away", async () => {
    render(<FilingsSection />);
    expect(await screen.findByText("Dispatch breach, carrier X")).toBeInTheDocument();
    expect(api.listFilings).toHaveBeenCalledWith("open");
    expect(screen.getByText("promise · order to delivery.dispatch")).toBeInTheDocument();
    // a filing with no title or reference is called by its kind, never left blank
    expect(screen.getAllByText("Document").length).toBeGreaterThan(1);
    expect(screen.getByText("2 filings")).toBeInTheDocument();
    expect(screen.getByText("ana")).toBeInTheDocument();                // filed by a named person
    expect(screen.getByRole("button", { name: /CSV/ })).toBeInTheDocument();
  });

  it("closes one only with what happened, under the name given, and reads the list again", async () => {
    render(<FilingsSection />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Close" }))[0]);
    const send = screen.getByRole("button", { name: "Close it" });
    expect(send).toBeDisabled();                                   // an outcome is the point of closing
    fireEvent.change(screen.getByLabelText("What happened"), { target: { value: "carrier re-routed via hub B" } });
    fireEvent.change(screen.getByLabelText("What it recovered"), { target: { value: "34 late lines" } });
    fireEvent.change(screen.getByPlaceholderText("your name"), { target: { value: "Ana" } });
    fireEvent.click(send);
    await waitFor(() => expect(api.closeFiling).toHaveBeenCalledWith("f1", "carrier re-routed via hub B", "34 late lines", "Ana"));
    await waitFor(() => expect(api.listFilings).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("filing-close")).toBeNull();
  });

  it("says what belongs here when nothing is open", async () => {
    api.listFilings.mockResolvedValue([]);
    render(<FilingsSection />);
    expect(await screen.findByText(/Nothing is filed and open/)).toBeInTheDocument();
  });

  it("words a reference and an age", () => {
    expect(aboutWords("finding:late_dispatch")).toBe("finding · late dispatch");
    expect(aboutWords("odd")).toBe("odd");
    const now = Date.parse("2026-10-05T12:00:00Z");
    expect(openFor("2026-10-05T09:00:00Z", now)).toBe("today");
    expect(openFor("2026-10-01T09:00:00Z", now)).toBe("4 days");
  });
});

describe("on probation", () => {
  const totals = (probation: number) => ({ rows: [], window_days: 7, generated_at: "", totals: { automations: 6, live: 4, probation } });

  it("is one count with the door to the Hub map", async () => {
    api.getHubMap.mockResolvedValue(totals(2));
    const open = vi.fn();
    render(<ProbationSection onOpenHub={open} />);
    expect(await screen.findByText(/of 6 automations on probation/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hub map" }));
    expect(open).toHaveBeenCalled();
  });

  it("says none is, and says so when the hub map is not on the install", async () => {
    api.getHubMap.mockResolvedValue(totals(0));
    const { unmount } = render(<ProbationSection onOpenHub={() => undefined} />);
    expect(await screen.findByText("None of 6 automations is on probation.")).toBeInTheDocument();
    unmount();
    api.getHubMap.mockResolvedValue({ ...totals(0), totals: { automations: 0, live: 0, probation: 0 } });
    const none = render(<ProbationSection onOpenHub={() => undefined} />);
    expect(await screen.findByText("No automation is declared yet, so none is on probation.")).toBeInTheDocument();
    none.unmount();
    api.getHubMap.mockResolvedValue(null);
    render(<ProbationSection onOpenHub={() => undefined} />);
    expect(await screen.findByText("The hub map is not on this install.")).toBeInTheDocument();
  });
});
