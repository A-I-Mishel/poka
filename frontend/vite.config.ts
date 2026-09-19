import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    // Default 500kB warning limit (was 800 to hide bloat): frontend is
    // zero-dep vanilla JS — the bundle must stay small, and the old
    // manualChunks split for panels.js added a waterfall with no lazy
    // import() to justify it (openSection awaits def.render(), not a
    // dynamic import), so it ships as one bundle.
    chunkSizeWarningLimit: 500,
  },
});
