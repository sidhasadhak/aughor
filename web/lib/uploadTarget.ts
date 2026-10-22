/**
 * Where a file upload lands: the uploads connection of the workspace the reader stands in.
 *
 * Until 2026-10-23 every upload went to the one built-in `workspace` connection whatever workspace
 * was selected (`AddDataPanel` carried the id as a constant), so a new customer's files landed in a
 * connection their workspace did not hold, beside everyone else's (the Olist run, gaps 1 and 2).
 *
 * The rule now: the Default workspace keeps the built-in `workspace`; any other workspace uses its
 * own local-upload connection, made on its first upload and named after it ("Olist uploads"); a
 * workspace that was given the built-in one by hand keeps using it, because its files are already
 * there. The local-upload connector stores per connection id, so nothing moves.
 */
import { addConnection, getConnections, getWorkspace } from "./api";

/** The built-in upload connection — the Default workspace's, and the only one before 2026-10-23. */
export const BUILTIN_UPLOADS_ID = "workspace";
export const BUILTIN_UPLOADS_LABEL = "Workspace";

export interface UploadTarget {
  id: string;
  /** What the panel calls it: "Workspace" for the built-in, else the connection's own name. */
  label: string;
}

const builtin: UploadTarget = { id: BUILTIN_UPLOADS_ID, label: BUILTIN_UPLOADS_LABEL };

/** The name a workspace's own uploads connection is given when it is made. */
export function uploadsNameFor(workspaceName: string): string {
  return `${workspaceName.trim() || "Workspace"} uploads`;
}

/**
 * Resolve the workspace's uploads connection. `null` means the workspace has none yet — it is made
 * by `createUploadTarget` on the first upload, never by merely opening the panel.
 */
export async function resolveUploadTarget(workspaceId?: string | null): Promise<UploadTarget | null> {
  if (!workspaceId) return builtin;
  const [ws, conns] = await Promise.all([getWorkspace(workspaceId), getConnections()]);
  if (ws.is_default) return builtin;
  const members = new Set(ws.connection_ids ?? []);
  const own = conns.find(c => members.has(c.id) && c.conn_type === "local_upload" && c.id !== BUILTIN_UPLOADS_ID);
  if (own) return { id: own.id, label: own.name };
  if (members.has(BUILTIN_UPLOADS_ID)) return builtin;
  return null;
}

/** Make the workspace's own uploads connection (a member of it from birth) and return it. */
export async function createUploadTarget(workspaceId: string): Promise<UploadTarget> {
  const ws = await getWorkspace(workspaceId);
  const label = uploadsNameFor(ws.name);
  const created = await addConnection(label, "local_upload", "local://", undefined, {}, workspaceId);
  return { id: created.id, label };
}
