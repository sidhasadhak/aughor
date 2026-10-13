// @vitest-environment jsdom

/**
 * A follow-up asked under a past run, in an open Data Canvas, opens the chat ASKING it.
 *
 * 2026-10-13. The run's composer handed the canvas the question and its mode, and the canvas threw both away: it
 * opened a fresh, empty chat. The chat screen's own history carries them (`app/page.tsx`); this holds the canvas to it.
 */
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CanvasWorkspace } from "@/components/CanvasWorkspace";
import type { HistoryDetailPanel } from "@/components/HistoryDetailPanel";
import type { Canvas, Connection } from "@/lib/api";
import { act, render, screen } from "@/lib/testing";

type Continue = NonNullable<ComponentProps<typeof HistoryDetailPanel>["onContinue"]>;
/** What the past run was handed to continue with — called as its composer's Send would. */
const run = vi.hoisted(() => ({ onContinue: undefined as Continue | undefined }));

const api = vi.hoisted(() => ({
  getCanvasHistory: vi.fn(),
  getCanvasArtifacts: vi.fn(),
  getCanvasDocuments: vi.fn(),
}));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  getCanvasHistory: api.getCanvasHistory,
  getCanvasArtifacts: api.getCanvasArtifacts,
  getCanvasDocuments: api.getCanvasDocuments,
  listDocuments: vi.fn().mockResolvedValue([]),
  deleteCanvasArtifact: vi.fn().mockResolvedValue(undefined),
  updateCanvas: vi.fn(),
}));
// The chat shows what it was seeded with; the past run is only its composer's hand-off.
vi.mock("@/components/ChatPanel", () => ({
  ChatPanel: ({ initialQuestion, initialMode }: { initialQuestion?: string; initialMode?: string }) =>
    <div data-testid="chat" data-question={initialQuestion ?? ""} data-mode={initialMode ?? ""} />,
}));
vi.mock("@/components/HistoryDetailPanel", () => ({
  HistoryDetailPanel: ({ onContinue }: { onContinue?: Continue }) => {
    run.onContinue = onContinue;
    return <div data-testid="past-run" />;
  },
}));
vi.mock("@/components/ConfigurePanel", () => ({ ConfigurePanel: () => null }));
vi.mock("@/components/LifecyclePanel", () => ({ LifecyclePanel: () => null }));

const CANVAS: Canvas = {
  id: "cv1", name: "Returns", description: "", is_legacy: false, created_at: "", updated_at: "",
  scopes: [{ connection_id: "thelook", schema_name: "thelook", tables: ["thelook.order_items"] }],
};
const CONNECTIONS = [{ id: "thelook", name: "theLook", conn_type: "bigquery" }] as unknown as Connection[];

beforeEach(() => {
  run.onContinue = undefined;
  api.getCanvasHistory.mockReset().mockResolvedValue([]);
  api.getCanvasArtifacts.mockReset().mockResolvedValue([]);
  api.getCanvasDocuments.mockReset().mockResolvedValue([]);
});

describe("continuing a past run in chat", () => {
  it("carries the question and its mode into the chat", () => {
    render(<CanvasWorkspace canvas={CANVAS} connections={CONNECTIONS} onClose={vi.fn()} onCanvasUpdate={vi.fn()}
      initialOpenInvId="inv1" />);
    expect(screen.getByTestId("past-run")).toBeInTheDocument();
    expect(screen.getByTestId("chat")).toHaveAttribute("data-question", "");

    act(() => run.onContinue?.("Why did returns rise in July?", "ask"));

    const chat = screen.getByTestId("chat");
    expect(chat).toHaveAttribute("data-question", "Why did returns rise in July?");
    expect(chat).toHaveAttribute("data-mode", "ask");
  });
});
