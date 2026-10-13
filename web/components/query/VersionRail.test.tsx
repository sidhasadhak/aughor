// @vitest-environment jsdom
/**
 * The version rail says when a version was saved the way the history rail beside it does — "3h ago", the full time on
 * hover — never the stored ISO string. The versions read is stubbed; one version, so no diff is drawn.
 */
import { describe, expect, it, vi } from "vitest";

import type { SavedQueryVersion } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { render, screen } from "@/lib/testing";

const api = vi.hoisted(() => ({
  listSavedQueryVersions: vi.fn(), diffSavedQueryVersion: vi.fn(), restoreSavedQuery: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

import { VersionRail } from "./VersionRail";

describe("the version rail", () => {
  it("says when a version was saved as the rail beside it does, with the full time on hover", async () => {
    const at = new Date(Date.now() - 3 * 3600_000).toISOString();
    const v: SavedQueryVersion = { version: 1, state: "draft", created_at: at, name: "Revenue", sql: "SELECT 1", spec: {} };
    api.listSavedQueryVersions.mockResolvedValue([v]);
    render(<VersionRail queryId="q1" onRestored={vi.fn()} />);
    const when = await screen.findByText("3h ago");
    expect(when).toHaveAttribute("title", formatTimestamp(at));
    expect(screen.queryByText(/\d{4}-\d{2}-\d{2}/)).toBeNull();
  });
});
