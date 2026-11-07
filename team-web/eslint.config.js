import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**"] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      globals: {
        document: "readonly",
        window: "readonly",
        URLSearchParams: "readonly",
        Headers: "readonly",
        RequestInit: "readonly",
        fetch: "readonly",
        KeyboardEvent: "readonly",
      },
    },
  },
);
