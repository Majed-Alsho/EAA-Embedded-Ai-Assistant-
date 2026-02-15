import React from "react";
import type { ComfyBridge } from "../hooks/useComfyBridge";

export function ComfyPanel(props: { comfy: ComfyBridge; isBusy: boolean }) {
  const { comfy, isBusy } = props;

  const styles: Record<string, React.CSSProperties | ((...args: any[]) => React.CSSProperties)> = {
    wrap: {
      flex: 1,
      minHeight: 0,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    },
    form: { padding: 12, display: "flex", flexDirection: "column", gap: 10 },
    badge: {
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      padding: "6px 10px",
      borderRadius: 999,
      border: "1px solid #2a3a50",
      background: "#0b1220",
      fontSize: 12,
      fontWeight: 800,
      opacity: 0.95,
      color: "#e6edf3",
    },
    text: {
      width: "100%",
      padding: "10px 12px",
      borderRadius: 12,
      border: "1px solid #2a3a50",
      background: "#0b1220",
      color: "#e6edf3",
      outline: "none",
    },
    smallBtn: (danger?: boolean) => ({
      padding: "8px 10px",
      borderRadius: 10,
      border: "1px solid #2a3a50",
      background: danger ? "#2a1220" : "#0e1521",
      color: "#e6edf3",
      cursor: "pointer",
      fontSize: 12,
      fontWeight: 800,
      opacity: 1,
    }),
    statusBox: {
      flex: "0 0 auto",
      maxHeight: 140,
      padding: 12,
      overflow: "auto",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      fontSize: 12,
      whiteSpace: "pre-wrap",
      background: "#0e1521",
      borderTop: "1px solid #1d2836",
      borderBottom: "1px solid #1d2836",
      position: "relative",
      zIndex: 1,
      color: "#e6edf3",
    },
    iframe: { flex: 1, minHeight: 0, border: "none", background: "#0b0f14", position: "relative", zIndex: 0 },
    mono: {
      flex: 1,
      minHeight: 0,
      padding: 12,
      overflow: "auto",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      fontSize: 12,
      whiteSpace: "pre-wrap",
      borderTop: "1px solid #1d2836",
      background: "#0b0f14",
      color: "#e6edf3",
    },
  };

  const smallBtn = styles.smallBtn as (danger?: boolean) => React.CSSProperties;

  return (
    <div style={styles.wrap as React.CSSProperties}>
      <div style={styles.form as React.CSSProperties}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span style={styles.badge as React.CSSProperties}>URL: {comfy.comfyUrl}</span>

          <button style={smallBtn()} disabled={isBusy} onClick={() => void comfy.start()}>
            Start
          </button>
          <button style={smallBtn()} disabled={isBusy} onClick={() => void comfy.stop()}>
            Stop
          </button>

          <button style={smallBtn()} disabled={isBusy} onClick={() => void comfy.ping()}>
            Ping
          </button>
          <button
            style={smallBtn()}
            disabled={isBusy || !comfy.running}
            onClick={() => void comfy.pingBridge().catch((e) => {/* status already set in hook */})}
          >
            Ping bridge
          </button>

          <button style={smallBtn()} disabled={isBusy} onClick={() => comfy.reload()}>
            Reload
          </button>
          <button style={smallBtn()} onClick={() => void comfy.openBrowser()}>
            Open in Browser
          </button>
          <button style={smallBtn(true)} onClick={() => comfy.clearStatus()}>
            Clear status
          </button>
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <span style={styles.badge as React.CSSProperties}>Last workflow: {comfy.lastWorkflowName}</span>

          <span style={styles.badge as React.CSSProperties}>
            Bridge: <b>{comfy.bridgeReady ? "READY" : "NOT READY"}</b>
            {comfy.bridgeInfo ? ` — ${comfy.bridgeInfo}` : ""}
          </span>

          {comfy.bridgeLast ? <span style={styles.badge as React.CSSProperties}>{comfy.bridgeLast}</span> : null}

          <button style={smallBtn()} disabled={isBusy} onClick={() => comfy.browseWorkflowJson()}>
            Browse JSON
          </button>

          <select
            style={{ ...(styles.text as React.CSSProperties), width: 280 }}
            value={comfy.pickedWorkflowId}
            onChange={(e) => comfy.setPickedWorkflowId(e.target.value)}
          >
            {comfy.workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.label}
              </option>
            ))}
          </select>

          <button style={smallBtn()} disabled={isBusy} onClick={() => void comfy.loadPreset()}>
            Load preset
          </button>

          {/* hidden file input */}
          <input
            ref={comfy.fileInputRef}
            type="file"
            accept=".json,application/json"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              void comfy.onWorkflowFilePicked(f);
              e.currentTarget.value = "";
            }}
          />
        </div>
      </div>

      <div style={styles.statusBox as React.CSSProperties}>{comfy.status || "Status will show here."}</div>

      {comfy.running ? (
        <iframe
          key={comfy.iframeKey}
          ref={comfy.iframeRef}
          title="picture-video"
          style={styles.iframe as React.CSSProperties}
          src={comfy.iframeSrc}
          onLoad={() => comfy.onIframeLoad()}
        />
      ) : (
        <div style={{ ...(styles.mono as React.CSSProperties), borderTop: "1px solid #1d2836" }}>
          ComfyUI is stopped.{"\n\n"}Click Start to run it. When you click Stop, it should exit and free VRAM.
        </div>
      )}
    </div>
  );
}
