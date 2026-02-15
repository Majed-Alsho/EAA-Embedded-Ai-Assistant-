import React, { useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { toolStyles } from "../../../styles/toolStyles";

type Props = {
  isBusy: boolean;
  setIsBusy: (v: boolean) => void;
  logLine: (s: string) => void;
};

export function SandboxPanel({ isBusy, setIsBusy, logLine }: Props) {
  const styles = useMemo(() => toolStyles(), []);
  const [status, setStatus] = useState<string>(
    "Sandbox preview: stopped.\nClick Start to run Vite in EAA_Workspace/EAA_Sandbox on http://127.0.0.1:1421/"
  );
  const [url, setUrl] = useState<string>("http://127.0.0.1:1421/");
  const [running, setRunning] = useState(false);

  async function start() {
    if (isBusy) return;
    setIsBusy(true);
    try {
      const out = await invoke<string>("eaa_start_sandbox_preview");
      setStatus(out);
      setRunning(true);
      logLine(out);
    } catch (e: any) {
      const msg = String(e);
      setStatus(msg);
      logLine(msg);
    } finally {
      setIsBusy(false);
    }
  }

  async function stop() {
    setIsBusy(true);
    try {
      const out = await invoke<string>("eaa_stop_sandbox_preview");
      setStatus(out);
      setRunning(false);
      logLine(out);
    } catch (e: any) {
      const msg = String(e);
      setStatus(msg);
      logLine(msg);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div style={styles.panel}>
      <div style={styles.row}>
        <div style={{ ...styles.label, minWidth: 34 }}>URL:</div>
        <input
          style={{ ...styles.input, flex: 1 }}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          spellCheck={false}
        />
        <button style={styles.button} onClick={start} disabled={isBusy || running}>
          Start
        </button>
        <button style={styles.buttonSecondary} onClick={stop} disabled={isBusy || !running}>
          Stop
        </button>
        <button style={styles.buttonSecondary} onClick={() => setStatus("")}>Clear status</button>
      </div>

      <div style={{ ...styles.monoBox, maxHeight: 140 }}>
        {status || "(no status)"}
      </div>

      <iframe title="sandbox" src={url} style={styles.iframe} />
    </div>
  );
}
