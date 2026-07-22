"use client";

import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

const emptySubscribe = () => () => {};

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  // Hydration guard: false during SSR, true after mount — without a setState-in-effect.
  const mounted = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );

  if (!mounted) {
    return <div className="h-9 w-9" aria-hidden />;
  }

  const isDark = resolvedTheme === "dark";
  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="flex h-9 w-9 items-center justify-center rounded-lg text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
      aria-label={`Switch to ${isDark ? "light" : "dark"} theme`}
      title="Toggle theme"
    >
      {isDark ? "☀️" : "🌙"}
    </button>
  );
}
