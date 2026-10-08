"use client";

/**
 * SizePick — one of the six sizes an element of a cockpit may take, by name (the user,
 * 2026-10-08: "make each component size adjustable… without losing the elegance and
 * robustness"). The set is closed on purpose: a size is a prop the validator counts and a
 * version keeps, never free pixels. The corner drag on a tile lands on one of these too.
 */
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SIZES, SPAN, type Size } from "@/lib/cockpit/catalog";

/** The sizes, in the words a person picks them by. */
export const SIZE_WORDS: Record<Size, string> = {
  small: "Small", wide: "Wide", tall: "Tall", large: "Large", full: "Full width", hero: "Hero",
};

export function sizeWords(size: Size): string {
  return `${SIZE_WORDS[size]} · ${SPAN[size].w}×${SPAN[size].h}`;
}

export function SizePick({ value, onPick, label, disabled }: {
  value: Size; onPick: (s: Size) => void; label: string; disabled?: boolean;
}) {
  const items = Object.fromEntries(SIZES.map(s => [s, SIZE_WORDS[s]]));
  return (
    <Select value={value} onValueChange={v => { if (v && v !== value) onPick(v as Size); }} items={items} disabled={disabled}>
      <SelectTrigger size="sm" aria-label={label} title="Size" data-testid="size-pick" style={{ minWidth: 96 }}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {SIZES.map(s => <SelectItem key={s} value={s}>{sizeWords(s)}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}
