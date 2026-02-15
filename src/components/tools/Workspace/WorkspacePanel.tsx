import React, { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { toolStyles as toolStylesRaw } from "../../../styles/toolStyles";

type Props = {
  isBusy: boolean;
  setIsBusy: (b: boolean) => void; // kept for compatibility, but we do NOT toggle app-level loading here
  logLine: (s: string) => void;
};

type Styles = Record<string, any>;

function getStyles(): Styles {
  const s: any = toolStylesRaw as any;
  return typeof s === "function" ? s() : s;
}

function styleOf(v: any): React.CSSProperties {
  return typeof v === "function" ? v() : v;
}

function joinPath(base: string, name: string): string {
  if (!base) return name;
  const b = base.replace(/[\\/]+$/, "");
  const n = name.replace(/^[\\/]+/, "");
  return `${b}/${n}`;
}

function parentDir(p: string): string {
  const s = p.replace(/[\\/]+$/, "");
  const idx = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
  if (idx <= 0) return s; // stay at root-ish
  return s.slice(0, idx);
}

export function WorkspacePanel({ isBusy, logLine }: Props) {
  const styles = useMemo(() => getStyles(), []);
  const [root, setRoot] = useState<string>(() => localStorage.getItem("eaa.workspace.root") || "C:/");
  const [inputRoot, setInputRoot] = useState(root);
  const [history, setHistory] = useState<string[]>([root]);
  const [historyIdx, setHistoryIdx] = useState(0);
  const historyIdxRef = useRef(0);
  useEffect(() => { historyIdxRef.current = historyIdx; }, [historyIdx]);

  const [entries, setEntries] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [previewPath, setPreviewPath] = useState<string>("");
  const [previewText, setPreviewText] = useState<string>("");

  
  function pushHistory(path: string) {
    setHistory(prev => {
      const trimmed = prev.slice(0, historyIdxRef.current + 1);
      trimmed.push(path);
      return trimmed;
    });
    setHistoryIdx(i => i + 1);
  }

  function navigate(path: string) {
    setRoot(path);
    setInputRoot(path);
    pushHistory(path);
    refresh(path);
  }

  function goBack() {
    if (historyIdx <= 0) return;
    const prevPath = history[historyIdx - 1];
    setHistoryIdx(i => i - 1);
    setRoot(prevPath);
    setInputRoot(prevPath);
    refresh(prevPath);
  }

async function refresh(nextRoot?: string) {
    const effective = (nextRoot ?? root).trim();
    if (!effective) return;

    setLoading(true);
    try {
      // Backend returns names with trailing '/' for directories.
      const list = await invoke<string[]>("eaa_list_workspace_files", { root: effective });
      setEntries(Array.isArray(list) ? list : []);
      logLine(`[workspace] listed: ${effective}`);
    } catch (e: any) {
      setEntries([]);
      logLine(`[workspace][error] ${String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  async function openFile(fullPath: string) {
    setLoading(true);
    try {
      const txt = await invoke<string>("eaa_read_file", { relPath: fullPath });
      setPreviewPath(fullPath);
      setPreviewText(txt);

      // Let other panels pick it up if they want.
      try {
        localStorage.setItem("eaa.lastToolPath", fullPath);
        window.dispatchEvent(new CustomEvent("eaa:openFile", { detail: { path: fullPath } }));
      } catch {}

      logLine(`[read] ${fullPath}`);
    } catch (e: any) {
      setPreviewPath(fullPath);
      setPreviewText(String(e));
      logLine(`[read][error] ${fullPath}: ${String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  async function clickEntry(name: string) {
    const isDir = name.endsWith("/");
    const cleanName = isDir ? name.slice(0, -1) : name;
    const full = joinPath(root, cleanName);

    if (isDir) {
      const nextRoot = full;
      setRoot(nextRoot);
      setInputRoot(nextRoot);
      localStorage.setItem("eaa.workspace.root", nextRoot);
      setPreviewPath("");
      setPreviewText("");
      await refresh(nextRoot);
    } else {
      await openFile(full);
    }
  }

  function onSetRoot() {
    const next = inputRoot.trim();
    if (!next) return;
    setRoot(next);
    localStorage.setItem("eaa.workspace.root", next);
    setPreviewPath("");
    setPreviewText("");
    refresh(next);
  }

  function onUp() {
    const next = parentDir(root);
    if (!next || next === root) return;
    setRoot(next);
    setInputRoot(next);
    localStorage.setItem("eaa.workspace.root", next);
    setPreviewPath("");
    setPreviewText("");
    refresh(next);
  }

  useEffect(() => {
    refresh(root);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const disabled = isBusy || loading;

  return (
    <div style={{ ...styleOf(styles.panel), height: "100%" }}>
      <div style={{ ...styleOf(styles.headerRow), marginBottom: 8 }}>
        <div style={styleOf(styles.title)}>Files</div>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
        <input
          value={inputRoot}
          onChange={(e) => setInputRoot(e.target.value)}
          placeholder="Root Folder"
          style={{
            ...styleOf(styles.input),
            flex: 1,
            minWidth: 0,
          }}
          disabled={disabled}
        />
        <button style={styleOf(styles.smallBtn)} onClick={onSetRoot} disabled={disabled}>Set</button>
        <button style={styleOf(styles.smallBtn)} onClick={() => refresh()} disabled={disabled}>Refresh</button>
        <button style={styleOf(styles.smallBtn)} onClick={onUp} disabled={disabled}>Up</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, height: "calc(100% - 90px)" }}>
        {/* List */}
        <div style={{
          border: "1px solid rgba(0,229,255,0.2)",
          borderRadius: 12,
          overflow: "auto",
          padding: 6,
        }}>
          {entries.length === 0 && (
            <div style={{ opacity: 0.7, padding: 10 }}>No files.</div>
          )}

          {entries.map((e) => {
            const isDir = e.endsWith("/");
            const name = isDir ? e.slice(0, -1) : e;
            const icon = isDir ? "📁" : "📄";
            return (
              <button
                key={e}
                onClick={() => clickEntry(e)}
                disabled={disabled}
                style={{
                  ...styleOf(styles.listItem),
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-start",
                  gap: 10,
                  padding: "8px 10px",
                  marginBottom: 6,
                  cursor: disabled ? "not-allowed" : "pointer",
                }}
                title={joinPath(root, name)}
              >
                <span style={{ width: 22, textAlign: "center" }}>{icon}</span>
                <span
                  style={{
                    color: "#00e5ff",
                    textShadow: "0 0 10px rgba(0,229,255,0.35)",
                    fontWeight: 600,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {name}{isDir ? "/" : ""}
                </span>
              </button>
            );
          })}
        </div>

        {/* Preview */}
        <div style={{
          border: "1px solid rgba(0,229,255,0.2)",
          borderRadius: 12,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}>
          <div style={{ padding: "8px 10px", borderBottom: "1px solid rgba(255,255,255,0.06)", opacity: 0.9 }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>Preview</div>
            <div style={{ fontSize: 12, opacity: 0.75, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {previewPath || "(click a file)"}
            </div>
          </div>
          <pre style={{
            margin: 0,
            padding: 12,
            overflow: "auto",
            flex: 1,
            background: "rgba(0,0,0,0.25)",
            color: "#e5e7eb",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
            fontSize: 13,
            lineHeight: 1.5,
          }}>
{previewText || ""}
          </pre>
        </div>
      </div>
    </div>
  );
}
