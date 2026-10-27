"use client";

/**
 * A box opened on a sheet — a toolbar's Filter or Sort, the Share box, a column's ⓘ — closes on the next click outside
 * it or on Escape, so none outlives what the person does next (the user, 2026-10-27, of a pop-up that stayed open while a
 * panel opened beside it) — a click on a neighbouring button too. A click on what opened it is left to it (it says
 * `aria-expanded="true"` while the box is open, and toggles it). A dropdown the box holds renders elsewhere on the
 * page; a choice made in it is the box's own, never a click outside.
 */
import { type RefObject, useEffect } from "react";

const INSIDE_ELSEWHERE = '[aria-expanded="true"], [data-slot="select-content"], [data-radix-popper-content-wrapper], [role="listbox"]';

export function useCloseOutside(ref: RefObject<HTMLElement | null>, onClose: () => void): void {
  useEffect(() => {
    const down = (e: PointerEvent) => {
      const el = ref.current;
      const target = e.target;
      if (!el || !(target instanceof Element)) return;
      if (el.contains(target) || target.closest(INSIDE_ELSEWHERE)) return;
      onClose();
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("pointerdown", down);
    window.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down);
      window.removeEventListener("keydown", key);
    };
  }, [ref, onClose]);
}
