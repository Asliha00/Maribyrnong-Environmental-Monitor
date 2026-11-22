/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const api = { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } };

/** The site-wide headers from vercel.json (CSP etc.), so `vite preview` serves the production
 * build exactly as Vercel does and browser tests see real CSP violations (SEC-22). */
function vercelHeaders(): Record<string, string> {
  const config = JSON.parse(
    readFileSync(fileURLToPath(new URL("../vercel.json", import.meta.url)), "utf-8"),
  ) as { headers: { source: string; headers: { key: string; value: string }[] }[] };
  const global = config.headers.find((rule) => rule.source === "/(.*)");
  return Object.fromEntries((global?.headers ?? []).map((h) => [h.key, h.value]));
}

// The /api proxy keeps local development same-origin, exactly like production
// on Vercel, so cookies and CSRF behave the same in both places.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: api,
  },
  preview: {
    port: 4173,
    strictPort: true,
    proxy: api,
    headers: vercelHeaders(),
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
