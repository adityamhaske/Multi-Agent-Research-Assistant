import { useEffect, useRef, type RefObject } from "react";

/**
 * Keyboard behaviour every modal here shares: focus moves into the panel on open, Tab cycles
 * inside it, Escape closes, and focus returns to whatever opened it.
 *
 * `aria-modal="true"` tells assistive tech that everything outside is inert. Without the trap
 * that is a lie: a keyboard user tabs straight out of the dialog into a page their screen
 * reader has been told does not exist. Without the return, focus lands at the top of the page.
 *
 * Keyed on `open` alone: a caller's inline `onClose` is a new function every render, and
 * re-running on it would pull focus out of a field on every keystroke.
 */
export function useDialogFocus(
  open: boolean,
  onClose: () => void,
  panelRef: RefObject<HTMLElement | null>,
  initialFocus?: RefObject<HTMLElement | null>,
) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    if (!open) return;
    const returnTo = document.activeElement as HTMLElement | null;
    (initialFocus?.current ?? panelRef.current)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close.current();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, iframe, object, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      returnTo?.focus?.();
    };
  }, [open, panelRef, initialFocus]);
}
