// @vitest-environment jsdom
/**
 * DS-4 — what replaced the `window.prompt`.
 *
 * The prompt was blind: whatever you typed became a `{"$from": "step.key"}` binding, and
 * a typo drew a correct-looking edge that the run then skipped at 09:00. That is the
 * failure B1 ended for closed-set ports; this closes it for the one port whose set is
 * genuinely open.
 *
 * So the two properties worth guarding are: the picker OFFERS what the step has actually
 * been seen to publish, and it still ACCEPTS a key nobody has observed — because the set
 * is open by declaration, and refusing an unobserved key would be the canvas teaching a
 * rule the engine does not have.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OutcomeKeyPicker } from "@/components/automations/OutcomeKeyPicker";

function mount(over: Partial<React.ComponentProps<typeof OutcomeKeyPicker>> = {}) {
  const onPick = vi.fn();
  const onCancel = vi.fn();
  render(
    <OutcomeKeyPicker
      from="step3" field="message" candidates={["annotation", "id"]}
      onPick={onPick} onCancel={onCancel} {...over}
    />,
  );
  return { onPick, onCancel };
}

describe("offering the keys the step really published", () => {
  it("names the step and the field, so the question is answerable without the canvas", () => {
    mount();
    const picker = screen.getByTestId("outcome-key-picker");
    expect(picker.textContent).toContain("step3");
    expect(picker.textContent).toContain("message");
  });

  it("binds on a click, with the key exactly as published", () => {
    const { onPick } = mount();
    fireEvent.click(screen.getByRole("button", { name: "annotation" }));
    expect(onPick).toHaveBeenCalledWith("annotation");
  });

  it("says the keys came from a run, not from a schema it does not have", () => {
    mount();
    expect(screen.getByTestId("outcome-key-picker").textContent)
      .toContain("published on its last run");
  });
});

describe("the open tail", () => {
  it("accepts a key nobody has observed", () => {
    // `PUBLISHED_KEYS` declares this set OPEN and the executor's dispatcher is
    // injectable, so an unobserved key is legitimate. Refusing it here would be the
    // canvas inventing a rule `validate_chain` does not enforce.
    const { onPick } = mount({ candidates: [] });
    fireEvent.change(screen.getByLabelText("Outcome key"), { target: { value: "receipt_id" } });
    fireEvent.click(screen.getByRole("button", { name: "Bind" }));
    expect(onPick).toHaveBeenCalledWith("receipt_id");
  });

  it("binds on Enter, because typing then reaching for a button is the slow path", () => {
    const { onPick } = mount({ candidates: [] });
    const input = screen.getByLabelText("Outcome key");
    fireEvent.change(input, { target: { value: "job_id" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onPick).toHaveBeenCalledWith("job_id");
  });

  it("trims, so a stray space cannot become part of the key", () => {
    // `"step3. ts"` is a binding that resolves to nothing and reads as correct.
    const { onPick } = mount({ candidates: [] });
    fireEvent.change(screen.getByLabelText("Outcome key"), { target: { value: "  ts  " } });
    fireEvent.keyDown(screen.getByLabelText("Outcome key"), { key: "Enter" });
    expect(onPick).toHaveBeenCalledWith("ts");
  });

  it("never binds an empty key", () => {
    const { onPick } = mount({ candidates: [] });
    fireEvent.keyDown(screen.getByLabelText("Outcome key"), { key: "Enter" });
    expect(screen.getByRole("button", { name: "Bind" })).toBeDisabled();
    expect(onPick).not.toHaveBeenCalled();
  });
});

describe("the three states are three different sentences", () => {
  it("says it is still looking while the lookup is in flight", () => {
    mount({ candidates: null });
    expect(screen.getByTestId("outcome-key-picker").textContent).toContain("looking up");
  });

  it("says a step that never ran has no known keys — not that it has none", () => {
    // "no keys" and "we have not seen its keys" are opposite claims about the same
    // screen, and only one of them is true for a step that has not run here.
    mount({ candidates: [] });
    expect(screen.getByTestId("outcome-key-picker").textContent)
      .toContain("has not run here yet");
  });

  it("offers no key buttons when there are none, rather than an empty row", () => {
    mount({ candidates: [] });
    expect(screen.queryByRole("button", { name: "annotation" })).toBeNull();
  });
});

describe("cancelling", () => {
  it("cancels on Escape and on the button, and binds nothing either way", () => {
    const { onPick, onCancel } = mount();
    fireEvent.keyDown(screen.getByLabelText("Outcome key"), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onPick).not.toHaveBeenCalled();
  });
});
