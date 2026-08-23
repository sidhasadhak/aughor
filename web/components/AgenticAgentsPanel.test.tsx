// @vitest-environment jsdom
/**
 * VA-7 — the configuration history has to be readable as a CHANGE.
 *
 * Before this, a row rendered a truncated copy of the instructions: two revisions
 * differing only in schema scope looked identical, and two differing by one sentence of a
 * long prompt looked identical too. The history could be counted but not read.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentRevision, UserAgent } from "@/lib/api";

const listAgentRevisions = vi.fn();
const restoreAgentRevision = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    listAgentRevisions: (...a: unknown[]) => listAgentRevisions(...a),
    restoreAgentRevision: (...a: unknown[]) => restoreAgentRevision(...a),
  };
});

const { AgentConfigHistory, valueText } = await import("@/components/AgenticAgentsPanel");

const rev = (version: number, over: Partial<AgentRevision> = {}): AgentRevision => ({
  version, at: "2026-08-24T01:00:00", config_rev: `rev${version}`, author: "",
  name: "A", config: { instructions: `v${version}`, schema_scope: "public", doc_ids: [] },
  changed: ["instructions"], ...over,
});

const agent = (over: Partial<UserAgent> = {}) =>
  ({ id: "ua_1", name: "A", config_rev: "rev2", ...over } as UserAgent);

const show = (revisions: AgentRevision[]) => {
  listAgentRevisions.mockResolvedValue({ current_rev: "rev2", eval_basis: "none", revisions });
  return render(
    <AgentConfigHistory agent={agent()} onChanged={() => {}} onError={() => {}} />);
};

beforeEach(() => {
  listAgentRevisions.mockReset();
  restoreAgentRevision.mockReset();
});

describe("valueText", () => {
  it("counts a list and then names it", () => {
    expect(valueText("doc_ids", ["a", "b"])).toBe("2: a, b");
  });

  it("calls an empty binding none rather than showing a blank", () => {
    // An empty `doc_ids` is the RESTRICTIVE case, not an unset one — a blank reads as
    // "no restriction" and means the opposite.
    expect(valueText("doc_ids", [])).toBe("none");
  });

  it("distinguishes empty instructions from an unset field", () => {
    expect(valueText("instructions", "")).toBe("no instructions");
    expect(valueText("schema_scope", "")).toBe("not set");
  });
});

describe("AgentConfigHistory", () => {
  it("shows a single-revision agent instead of hiding until there are two", async () => {
    // Every agent that predated revision tracking had zero or one entry, so a panel that
    // hid below two showed those agents nothing at all.
    show([rev(1, { changed: [], config_rev: "rev2" })]);
    expect(await screen.findByText(/the configuration it started with/i)).toBeInTheDocument();
  });

  it("names the fields an edit moved", async () => {
    show([rev(2, { changed: ["instructions", "schema_scope"] }), rev(1, { changed: [] })]);
    expect(await screen.findByText("Instructions")).toBeInTheDocument();
    expect(screen.getByText("Schema scope")).toBeInTheDocument();
  });

  it("opens to the before and after of each changed field", async () => {
    show([
      rev(2, { changed: ["instructions"], config: { instructions: "after text", doc_ids: [] } }),
      rev(1, { changed: [], config: { instructions: "before text", doc_ids: [] } }),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: /what changed/i }));

    expect(screen.getByText("before text")).toBeInTheDocument();
    expect(screen.getByText("after text")).toBeInTheDocument();
  });

  it("says earlier history is not loaded rather than claiming nothing changed", async () => {
    // `changed: null` means the predecessor fell outside the window. Rendering that as
    // "no change" would tell the reader an edit did nothing.
    show([rev(9, { changed: null })]);
    expect(await screen.findByText(/earlier history not loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(/no governing change/i)).not.toBeInTheDocument();
  });

  it("offers no diff on the revision an agent started with", async () => {
    show([rev(1, { changed: [], config_rev: "rev2" })]);
    await screen.findByText(/the configuration it started with/i);
    expect(screen.queryByRole("button", { name: /what changed/i })).not.toBeInTheDocument();
  });
});
