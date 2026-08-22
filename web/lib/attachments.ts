/**
 * CA-5 — what happens to a file dropped into the conversation.
 *
 * Before this, every attachment went to `/documents/upload` — the RAG document path —
 * and a CSV became prose the model could read *about* rather than a table it could
 * query. The specimen's path was the other one: a dropped CSV becomes a workspace
 * table, and the next question is answered from it with the whole guard battery in
 * front. So the file's KIND decides its door:
 *
 *   data (csv/tsv/xlsx/json/parquet) → the connection's file ingest → a real table
 *   everything else (pdf/md/txt/docx) → the document store → retrieval context
 *
 * The other half of the fix is honesty. The old call site swallowed upload failures
 * ("Non-fatal: still send the question even if upload fails") and sent the question
 * anyway — so a question ABOUT a file that never arrived was answered from whatever
 * else was lying around, with nothing on screen saying the file was missing. Every
 * outcome here is returned as a value the caller must render.
 */
import { uploadDocument, uploadFileToConnection } from "@/lib/api";

/** Extensions the file connectors can ingest as a table. */
const DATA_EXT = ["csv", "tsv", "txt.gz", "xlsx", "xls", "json", "jsonl", "parquet"];

export type AttachmentKind = "data" | "document";

export interface AttachmentResult {
  kind: AttachmentKind;
  filename: string;
  /** Set when the file became a queryable table. */
  table?: string;
  /** Set when the upload failed — the message is shown, never swallowed. */
  error?: string;
}

export function extensionOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
}

/** Which door this file takes. Exported so the UI can label the drop zone honestly. */
export function attachmentKind(file: File): AttachmentKind {
  return DATA_EXT.includes(extensionOf(file.name)) ? "data" : "document";
}

/**
 * Upload one attachment through the door its kind names. Never throws: a failure is
 * an `error` on the result, because the caller has to keep the conversation usable
 * either way — and has to be able to SAY what went wrong.
 */
export async function uploadAttachment(
  file: File,
  connectionId: string,
): Promise<AttachmentResult> {
  const kind = attachmentKind(file);
  if (kind === "data") {
    // A data file with no connection to land in is a refusal, not a silent document.
    if (!connectionId) {
      return { kind, filename: file.name, error: "No connection selected to import this into." };
    }
    try {
      const res = await uploadFileToConnection(connectionId, file);
      const table = res.schema ? `${res.schema}.${res.table_name}` : res.table_name;
      return { kind, filename: file.name, table };
    } catch (e) {
      // The backend's own sentence — "Connection is not a file connector" for a
      // warehouse, a parse error for a malformed CSV — is more useful than ours.
      return { kind, filename: file.name, error: (e as Error).message || "Import failed" };
    }
  }
  try {
    await uploadDocument(file);
    return { kind, filename: file.name };
  } catch (e) {
    return { kind, filename: file.name, error: (e as Error).message || "Upload failed" };
  }
}
