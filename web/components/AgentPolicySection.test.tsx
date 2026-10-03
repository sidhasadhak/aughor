// @vitest-environment jsdom
/**
 * DE-2b (ROADMAP §3.51) — Settings ▸ Organization shows what an outside agent may do, apart from how it came
 * to be so: the policy a person saved (or the default nobody set), the environment's narrowing, and the
 * effective result. Pinned: what the section says for each, what it sends on save, that `act` is a named
 * person's to give (the form is disabled without `admin.manage_org`, and says so), and that a refusal is
 * shown in the server's words.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentPolicySection, describeEffective, parseAllowlist } from "@/components/AgentPolicySection";
import type { AgentPolicyView } from "@/lib/api";

const api = vi.hoisted(() => ({
  getAgentPolicy: vi.fn(), updateAgentPolicy: vi.fn(), clearAgentPolicy: vi.fn(), getMyAccess: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const policy = (over: Partial<AgentPolicyView["effective"]> = {}): AgentPolicyView["effective"] => ({
  level: "run", connections: null, tools: null, set_by: "", updated_at: "", source: "default", narrowed_by: [], ...over,
});
const view = (over: Partial<AgentPolicyView> = {}): AgentPolicyView => ({
  effective: policy(), saved: null, environment: { level: null, connections: null, tools: null },
  levels: ["read", "run", "act"], ...over,
});

beforeEach(() => {
  api.getAgentPolicy.mockReset();
  api.updateAgentPolicy.mockReset();
  api.clearAgentPolicy.mockReset();
  api.getMyAccess.mockReset();
  api.getMyAccess.mockResolvedValue(null);
});

describe("the sentence", () => {
  it("says the default was set by nobody, a saved one by whom, and what the environment narrowed", () => {
    expect(describeEffective(view())).toBe("run · the default — set by nobody");
    const saved = policy({ level: "act", set_by: "ada@example.com", updated_at: "2026-10-03T12:00:00+00:00", source: "saved" });
    expect(describeEffective(view({ effective: saved, saved }))).toMatch(/^act · set by ada@example.com on /);
    const narrowed = policy({ level: "read", source: "narrowed", narrowed_by: ["level"] });
    expect(describeEffective(view({ effective: narrowed, saved })))
      .toMatch(/^read · set by ada@example.com on .*; the environment narrowed the level$/);
  });

  it("reads a comma list, and blank as all", () => {
    expect(parseAllowlist(" a, b ,,c ")).toEqual(["a", "b", "c"]);
    expect(parseAllowlist("   ")).toBeNull();
  });
});

describe("the section", () => {
  it("shows the default in force and saves a person's choice with its allowlists", async () => {
    api.getAgentPolicy.mockResolvedValue(view());
    api.updateAgentPolicy.mockImplementation(async (body: { level: "read" | "run" | "act"; connections?: string[] | null; tools?: string[] | null }) => {
      const saved = policy({ ...body, connections: body.connections ?? null, tools: body.tools ?? null, set_by: "ada@example.com", updated_at: "2026-10-03T12:00:00+00:00", source: "saved" });
      return view({ effective: saved, saved });
    });
    render(<AgentPolicySection />);
    await waitFor(() => expect(screen.getByTestId("agent-policy-effective")).toHaveTextContent("run · the default — set by nobody"));
    expect(screen.queryByTestId("agent-policy-clear")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /Act/ }));
    fireEvent.change(screen.getByLabelText("Connections the agent may touch"), { target: { value: "c1, c2" } });
    fireEvent.click(screen.getByTestId("agent-policy-save"));
    await waitFor(() => expect(api.updateAgentPolicy).toHaveBeenCalledWith({ level: "act", connections: ["c1", "c2"], tools: null }));
    await waitFor(() => expect(screen.getByTestId("agent-policy-effective")).toHaveTextContent("act · set by ada@example.com"));
    expect(screen.getByText("Saved ✓")).toBeInTheDocument();
    // A saved policy can be returned to the default.
    api.clearAgentPolicy.mockResolvedValue(view());
    fireEvent.click(screen.getByTestId("agent-policy-clear"));
    await waitFor(() => expect(api.clearAgentPolicy).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId("agent-policy-effective")).toHaveTextContent("the default — set by nobody"));
  });

  it("says what the environment pins, and shows the narrowed result in force", async () => {
    const saved = policy({ level: "act", set_by: "ada@example.com", source: "saved" });
    api.getAgentPolicy.mockResolvedValue(view({
      saved, effective: policy({ level: "read", set_by: "ada@example.com", source: "narrowed", narrowed_by: ["level"] }),
      environment: { level: "read", connections: null, tools: ["ask"] },
    }));
    render(<AgentPolicySection />);
    await waitFor(() => expect(screen.getByTestId("agent-policy-environment"))
      .toHaveTextContent("pins the level at read, 1 tool — a saved policy can only be narrower than that, never wider"));
    expect(screen.getByTestId("agent-policy-effective")).toHaveTextContent("read · set by ada@example.com; the environment narrowed the level");
  });

  it("is disabled without admin.manage_org, and says so", async () => {
    api.getAgentPolicy.mockResolvedValue(view());
    api.getMyAccess.mockResolvedValue({ user_id: "u", org_id: "o", roles: ["viewer"], permissions: ["analysis.run"] });
    render(<AgentPolicySection />);
    await waitFor(() => expect(screen.getByTestId("agent-policy-locked")).toHaveTextContent("needs the admin.manage_org permission"));
    expect(screen.getByTestId("agent-policy-save")).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Read/ })).toBeDisabled();
  });

  it("shows a refusal in the server's words", async () => {
    api.getAgentPolicy.mockResolvedValue(view());
    api.updateAgentPolicy.mockRejectedValue(new Error("an agent policy is set by a named person"));
    render(<AgentPolicySection />);
    await waitFor(() => expect(screen.getByTestId("agent-policy-effective")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("agent-policy-save"));
    await waitFor(() => expect(screen.getByTestId("agent-policy-error")).toHaveTextContent("an agent policy is set by a named person"));
  });
});
