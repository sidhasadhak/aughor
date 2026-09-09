// @vitest-environment jsdom
/**
 * The palette's keyboard cursor must select THE ROW UNDER THE HIGHLIGHT.
 *
 * It did not. The list renders GROUPED (`SECTION_ORDER`: commands, then navigation,
 * then runs, tables, canvases, spotlight) and the highlight is an index counted down
 * those rendered rows — but `flatResults`, which Enter read, was the raw Fuse result
 * order. Fuse ranks by score, and a navigation row routinely outscores the command
 * that renders above it, so the two orders disagree in the ordinary case.
 *
 * Measured on the live app before the fix: typing "add connection" highlighted
 * "Add a data source" and Enter ran the "Connections" navigation row instead — the
 * keyboard did something different from clicking the row the user was looking at.
 *
 * This test pins the invariant, not the incident: whatever the query, Enter runs the
 * item whose row carries `data-active`.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

// The palette mounts a chat hook (Spotlight's answer pane) and fetches recent runs on
// open. Neither is under test; stub both so this stays a keyboard-navigation test.
vi.mock("@/lib/useAughorChat", () => ({
  useAughorChat: () => ({ messages: [], sendMessage: vi.fn(), status: "ready", error: null }),
}));
vi.mock("@/lib/schema-context", () => ({ useRichSchema: () => ({ schema: null }) }));

const { CommandPalette, GlobalCommands } = await import("@/components/CommandPalette");

it("Enter activates the highlighted row, not Fuse's top hit", async () => {
  // jsdom has no layout, so it ships no scrollIntoView; the cursor effect calls it.
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  const onNavigate = vi.fn();
  const onAddSource = vi.fn();
  const user = userEvent.setup();

  render(
    <>
      <GlobalCommands onNavigate={onNavigate} onGoToChat={vi.fn()} onAddSource={onAddSource} />
      <CommandPalette open onClose={vi.fn()} selectedConn="c1"
        onNavigate={onNavigate} onGoToChat={vi.fn()} />
    </>,
  );

  await user.type(screen.getByPlaceholderText(/search/i), "add connection");

  // Whatever ranked first, the highlight is what the user is aiming at.
  const active = document.querySelector("[data-active='true']");
  expect(active, "no row is highlighted — the cursor has nothing to point at").toBeTruthy();
  const highlighted = active!.textContent ?? "";

  await user.keyboard("{Enter}");

  if (highlighted.includes("Add a data source")) {
    expect(onAddSource).toHaveBeenCalled();
    expect(onNavigate).not.toHaveBeenCalled();
  } else {
    // The ordering could legitimately change; the invariant may not.
    expect(onNavigate, `highlighted "${highlighted}" but nothing ran`).toHaveBeenCalled();
  }
});
