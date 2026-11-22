import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "18" } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // SEC-22: rely on React's escaping; raw HTML injection is banned outright
      "react/no-danger": "error",
      "react/no-danger-with-children": "error",
      "no-restricted-properties": [
        "error",
        // SEC-09: tokens live in HttpOnly cookies, never in browser storage
        { object: "localStorage", message: "Do not use localStorage (SEC-09)." },
        {
          object: "window",
          property: "localStorage",
          message: "Do not use localStorage (SEC-09).",
        },
      ],
    },
  },
);
