/**
 * The Briefing's entrance plays once a session — verdict, then the numbers that moved, then the
 * cards, 60ms apart — because on the first open the order tells a reader what to read first. On
 * every later open (a layer switch, Reload, Regenerate, a page refresh) they are waiting on the
 * content, not the order, so it paints at once.
 */
const KEY = "aughor.briefing.entered";

type SessionStore = Pick<Storage, "getItem" | "setItem">;

/** Held for the page too, so a browser that refuses storage still enters only once. */
let claimedThisPage = false;

function sessionStore(): SessionStore | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

/** True exactly once a session: the caller that gets it plays the entrance. */
export function claimBriefingEntrance(store: SessionStore | null = sessionStore()): boolean {
  if (claimedThisPage) return false;
  claimedThisPage = true;
  try {
    if (store?.getItem(KEY)) return false;
    store?.setItem(KEY, "1");
  } catch {
    // Storage refused: the page-level claim above still keeps it to one entrance.
  }
  return true;
}

/** Test seam: forget the page-level claim, as a page refresh would. */
export function forgetPageClaimForTests(): void {
  claimedThisPage = false;
}
