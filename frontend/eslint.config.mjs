// Baseline flat config: correctness over style (matches ruff F+E9 posture).
// Browser modules in src/ (ESM, vanilla JS); Node scripts at root/e2e.
import globals from "globals";

export default [
  {
    ignores: ["dist/**", "node_modules/**", "test-results/**", "playwright-report/**"],
  },
  {
    files: ["src/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
      "no-redeclare": "error",
      "no-unreachable": "error",
      "no-self-assign": "error",
      // XSS guardrail: javascript: URLs must never become links/hrefs.
      // Server-provided URLs pass isSafeHttpUrl() (ui.js) first.
      "no-script-url": "error",
    },
  },
  {
    files: ["smoke.mjs", "playwright.config.ts", "vitest.config.ts", "e2e/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
    },
  },
];
