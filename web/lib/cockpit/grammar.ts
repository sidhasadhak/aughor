/**
 * What the writer of a cockpit is told (Arc CT, CT-5).
 *
 * The library can write this itself: `catalog.prompt()`. Measured in CT-1, that text is 15,783
 * characters for five components, and most of it teaches what this arc refuses — actions,
 * `watch`, `repeat`, expressions in props. A model told how to do a thing will try it.
 *
 * So the grammar is written here, from the SAME constants the rules read. A component, a tone,
 * a status or a limit that changes in the catalog changes in this text with it, and the
 * example below is checked by the rules in a test: a grammar that taught a spec the rules
 * refuse would cost a model call every time it was followed.
 *
 * The server reads it through the validator bundle; it keeps no copy.
 */
import {
  COMPONENT_NAMES, MAX_COLUMNS, MAX_LABEL, MAX_TITLE, MAY_BE_CONDITIONAL, MAY_HOLD, TONES,
  type ComponentName,
} from "@/lib/cockpit/catalog";
import { CARD_STATUSES, RANGE_STATUSES, RANGE_STATUS_PATH, TAB_PATH } from "@/lib/cockpit/hostState";
import { MAX_PATCHES } from "@/lib/cockpit/patch";
import { MAX_CARDS, MAX_ELEMENTS, MAX_TABS } from "@/lib/cockpit/rules";

/** A small cockpit the rules accept. Its card ids are the names a draft gives its new cards. */
export const GRAMMAR_EXAMPLE = {
  root: "cockpit",
  state: { tab: "overview" },
  elements: {
    cockpit: { type: "Cockpit", props: { title: "Returns" }, children: ["tabs"] },
    tabs: { type: "Tabs", props: { value: { $bindState: TAB_PATH } }, children: ["tab-overview", "tab-detail"] },
    "tab-overview": { type: "Tab", props: { name: "overview", label: "Overview" }, children: ["sec-alerts", "sec-headline"] },
    "sec-alerts": {
      type: "Section", props: { title: "Needs a look", columns: 1 }, children: ["alert-rate"],
      visible: { $state: "/cards/return-rate/status", eq: "over" },
    },
    "alert-rate": { type: "Card", props: { card: "return-rate", tone: "bad" }, children: [] },
    "sec-headline": { type: "Section", props: { title: "Headline", columns: 2 }, children: ["card-rate", "card-revenue"] },
    "card-rate": { type: "Card", props: { card: "return-rate" }, children: [] },
    "card-revenue": {
      type: "Card", props: { card: "net-revenue" }, children: [],
      visible: { $state: RANGE_STATUS_PATH, neq: "to_date" },
    },
    "tab-detail": { type: "Tab", props: { name: "detail", label: "Detail" }, children: ["sec-detail"] },
    "sec-detail": { type: "Section", props: { title: "By category" }, children: ["card-by-category"] },
    "card-by-category": { type: "Card", props: { card: "returns-by-category" }, children: [] },
  },
} as const;

const HOLDS: Record<ComponentName, string> = {
  Cockpit: "the root, one in a spec",
  Tabs: "the row of tabs",
  Tab: "one tab",
  Section: "a titled group of cards",
  Card: "one card, by its id",
};

const PROPS: Record<ComponentName, string> = {
  Cockpit: `title (text, up to ${MAX_TITLE} characters)`,
  Tabs: `value, always {"$bindState": "${TAB_PATH}"}`,
  Tab: `name (an identifier: lower-case letters, digits, "-" and "_", beginning with a letter), `
    + `label (text, up to ${MAX_LABEL} characters)`,
  Section: `title (text, up to ${MAX_TITLE} characters), columns (1 to ${MAX_COLUMNS}, optional)`,
  Card: `card (a card id), tone (optional, one of: ${TONES.join(", ")})`,
};

function component(name: ComponentName): string {
  const may = MAY_HOLD[name];
  const holds = name === "Cockpit"
    ? "Holds ONE Tabs, or one or more Section, never both."
    : may.length ? `Holds ${may.join(", ")}, at least one.` : "Holds nothing.";
  return `- ${name}: ${HOLDS[name]}. props: ${PROPS[name]}. ${holds}`;
}

export function grammar(): string {
  return [
    "A cockpit is one JSON object: {\"root\": <element key>, \"state\": {\"tab\": <tab name>}, \"elements\": {<key>: <element>}}.",
    "An element is {\"type\", \"props\", \"children\"} and, where allowed, \"visible\". \"children\" is a list of element keys, "
      + "and [] when the element holds none. An element carries nothing else, and a prop is written, never computed.",
    "",
    "The components:",
    ...COMPONENT_NAMES.map(component),
    "",
    "Every element but the root is held by exactly one other. \"state\" may seed \"tab\" with the name of the tab to open on, "
      + "and nothing else; it is left out when the cockpit has no tabs.",
    "",
    `Conditions. Only these may carry "visible": ${MAY_BE_CONDITIONAL.join(", ")}. A condition compares a status the host publishes, `
      + "with \"eq\" or \"neq\":",
    `  {"$state": "/cards/<card id>/status", "eq": "over"}   one of: ${CARD_STATUSES.join(", ")}`,
    `  {"$state": "${RANGE_STATUS_PATH}", "neq": "final"}   one of: ${RANGE_STATUSES.join(", ")}`,
    "Add \"not\": true to turn one round. A list of conditions means all of them; {\"$or\": [...]} means any of them. "
      + "A condition reads nothing else: no figure, no tab.",
    "A card is \"over\" when its figure has crossed the limit the card carries, and \"unmeasured\" when it carries no limit. "
      + "The range is \"standing\" when the reader chose none.",
    "",
    "Text. A title or a label names a thing. It never states a figure: no amount, no percentage. "
      + "A figure appears inside a card, where it is measured.",
    "",
    `Size. At most ${MAX_ELEMENTS} elements, ${MAX_TABS} tabs, and ${MAX_CARDS} cards placed.`,
    "",
    "An example, which places three cards by the names its draft gave them:",
    JSON.stringify(GRAMMAR_EXAMPLE),
    "",
    "An edit is a list of RFC 6902 operations against the cockpit as it stands: add, remove, replace, move, copy, test. "
      + "Each has a \"path\" such as \"/elements/sec-headline/props/title\", or \"/elements/sec-headline/children/-\" for the end of a list. "
      + "An operation applies exactly or the whole edit is refused: replacing or removing what is not there is a refusal. "
      + `An edit holds at most ${MAX_PATCHES} operations.`,
  ].join("\n");
}
