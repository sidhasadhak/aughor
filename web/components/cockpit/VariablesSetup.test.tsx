// @vitest-environment jsdom

/**
 * Variables in the builder (Arc AP-8; design-mockups/cockpit-builder.html screens 11–12). While variables are on, the
 * Data tab is Variables: the values first — each with where it comes from, what it holds now and how much reads it, a
 * query of the person's own among them — then the sets, then what the pieces output. A value's setup says where it comes
 * from and what it holds; a set's condition compares with any value its kind allows; a query reads one as `{{name}}`,
 * tried here with a value of its kind. Off, each is as it was. Every read is mocked — no test reaches an API.
 */
import { choose, fireEvent, optionsOf, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CockpitBuilder } from "@/components/cockpit/CockpitBuilder";
import { QuerySetup } from "@/components/cockpit/QuerySetup";
import { DataPane, SetSetup, ValueSetup } from "@/components/cockpit/WiringSetup";
import type { CockpitSpec } from "@/lib/cockpit/edit";

const objects = vi.hoisted(() => ({ queryObjects: vi.fn(), cachedObjectCatalog: vi.fn(), getDeclaredActions: vi.fn() }));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));
const types = vi.hoisted(() => ({ getObjectType: vi.fn(), getProcesses: vi.fn() }));
vi.mock("@/lib/objectTypes", async (original) => ({ ...(await original<typeof import("@/lib/objectTypes")>()), ...types }));
const api = vi.hoisted(() => ({ previewCockpitQuery: vi.fn(), keepCockpitQuery: vi.fn(), getCatalogTree: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const prop = (name: string, role: string, data_type = "STRING") =>
  ({ name, display_name: name.replace(/_/g, " ").replace(/^\w/, c => c.toUpperCase()), role, data_type, unit: "", is_key: name === "id", null_rate: 0, description: "", source: {} });
const ORDER = { id: "order", object_type: "order", segments: [], links: [], derived: { segments: [], properties: [], metrics: [] },
  properties: [prop("id", "key", "INT64"), prop("status", "dimension"), prop("created_at", "timestamp", "TIMESTAMP"), prop("num_of_item", "measure", "INT64")] };

function desk(): CockpitSpec {
  return {
    root: "cockpit",
    values: {
      window: { label: "Window", kind: "days", value: 14 },
      country: { label: "Country", kind: "text", value: "China", from: { by: "reader" } },
      since: { label: "Since", kind: "date", value: "2026-09-01" },
      "waiting-count": { label: "Waiting count", kind: "number", from: { by: "count", set: "waiting" } },
      status: { label: "Its status", kind: "text", from: { by: "chosen", choice: "chosen-order", path: "status" } },
    },
    sets: {
      placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
      waiting: { label: "Waiting", from: "placed", segment: "overdue_dispatch" },
      big: { label: "Big", entity: "order", where: [{ path: "status", op: "=", value: "Processing" }] },
    },
    elements: {
      cockpit: { type: "Cockpit", props: { title: "Desk" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Desk" }, children: ["table", "q"] },
      table: { type: "ObjectTable", props: { set: "waiting", chooses: "chosen-order" }, children: [] },
      q: { type: "Card", props: { card: "q1" }, children: [] },
    },
  };
}
const READS: Record<string, string[]> = { q1: ["country", "window"] };
const cardReads = (id: string) => READS[id] ?? [];
const cardTitle = (id: string) => (id === "q1" ? "Sales in the country" : undefined);

let conn = 0;
beforeEach(() => {
  vi.clearAllMocks();
  objects.queryObjects.mockImplementation(async (b: { segment?: string }) => ({ path: "compiled", rows: [[b.segment ? "1009" : "6987"]], caveats: [], error: null }));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Order" }] });
  objects.getDeclaredActions.mockResolvedValue({});
  types.getObjectType.mockImplementation(async () => ORDER);
  types.getProcesses.mockResolvedValue({ processes: [], rules: [] });
  api.previewCockpitQuery.mockResolvedValue({ connection_id: "thelook", refused: [], columns: [{ name: "n", type: "INT64" }], rows: [[3]], reads: ["window"] });
  api.getCatalogTree.mockResolvedValue({ sections: [] });
});

describe("the Variables pane", () => {
  it("lists the values first — where each comes from, what it holds now, how much reads it — then the sets, then the pieces' output", async () => {
    render(<DataPane spec={desk()} selected={null} onSelect={vi.fn()} onChange={vi.fn()} connectionId={`c${++conn}`} variablesOn cardReads={cardReads} />);
    const pane = screen.getByTestId("builder-data");
    const labels = [...pane.querySelectorAll("div")].filter(d => /^(Values|Sets|From the pieces)/.test(d.textContent ?? "") && d.children.length <= 1).map(d => d.textContent?.replace(/\d+ of \d+$/, ""));
    expect(labels).toEqual(["Values", "Sets", "From the pieces"]);
    const values = screen.getAllByTestId("data-value");
    expect(values.map(v => v.dataset.name)).toEqual(["window", "country", "since", "waiting-count", "status"]);
    expect(values[0]).toHaveTextContent("days · set by you");
    expect(values[0]).toHaveTextContent("14 days");
    expect(values[0]).toHaveTextContent("used in 2");                                          // the set Placed, and the query
    expect(values[1]).toHaveTextContent("words · set by the reader");
    expect(values[1]).toHaveTextContent("used in 1");                                          // the query
    expect(values[2]).toHaveTextContent("not used yet");
    expect(values[3]).toHaveTextContent("a number · counted from Waiting");
    await waitFor(() => expect(values[3]).toHaveTextContent("1,009"));                         // counted at the object door
    expect(values[4]).toHaveTextContent("words · read from the chosen order");
    expect(values[4]).toHaveTextContent("once one is chosen");
    expect(screen.getAllByTestId("data-set").map(s => s.dataset.name)).toEqual(["placed", "waiting", "big"]);
    expect(screen.getByTestId("data-choice")).toHaveTextContent("used in 1");                 // Its status reads it; the table makes it
  });

  it("starts a new set from the connection's first entity on a cockpit whose cards are all queries", async () => {
    const onChange = vi.fn();
    const spec: CockpitSpec = { root: "cockpit", values: desk().values, elements: { cockpit: { type: "Cockpit", props: { title: "Sales" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Sales" }, children: ["q"] }, q: { type: "Card", props: { card: "q1" }, children: [] } } };
    delete spec.values!["waiting-count"];
    delete spec.values!.status;
    render(<DataPane spec={spec} selected={null} onSelect={vi.fn()} onChange={onChange} connectionId={`c${++conn}`} variablesOn cardReads={cardReads} />);
    await waitFor(() => expect(screen.getByTestId("data-new-set")).toBeEnabled());
    fireEvent.click(screen.getByTestId("data-new-set"));
    expect(onChange.mock.calls[0][0].sets["new-set"]).toEqual({ label: "New set", entity: "order" });
  });

  it("is the Data tab as it was while variables are off", () => {
    render(<DataPane spec={desk()} selected={null} onSelect={vi.fn()} onChange={vi.fn()} connectionId={`c${++conn}`} />);
    expect(screen.getByTestId("builder-data")).not.toHaveAttribute("data-variables");
    expect(screen.getAllByTestId("data-set")[0].compareDocumentPosition(screen.getAllByTestId("data-value")[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("is named Variables in the builder, and a value chosen there is a variable", () => {
    const spec = desk();
    render(
      <CockpitBuilder spec={spec} onChange={vi.fn()} connectionId="thelook" schema="thelook" bar={null} wiringOn variablesOn cardReads={cardReads}>
        {() => <div data-testid="cockpit-stub" />}
      </CockpitBuilder>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Variables" }));
    fireEvent.click(screen.getAllByTestId("data-value")[1]);
    expect(screen.getByTestId("builder-selection")).toHaveTextContent("Variable");
    expect(screen.getByTestId("builder-selection")).toHaveTextContent("the piece that reads it is dashed");   // the query's card
  });
});

describe("a value's setup", () => {
  it("comes from the reader, offering the choices typed — the value it starts from always one of them", async () => {
    const onChange = vi.fn();
    render(<ValueSetup spec={desk()} name="window" onChange={onChange} onGone={vi.fn()} variablesOn connectionId="thelook" cardReads={cardReads} cardTitle={cardTitle} />);
    await choose(screen.getByLabelText("Comes from"), "reader");
    expect(onChange.mock.calls[0][0].values.window).toEqual({ label: "Window", kind: "days", value: 14, from: { by: "reader" } });
    const reader = onChange.mock.calls[0][0] as CockpitSpec;
    onChange.mockClear();
    render(<ValueSetup spec={reader} name="window" onChange={onChange} onGone={vi.fn()} variablesOn connectionId="thelook" />, { container: document.body.appendChild(document.createElement("div")) });
    const choices = screen.getAllByLabelText("The choices offered").at(-1)!;
    fireEvent.change(choices, { target: { value: "7, 30, 90, 30" } });
    fireEvent.blur(choices);
    expect(onChange.mock.calls[0][0].values.window).toEqual({ label: "Window", kind: "days", value: 7, from: { by: "reader", options: [7, 30, 90] } });
    fireEvent.change(choices, { target: { value: "7, fortnight" } });
    fireEvent.blur(choices);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(screen.getAllByTestId("value-setup-said").at(-1)).toHaveTextContent("Each choice is a number of days.");
  });

  it("is counted from a set, as a number; or read off the chosen object, from a property of its own", async () => {
    const onChange = vi.fn();
    render(<ValueSetup spec={desk()} name="window" onChange={onChange} onGone={vi.fn()} variablesOn connectionId={`c${++conn}`} />);
    await choose(screen.getByLabelText("Comes from"), "count");
    expect(onChange.mock.calls[0][0].values.window).toEqual({ label: "Window", kind: "number", from: { by: "count", set: "placed" } });
    await choose(screen.getByLabelText("Comes from"), "chosen");
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
    expect(onChange.mock.calls[1][0].values.window).toEqual({ label: "Window", kind: "text", from: { by: "chosen", choice: "chosen-order", path: "status" } });
  });

  it("reads a property of the chosen object as its kind: a moment as a day", async () => {
    const onChange = vi.fn();
    render(<ValueSetup spec={desk()} name="status" onChange={onChange} onGone={vi.fn()} variablesOn connectionId={`c${++conn}`} />);
    await waitFor(() => expect(optionsOf(screen.getByLabelText("The property it reads")).map(o => o.value)).toEqual(["status", "created_at", "num_of_item"]));
    await choose(screen.getByLabelText("The property it reads"), "created_at");
    expect(onChange.mock.calls[0][0].values.status).toEqual({ label: "Its status", kind: "date", from: { by: "chosen", choice: "chosen-order", path: "created_at" } });
    await choose(screen.getByLabelText("The property it reads"), "num_of_item");
    expect(onChange.mock.calls[1][0].values.status.kind).toBe("number");
  });

  it("takes its new name's spelling in SQL while nothing reads it — {{country}}, never {{window-2}} — and keeps it once one does", () => {
    const onChange = vi.fn(), onRenamed = vi.fn();
    const spec = desk();
    spec.values!["window-2"] = { label: "Window", kind: "text", value: "China", from: { by: "reader" } };
    const { unmount } = render(<ValueSetup spec={spec} name="window-2" onChange={onChange} onGone={vi.fn()} variablesOn connectionId="thelook"
      cardReads={cardReads} onRenamed={onRenamed} />);
    const name = screen.getByLabelText("The value's name");
    fireEvent.change(name, { target: { value: "Country of the customer" } });
    fireEvent.blur(name);
    const next = onChange.mock.calls[0][0] as CockpitSpec;
    expect(Object.keys(next.values!)).toEqual(["window", "country", "since", "waiting-count", "status", "country-of-the-customer"]);
    expect(next.values!["country-of-the-customer"]).toEqual({ ...spec.values!["window-2"], label: "Country of the customer" });
    expect(onRenamed).toHaveBeenCalledWith("country-of-the-customer");
    unmount();
    onChange.mockClear(); onRenamed.mockClear();
    render(<ValueSetup spec={desk()} name="country" onChange={onChange} onGone={vi.fn()} variablesOn connectionId="thelook"
      cardReads={cardReads} onRenamed={onRenamed} />);
    const read = screen.getByLabelText("The value's name");
    fireEvent.change(read, { target: { value: "Market" } });
    fireEvent.blur(read);
    expect(onChange.mock.calls[0][0].values).toMatchObject({ country: { label: "Market" } });  // the query still reads {{country}}
    expect(onRenamed).not.toHaveBeenCalled();
  });

  it("says every query that reads it, and is not taken away while one does", () => {
    render(<ValueSetup spec={desk()} name="country" onChange={vi.fn()} onGone={vi.fn()} variablesOn connectionId="thelook" cardReads={cardReads} cardTitle={cardTitle} />);
    expect(screen.getByTestId("setup-read-by")).toHaveTextContent("Your query · Sales in the country");
    expect(screen.getByTestId("setup-wire-delete")).toBeDisabled();
  });

  it("offers a day only while variables are on", () => {
    const { unmount } = render(<ValueSetup spec={desk()} name="window" onChange={vi.fn()} onGone={vi.fn()} />);
    expect(optionsOf(screen.getByLabelText("Kind")).map(o => o.value)).toEqual(["days", "number", "text"]);
    expect(screen.queryByLabelText("Comes from")).toBeNull();
    unmount();
    render(<ValueSetup spec={desk()} name="window" onChange={vi.fn()} onGone={vi.fn()} variablesOn connectionId="thelook" />);
    expect(optionsOf(screen.getByLabelText("Kind")).map(o => o.value)).toEqual(["days", "number", "text", "date"]);
  });
});

describe("a set's condition, compared with a value", () => {
  it("offers the values its kind allows — words by is and is not, a day for a moment — and keeps one across comparisons", async () => {
    const onChange = vi.fn();
    render(<SetSetup spec={desk()} name="big" onChange={onChange} onGone={vi.fn()} connectionId={`c${++conn}`} variablesOn />);
    await waitFor(() => expect(screen.getByLabelText("Compared with")).toBeInTheDocument());
    expect(optionsOf(screen.getByLabelText("Compared with")).map(o => o.value)).toEqual(["", "country", "status"]);
    await choose(screen.getByLabelText("Compared with"), "country");
    expect(onChange.mock.calls[0][0].sets.big.where).toEqual([{ path: "status", op: "=", value_from: "country" }]);
  });

  it("keeps a word for is not, and offers no value for a comparison words cannot make", async () => {
    const onChange = vi.fn();
    const spec = desk();
    spec.sets!.big.where = [{ path: "status", op: "=", value_from: "country" }];
    render(<SetSetup spec={spec} name="big" onChange={onChange} onGone={vi.fn()} connectionId={`c${++conn}`} variablesOn />);
    await waitFor(() => expect(screen.getByLabelText("Is")).toBeInTheDocument());
    await choose(screen.getByLabelText("Is"), "!=");
    expect(onChange.mock.calls[0][0].sets.big.where).toEqual([{ path: "status", op: "!=", value_from: "country" }]);
    await choose(screen.getByLabelText("Is"), ">");
    expect(onChange).toHaveBeenCalledTimes(1);                                                 // waits for one typed
    expect(screen.queryByLabelText("Compared with")).toBeNull();
  });

  it("compares a moment with a day value, and counts back days by a days value", async () => {
    const onChange = vi.fn();
    const spec = desk();
    spec.sets!.big.where = [{ path: "created_at", op: ">=", value: "2026-09-01" }];
    render(<SetSetup spec={spec} name="big" onChange={onChange} onGone={vi.fn()} connectionId={`c${++conn}`} variablesOn />);
    await waitFor(() => expect(screen.getByLabelText("Compared with")).toBeInTheDocument());
    expect(optionsOf(screen.getByLabelText("Compared with")).map(o => o.value)).toEqual(["", "since"]);
    await choose(screen.getByLabelText("Is"), "in_last");
    expect(onChange.mock.calls[0][0].sets.big.where).toEqual([{ path: "created_at", op: "in_last", value: 14 }]);
  });
});

describe("a query of the person's own, reading values", () => {
  const values = desk().values!;

  it("inserts a value as {{name}} where the cursor is, and is tried with the value it starts from", async () => {
    render(<QuerySetup connectionId="thelook" onKept={vi.fn()} values={values} />);
    const sql = screen.getByLabelText("SQL") as HTMLTextAreaElement;
    fireEvent.change(sql, { target: { value: "SELECT COUNT(*) AS n FROM orders WHERE created_at > " } });
    fireEvent.click(screen.getByTestId("query-values-open"));
    const offered = within(screen.getByTestId("query-values")).getAllByRole("listitem");
    expect(offered.map(o => o.textContent)).toEqual(["{{window}}Window · days", "{{country}}Country · words", "{{since}}Since · a day",
      "{{waiting-count}}Waiting count · a number", "{{status}}Its status · words"]);
    fireEvent.click(offered[0]);
    expect(sql.value).toBe("SELECT COUNT(*) AS n FROM orders WHERE created_at > {{window}}");
    await waitFor(() => expect(document.activeElement).toBe(sql));                            // writing goes on after it
    expect(sql.selectionStart).toBe(sql.value.length);
    expect(within(screen.getByTestId("query-tried")).getByLabelText("Try Window as")).toHaveValue(14);
    fireEvent.click(screen.getByTestId("query-run"));
    await waitFor(() => expect(api.previewCockpitQuery).toHaveBeenCalled());
    expect(api.previewCockpitQuery.mock.calls[0][1].values).toEqual({ window: { kind: "days", value: 14 } });
  });

  it("asks for a value to try one with that has none here, and runs nothing until it has one", async () => {
    render(<QuerySetup connectionId="thelook" onKept={vi.fn()} values={values} />);
    fireEvent.change(screen.getByLabelText("SQL"), { target: { value: "SELECT 1 WHERE {{waiting-count}} > 3 AND {{nowhere}} = 1" } });
    fireEvent.click(screen.getByTestId("query-run"));
    expect(await screen.findByTestId("query-refused")).toHaveTextContent("Give Waiting count a number to try the query with.");
    expect(screen.getByTestId("query-refused")).toHaveTextContent("{{nowhere}} is not one of this cockpit's values.");
    expect(api.previewCockpitQuery).not.toHaveBeenCalled();
    fireEvent.change(within(screen.getByTestId("query-tried")).getByLabelText("Try Waiting count as"), { target: { value: "1009" } });
    fireEvent.change(screen.getByLabelText("SQL"), { target: { value: "SELECT 1 WHERE {{waiting-count}} > 3" } });
    fireEvent.click(screen.getByTestId("query-run"));
    await waitFor(() => expect(api.previewCockpitQuery.mock.calls[0][1].values).toEqual({ "waiting-count": { kind: "number", value: 1009 } }));
  });

  it("offers no variable while variables are off, and sends none", async () => {
    render(<QuerySetup connectionId="thelook" onKept={vi.fn()} />);
    expect(screen.queryByTestId("query-values-open")).toBeNull();
    fireEvent.change(screen.getByLabelText("SQL"), { target: { value: "SELECT 1" } });
    fireEvent.click(screen.getByTestId("query-run"));
    await waitFor(() => expect(api.previewCockpitQuery).toHaveBeenCalled());
    expect(api.previewCockpitQuery.mock.calls[0][1]).not.toHaveProperty("values");
  });
});

describe("a set read whole (Arc AP-8b)", () => {
  const link = (name: string, to: string, to_name: string, kind: "to-one" | "to-many") =>
    ({ name, to, to_name, kind, traversable: true, business_name: "", business_name_source: "", verb: "", relationship: name, direction: "out",
      to_type: to, cardinality: kind === "to-one" ? "N:1" : "1:N", measured: true, on: "" });
  beforeEach(() => {
    types.getObjectType.mockImplementation(async (name: string) => (name === "order"
      ? { ...ORDER, links: [link("placed_by", "user", "Customer", "to-one"), link("order_items", "order_item", "Order line", "to-many"),
        { ...link("untrusted", "product", "Product", "to-many"), traversable: false }] }
      : { ...ORDER, id: name, object_type: name, links: [] }));
  });

  it("gets its objects' linked objects through any link the door may cross — the set then holds those", async () => {
    const onChange = vi.fn();
    render(<SetSetup spec={desk()} name="waiting" onChange={onChange} onGone={vi.fn()} connectionId={`c${++conn}`} variablesOn />);
    await waitFor(() => expect(optionsOf(screen.getByLabelText("Gets its linked objects")).map(o => o.text))
      .toEqual(["No — its own order objects", "Customer · through placed by", "Order line · through order items"]));
    await choose(screen.getByLabelText("Gets its linked objects"), "placed_by");
    expect(onChange.mock.calls[0][0].sets.waiting).toEqual({ label: "Waiting", from: "placed", segment: "overdue_dispatch",
      traverse: { link: "placed_by", entity: "user" }, combine: null });
  });

  it("is combined only with sets of the objects it holds, in either, both or but not", async () => {
    const onChange = vi.fn();
    render(<SetSetup spec={desk()} name="big" onChange={onChange} onGone={vi.fn()} connectionId={`c${++conn}`} variablesOn />);
    await choose(screen.getByLabelText("How it is combined"), "but_not");
    expect(onChange.mock.calls[0][0].sets.big.combine).toEqual({ op: "but_not", set: "placed" });
    const spec = desk();
    spec.sets!.big.combine = { op: "but_not", set: "placed" };
    spec.sets!.theirs = { label: "Their customers", from: "waiting", traverse: { link: "placed_by", entity: "user" } };
    render(<SetSetup spec={spec} name="big" onChange={onChange} onGone={vi.fn()} connectionId={`c${++conn}`} variablesOn />,
      { container: document.body.appendChild(document.createElement("div")) });
    expect(optionsOf(screen.getAllByLabelText("The set it is combined with").at(-1)!).map(o => o.value)).toEqual(["placed", "waiting"]);   // never Their customers
  });

  it("says in the Variables list what it reaches and what it is combined with", () => {
    const spec = desk();
    spec.sets!.theirs = { label: "Their customers", from: "waiting", traverse: { link: "placed_by", entity: "user" } };
    spec.sets!.big.combine = { op: "but_not", set: "placed" };
    render(<DataPane spec={spec} selected={null} onSelect={vi.fn()} onChange={vi.fn()} connectionId={`c${++conn}`} variablesOn />);
    const line = (n: string) => screen.getAllByTestId("data-set").find(x => x.dataset.name === n)!;
    expect(line("theirs")).toHaveTextContent("Waiting → user");
    expect(line("big")).toHaveTextContent("1 condition · but not in Placed");
  });

  it("offers neither while variables are off", () => {
    render(<SetSetup spec={desk()} name="big" onChange={vi.fn()} onGone={vi.fn()} connectionId={`c${++conn}`} />);
    expect(screen.queryByTestId("set-traverse")).toBeNull();
    expect(screen.queryByTestId("set-combine")).toBeNull();
  });
});
