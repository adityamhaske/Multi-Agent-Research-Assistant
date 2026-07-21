"use client";

import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

const emptySubscribe = () => () => {};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  // Hydration guard: false during SSR, true after mount — without a setState-in-effect.
  const mounted = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );

  if (!mounted) {
    return <div className="w-8 h-8 rounded-md" />; // placeholder
  }

  const isDark = theme === "dark";

  return (
    <button
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="p-2 rounded-md hover:bg-[var(--color-bg-hover)] transition-colors text-slate-400 hover:text-slate-100 flex items-center justify-center w-9 h-9"
      aria-label="Toggle Theme"
      title="Toggle Theme"
    >
      {isDark ? "☀️" : "🌙"}
    </button>
  );
}
