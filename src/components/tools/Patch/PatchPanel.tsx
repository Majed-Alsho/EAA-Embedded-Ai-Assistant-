import React, { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { toolStyles } from "../../../styles/toolStyles";

export function PatchPanel({
  isBusy,
  setIsBusy,
  logLine,
  defaultPath,
}: {
  isBusy: boolean;
  setIsBusy: (b: boolean) => void;
  logLine: (s: string) => void;
  defaultPath?: string;
}) {
  const styles = useMemo(() => toolStyles(), []);

  const [relPath, setRelPath] = useState(defaultPath || "");
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [replaceAll, setReplaceAll] = useState(true);
  const [out, setOut] = useState("");

  useEffect(() => {
    if (defaultPath) setRelPath(defaultPath);
  }, [defaultPath]);

  async function run() {
    if (!relPath.trim()) return;

    setIsBusy(true);
    try {
      const res = await invoke<string>("eaa_patch_file", {
        // Rust command uses rename_all = "camelCase" so the argument is relPath/replaceAll
        relPath: relPath.trim(),
        find,
        replace,
        replaceAll,
      });
      setOut(res);
      logLine(`[patch] ${res}`);
    } catch (e) {
      const msg = String(e);
      setOut(msg);
      logLine(`[error] ${msg}`);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div style={styles.panel}>
      <div style={styles.title}>Patch</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
        <div>
          <div style={styles.label}>File path</div>
          <input
            style={styles.input}
            value={relPath}
            onChange={(e) => setRelPath(e.target.value)}
            placeholder="C:\\path\\to\\file.txt or relative\\path.txt"
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div>
            <div style={styles.label}>Find</div>
            <textarea
              style={styles.textarea}
              value={find}
              onChange={(e) => setFind(e.target.value)}
              placeholder="Text to find"
              rows={8}
            />
          </div>
          <div>
            <div style={styles.label}>Replace with</div>
            <textarea
              style={styles.textarea}
              value={replace}
              onChange={(e) => setReplace(e.target.value)}
              placeholder="Replacement text"
              rows={8}
            />
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, opacity: 0.9 }}>
            <input
              type="checkbox"
              checked={replaceAll}
              onChange={(e) => setReplaceAll(e.target.checked)}
              disabled={isBusy}
            />
            Replace all occurrences
          </label>

          <button disabled={isBusy} style={styles.btn} onClick={run}>
            Apply Patch
          </button>
        </div>

        <div style={{ flex: 1 }}>
          <div style={styles.label}>Result</div>
          <pre style={styles.output}>{out}</pre>
        </div>
      </div>
    </div>
  );
}
