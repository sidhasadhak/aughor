// @vitest-environment jsdom
/**
 * Arc ED, ED-2 — a person names a service principal's grant when minting it, and each principal's row says what it is
 * held to: its grant, or the agent policy alone.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { render } from "@/lib/testing";

const api = vi.hoisted(() => ({
  mintServicePrincipal: vi.fn(async (_body: Record<string, unknown>) => ({ key: "k-once" })),
  revokeServicePrincipal: vi.fn(async () => ({})),
}));
vi.mock("@/lib/record", async importOriginal => ({ ...(await importOriginal<typeof import("@/lib/record")>()), ...api }));

import { Principals } from "./DeveloperPanel";

afterEach(() => { vi.clearAllMocks(); });

describe("service principals and their grants", () => {
  it("says what each principal is held to", () => {
    render(<Principals onChanged={() => {}} principals={[
      { name: "acme", areas: ["catalog:read"], entities: ["Order"] },
      { name: "plain" },
    ]} />);
    expect(screen.getByText("Held to its grant: areas catalog:read · entities Order")).toBeInTheDocument();
    expect(screen.getByText("Held to the agent policy alone")).toBeInTheDocument();
  });

  it("mints with the areas, entities and actions a person named, and nothing they did not", async () => {
    render(<Principals onChanged={() => {}} principals={[]} />);
    fireEvent.change(screen.getByLabelText("Service principal name"), { target: { value: "vendor" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "objects:read" }));
    fireEvent.change(screen.getByLabelText("Entities it may read"), { target: { value: " Order, Customer " } });
    fireEvent.click(screen.getByRole("button", { name: "Mint a principal" }));
    await waitFor(() => expect(api.mintServicePrincipal).toHaveBeenCalledTimes(1));
    expect(api.mintServicePrincipal.mock.calls[0][0]).toEqual(
      { name: "vendor", note: "", areas: ["objects:read"], entities: ["Order", "Customer"] });
    expect(await screen.findByText("k-once")).toBeInTheDocument();
  });

  it("mints a principal with no grant as it always did", async () => {
    render(<Principals onChanged={() => {}} principals={[]} />);
    fireEvent.change(screen.getByLabelText("Service principal name"), { target: { value: "plain" } });
    fireEvent.click(screen.getByRole("button", { name: "Mint a principal" }));
    await waitFor(() => expect(api.mintServicePrincipal).toHaveBeenCalledTimes(1));
    expect(api.mintServicePrincipal.mock.calls[0][0]).toEqual({ name: "plain", note: "" });
  });
});
