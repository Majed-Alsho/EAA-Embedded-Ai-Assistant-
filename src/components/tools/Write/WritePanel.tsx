import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { toolStyles } from "../../../styles/toolStyles";

type Props = {
  isBusy: boolean;
  defaultPath: string;
};

function looksAbsolute(p: string) {
  const s = (p || "").trim();
  if (!s) return false;
  if (s.startsWith("\\\\")) return true; // UNC path
  return /^[A-Za-z]:[\\/]/.test(s);
}

  const STORAGE_KEY = "eaa.write.path";
const STORAGE_CONTENT_KEY = "eaa.write.content";

export function WritePanel({ isBusy, defaultPath }: Props) {
  const styles = useMemo(() => toolStyles(), []);
  const [relPath, setRelPath] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEY) ?? defaultPath;
  });
  const [content, setContent] = useState<string>(() => {
    return localStorage.getItem(STORAGE_CONTENT_KEY) ?? "";
  });
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, relPath);
    } catch {
      // ignore
    }
  }, [relPath]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_CONTENT_KEY, content);
    } catch {
      // ignore
    }
  }, [content]);

  async function onWrite() {
    setStatus("");
    try {
      // Rust command uses rename_all = "camelCase" so the argument is relPath
      await invoke("eaa_write_file", { relPath: relPath, content });
      setStatus("Wrote file successfully.");
    } catch (e: any) {
      setStatus(String(e?.message ?? e ?? "Write failed"));
    }
  }

  return (
    <div style={styles.panel}>
      <div style={styles.title}>Write</div>
      <div style={styles.row}>
        <div style={styles.label}>FILE PATH</div>
        <input
          style={styles.input}
          value={relPath}
          placeholder="C:\\Users\\you\\file.txt or relative\\path.txt"
          onChange={(e) => setRelPath(e.target.value)}
        />
      </div>
      <textarea
        style={styles.textarea}
        value={content}
        placeholder="File contents..."
        onChange={(e) => setContent(e.target.value)}
      />
      <div style={styles.btnRow}>
        <button disabled={isBusy} style={styles.button} onClick={onWrite}>
          Write
        </button>
      </div>
      {status ? <pre style={styles.output}>{status}</pre> : null}
    </div>
  );
}
