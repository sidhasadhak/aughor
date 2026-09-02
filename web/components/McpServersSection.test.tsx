// @vitest-environment jsdom
/**
 * VA-9d — the MCP servers surface renders the SERVER's verdicts, never its own.
 *
 * Three claims, and the first two look like copy checks and are not:
 *
 * * **A refused tool is LISTED, not hidden.** A roster that showed only what it could call
 *   would be the catalogue-that-lies failure DS-10 exists to end — a reader would have no
 *   way to tell "the server does not offer that" from "we will not call it".
 * * **The refusal sentence is the server's, verbatim.** The read-only-first posture lives
 *   in those words, including the one that surprises people: a tool declaring nothing is
 *   refused because the protocol reads a missing declaration as "may modify". A client
 *   that re-worded them would be re-deciding the posture.
 * * **Adding a server contacts nothing.** Registering and running something against a
 *   third party are different acts, and the surface must not fuse them.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { McpServersSection } from "@/components/McpServersSection";
import type { McpServerRow, McpToolRow } from "@/lib/api";

const api = vi.hoisted(() => ({
  listMcpServers: vi.fn(),
  createMcpServer: vi.fn(),
  updateMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  discoverMcpServer: vi.fn(),
  mcpServerHealth: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const REFUSAL = "This server does not declare the tool as read-only, and the protocol "
  + "reads a missing declaration as 'may modify'.";

const tool = (over: Partial<McpToolRow> = {}): McpToolRow => ({
  server_id: "s1", name: "read_the_weather", title: "", description: "Reads the weather",
  input_schema: {}, disposition: "callable", reason: "",
  read_only_hint: true, destructive_hint: null,
  discovered_at: "2026-09-02T10:00:00Z", ...over,
});

const server = (over: Partial<McpServerRow> = {}): McpServerRow => ({
  id: "s1", name: "Fixture tools", transport: "stdio", command: "/usr/bin/python",
  args: ["server.py"], env: {}, url: "", has_auth: false, enabled: true,
  created_at: "", updated_at: "", discovered_at: "2026-09-02T10:00:00Z",
  tool_count: 2, callable_count: 1,
  tools: [tool(), tool({ name: "unannotated_thing", disposition: "refused_mutating",
                         reason: REFUSAL, read_only_hint: null, description: "" })],
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  api.listMcpServers.mockResolvedValue({ servers: [] });
  api.createMcpServer.mockResolvedValue(server());
  api.updateMcpServer.mockResolvedValue(server());
  api.deleteMcpServer.mockResolvedValue(undefined);
  api.discoverMcpServer.mockResolvedValue(server());
});

describe("the empty state", () => {
  it("says what the emptiness MEANS rather than apologising for it", async () => {
    render(<McpServersSection />);
    expect(await screen.findByText(/can call no MCP server at all/i)).toBeInTheDocument();
  });

  it("offers the catalog's last entry by name", async () => {
    render(<McpServersSection />);
    expect(await screen.findByRole("button", { name: /custom mcp/i })).toBeInTheDocument();
  });
});

describe("adding a server", () => {
  it("contacts nothing — registering and running are different acts", async () => {
    render(<McpServersSection />);
    fireEvent.click(await screen.findByRole("button", { name: /custom mcp/i }));
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Docs" } });
    fireEvent.change(screen.getByLabelText(/server url/i),
      { target: { value: "https://example.com/mcp" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(api.createMcpServer).toHaveBeenCalled());
    expect(api.discoverMcpServer).not.toHaveBeenCalled();
  });

  it("warns that a local process runs with the deployment's privileges", async () => {
    render(<McpServersSection />);
    fireEvent.click(await screen.findByRole("button", { name: /custom mcp/i }));
    fireEvent.click(screen.getByRole("button", { name: /local process/i }));
    expect(screen.getByText(/own privileges/i)).toBeInTheDocument();
    // Said BEFORE the command is pasted, not after it runs.
    expect(screen.getByText(/Nothing is passed to a shell/i)).toBeInTheDocument();
  });

  it("keeps the command and its arguments apart", async () => {
    render(<McpServersSection />);
    fireEvent.click(await screen.findByRole("button", { name: /custom mcp/i }));
    fireEvent.click(screen.getByRole("button", { name: /local process/i }));
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Local" } });
    fireEvent.change(screen.getByLabelText(/^command$/i), { target: { value: "npx" } });
    fireEvent.change(screen.getByLabelText(/arguments/i),
      { target: { value: "-y @modelcontextprotocol/server-everything" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(api.createMcpServer).toHaveBeenCalledWith(
      expect.objectContaining({
        transport: "stdio", command: "npx",
        args: ["-y", "@modelcontextprotocol/server-everything"],
      })));
  });
});

describe("the roster", () => {
  beforeEach(() => api.listMcpServers.mockResolvedValue({ servers: [server()] }));

  it("says how many tools this deployment may actually call", async () => {
    render(<McpServersSection />);
    expect(await screen.findByText(/2 tools · 1 callable here/)).toBeInTheDocument();
  });

  it("LISTS a refused tool rather than hiding it, with the server's own sentence", async () => {
    render(<McpServersSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^tools$/i }));

    expect(await screen.findByText("unannotated_thing")).toBeInTheDocument();
    expect(screen.getByText(REFUSAL)).toBeInTheDocument();
  });

  it("never shows the roster without saying when it was read", async () => {
    render(<McpServersSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^tools$/i }));
    expect(await screen.findByText(/Read from the server at/)).toBeInTheDocument();
  });

  it("offers Discover, and Re-discover once a roster exists", async () => {
    render(<McpServersSection />);
    expect(await screen.findByRole("button", { name: /re-discover/i })).toBeInTheDocument();
  });

  it("says 'not discovered yet' rather than implying a server offers nothing", async () => {
    api.listMcpServers.mockResolvedValue({
      servers: [server({ discovered_at: "", tool_count: 0, callable_count: 0, tools: [] })],
    });
    render(<McpServersSection />);
    expect(await screen.findByText(/not discovered yet/)).toBeInTheDocument();
  });
});

describe("errors", () => {
  it("shows the server's sentence, not a status code", async () => {
    api.listMcpServers.mockResolvedValue({ servers: [server()] });
    api.discoverMcpServer.mockRejectedValue(
      new Error("Fixture tools could not be reached: No such file or directory: 'npx'"));
    render(<McpServersSection />);
    fireEvent.click(await screen.findByRole("button", { name: /re-discover/i }));
    expect(await screen.findByText(/No such file or directory/)).toBeInTheDocument();
  });
});

describe("a credential never reaches this component", () => {
  it("has no field for it to render — the server drops it, not masks it", async () => {
    api.listMcpServers.mockResolvedValue({
      servers: [server({ transport: "http", command: "", args: [],
                         url: "https://example.com/mcp", has_auth: true })],
    });
    render(<McpServersSection />);
    expect(await screen.findByText(/auth header stored/)).toBeInTheDocument();
    // `McpServerRow` carries no `auth_header` at all, so there is nothing to leak here.
    expect(screen.queryByText(/Bearer /)).toBeNull();
  });
});
