import React, { useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

type Preset = { id: string; label: string; file: string };

const PRESETS: Preset[] = [
  {
    id: "ltx_text_no_picture",
    label: "LTX — Text → Image (no picture)",
    file: "ltx_text_no_picture_workflow.json",
  },
  {
    id: "ltx_img_text_with_picture",
    label: "LTX — Image+Text → Image (with picture)",
    file: "ltx_picture_with_picture_workflow.json",
  },
  {
    id: "ltx_img_text_no_picture",
    label: "LTX — Image+Text → Image (no picture)",
    file: "ltx_picture_no_picture_workflow.json",
  },
];

function safeJsonParse(text: string): { ok: true; obj: any } | { ok: false; err: string } {
  try {
    const obj = JSON.parse(text);
    return { ok: true, obj };
  } catch (e: any) {
    return { ok: false, err: String(e?.message || e) };
  }
}

export default function PictureVideoTab() {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [status, setStatus] = useState<string>("");
  const [comfyUrl, setComfyUrl] = useState("http://127.0.0.1:8188/");
  const [selectedPresetId, setSelectedPresetId] = useState(PRESETS[0].id);
  const [lastWorkflow, setLastWorkflow] = useState<string>("(none)");
  const selectedPreset = useMemo(
    () => PRESETS.find((p) => p.id === selectedPresetId) ?? PRESETS[0],
    [selectedPresetId]
  );

  function postWorkflowToComfy(workflowObj: any) {
    const win = iframeRef.current?.contentWindow;
    if (!win) {
      setStatus("[workflow][error] iframe is not ready.");
      return;
    }

    // IMPORTANT: send the OBJECT, not the filename/label
    win.postMessage({ type: "EAA_LOAD_WORKFLOW", workflow: workflowObj }, "*");
    setStatus("[workflow] Posted workflow JSON to ComfyUI (via bridge). If nothing appears, click Reload, then try again.");
  }

  async function startComfy() {
    try {
      const r = await invoke<string>("eaa_start_comfyui");
      setStatus(r);
    } catch (e: any) {
      setStatus(`[error] start comfyui failed: ${String(e)}`);
    }
  }

  async function stopComfy() {
    try {
      const r = await invoke<string>("eaa_stop_comfyui");
      setStatus(r);
    } catch (e: any) {
      setStatus(`[error] stop comfyui failed: ${String(e)}`);
    }
  }

  async function pingComfy() {
    try {
      const r = await invoke<string>("eaa_comfyui_ping");
      setStatus(r);
    } catch (e: any) {
      setStatus(`[error] ping failed: ${String(e)}`);
    }
  }

  function reloadIframe() {
    if (iframeRef.current) {
      iframeRef.current.src = comfyUrl;
      setStatus("[ok] Reloaded ComfyUI iframe.");
    }
  }

  function openInBrowser() {
    window.open(comfyUrl, "_blank");
  }

  function clearStatus() {
    setStatus("");
  }

  function browseJsonClick() {
    fileInputRef.current?.click();
  }

  async function onBrowseFilePicked(file?: File | null) {
    if (!file) return;
    setLastWorkflow(file.name);

    const text = await file.text();
    const parsed = safeJsonParse(text);
    if (!parsed.ok) {
      setStatus(`[workflow][error] JSON parse failed: ${parsed.err}`);
      return;
    }

    postWorkflowToComfy(parsed.obj);
  }

  async function loadPreset() {
    // We read it via backend so you can ship presets in allowed locations.
    // Put preset files here:
    //   %USERPROFILE%\EAA_Workspace\presets\
    // Example:
    //   C:\Users\offic\EAA_Workspace\presets\ltx_picture_with_picture_workflow.json

    try {
      const fileName = selectedPreset.file;
      setLastWorkflow(fileName);

      const text = await invoke<string>("eaa_read_any_file", { relPath: fileName });
      const parsed = safeJsonParse(text);
      if (!parsed.ok) {
        setStatus(`[workflow][error] Preset JSON parse failed: ${parsed.err}`);
        return;
      }

      postWorkflowToComfy(parsed.obj);
      setStatus(`[workflow] Loaded preset JSON "${selectedPreset.label}" and posted to ComfyUI. If nothing appears, click Reload then try again.`);
    } catch (e: any) {
      setStatus(
        `[workflow][error] Can't read that file from disk.\nReason: ${String(e)}\n\nPut presets in: %USERPROFILE%\\EAA_Workspace\\presets\\`
      );
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, height: "100%" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        <div style={{ padding: "6px 10px", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 10 }}>
          URL:{" "}
          <input
            value={comfyUrl}
            onChange={(e) => setComfyUrl(e.target.value)}
            style={{
              width: 260,
              background: "transparent",
              border: "none",
              color: "inherit",
              outline: "none",
            }}
          />
        </div>

        <button onClick={startComfy}>Start</button>
        <button onClick={stopComfy}>Stop</button>
        <button onClick={pingComfy}>Ping</button>
        <button onClick={reloadIframe}>Reload</button>
        <button onClick={openInBrowser}>Open in Browser</button>
        <button onClick={clearStatus} style={{ background: "#4b1f28" }}>
          Clear status
        </button>

        <div style={{ marginLeft: 10, opacity: 0.9 }}>
          Last workflow: <b>{lastWorkflow}</b>
        </div>

        <button onClick={browseJsonClick}>Browse JSON</button>

        <select value={selectedPresetId} onChange={(e) => setSelectedPresetId(e.target.value)}>
          {PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>

        <button onClick={loadPreset}>Load preset</button>

        <input
          ref={fileInputRef}
          type="file"
          accept=".json,application/json"
          style={{ display: "none" }}
          onChange={(e) => onBrowseFilePicked(e.target.files?.[0])}
        />
      </div>

      {status ? (
        <pre
          style={{
            margin: 0,
            padding: 10,
            borderRadius: 12,
            border: "1px solid rgba(255,255,255,0.12)",
            background: "rgba(0,0,0,0.25)",
            whiteSpace: "pre-wrap",
          }}
        >
          {status}
        </pre>
      ) : null}

      <div style={{ flex: 1, minHeight: 400, borderRadius: 14, overflow: "hidden", border: "1px solid rgba(255,255,255,0.12)" }}>
        <iframe
          ref={iframeRef}
          src={comfyUrl}
          title="ComfyUI"
          style={{ width: "100%", height: "100%", border: "none" }}
        />
      </div>
    </div>
  );
}
