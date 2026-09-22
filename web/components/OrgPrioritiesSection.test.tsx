// CB-6 — people write the quarter's priorities; the editor adds, edits and removes rows.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { OrgPrioritiesSection } from "./OrgPrioritiesSection";

describe("OrgPrioritiesSection", () => {
  it("adds a row, edits it, and removes it", () => {
    const onChange = vi.fn();
    const { rerender } = render(<OrgPrioritiesSection value={[]} onChange={onChange} />);
    fireEvent.click(screen.getByText("Add a priority"));
    expect(onChange).toHaveBeenLastCalledWith([{ metric: "", target: "", direction: "", by: "", note: "" }]);
    rerender(<OrgPrioritiesSection value={[{ metric: "", target: "", direction: "", by: "", note: "" }]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Priority 1 metric"), { target: { value: "return rate" } });
    expect(onChange).toHaveBeenLastCalledWith([{ metric: "return rate", target: "", direction: "", by: "", note: "" }]);
    fireEvent.change(screen.getByLabelText("Priority 1 direction"), { target: { value: "down" } });
    expect(onChange).toHaveBeenLastCalledWith([{ metric: "", target: "", direction: "down", by: "", note: "" }]);
    fireEvent.click(screen.getByText("Remove"));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});
