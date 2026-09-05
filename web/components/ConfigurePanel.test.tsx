// @vitest-environment jsdom
/**
 * Instructions tab — two scopes, two stores, no cross-writes.
 *
 * PR #441 wired both instruction stores into the prompt; the connection-level one
 * had no editor (API-only). This pins the editor that closes that gap: both scopes
 * load from their own endpoint, a save writes ONLY its own scope's store, and a
 * canvas with no connection scope renders no connection editor (there is no id to
 * write under — a save would strand text beneath a "" key no ask ever resolves).
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getCanvasInstructions = vi.fn();
const putCanvasInstructions = vi.fn();
const getConnectionInstructions = vi.fn();
const putConnectionInstructions = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getCanvasInstructions: (...a: unknown[]) => getCanvasInstructions(...a),
    putCanvasInstructions: (...a: unknown[]) => putCanvasInstructions(...a),
    getConnectionInstructions: (...a: unknown[]) => getConnectionInstructions(...a),
    putConnectionInstructions: (...a: unknown[]) => putConnectionInstructions(...a),
  };
});

const { InstructionsTab } = await import("@/components/ConfigurePanel");

beforeEach(() => {
  getCanvasInstructions.mockReset().mockResolvedValue("canvas rules");
  putCanvasInstructions.mockReset().mockResolvedValue(undefined);
  getConnectionInstructions.mockReset().mockResolvedValue("connection rules");
  putConnectionInstructions.mockReset().mockResolvedValue(undefined);
});

describe("InstructionsTab", () => {
  it("loads each scope from its own endpoint", async () => {
    render(<InstructionsTab canvasId="cv_1" connectionId="conn_a" />);
    await waitFor(() => {
      expect(screen.getByLabelText("This Canvas")).toHaveValue("canvas rules");
      expect(screen.getByLabelText("Whole connection")).toHaveValue("connection rules");
    });
    expect(getCanvasInstructions).toHaveBeenCalledWith("cv_1");
    expect(getConnectionInstructions).toHaveBeenCalledWith("conn_a");
  });

  it("saving the connection editor writes only the connection store", async () => {
    getConnectionInstructions.mockResolvedValue("");
    render(<InstructionsTab canvasId="cv_1" connectionId="conn_a" />);
    const box = screen.getByLabelText("Whole connection");
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.type(box, "Exclude test accounts.");
    // the connection section's Save is the second (canvas renders first)
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[1]);
    await waitFor(() =>
      expect(putConnectionInstructions).toHaveBeenCalledWith("conn_a", "Exclude test accounts."));
    expect(putCanvasInstructions).not.toHaveBeenCalled();
  });

  it("saving the canvas editor writes only the canvas store", async () => {
    render(<InstructionsTab canvasId="cv_1" connectionId="conn_a" />);
    const box = screen.getByLabelText("This Canvas");
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(putCanvasInstructions).toHaveBeenCalledWith("cv_1", "canvas rules"));
    expect(putConnectionInstructions).not.toHaveBeenCalled();
  });

  it("renders no connection editor without a connection scope", async () => {
    render(<InstructionsTab canvasId="cv_1" connectionId="" />);
    await waitFor(() => expect(screen.getByLabelText("This Canvas")).toBeEnabled());
    expect(screen.queryByLabelText("Whole connection")).toBeNull();
    expect(getConnectionInstructions).not.toHaveBeenCalled();
  });
});
