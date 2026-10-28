// @vitest-environment jsdom
/**
 * TC-3 — an automation's history says the version each run ran under, and lists the versions kept.
 *
 * The property each test defends: what was not kept is SAID. Versions off draws nothing (the key
 * is absent, so a run card is unchanged); a run that kept no version says so instead of showing a
 * blank; a version no save recorded names nobody; and a read that failed says it failed rather
 * than drawing an empty history that reads as "never changed".
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VersionsList, runVersionLabel, versionLine } from "@/components/AutomationsPanel";
import type { AutomationRun, AutomationVersion, AutomationVersions } from "@/lib/api";

const run = (over: Partial<AutomationRun> = {}): AutomationRun => ({
  id: "r1", automation_id: "a1", outcome: "fired", reason: "due",
  started_at: "2026-10-26T09:00:00Z", duration_ms: 3, effects: [], error: "", ...over,
} as AutomationRun);

const version = (over: Partial<AutomationVersion> = {}): AutomationVersion => ({
  version: 1, version_id: "art-1", saved_by: "user:amit", saved_at: "2026-10-26T09:00:00Z",
  source: "saved", superseded_by: "", definition: {}, ...over,
});

const history = (over: Partial<AutomationVersions> = {}): AutomationVersions => ({
  automation_id: "a1", current_version: 2, current_kept: true, why_not: "",
  versions: [version({ version: 2, version_id: "art-2" }), version({ superseded_by: "art-2" })],
  ...over,
});

describe("runVersionLabel", () => {
  it("says nothing for a run from a server before versions — the run card is what it was", () => {
    expect(runVersionLabel(run())).toBe("");
  });
  it("says a run kept no version, rather than leaving a blank", () => {
    expect(runVersionLabel(run({ version: null }))).toBe("no version kept");
  });
  it("names the version a run ran under", () => {
    expect(runVersionLabel(run({ version: 3 }))).toBe("v3");
  });
});

describe("versionLine", () => {
  it("names who saved it, and says nothing more for an ordinary save", () => {
    const line = versionLine(version());
    expect(line.startsWith("saved by amit · ")).toBe(true);
    expect(line).not.toContain("· saved");
  });
  it("names nobody for a version no save recorded, and says how it was kept", () => {
    const line = versionLine(version({ saved_by: "", source: "in place when versions began" }));
    expect(line.startsWith("who saved it was not recorded · ")).toBe(true);
    expect(line.endsWith("· in place when versions began")).toBe(true);
  });
});

describe("VersionsList", () => {
  it("draws nothing when there are no versions to read", () => {
    const { container } = render(<VersionsList versions={null} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("says a failed read failed, never an empty history", () => {
    render(<VersionsList versions="failed" />);
    expect(screen.getByText("Its versions could not be read.")).toBeInTheDocument();
  });
  it("lists the versions newest first and says which one runs", () => {
    render(<VersionsList versions={history()} />);
    expect(screen.getByText("Versions · runs as v2")).toBeInTheDocument();
    expect(screen.getAllByText(/^v\d$/).map(n => n.textContent)).toEqual(["v2", "v1"]);
  });
  it("says why the current definition is not among them", () => {
    const why = "its current definition was saved before versions were kept";
    render(<VersionsList versions={history({ current_version: null, current_kept: false, why_not: why })} />);
    expect(screen.getByText("Versions")).toBeInTheDocument();
    expect(screen.getByText(why)).toBeInTheDocument();
  });
});
