import { Icon } from "@/components/ui/icon";

/** Arc OC-7 — a value masked for this reader is said, with why and who may read it: an empty cell would read as
 *  "no value", and withheld is said, never implied. */
export function Masked({ why }: { why: string }) {
  return (
    <span data-testid="property-masked" style={{ color: "var(--t3)" }}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><Icon name="lock" size={11} />masked</span>
      <span className="aug-fs-xs" style={{ display: "block" }}>{why}</span>
    </span>
  );
}
