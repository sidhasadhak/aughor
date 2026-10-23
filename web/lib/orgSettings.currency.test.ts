/**
 * The currency a money figure carries on screen (2026-10-23, the Olist study's Gap 14): its DATASET's, as a
 * person confirmed it — never the org's preference, never the profile's guess, never a default "$".
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  currentDataCurrency, effectiveCurrencySymbol, localizeCurrency, registerCurrencyLoader, setCurrentDataset,
  setDataCurrency, setOrgSettingsCache, unconfirmedCurrencyNote, type DataCurrency,
} from "./orgSettings";
import type { OrgSettings } from "./api";

const held = (conn: string, schema: string | null, code: string, inferred = ""): DataCurrency => ({
  connection_id: conn, schema_name: schema, code, status: code ? "confirmed" : inferred ? "inferred" : "unknown",
  inferred, confirmed_by: code ? "amit" : "", confirmed_at: "",
});

afterEach(() => { setCurrentDataset(""); registerCurrencyLoader(null); setOrgSettingsCache(null); });

describe("the dataset's confirmed currency labels the money in view", () => {
  it("is no symbol until a person confirms it, whatever the org reports in", () => {
    setOrgSettingsCache({ currency_code: "USD" } as OrgSettings);
    setCurrentDataset("workspace", "olist");
    setDataCurrency(held("workspace", "olist", "", "BRL"));
    expect(effectiveCurrencySymbol()).toBe("");
    expect(localizeCurrency("health_beauty earned $1,258,681.34")).toBe("health_beauty earned 1,258,681.34");
    expect(unconfirmedCurrencyNote()).toBe(
      "Amounts are plain: no one has confirmed this data's currency (the profile suggests BRL).");
  });

  it("follows the dataset in view: Olist's reais and main's euros on one connection", () => {
    setDataCurrency(held("workspace", "olist", "BRL", "BRL"));
    setDataCurrency(held("workspace", "main", "", "EUR"));
    setCurrentDataset("workspace", "olist");
    expect(effectiveCurrencySymbol()).toBe("R$");
    expect(localizeCurrency("GMV was $848,860")).toBe("GMV was R$848,860");
    expect(unconfirmedCurrencyNote()).toBe("");
    setCurrentDataset("workspace", "main");
    expect(effectiveCurrencySymbol()).toBe("");
    expect(currentDataCurrency()?.inferred).toBe("EUR");
  });

  it("keeps a \"$\" only when USD is what a person confirmed", () => {
    setCurrentDataset("8233e4fd", "");
    setDataCurrency(held("8233e4fd", null, "USD", "USD"));
    expect(localizeCurrency("revenue was $21,414.64")).toBe("revenue was $21,414.64");
  });

  it("reads each dataset once, when it first comes into view", () => {
    const load = vi.fn();
    registerCurrencyLoader(load);
    setCurrentDataset("fresh", "a");
    expect(load).toHaveBeenCalledWith("fresh", "a");
    setDataCurrency(held("fresh", "a", "BRL"));
    setCurrentDataset("fresh", "b");
    setCurrentDataset("fresh", "a");                         // already read: not asked again
    expect(load.mock.calls).toEqual([["fresh", "a"], ["fresh", "b"]]);
  });
});
