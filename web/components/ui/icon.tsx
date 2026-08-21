"use client";

/**
 * icon.tsx — ONE icon set for the platform.
 *
 * Before this file there were three, and no register of what any of them drew:
 * `lucide-react` in 4 files, `@atlaskit/icon` in 10, and 97 hand-written `<svg>`
 * elements across 34 more — including four separate `ICONS` path maps that had each
 * re-drawn the same glyph slightly differently. An icon is a word in the interface's
 * vocabulary, and a word that is spelled three ways is three words.
 *
 * Tabler is the set (https://github.com/tabler/tabler-icons): one stroke weight, one
 * 24px grid, drawn for interfaces at small sizes. It is imported HERE and nowhere else,
 * so the platform has a single place that answers "which glyph means catalog".
 *
 * ── HOW TO USE ──────────────────────────────────────────────────────────────
 *     <Icon name="catalog" />            // 14px, currentColor — the default
 *     <Icon name="refresh" size={16} />
 *
 * Names are ROLES in this product's language ("catalog", "brief", "playbook"), not
 * Tabler's file names, so the drawing can be re-chosen later without touching call
 * sites. Adding one means adding a row to ICONS and nothing else.
 *
 * Sizes come from the type scale's small end: 14 default, 16 for a lone control.
 *
 * ── WHY STROKE IS COMPUTED, NOT CONSTANT ────────────────────────────────────
 * Tabler draws on a 24-unit grid, so a FIXED stroke shrinks with the glyph: 1.6 units
 * at 11px renders 1.6 x 11/24 = 0.73 device pixels. On a retina screen that rounds up
 * and looks correct — which is exactly why it survives a 2x screenshot. On an ordinary
 * 1x monitor it is sub-pixel, and the browser paints it as a soft grey smear rather
 * than a line. Measured across the catalog screen, every size in use came in under one
 * device pixel: 11px 0.73, 13px 0.87, 14px 0.93, 16px 1.07. The hand-drawn glyphs
 * these replaced sat near 1.0-1.5, because each was drawn on its own small grid.
 *
 * So stroke is a function of size, holding the DEVICE stroke near 1.1px across the
 * scale — optical sizing, the same reason a 9pt typeface is not the 72pt one scaled
 * down. Clamped at both ends: 2.4 units so an 11px glyph never fills in, and 1.0 so a
 * 48px empty-state mark stays an outline (which is also, exactly, the weight the 48px
 * drawing it replaced was drawn at).
 *
 * Pass `stroke` explicitly to override; a few call sites carry a weight from the
 * drawing they replaced.
 */

import {
  IconActivity, IconAlertTriangle, IconArrowRight, IconBolt, IconBook,
  IconBrandDatabricks, IconCategory, IconCheck, IconChevronDown, IconChevronRight,
  IconCircleCheck, IconClock, IconCode, IconDatabase, IconDeviceFloppy, IconDots,
  IconFileText, IconFilter, IconHelp, IconHistory, IconHome, IconInbox, IconInfoCircle,
  IconLayersIntersect, IconLayoutSidebar, IconMessage, IconMoon, IconPlayerPlay,
  IconPlug, IconPlus, IconRefresh, IconSearch, IconSend, IconSettings, IconShieldCheck,
  IconSitemap, IconSparkles, IconStar, IconSun, IconTable, IconTrash, IconUpload, IconX,
  IconAbc, IconAdjustmentsHorizontal, IconAlertCircle, IconArrowLeft, IconBell,
  IconBookmark, IconCalendar, IconChartBar, IconChevronLeft, IconChevronUp, IconColumns,
  IconCompass, IconCopy, IconDotsVertical, IconDownload, IconExternalLink, IconEye,
  IconFolder, IconGripVertical, IconHash, IconKey, IconLink, IconLoader2, IconLock,
  IconMaximize, IconMessageCircle, IconMinus, IconPencil, IconPin, IconPoint,
  IconPlayerStop, IconRobot, IconSchema, IconServer, IconTarget, IconTerminal2,
  IconToggleLeft, IconTrendingDown, IconTrendingUp, IconUser, IconUsers, IconWand,
  IconBulb, IconFlask, IconScale, IconZoomIn,
  IconArrowsSplit2, IconBinaryTree, IconChartDots3, IconGauge, IconHandStop, IconStack2,
  IconList, IconPaperclip,
} from "@tabler/icons-react";
import type { ComponentType } from "react";

interface GlyphProps {
  size?: number | string;
  stroke?: number;
  className?: string;
  role?: string;
  "aria-label"?: string;
  "aria-hidden"?: boolean;
}
type Glyph = ComponentType<GlyphProps>;

