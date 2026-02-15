import js from "@eslint/js";

export default [
  js.configs.recommended,
  {
    ignores: ["dist/**", "src-tauri/**", "node_modules/**"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
    },
  },
];
