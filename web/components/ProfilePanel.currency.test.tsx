// @vitest-environment jsdom
/**
 * The data's currency on the Profile page (2026-10-23, the Olist study's Gap 14): the profile PROPOSES it,
 * a person confirms it — for this dataset — and only then does it label a figure.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getDataCurrency: vi.fn(), confirmDataCurrency: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));

import { CurrencyFact } from "./ProfilePanel";
import { effectiveCurrencySymbol, setCurrentDataset } from "@/lib/orgSettings";

const olist = (code: string) => ({ connection_id: "workspace", schema_name: "olist", code, inferred: "BRL",
  status: code ? "confirmed" : "inferred", profile_confidence: 0.97, confirmed_by: code ? "amit" : "", confirmed_at: "" });

beforeEach(() => { api.getDataCurrency.mockReset(); api.confirmDataCurrency.mockReset(); setCurrentDataset("workspace", "olist"); });
afterEach(() => setCurrentDataset(""));

describe("CurrencyFact", () => {
  it("offers the profile's suggestion to confirm, and a confirmation labels the figures in view", async () => {
    api.getDataCurrency.mockResolvedValue(olist(""));
    api.confirmDataCurrency.mockResolvedValue(olist("BRL"));
    render(<Theme><dl><CurrencyFact connectionId="workspace" schema="olist" /></dl></Theme>);
    const fact = await screen.findByTestId("profile-currency");
    expect(fact).toHaveTextContent("suggested by the profile · unconfirmed");
    expect(effectiveCurrencySymbol()).toBe("");                          // a suggestion labels nothing
    fireEvent.click(screen.getByText("Confirm BRL"));
    await waitFor(() => expect(fact).toHaveTextContent("✓ confirmed"));
    expect(api.confirmDataCurrency).toHaveBeenCalledWith("workspace", "olist", "BRL");
    expect(effectiveCurrencySymbol()).toBe("R$");                         // the page's figures follow at once
  });

  it("lets a person state another code, and refuses one that is not three letters", async () => {
    api.getDataCurrency.mockResolvedValue(olist(""));
    api.confirmDataCurrency.mockResolvedValue({ ...olist("EUR"), code: "EUR" });
    render(<Theme><dl><CurrencyFact connectionId="workspace" schema="olist" /></dl></Theme>);
    fireEvent.click(await screen.findByText("Another currency"));
    const input = screen.getByLabelText("Currency code");
    fireEvent.change(input, { target: { value: "eu" } });
    expect(screen.getByText("Save").closest("button")).toBeDisabled();
    fireEvent.change(input, { target: { value: "eur" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(api.confirmDataCurrency).toHaveBeenCalledWith("workspace", "olist", "EUR"));
  });
});
