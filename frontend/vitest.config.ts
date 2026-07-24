import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["{lib,components,hooks}/**/*.test.{ts,tsx}"],
    // Playwright specs live in e2e/ and are driven by @playwright/test, not Vitest.
    exclude: ["e2e/**", "node_modules/**", ".next/**"],
  },
});
