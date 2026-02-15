export function monacoLangFromPath(p: string): string {
  const lower = (p || "").toLowerCase();
  if (lower.endsWith(".tsx")) return "typescript";
  if (lower.endsWith(".ts")) return "typescript";
  if (lower.endsWith(".jsx")) return "javascript";
  if (lower.endsWith(".js")) return "javascript";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".css")) return "css";
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  if (lower.endsWith(".md")) return "markdown";
  if (lower.endsWith(".sh") || lower.endsWith(".bash")) return "shell";
  return "plaintext";
}
