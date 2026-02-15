// Shared Monaco Editor options used across tool panels.
// Keep it minimal and dark-friendly.

export const MONACO_OPTIONS = {
  readOnly: true,
  minimap: { enabled: false },
  fontSize: 13,
  lineNumbers: "on",
  wordWrap: "on",
  scrollBeyondLastLine: false,
  automaticLayout: true,
  renderLineHighlight: "none",
  padding: { top: 10, bottom: 10 },
};

export function languageFromPath(path: string): string {
  const p = (path || "").replace(/\\/g, "/");
  const base = (p.split("/").pop() || "").toLowerCase();
  // Cargo.lock is TOML-like and benefits from TOML highlighting.
  if (base === "cargo.lock") return "toml";

  // Special cases
  if (base === "cargo.lock") return "toml";
  if (base.endsWith(".d.ts")) return "typescript";

  const m = base.match(/\.([a-z0-9]+)$/);
  const ext = m ? m[1] : "";
  switch (ext) {
    case "ts":
    case "tsx":
      return "typescript";
    case "js":
    case "jsx":
      return "javascript";
    case "json":
      return "json";
    case "md":
      return "markdown";
    case "css":
      return "css";
    case "html":
    case "htm":
      return "html";
    case "rs":
      return "rust";
    case "py":
      return "python";
    case "toml":
      return "toml";
    case "yaml":
    case "yml":
      return "yaml";
    case "xml":
      return "xml";
    case "ini":
      return "ini";
    case "sh":
    case "bash":
      return "shell";
    case "txt":
    case "log":
    case "lock":
      return "plaintext";
    default:
      return "plaintext";
  }
}
