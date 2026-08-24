import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Playwright's own output. Both are gitignored, so CI's fresh checkout never has
    // them and this changes nothing there — it stops `npm run e2e && npm run lint`
    // locally from reporting thousands of errors inside the report's bundled viewer
    // JavaScript. A local check that disagrees with CI is worse than no local check,
    // because the noise is where a real finding would have been.
    "playwright-report/**",
    "test-results/**",
  ]),
]);

export default eslintConfig;
