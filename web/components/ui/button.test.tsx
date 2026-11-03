// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";

const pressScales = (name: string) => screen.getByRole("button", { name }).classList.contains("aug-press");

describe("an action looks like a button at rest", () => {
  afterEach(cleanup);
  const variantOf = (name: string) => screen.getByRole("button", { name }).className.match(/rt-variant-\w+/)?.[0];

  it("draws an edge on an action, and none on a row or an icon alone", () => {
    render(<>
      <Button variant="ghost">Check again</Button>
      <Button variant="plain">A whole row</Button>
      <Button variant="ghost" size="icon-xs" aria-label="Close">×</Button>
    </>);
    expect(variantOf("Check again")).toBe("rt-variant-outline");
    expect(variantOf("A whole row")).toBe("rt-variant-ghost");
    expect(variantOf("Close")).toBe("rt-variant-ghost");
  });
});

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
