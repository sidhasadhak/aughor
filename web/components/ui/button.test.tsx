// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";

const pressScales = (name: string) => screen.getByRole("button", { name }).classList.contains("aug-press");

describe("press feedback", () => {
  afterEach(cleanup);

  it("scales the Primary and no other variant", () => {
    render(<>
      <Button>Run</Button>
      <Button variant="secondary">Cancel</Button>
      <Button variant="ghost">Row action</Button>
      <Button variant="outline">Filter</Button>
    </>);
    expect(pressScales("Run")).toBe(true);
    expect(pressScales("Cancel")).toBe(false);
    expect(pressScales("Row action")).toBe(false);
    expect(pressScales("Filter")).toBe(false);
  });

  it("keeps a Primary still when it is static", () => {
    render(<Button static>Submit</Button>);
    expect(pressScales("Submit")).toBe(false);
  });
});