/** Role → glyph. The ONE place a drawing is chosen. */
const ICONS = {
  // navigation
  home: IconHome,
  inbox: IconInbox,
  canvas: IconFileText,
  brief: IconFileText,
  playbook: IconBook,
  health: IconActivity,
  activity: IconActivity,
  catalog: IconDatabase,
  db: IconDatabase,
  table: IconTable,
  builder: IconCategory,
  sql: IconCode,
  layers: IconLayersIntersect,
  node: IconSitemap,
  process: IconSitemap,
  agents: IconBrandDatabricks,
  shield: IconShieldCheck,
  settings: IconSettings,
  metric: IconActivity,
  plug: IconPlug,
  schema: IconSchema,
  folder: IconFolder,
  column: IconColumns,
  key: IconKey,
  server: IconServer,
  terminal: IconTerminal2,
  robot: IconRobot,
  compass: IconCompass,
  target: IconTarget,
  chart: IconChartBar,
  user: IconUser,
  users: IconUsers,
  lock: IconLock,
  gauge: IconGauge,
  hand: IconHandStop,
  flow: IconArrowsSplit2,
  kgraph: IconBinaryTree,
  memory: IconStack2,
  graph: IconChartDots3,

  // column TYPES — the catalog's four data-type marks
  num: IconHash,
  date: IconCalendar,
  text: IconAbc,
  bool: IconToggleLeft,

  // actions
  run: IconPlayerPlay,
  save: IconDeviceFloppy,
  refresh: IconRefresh,
  search: IconSearch,
  filter: IconFilter,
  plus: IconPlus,
  close: IconX,
  trash: IconTrash,
  send: IconSend,
  upload: IconUpload,
  more: IconDots,
  history: IconHistory,
  panel: IconLayoutSidebar,
  next: IconArrowRight,
  back: IconArrowLeft,
  edit: IconPencil,
  copy: IconCopy,
  download: IconDownload,
  external: IconExternalLink,
  link: IconLink,        // a relationship between two things — a join, a hyperlink
  attach: IconPaperclip, // a file carried alongside a message — NOT the same idea
  list: IconList,
  eye: IconEye,
  minus: IconMinus,
  sliders: IconAdjustmentsHorizontal,
  expand: IconMaximize,
  pin: IconPin,
  bookmark: IconBookmark,
  stop: IconPlayerStop,
  wand: IconWand,
  morev: IconDotsVertical,
  grip: IconGripVertical,

  // state & meaning
  check: IconCheck,
  ok: IconCircleCheck,
  info: IconInfoCircle,
  warning: IconAlertTriangle,
  help: IconHelp,
  clock: IconClock,
  spark: IconSparkles,
  bolt: IconBolt,
  idea: IconBulb,
  flask: IconFlask,
  scales: IconScale,
  zoom: IconZoomIn,
  star: IconStar,
  chat: IconMessage,
  sun: IconSun,
  moon: IconMoon,
  alert: IconAlertCircle,
  bell: IconBell,
  message: IconMessageCircle,
  trendup: IconTrendingUp,
  trenddown: IconTrendingDown,
  spinner: IconLoader2,
  dot: IconPoint,

  // disclosure
  chevd: IconChevronDown,
  chevr: IconChevronRight,
  chevu: IconChevronUp,
  chevl: IconChevronLeft,
} satisfies Record<string, Glyph>;

export type IconName = keyof typeof ICONS;

/** Every role this set answers to — for the icon gate and for a picker. */
export const ICON_NAMES = Object.keys(ICONS) as IconName[];

/** Stroke in Tabler's 24-unit grid that renders ~1.1 device pixels at `size`. */
function opticalStroke(size: number): number {
  return Math.min(2.4, Math.max(1.0, Math.round((26 / size) * 100) / 100));
}

export function Icon({
  name, size = 14, stroke, className, label,
}: { name: IconName; size?: number; stroke?: number; className?: string; label?: string }) {
  const Glyph = ICONS[name] ?? ICONS.info;
  const weight = stroke ?? opticalStroke(size);
  // An icon is either a picture that carries meaning or decoration beside a word that
  // already carries it. Naming both is worse than naming neither: a screen reader then
  // reads "Copy, Copy" on every button. `label` marks the first case; its absence marks
  // the second and hides the glyph from the accessibility tree entirely.
  return label
    ? <Glyph size={size} stroke={weight} className={className} role="img" aria-label={label} />
    : <Glyph size={size} stroke={weight} className={className} aria-hidden />;
}
