// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

const strokeOf = (container: HTMLElement) => container.querySelector("svg")?.getAttribute("stroke-width");

describe("an icon's stroke follows the label beside it", () => {
  afterEach(cleanup);

  it("is the optical stroke for its size on its own", () => {
    expect(strokeOf(render(<Icon name="refresh" size={16} />).container)).toBe("1.63");
  });

  it("steps up 4/3 inside a labelled button, whose label is 500–600", () => {
    expect(strokeOf(render(<Button><Icon name="refresh" size={16} />Refresh</Button>).container)).toBe("2.17");
  });

  it("stays regular in an icon-only button, and an explicit stroke always wins", () => {
    expect(strokeOf(render(<Button size="icon" aria-label="Refresh"><Icon name="refresh" size={16} /></Button>).container)).toBe("1.63");
    expect(strokeOf(render(<Button><Icon name="refresh" size={16} stroke={1.5} />Refresh</Button>).container)).toBe("1.5");
  });
});
