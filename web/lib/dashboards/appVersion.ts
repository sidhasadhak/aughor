/**
 * What an App's owner is told about the version its readers read (Arc ED, ED-4; the user, 2026-10-24: readers see the
 * last published version).
 *
 * Each kept version says where it stands — draft, published or archived — and the newest says which version the App's
 * readers read (`published_version`, null while it reaches nobody). A keep since then is the owner's draft: it is said
 * beside the door that publishes it, and publishing to the same audience publishes it. A server from before App
 * versions says neither, and every word here reads as it did then.
 */
import type { DashboardVersion } from "@/lib/api";

type Kept = Pick<DashboardVersion, "version" | "published_to" | "state" | "published_version">;

export interface AppWords {
  /** The publish door's label. */
  label: string;
  /** What the door's title adds, "" when nothing is unpublished. */
  title: string;
  /** Changes kept since the version the readers read: publishing to the same audience publishes them. */
  draft: boolean;
  /** The version the readers read, when one is said. */
  readersSee: number | null;
}

export function appWords(kept: Kept): AppWords {
  const to = kept.published_to ?? [];
  if (!to.length) return { label: "Publish as an App", title: "", draft: false, readersSee: null };
  const names = to.map(t => t.name).join(", ");
  const readersSee = typeof kept.published_version === "number" ? kept.published_version : null;
  const draft = kept.state === "draft" && readersSee !== null && readersSee !== kept.version;
  return draft
    ? { label: `An App for ${names} · readers see version ${readersSee}`,
        title: `What you kept since version ${readersSee} is a draft. Its readers read version ${readersSee} until you publish.`,
        draft, readersSee }
    : { label: `An App for ${names}`, title: "", draft, readersSee };
}
