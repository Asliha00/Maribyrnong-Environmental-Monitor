import { join } from "node:path";

/** Saved sessions written by auth.setup.ts (git-ignored). */
export const STATE = {
  analyst: join(import.meta.dirname, ".auth", "analyst.json"),
};
