// @vitest-environment jsdom

/**
 * ON-10 — the question's frame, shown with the answer.
 *
 * What these pin: the block says what the question was read as and nothing when the question reached nothing
 * declared; a model's choice among equally-fitting definitions is said as one, with the definitions it chose among;
 * and the details name the definition, the rules with the links they were applied through, where the reading started
 * and the drivers — the ones the question named first — plus a rule the frame could not apply and why.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { QuestionFrame } from "@/components/QuestionFrame";
import type { FrameOutcome, OntologyFrame } from "@/lib/types";

const dispatch: FrameOutcome = {
  kind: "promise", name: "dispatch_breach_rate", label: "the dispatch promise of Order to delivery (stage dispatched)",
  entity: "OrderItem", object_type: "order_item", process: "order_to_delivery", stage: "dispatched", promise: "dispatch",
  segment: "late_dispatch", metric: "dispatch_breach_rate", lag: "",
  definition: "an Order Line breaks it when dispatched (order_item_to_order.order_delivered_carrier_date) after the deadline shipping_limit_date",
  measured: "10,423 of the 111,456 OrderItem objects that reached dispatched broke the dispatch promise (9.35%)",
  rate: 0.093517, usable: true, why_not: "", caveats: [], matched: ["dispatch"], score: 2, note: "",
};
const delivery: FrameOutcome = { ...dispatch, name: "delivery_breach_rate", label: "the delivery promise", entity: "Order" };

function frame(over: Partial<OntologyFrame> = {}): OntologyFrame {
  return {
    question: "What is causing a delay in warehouse dispatch?", connection_id: "baef6c3e", schema_name: "ecommerce",
    hops: 2, terms: [], outcomes: [dispatch], chosen: 0, chosen_by: "names",
    start: { object_type: "order_item", entity: "OrderItem", name: "Order Line", table: "order_items",
             key: "order_item_id", key_unique: false },
    rules: [
      { id: "southeast", label: "Southeast", entity: "Seller", words: "Seller.seller_state is one of SP, RJ, MG, ES",
        owner: "operations", matched: "Southeast", via: "order_item_to_seller", filters: [], measured: "", usable: true,
        why_not: "" },
      { id: "five_star", label: "Five star", entity: "Review", words: "rating = 5", owner: "", matched: "five star",
        via: "", filters: [], measured: "", usable: false,
        why_not: "Review is not reachable from OrderItem by measured to-one links within 2 hops" },
    ],
    moments: [],
    drivers: [
      { path: "order_item_to_product.product_category_name", label: "product category name", entity: "Product",
        object_type: "product", property: "product_category_name", table: "products", links: [], named: false },
      { path: "order_item_to_seller.seller_state", label: "seller state", entity: "Seller", object_type: "seller",
        property: "seller_state", table: "sellers", links: [], named: true },
    ],
    compiled: {}, notes: [],
    reading: 'Read "dispatch" as the dispatch promise of Order to delivery (stage dispatched).',
    defines: true, ambiguous: false,
    ...over,
  };
}

describe("QuestionFrame", () => {
  it("renders nothing when the question reached nothing declared", () => {
    const { container } = render(<QuestionFrame frame={frame({ defines: false, reading: "" })} />);
    expect(container).toBeEmptyDOMElement();
    const none = render(<QuestionFrame frame={null} />);
    expect(none.container).toBeEmptyDOMElement();
  });

  it("says what the question was read as, and a model's choice as one", () => {
    render(<QuestionFrame frame={frame({ outcomes: [dispatch, delivery], chosen_by: "model" })} />);
    expect(screen.getByText("Read as")).toBeInTheDocument();
    expect(screen.getByText(/Read "dispatch" as the dispatch promise/)).toBeInTheDocument();
    expect(screen.getByText(/fit 2 declared definitions \(dispatch_breach_rate, delivery_breach_rate\); a model/))
      .toBeInTheDocument();
  });

  it("does not claim a model chose when the declared names settled it", () => {
    render(<QuestionFrame frame={frame()} />);
    expect(screen.queryByText(/a model/)).not.toBeInTheDocument();
  });

  it("details the definition, the rules through their links, the start and the named drivers first", async () => {
    render(<QuestionFrame frame={frame()} />);
    await userEvent.click(screen.getByRole("button", { name: /How the question was framed/ }));
    expect(screen.getByText(/breaks it when dispatched/)).toBeInTheDocument();
    expect(screen.getByText(/Measured: 10,423 of the 111,456/)).toBeInTheDocument();
    expect(screen.getByText(/southeast: Seller.seller_state is one of SP, RJ, MG, ES \(through order_item_to_seller\)/))
      .toBeInTheDocument();
    expect(screen.getByText("Order Line (order_items)")).toBeInTheDocument();
    const drivers = screen.getAllByText(/^order_item_to_(seller|product)\./).map((el) => el.textContent);
    expect(drivers[0]).toBe("order_item_to_seller.seller_state · named in the question");
    expect(screen.getByText(/five_star was not applied: Review is not reachable/)).toBeInTheDocument();
  });
});
