import { useSyncExternalStore } from "react";

const emptySubscribe = () => () => {};

/**
 * False on the server and during hydration, true from the browser's first commit on.
 *
 * For markup that depends on something only the browser knows — the theme next-themes keeps
 * in localStorage, the reader's timezone and locale. Rendering it before mount makes the
 * server's HTML and the browser's first render disagree, and React throws error 418 and
 * re-renders the tree: the theme picker did this on every full load of
 * /settings/appearance. Read through `useSyncExternalStore` rather than set from an effect
 * (frontend/AGENTS.md, "No setState in an effect").
 */
export function useMounted(): boolean {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
}
