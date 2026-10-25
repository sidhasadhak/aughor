// @vitest-environment jsdom
/**
 * The Record's five views, laid out to CLARITY: the figures first, what needs a person under "Needs you", then one
 * row per thing. What every row would repeat — a state, a status, a warrant, an author — is said once, in a figure or
 * a group's heading; a row carries a chip only where it differs. The full text stays on the hover and in Copy · CSV.
 */
import { Theme } from "@radix-ui/themes";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Connection } from "@/lib/api";
import type { Claim, Corrections, Decision, Inquiry } from "@/lib/record";

import { CorrectionsPanel } from "./CorrectionsPanel";
import { RecordPanel } from "./RecordPanel";
import { DecisionsPanel } from "@/components/decisions/DecisionsPanel";
import { InquiriesPanel } from "@/components/inquiries/InquiriesPanel";

const record = vi.hoisted(() => ({
  listInquiries: vi.fn(), listDecisions: vi.fn(), listClaims: vi.fn(), getCorrections: vi.fn(), getOnboarding: vi.fn(),
  listDecisionKinds: vi.fn(),
}));
vi.mock("@/lib/record", async (original) => ({ ...(await original<typeof import("@/lib/record")>()), ...record }));

const CONNECTIONS = [{ id: "shop", name: "The shop" }] as unknown as Connection[];
const noop = () => undefined;
const WAITING = "data that would settle the open items";
const SCHEDULED = "[Scheduled-run context — written by code, not inferred]\nThis is a scheduled daily run at 2026-10-06T09:00Z.\nObserve 2026-09-28 (UTC).\nSay in the report ";

const inquiry = (x: Partial<Inquiry>): Inquiry => ({
  id: "q", key: "k", version: 1, question: "Why?", subject: "", connection_id: "shop", opened_by: "person", hypotheses: [],
  runs: [{ run: "r1", verdict: "answered", why: "Revenue rose", at: "2026-10-06" }], claims: [],
  open: [{ what: "The prior week was not measured", settled_by: "unstated — the report named the gap" }],
  decisions: [], state: "waiting", waiting_for: WAITING, closed_as: "", next_check: "2026-11-10", woke: [], refused: [],
  lessons: [], opened_at: "2026-10-06T09:00:00Z", extra: {}, recorded_at: "2026-10-06T09:00:00Z", superseded_by: "", ...x,
});

const claim = (x: Partial<Claim>): Claim => ({
  id: "c", key: "k", version: 1, kind: "finding", about: { kind: "connection", key: "shop" },
  statement: { text: "Orders fell 4% in September. Most of it was in Outerwear.", metric: "", value: null, unit: "", range_start: "", range_end: "", object_set: "" },
  tier: "measured", status: "Provisional", as_of: "2026-10-12", valid_from: "", valid_until: "", warrants: [], falsifier: "",
  next_check: "", owner: "", author: "agent:explorer", author_kind: "agent", definition_version: "", state: "", extra: {},
  recorded_at: "2026-10-12T09:00:00Z", supersedes: "", superseded_by: "", confidence: null,
  confidence_note: "no reference class counts a claim of kind 'finding' yet", ...x,
} as Claim);

const mount = (el: React.ReactElement) => render(<Theme>{el}</Theme>);

