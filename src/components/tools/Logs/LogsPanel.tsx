import React, { useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { toolStyles } from "../../../styles/toolStyles";

type Level = "all" | "system" | "workspace" | "info" | "warn" | "error";

function levelOf(line: string): Exclude<Level, "all"> {
  const l = line.toLowerCase();
  if (l.includes("[error]") || l.includes(" error:") || l.startsWith("error:")) return "error";
  if (l.includes("[warn]") || l.includes(" warning:") || l.startsWith("warn:")) return "warn";
  if (l.includes("[system]")) return "system";
  if (l.includes("[workspace]")) return "workspace";
  return "info";
}

function lineStyle(level: Exclude<Level, "all">): React.CSSProperties {
  switch (level) {
    case "error":
      return { color: "rgba(255,140,140,0.95)" };
    case "warn":
      return { color: "rgba(255,210,140,0.95)" };
    case "system":
      return { color: "rgba(160,200,255,0.95)" };
    case "workspace":
      return { color: "rgba(170,255,210,0.95)" };
    default:
      return { color: "rgba(255,255,255,0.92)" };
  }
}

export function LogsPanel({
  logs,
  setLogs,
  isBusy,
  setIsBusy,
  logLine,
}: {
  logs: string;
  setLogs: (s: string) => void;
  isBusy: boolean;
  setIsBusy: (b: boolean) => void;
  logLine: (s: string) => void;
}) {
  const styles = useMemo(() => toolStyles(), []);
  const [level, setLevel] = useState<Level>("all");

  const lines = useMemo(() => {
    const raw = logs.split(/\r?\n/).filter(Boolean);
    const filtered =
      level === "all"
        ? raw
        : raw.filter((x) => levelOf(x) === level);

    // keep the panel snappy
    const tail = filtered.slice(-800);

    return tail.map((x, i) => {
      const lv = levelOf(x);
      return (
        <div key={i} style={{ ...lineStyle(lv), fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12, lineHeight: 1.35 }}>
          {x}
        </div>
      );
    });
  }, [logs, level]);

  async function openFolder() {
    try {
      setIsBusy(true);
      await invoke("eaa_open_logs_folder");
    } catch (e) {
      logLine(String(e));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div style={styles.panel}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div style={styles.title}>Logs</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ fontSize: 12, opacity: 0.85 }}>Level</label>
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value as Level)}
            style={{
              ...styles.input,
              padding: "8px 10px",
              width: 110,
              borderRadius: 10,
              appearance: "auto",
            }}
          >
            <option value="all">all</option>
            <option value="system">system</option>
            <option value="workspace">workspace</option>
            <option value="info">info</option>
            <option value="warn">warn</option>
            <option value="error">error</option>
          </select>

          <button disabled={isBusy} style={toolStyles.smallBtn(isBusy)} onClick={openFolder}>
            Open Folder
          </button>
          <button
            disabled={isBusy}
            style={toolStyles.smallBtn(isBusy)}
            onClick={() => setLogs("")}
            title="Clear logs"
          >
            Clear
          </button>
        </div>
      </div>

      <div
        style={{
          flex: 1,
          overflow: "auto",
          borderRadius: 14,
          border: "1px solid rgba(0,255,255,0.18)",
          background: "rgba(0,0,0,0.35)",
          padding: 10,
        }}
      >
        {lines}
      </div>
    </div>
  );
}
