import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/node_modules/**",
      "**/.venv/**",
      "**/src-tauri/target/**",
      "**/sidecar/build/**",
      "**/build/**"
    ]
  },
  js.configs.recommended,
  ...tseslint.configs.strict,
  {
    files: ["src/**/*.ts", "tests/**/*.ts", "vite.config.ts"],
    languageOptions: { globals: { document: "readonly", window: "readonly", navigator: "readonly" } },
    rules: {
      "@typescript-eslint/no-confusing-void-expression": "off",
      "@typescript-eslint/restrict-template-expressions": "off"
    }
  }
);
