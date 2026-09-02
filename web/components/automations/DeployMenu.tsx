"use client";

/**
 * DS-17 · Deploy is a menu of doors.
 *
 * Every plane behind this button already existed. A chain could run on a schedule, post
 * into Slack as a bot, and be called as an MCP tool — each armed on a different screen, in
 * a different vocabulary, so "is this thing live?" had no answer short of visiting three
 * surfaces and knowing which flag to read on each. This says it once, on the surface where
 * the behaviour lives.
 *
 * **Every sentence on screen is the server's.** `reason` is rendered verbatim, and that is
 * the whole alt-door rule: a Slack door reading "connect via OAuth" would be correctly
 * SHAPED and point a self-hosted install at a door Slack refuses to open for it (no HTTPS
 * callback on a laptop). Only the server knows which door THIS deployment can open, so a
 * client that re-worded these would be re-deciding it — the hand-copied contract that rots.
 *
 * **The menu is fetched when it opens, not on render.** Each read counts bots, reads the
 * clock and looks for a tool-name clash; a canvas that did that on every frame would pay
 * for a menu nobody opened.
 *
 * **The token is shown once because it exists once.** The plaintext is in the issue
 * response and nowhere else, ever — so it is held in component state until this dialog
 * closes, and re-opening shows only the date it was minted. Rotating is the remedy for
 * having lost it, which is why that verb stays offered next to it.
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Icon, ICON_NAMES, type IconName } from "@/components/ui/icon";
import {
  getAutomationDoors, issueAutomationWebhook, revokeAutomationWebhook,
  setAutomationEnabled, setAutomationExposed,
  type AutomationDoor,
} from "@/lib/api";

/** The four states, as colour and word. `closed` is deliberately NOT an error hue: nothing
 *  is wrong with a door somebody has not opened yet, and painting it red would tell a
 *  reader to go fix something that is working as designed. */
const STATE: Record<AutomationDoor["state"], { label: string; color: string }> = {
  open:        { label: "open",        color: "var(--grn4)" },
  closed:      { label: "closed",      color: "var(--t3)" },
  needs_setup: { label: "needs setup", color: "var(--chart-3)" },
  unavailable: { label: "unavailable", color: "var(--red3)" },
};

/** The server names the glyph, but this set is the CLIENT's vocabulary — a name added to
 *  a palette or door table on the backend cannot be typechecked against it. A door drawn
 *  with a blank square would be a rendering bug reported as a product one, so an unknown
 *  name falls back to a real glyph. Same shape the canvas already uses for step kinds. */
function iconOf(name: string): IconName {
  return (ICON_NAMES as string[]).includes(name) ? (name as IconName) : "plug";
}

export interface DeployMenuProps {
  automationId: string;
  /** Refetch the record after a verb — `enabled` and `exposed_as_tool` both live on it,
   *  and the header's own chip reads them. */
  onChanged?: () => void;
}

