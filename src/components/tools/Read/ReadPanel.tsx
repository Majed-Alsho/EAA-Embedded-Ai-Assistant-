import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import Editor from "@monaco-editor/react";
import { toolStyles } from "../../../styles/toolStyles";
import { MONACO_OPTIONS } from "../../../styles/monaco";

type Props = {
  isBusy: boolean;
  defaultPath: string;
};

function looksAbsolute(p: string) {
  const s = (p || "").trim();
  if (!s) return false;
  // Windows: C:\..., UNC: \\server\share, POSIX: /...
  return /^[A-Za-z]:[\\/]/.test(s) || /^\\\\/.test(s) || s.startsWith("/");
}


function languageFromPath(p: string): string {
  const lower = (p || "").toLowerCase();
  const ext = lower.includes(".") ? lower.split(".").pop() || "" : "";
  switch (ext) {
    case "ts": return "typescript";
    case "tsx": return "typescript";
    case "js": return "javascript";
    case "jsx": return "javascript";
    case "json": return "json";
    case "rs": return "rust";
    case "py": return "python";
    case "md": return "markdown";
    case "html": return "html";
    case "css": return "css";
    case "toml":
      return "ini";
    case "lock":
      return "ini";
    case "yml":
    case "yaml": return "yaml";
    case "txt": return "plaintext";
    default: return "plaintext";
  }
}


  const STORAGE_KEY = "eaa.read.path";

export function ReadPanel({ isBusy, setIsBusy, logLine, defaultPath }: Props) {
  const styles = useMemo(() => toolStyles(), []);
  const hadStored = useMemo(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) != null;
    } catch {
      return false;
    }
  }, []);

  const [relPath, setRelPath] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ?? defaultPath;
    } catch {
      return defaultPath;
    }
  });
  const [output, setOutput] = useState("");

  // Keep the current path persisted.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, relPath);
    } catch {
      // ignore
    }
  }, [relPath]);

  // If the parent changes defaultPath (e.g. Files panel selection),
  // adopt it immediately and auto-read.
  useEffect(() => {
    const next = (defaultPath ?? "").trim();
    if (!next) return;
    if (next === relPath.trim()) return;
    setRelPath(next);
    // Auto-read selected file.
    void (async () => {
      try {
        setIsBusy(true);
        setOutput("(reading...)");
        const text = await invoke<string>("eaa_read_file", { rel_path: next });
        setOutput(text ?? "");
        logLine?.(`[read] opened: ${next}`);
      } catch (e: any) {
        setOutput(`ERROR: ${e?.toString?.() ?? e}`);
      } finally {
        setIsBusy(false);
      }
    })();
  }, [defaultPath]);

  async function onRead() {
    try {
      setIsBusy(true);
      setOutput("(reading...)");
      const text = await invoke<string>("eaa_read_file", { rel_path: relPath });
      setOutput(text ?? "");
      logLine?.(`[read] opened: ${relPath}`);
    } catch (e: any) {
      setOutput(`ERROR: ${e?.toString?.() ?? e}`);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div style={styles.panel}>
      <div style={styles.title}>Read</div>
      <div style={styles.row}>
        <div style={styles.label}>File Path</div>
        <input
          value={relPath}
          onChange={(e) => setRelPath(e.target.value)}
          placeholder={"C:\\Users\\you\\file.txt or relative\\path.txt"}
          style={styles.input}
        />
        <button onClick={onRead} disabled={isBusy} style={styles.button}>
          Read
        </button>
      </div>

      <div style={styles.editorWrap}>
        <Editor
          height="420px"
          language={languageFromPath(relPath)}
          value={output}
          theme="vs-dark"
          options={MONACO_OPTIONS as any}
        />
      </div>
    </div>
  );
}