beforeEach(() => {
  for (const f of Object.values(record)) f.mockReset();
  record.listDecisionKinds.mockResolvedValue({ kinds: [] });
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => vi.useRealTimers());

describe("Inquiries", () => {
  beforeEach(() => record.listInquiries.mockResolvedValue([
    inquiry({ id: "q1", question: SCHEDULED, runs: Array.from({ length: 7 }, (_, i) => ({ run: `r${i}`, verdict: "answered", why: `Day ${i}`, at: "" })) }),
    inquiry({ id: "q2", question: "What is causing delivery delays?" }),
    inquiry({ id: "q3", question: "Why did the delivered stage of order_fulfilment slowed?", state: "open", waiting_for: "",
      next_check: "", runs: [], open: [], opened_by: "process:order_fulfilment" }),
  ]));

  it("opens on the counts by state, and says the shared waiting reason once", async () => {
    mount(<InquiriesPanel connections={CONNECTIONS} openId={null} onOpen={noop} onOpenRun={noop} onOpenDecision={noop} onOpenClaim={noop} onAsk={noop} />);
    const figures = await screen.findByTestId("inquiry-figures");
    expect(within(screen.getByTestId("fig-inq-open")).getByText("1")).toBeInTheDocument();
    expect(within(screen.getByTestId("fig-inq-waiting")).getByText("2")).toBeInTheDocument();
    expect(within(screen.getByTestId("fig-inq-closed")).getByText("0")).toBeInTheDocument();
    expect(within(screen.getByTestId("fig-inq-items")).getByText("2")).toBeInTheDocument();
    // The long reason is said once, in the figure — never on each row.
    expect(within(figures).getByText(`for ${WAITING}`)).toBeInTheDocument();
    expect(screen.queryAllByText(new RegExp(WAITING))).toHaveLength(1);
  });

  it("reads a scheduled run's plumbing as a short label, folds empty columns and humanises the next check", async () => {
    mount(<InquiriesPanel connections={CONNECTIONS} openId={null} onOpen={noop} onOpenRun={noop} onOpenDecision={noop} onOpenClaim={noop} onAsk={noop} />);
    const list = await screen.findByTestId("inquiry-list");
    const row = within(list).getByRole("button", { name: "Scheduled daily run" });
    expect(row).toHaveAttribute("title", SCHEDULED.trim());                   // the full text, on hover
    expect(list.textContent).not.toMatch(/Scheduled-run context/);
    expect(list.textContent).not.toMatch(/Owner|Hypotheses|—|2026-11-10/);     // empty columns folded; no ISO day
    expect(within(list).getAllByText(/next check Tue 10 Nov/).length).toBe(2);
    // The open inquiry nobody has run is what needs a person, with its button on the row.
    const needs = screen.getByTestId("inquiry-needs");
    expect(needs).toHaveAttribute("data-waiting", "true");
    expect(within(needs).getByText(/order fulfilment slowed/)).toBeInTheDocument();
    expect(within(needs).getByRole("button", { name: "Open" })).toBeInTheDocument();
  });
});

describe("Decisions", () => {
  it("labels a ledger-written question in words and says once that none can be scored", async () => {
    record.listDecisions.mockResolvedValue([{
      id: "d1", key: "k", version: 1, question: "open_case: order:2 is in overdue_dispatch; proposed by the OC-8 receipt script",
      owner: "", approvers: [], options: [{ id: "approve", description: "approve the proposal" }, { id: "decline", description: "reject the proposal" }],
      chosen: "decline", dissent: [], relied_on: [], objective: "", decided_at: "2026-10-10T14:16:17Z", decided_by: "ana",
      review_on: "2026-12-08", expectation_claim: "", actions: [], outcome: "", reopened_by: "",
      source: { kind: "approval", ref: "a", detail: "" }, connection_id: "shop",
      extra: { expectation_note: "none: a staged proposal carries no expectation line" }, recorded_at: "", superseded_by: "",
    } as unknown as Decision]);
    mount(<DecisionsPanel connections={CONNECTIONS} selectedConn="shop" openId={null} onOpen={noop} onOpenClaim={noop} />);
    const list = await screen.findByTestId("decision-list");
    expect(within(list).getByRole("button", { name: "Open case: order:2 is in overdue dispatch" })).toBeInTheDocument();
    expect(within(list).getByText("declined")).toBeInTheDocument();
    expect(list.textContent).not.toMatch(/OC-8|2026-12-08/);
    expect(within(screen.getByTestId("fig-dec-expect")).getByText("1 cannot be scored")).toBeInTheDocument();
    expect(within(screen.getByTestId("decision-needs")).getByText("Nothing needs you")).toBeInTheDocument();
  });

  it("lists the kinds of decision people declared, with the rules each keeps", async () => {
    record.listDecisions.mockResolvedValue([]);
    record.listDecisionKinds.mockResolvedValueOnce({ kinds: [{
      id: "k1", key: "decision_kind:a_price_change", version: 1, name: "a price change", description: "",
      approvers: ["person:ana"], expectation_required: true, review_days: 14, authority_ceiling: null, metrics: ["gmv"],
      state: "active", declared_by: "user:amit", recorded_at: "",
    }] });
    mount(<DecisionsPanel connections={CONNECTIONS} selectedConn="shop" openId={null} onOpen={noop} onOpenClaim={noop} />);
    const kinds = await screen.findByTestId("decision-kinds");
    expect(kinds).toHaveTextContent("a price change");
    expect(kinds).toHaveTextContent("moves gmv");
    expect(kinds).toHaveTextContent("reviewed after 14 days");
    expect(kinds).toHaveTextContent("must say what it expects");
  });

  it("says how many reviews reached a verdict, never that each can be scored", async () => {
    // The decision-framework run: every review said cannot tell while the card read "each can be scored".
    const row = (id: string, verdict: string) => ({
      id, key: id, version: 2, question: `Decision ${id}`, owner: "", approvers: [], options: [], chosen: "go",
      dissent: [], relied_on: [], objective: "", decided_at: "2026-08-01T09:00:00Z", decided_by: "ana",
      review_on: "2026-09-01", expectation_claim: `p-${id}`, actions: [], outcome: `o-${id}`, reopened_by: "",
      source: { kind: "declared", ref: id, detail: "" }, connection_id: "shop", extra: {}, recorded_at: "",
      superseded_by: "", outcome_verdict: verdict,
    } as unknown as Decision);
    record.listDecisions.mockResolvedValue([row("d1", "cannot_tell"), row("d2", "missed")]);
    mount(<DecisionsPanel connections={CONNECTIONS} selectedConn="shop" openId={null} onOpen={noop} onOpenClaim={noop} />);
    const card = await screen.findByTestId("fig-dec-expect");
    expect(within(card).getByText("1 of 2 reviewed reached a verdict")).toBeInTheDocument();
    expect(card.textContent).not.toMatch(/each can be scored/);
  });
});

describe("Claims", () => {
  it("folds the marks every row shares into the figures, and chips only the row that differs", async () => {
    record.getOnboarding.mockResolvedValue({ coverage: { line: "Reads 5 of your 5 tables" }, shopping_list: [], shopping_note: "" });
    record.listClaims.mockResolvedValue([
      claim({ id: "a" }),
      claim({ id: "b", statement: { ...claim({}).statement, text: "Returns rose to 31%." }, supersedes: "a0", version: 2 }),
      claim({ id: "c", statement: { ...claim({}).statement, text: "Margins held at 40%." } }),
      claim({ id: "d", kind: "said", tier: "said", statement: { ...claim({}).statement, text: "Nothing we did." },
        author: "user:ana", author_kind: "person" }),
    ]);
    mount(<RecordPanel connections={CONNECTIONS} selectedConn="shop" openId={null} onOpen={noop} onOpenDecision={noop}
      onOpenRun={noop} onOpenReceipt={noop} onOpenDefinitions={noop} onOpenMap={noop} />);
    const list = await screen.findByTestId("claim-list");
    expect(within(screen.getByTestId("fig-claims-provisional")).getByText("4")).toBeInTheDocument();
    expect(within(screen.getByTestId("fig-claims-counted")).getByText("4 not counted yet")).toBeInTheDocument();
    // No row repeats "Provisional", "measured" or "not counted"; the restated one says so.
    expect(within(list).queryByText("Provisional")).toBeNull();
    expect(within(list).queryByText(/not counted/)).toBeNull();
    expect(within(list).getAllByText("restated")).toHaveLength(1);
    // A row reads as its first sentence; the whole statement is on the hover.
    expect(within(list).getByRole("button", { name: "Orders fell 4% in September." }))
      .toHaveAttribute("title", "Orders fell 4% in September. Most of it was in Outerwear.");
    // The day's heading says once what its rows share; the row by someone else names who.
    expect(within(list).getByText("Recorded Mon 12 Oct")).toBeInTheDocument();
    expect(within(list).getByText(/4 claims · mostly findings · The shop · mostly by the explorer agent/)).toBeInTheDocument();
    expect(within(list).getByText("said · by ana")).toBeInTheDocument();
  });
});

describe("Corrections", () => {
  it("names a re-booking with the same words as noise, folds the empty kinds, and keeps the note", async () => {
    const c: Corrections = {
      counts: { restatement: 3, refuted_hypothesis: 0, missed_move: 0, prediction_outside_interval: 1, decision_worse_than_expected: 0 },
      labels: { restatement: "a number we gave later changed", refuted_hypothesis: "a cause we thought likely tested false",
        missed_move: "a move a person found that nothing flagged", prediction_outside_interval: "a prediction whose actual fell outside its band",
        decision_worse_than_expected: "a decision that went worse than expected" },
      note: "a kind with 0 has none recorded, not none that happened",
      entries: [
        { kind: "restatement", at: "2026-10-12T12:00:00Z", connection_id: "shop", ref: "n1", believed: "Revenue was $10.", replaced_by: "Revenue was $12.", why: "restated" },
        { kind: "restatement", at: "2026-10-12T12:00:00Z", connection_id: "shop", ref: "n2", believed: "Same words.", replaced_by: "Same words.", why: "restated", claim_kind: "prediction" } as never,
        { kind: "restatement", at: "2026-10-12T12:00:00Z", connection_id: "shop", ref: "n3", believed: "Again.", replaced_by: "Again.", why: "restated", claim_kind: "prediction" } as never,
        { kind: "prediction_outside_interval", at: "2026-10-12T00:33:04Z", connection_id: "shop", ref: "p1",
          believed: "expected: Revenue $79,438 to $98,018 for 2026-09-07 to 2026-09-13 (its own past)",
          replaced_by: "the actual was 100794.9: above the band", why: "scored by code", low: "79437.7", high: "98017.6",
          actual: "100794.9", against: "above" } as never,
      ],
    };
    record.getCorrections.mockResolvedValue(c);
    mount(<CorrectionsPanel connections={CONNECTIONS} onOpenClaim={noop} onOpenDecision={noop} onOpenInquiryKey={noop} />);
    const figures = await screen.findByTestId("correction-figures");
    expect(within(screen.getByTestId("fig-corrections")).getByText("2")).toBeInTheDocument();
    expect(within(figures).getByText("not counted: 2 predictions re-booked, same words")).toBeInTheDocument();
    expect(screen.queryByText("Same words.")).toBeNull();
    expect(within(screen.getByTestId("fig-correction-rest")).getByText("0")).toBeInTheDocument();
    expect(screen.getByTestId("corrections-note")).toHaveAttribute("title", c.note);
    const missed = screen.getByTestId("correction-list-prediction_outside_interval");
    expect(within(missed).getByText("Revenue · 7–13 Sep")).toBeInTheDocument();
    expect(within(missed).getByText("$100.8K")).toBeInTheDocument();
    expect(within(missed).getByText("above its band")).toBeInTheDocument();
  });
});
