// @vitest-environment jsdom
/**
 * IP-2 — Settings ▸ Organization asks the installer's question again: every industry (each connection's
 * detected), or only the ticked ones. Pinned here: what the section sends for each answer, that an unchanged
 * answer cannot be saved, and that a save which drops business profiles says so.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { OrgIndustriesSection } from "@/components/OrgIndustriesSection";
import type { IndustryChoice } from "@/lib/api";

const api = vi.hoisted(() => ({ getIndustryChoice: vi.fn(), updateIndustryChoice: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const choice = (over: Partial<IndustryChoice> = {}): IndustryChoice => ({
  industries: null, source: "", updated_at: "", ignored: [], problem: "", profiles_refreshed: 0,
  shipped: [
    { id: "airline", name: "Airline", title: "Airline / Commercial Aviation", description: "" },
    { id: "retail", name: "Retail and e-commerce", title: "Retail / E-commerce", description: "" },
    { id: "saas", name: "SaaS", title: "SaaS / Subscription Software", description: "" },
  ],
  ...over,
});

beforeEach(() => {
  api.getIndustryChoice.mockReset();
  api.updateIndustryChoice.mockReset();
});

it("keeps every industry until only some are ticked, then saves those", async () => {
  api.getIndustryChoice.mockResolvedValue(choice());
  api.updateIndustryChoice.mockImplementation(async (industries: string[] | null) =>
    choice({ industries, source: "settings", profiles_refreshed: 2 }));
  render(<OrgIndustriesSection />);

  const every = await screen.findByRole("radio", { name: "Every industry" });
  expect(every).toBeChecked();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.getByRole("button", { name: "Save industries" })).toBeDisabled();   // nothing changed yet

  fireEvent.click(screen.getByRole("radio", { name: "Only these" }));
  expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  fireEvent.click(screen.getByRole("checkbox", { name: "Airline" }));
  fireEvent.click(screen.getByRole("button", { name: "Save industries" }));

  await waitFor(() => expect(api.updateIndustryChoice).toHaveBeenCalledWith(["retail", "saas"]));
  expect(await screen.findByText(
    "Saved. 2 business profiles will be rebuilt the next time their data is used.")).toBeInTheDocument();
});

it("saves every industry as null, and none as an empty list", async () => {
  api.getIndustryChoice.mockResolvedValue(choice({ industries: ["retail"] }));
  api.updateIndustryChoice.mockImplementation(async (industries: string[] | null) => choice({ industries }));
  render(<OrgIndustriesSection />);

  fireEvent.click(await screen.findByRole("checkbox", { name: "Retail and e-commerce" }));
  expect(screen.getByText("No industry package: every connection uses only the knowledge all industries share."))
    .toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save industries" }));
  await waitFor(() => expect(api.updateIndustryChoice).toHaveBeenLastCalledWith([]));

  fireEvent.click(await screen.findByRole("radio", { name: "Every industry" }));
  fireEvent.click(screen.getByRole("button", { name: "Save industries" }));
  await waitFor(() => expect(api.updateIndustryChoice).toHaveBeenLastCalledWith(null));
});

it("renders nothing when no industry package ships", async () => {
  api.getIndustryChoice.mockResolvedValue(choice({ shipped: [] }));
  const { container } = render(<OrgIndustriesSection />);
  await waitFor(() => expect(api.getIndustryChoice).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