export function DeployMenu({ automationId, onChanged }: DeployMenuProps) {
  const [open, setOpen] = React.useState(false);
  const [doors, setDoors] = React.useState<AutomationDoor[]>([]);
  const [summary, setSummary] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  /** The one-time plaintext, held only while this dialog is open. */
  const [issued, setIssued] = React.useState<{ url: string; token: string } | null>(null);

  const load = React.useCallback(async () => {
    try {
      const r = await getAutomationDoors(automationId);
      setDoors(r.doors);
      setSummary(r.summary);
      setError("");
    } catch {
      setError("Could not read this chain's doors.");
    }
  }, [automationId]);

  React.useEffect(() => { if (open) void load(); }, [open, load]);

  async function act(kind: string, fn: () => Promise<unknown>) {
    setBusy(kind);
    setError("");
    try {
      await fn();
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <Button variant="ghost" size="sm" className="aug-fs-xs" style={{ flexShrink: 0 }}
        onClick={() => setOpen(true)}>
        <Icon name="plug" size={12} /> Deploy
      </Button>

      <Dialog
        open={open}
        onOpenChange={(next: boolean) => {
          setOpen(next);
          // The plaintext dies with the dialog. Keeping it across opens would turn a
          // shown-once credential into one that lives in the tab until a reload.
          if (!next) { setIssued(null); setError(""); }
        }}
      >
        <DialogContent style={{ maxWidth: 620 }}>
          <DialogHeader>
            <DialogTitle>Deploy</DialogTitle>
            <DialogDescription>
              What this deployment can open for this chain. {summary}
            </DialogDescription>
          </DialogHeader>

          {error && (
            <div className="aug-fs-xs" style={{ color: "var(--red3)", marginBottom: 8 }}>
              {error}
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {doors.map(d => (
              <div key={d.kind} style={{
                display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 12px",
                border: "1px solid var(--b1)", borderRadius: "var(--r2)",
                background: "var(--bg-1)",
              }}>
                <span style={{ color: STATE[d.state].color, paddingTop: 2 }}>
                  <Icon name={iconOf(d.icon)} size={15} />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                    <span className="aug-fs-ui" style={{ fontWeight: 600 }}>{d.label}</span>
                    <span className="aug-fs-xs" style={{ color: STATE[d.state].color }}>
                      ● {STATE[d.state].label}
                    </span>
                    {d.detail && (
                      <span className="aug-fs-xs" style={{ color: "var(--t4)", overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.detail}</span>
                    )}
                  </div>
                  {/* The server's sentence, verbatim — see this file's header. */}
                  <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>
                    {d.reason}
                  </div>
                  {d.kind === "webhook" && issued && (
                    <IssuedUrl url={issued.url} token={issued.token} />
                  )}
                </div>
                <Verbs door={d} busy={busy} onAct={act} automationId={automationId}
                  onIssued={setIssued} />
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** The verbs a door offers HERE. A door whose fix lives on another screen offers none —
 *  its `reason` already names where to go, and a button that navigated away mid-deploy
 *  would lose the canvas the reader came from. */
function Verbs({ door, busy, onAct, automationId, onIssued }: {
  door: AutomationDoor;
  busy: string;
  onAct: (kind: string, fn: () => Promise<unknown>) => Promise<void>;
  automationId: string;
  onIssued: (v: { url: string; token: string } | null) => void;
}) {
  const working = busy === door.kind;
  const btn = (label: string, fn: () => Promise<unknown>, danger = false) => (
    <Button variant="ghost" size="xs" className="aug-fs-xs" disabled={working}
      style={{ flexShrink: 0, color: danger ? "var(--red3)" : undefined }}
      onClick={() => void onAct(door.kind, fn)}>
      {working ? "…" : label}
    </Button>
  );

  if (door.state === "needs_setup" || door.state === "unavailable") return null;

  if (door.kind === "schedule") {
    return door.state === "open"
      ? btn("Turn off", () => setAutomationEnabled(automationId, false))
      : btn("Turn on", () => setAutomationEnabled(automationId, true));
  }
  if (door.kind === "mcp_tool") {
    return door.state === "open"
      ? btn("Stop offering", () => setAutomationExposed(automationId, false))
      : btn("Offer as tool", () => setAutomationExposed(automationId, true));
  }
  if (door.kind === "webhook") {
    const issue = async () => onIssued(await issueAutomationWebhook(automationId));
    return (
      <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
        {door.state === "open"
          ? btn("Rotate", issue)
          : btn("Issue URL", issue)}
        {door.detail && btn("Revoke", async () => {
          await revokeAutomationWebhook(automationId);
          onIssued(null);
        }, true)}
      </div>
    );
  }
  // Slack, and anything added later: the fix is elsewhere and the reason says where.
  return null;
}

/** The one-time credential. Shown as the whole call, not a bare token, because what a
 *  reader has to paste somewhere else is the request — and a token on its own is the part
 *  of it most easily pasted into the wrong box. */
function IssuedUrl({ url, token }: { url: string; token: string }) {
  const [copied, setCopied] = React.useState(false);
  const curl = `curl -X POST ${url} -H "Authorization: Bearer ${token}"`;
  return (
    <div style={{ marginTop: 6 }}>
      <div className="aug-fs-xs" style={{ color: "var(--chart-3)", marginBottom: 4 }}>
        Shown once — copy it now. Rotating is the only way to get another.
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
        <code className="aug-fs-xs" style={{
          flex: 1, minWidth: 0, wordBreak: "break-all", color: "var(--t2)",
          background: "var(--bg-2)", border: "1px solid var(--b1)",
          borderRadius: "var(--r2)", padding: "6px 8px",
        }}>{curl}</code>
        <Button variant="ghost" size="xs" className="aug-fs-xs" style={{ flexShrink: 0 }}
          onClick={() => {
            void navigator.clipboard?.writeText(curl);
            setCopied(true);
          }}>
          <Icon name="copy" size={11} /> {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}
