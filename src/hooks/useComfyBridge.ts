import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

export type ComfyWorkflowPath = {
  id: string;
  label: string;
  path: string; // absolute path on disk
};

type Args = {
  logLine: (s: string) => void;
  workflows: ComfyWorkflowPath[];
  comfyUrl?: string;
};

export type ComfyBridge = {
  comfyUrl: string;
  iframeSrc: string;
  iframeKey: number;

  iframeRef: React.MutableRefObject<HTMLIFrameElement | null>;
  fileInputRef: React.MutableRefObject<HTMLInputElement | null>;

  status: string;
  running: boolean;
  iframeLoaded: boolean;

  bridgeReady: boolean;
  bridgeInfo: string;
  bridgeLast: string;

  pickedWorkflowId: string;
  setPickedWorkflowId: (id: string) => void;
  lastWorkflowName: string;

  start: () => Promise<void>;
  stop: () => Promise<void>;
  ping: () => Promise<void>;
  pingBridge: (timeoutMs?: number) => Promise<any>;
  reload: () => void;
  openBrowser: () => Promise<void>;
  clearStatus: () => void;

  browseWorkflowJson: () => void;
  onWorkflowFilePicked: (file: File | null) => Promise<void>;
  loadPreset: () => Promise<void>;

  onIframeLoad: () => void;

  workflows: ComfyWorkflowPath[];
};

function extractReadFileBody(readOut: string): string {
  const endMarker = "\n===== end file =====";
  const end = readOut.lastIndexOf(endMarker);
  if (end < 0) return readOut;

  const firstNl = readOut.indexOf("\n");
  if (firstNl < 0) return readOut;

  return readOut.slice(firstNl + 1, end);
}

export function useComfyBridge(args: Args): ComfyBridge {
  const { logLine, workflows, comfyUrl: comfyUrlArg } = args;

  const comfyUrl = comfyUrlArg ?? "http://127.0.0.1:8188/";

  const comfyOrigin = useMemo(() => {
    try {
      return new URL(comfyUrl).origin;
    } catch {
      return "http://127.0.0.1:8188";
    }
  }, [comfyUrl]);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [status, setStatus] = useState<string>(
    "Picture/Video: not checked.\nClick Start to launch ComfyUI (not in background), then Ping."
  );
  const [running, setRunning] = useState(false);
  const [iframeKey, setIframeKey] = useState(1);
  const [iframeLoaded, setIframeLoaded] = useState(false);

  const [bridgeReady, setBridgeReady] = useState(false);
  const [bridgeInfo, setBridgeInfo] = useState("");
  const [bridgeLast, setBridgeLast] = useState("");

  const [pickedWorkflowId, setPickedWorkflowId] = useState<string>(workflows[0]?.id ?? "");
  const [lastWorkflowName, setLastWorkflowName] = useState<string>("(none)");

  const comfyPendingWorkflowRef = useRef<{ workflow: any; name: string } | null>(null);

  // pending request map (ping/workflow)
  const lastBridgePingIdRef = useRef<string | null>(null);
  const lastWorkflowIdRef = useRef<string | null>(null);

  const bridgePendingRef = useRef(
    new Map<string, { resolve: (v: any) => void; reject: (e: any) => void; t: any }>()
  );

  const iframeSrc = useMemo(() => {
    try {
      const u = new URL(comfyUrl);
      u.searchParams.set("eaa", String(iframeKey)); // cache-bust so extensions reload
      return u.toString();
    } catch {
      return comfyUrl;
    }
  }, [comfyUrl, iframeKey]);

  function comfyPost(msg: any) {
    const win = iframeRef.current?.contentWindow;
    if (!win) return false;
    try {
      win.postMessage(msg, comfyOrigin);
      return true;
    } catch {
      return false;
    }
  }

  function waitForReply(requestId: string, timeoutMs: number) {
    return new Promise((resolve, reject) => {
      const t = window.setTimeout(() => {
        bridgePendingRef.current.delete(requestId);

        // If bridge was already ready, assume success to avoid false negatives.
        if (bridgeReady) resolve({ ok: true, note: "timeout-assumed-success" });
        else reject(new Error("timeout"));
      }, timeoutMs);

      bridgePendingRef.current.set(requestId, { resolve, reject, t });
    });
  }

  // Listen to ComfyUI bridge messages (READY / ACK / RESULT / LOG)
  useEffect(() => {
    const onMsg = (ev: MessageEvent) => {
      const iframeWin = iframeRef.current?.contentWindow;
      if (!iframeWin) return;

      const okOrigin =
        ev.origin === comfyOrigin ||
        ev.origin === comfyOrigin.replace("127.0.0.1", "localhost") ||
        ev.origin === comfyOrigin.replace("localhost", "127.0.0.1");
      if (!okOrigin) return;

      const d: any = ev.data;
      if (!d || typeof d !== "object") return;

      if (d.type === "EAA_BRIDGE_READY") {
        setBridgeReady(true);
        setBridgeInfo(`READY v${d.version || "?"} hasApp=${String(!!d.hasApp)}`);
        setBridgeLast("Bridge says READY");
        setIframeLoaded(true);

        // auto-send pending workflow
        const pending = comfyPendingWorkflowRef.current;
        if (pending?.workflow) void sendWorkflowOnce(pending.workflow, pending.name);
        return;
      }

      if (d.type === "EAA_BRIDGE_LOG") {
        const lvl = String(d.level || "log");
        const msg = String(d.message || "");
        setBridgeLast(`${lvl}: ${msg}`);
        return;
      }

      const isPingReply = d.type === "EAA_BRIDGE_PONG" || d.type === "EAA_BRIDGE_ACK";
      const isWfReply = d.type === "EAA_LOAD_WORKFLOW_RESULT" || d.type === "EAA_LOAD_WORKFLOW_ACK";
      if (!isPingReply && !isWfReply) return;

      const rid = String(
        d.requestId ?? (isPingReply ? lastBridgePingIdRef.current : lastWorkflowIdRef.current) ?? ""
      );
      if (!rid) return;

      const p = bridgePendingRef.current.get(rid);
      if (!p) return;

      bridgePendingRef.current.delete(rid);
      try {
        clearTimeout(p.t);
      } catch {}
      p.resolve(d);
    };

    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [comfyOrigin, bridgeReady]);

  async function pingBridge(timeoutMs = 1500) {
    if (!running) throw new Error("ComfyUI not running");

    const requestId = `ping-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    lastBridgePingIdRef.current = requestId;
    setBridgeLast("Pinging bridge…");

    // send both ping styles (old + new bridge)
    const ok1 = comfyPost({ type: "EAA_PING_BRIDGE", requestId, ts: Date.now() });
    const ok2 = comfyPost({ type: "EAA_BRIDGE_PING", requestId, ts: Date.now() });
    if (!ok1 && !ok2) throw new Error("iframe not ready");

    const res: any = await waitForReply(requestId, timeoutMs);

    const ver = String(res?.version || "?");
    setBridgeReady(true);
    setBridgeInfo(`READY v${ver}`);
    setBridgeLast("Bridge ACK ✅");
    return res;
  }

  async function sendWorkflowOnce(workflowObj: any, name: string) {
    if (!running) {
      setStatus(`[workflow] ComfyUI is stopped.\nQueued "${name}".`);
      return false;
    }

    if (!iframeRef.current?.contentWindow) {
      setStatus(`[workflow] No iframe yet.\nQueued "${name}".`);
      return false;
    }

    if (!iframeLoaded) {
      setStatus(`[workflow] Iframe still loading.\nQueued "${name}".\nWill auto-send when iframe loads.`);
      return false;
    }

    if (!bridgeReady) {
      try {
        await pingBridge(1800);
      } catch (e) {
        setBridgeLast(`Bridge ping failed: ${String(e)}`);
      }
    }

    const requestId = `wf-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    lastWorkflowIdRef.current = requestId;

    setStatus(`[workflow] Sending "${name}" to ComfyUI UI.\nWaiting for ACK from bridge...`);

    const posted = comfyPost({
      type: "EAA_LOAD_WORKFLOW",
      requestId,
      name,
      workflow: workflowObj,
      ts: Date.now(),
    });

    if (!posted) {
      setStatus(`[workflow] postMessage failed (iframe not ready). Queued "${name}".`);
      return false;
    }

    try {
      const res: any = await waitForReply(requestId, 4000);
      if (res?.ok) {
        setStatus(`[workflow] Loaded ✅ (${name})\nTip: After load, hit Run in ComfyUI.`);
        return true;
      }

      const err = String(res?.error || "unknown error");
      setStatus(`[workflow][error] Bridge replied but failed:\n${err}`);
      return false;
    } catch (e) {
      setStatus(
        `[workflow][error] Sent "${name}" but got no ACK.\n` +
          `Bridge is loaded, but the handshake didn't complete.\n` +
          `${String(e)}`
      );
      return false;
    }
  }

  async function postWorkflow(workflow: any, name: string) {
    setLastWorkflowName(name);
    comfyPendingWorkflowRef.current = { workflow, name };

    if (!running) {
      setStatus(`[workflow] ComfyUI is stopped.\nQueued "${name}".\nStart ComfyUI first.`);
      return;
    }

    if (!iframeLoaded) {
      setStatus(`[workflow] Iframe still loading.\nQueued "${name}".\nWill auto-send when iframe loads.`);
      return;
    }

    await sendWorkflowOnce(workflow, name);
  }

  async function loadWorkflowFromDiskPath(absPath: string, label: string) {
    setStatus(`[workflow] Loading from disk:\n${absPath}\n\nThis requires backend command: eaa_read_any_file(path)`);
    try {
      const raw = await invoke<string>("eaa_read_any_file", { path: absPath });
      const text = typeof raw === "string" ? raw : JSON.stringify(raw);
      const jsonText = extractReadFileBody(text);
      const wf = JSON.parse(jsonText);
      await postWorkflow(wf, label);
    } catch (err) {
      setStatus(
        `[workflow][error] Can't read that file from disk.\nReason: ${String(err)}\n\nUse "Browse JSON" OR add eaa_read_any_file in backend.`
      );
    }
  }

  async function ping() {
    setStatus(`Pinging ComfyUI...\nURL: ${comfyUrl}`);

    // 1) backend ping first
    try {
      await invoke<any>("eaa_comfyui_ping");
      setRunning(true);
      setStatus(`ComfyUI: reachable ✅\nURL: ${comfyUrl}`);
      setIframeKey((k) => k + 1);
      return;
    } catch {
      // ignore and fallback
    }

    // 2) fetch fallback
    try {
      const r = await fetch(new URL("system_stats", comfyUrl).toString());
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json();
      setRunning(true);
      setStatus(`ComfyUI: reachable ✅\nURL: ${comfyUrl}`);
      setIframeKey((k) => k + 1);
    } catch (e2: any) {
      setRunning(false);
      setStatus(
        `ComfyUI: NOT reachable ❌\nURL: ${comfyUrl}\n${String(e2?.message ?? e2)}\n\nClick Start, then Ping.`
      );
    }
  }

  function reload() {
    setIframeLoaded(false);
    setBridgeReady(false);
    setBridgeInfo("");
    setBridgeLast("Reload requested");
    setIframeKey((k) => k + 1);
    setStatus((s) => `${s}\n[ui] Reload requested`);
  }

  async function openBrowser() {
    try {
      await invoke("eaa_open_url", { url: comfyUrl });
    } catch (err) {
      logLine(`[error] open browser failed: ${String(err)}`);
    }
  }

  function clearStatus() {
    setStatus("");
  }

  async function start() {
    setStatus("[start] Launching ComfyUI...\nIf this fails, you haven't added eaa_start_comfyui in backend yet.");
    try {
      const out = await invoke<string>("eaa_start_comfyui");
      setRunning(true);

      setStatus(out || "ComfyUI started.");
      setIframeLoaded(false);
      setBridgeReady(false);
      setBridgeInfo("");
      setBridgeLast("Starting…");
      setIframeKey((k) => k + 1);

      logLine(`[media] start comfyui -> ${out}`);
    } catch (err) {
      setRunning(false);
      const msg =
        `[error] start comfyui failed: ${String(err)}\n\n` +
        `You need a backend command named eaa_start_comfyui that starts ComfyUI.`;
      setStatus(msg);
      logLine(msg);
    }
  }

  async function stop() {
    setStatus("[stop] Stopping ComfyUI...\nIf this fails, you haven't added eaa_stop_comfyui in backend yet.");
    try {
      const out = await invoke<string>("eaa_stop_comfyui");
      setRunning(false);
      setBridgeReady(false);
      setBridgeInfo("");
      setBridgeLast("Stopped");
      setStatus(out || "ComfyUI stopped.");
      logLine(`[media] stop comfyui -> ${out}`);
    } catch (err) {
      const msg =
        `[error] stop comfyui failed: ${String(err)}\n\n` +
        `You need a backend command named eaa_stop_comfyui that stops/kill ComfyUI so it frees VRAM.`;
      setStatus(msg);
      logLine(msg);
    }
  }

  function browseWorkflowJson() {
    fileInputRef.current?.click();
  }

  async function onWorkflowFilePicked(file: File | null) {
    if (!file) return;
    setStatus(`[workflow] Reading file: ${file.name}`);
    try {
      const text = await file.text();
      const wf = JSON.parse(text);
      await postWorkflow(wf, file.name);
    } catch (err) {
      setStatus(`[workflow][error] Invalid JSON:\n${String(err)}`);
    }
  }

  async function loadPreset() {
    const w = workflows.find((x) => x.id === pickedWorkflowId) ?? workflows[0];
    if (!w) return;
    await loadWorkflowFromDiskPath(w.path, w.label);
  }

  function onIframeLoad() {
    setIframeLoaded(true);
    setBridgeReady(false);
    setBridgeInfo("");
    setBridgeLast("iframe loaded — waiting for bridge…");

    // give extensions time, then ping bridge
    window.setTimeout(() => {
      void pingBridge(1800).catch(() => {});
    }, 450);

    const pending = comfyPendingWorkflowRef.current;
    if (pending?.workflow) void sendWorkflowOnce(pending.workflow, pending.name);
  }

  // If workflows prop changes and picked is invalid, fix it
  useEffect(() => {
    if (!workflows.length) return;
    if (!pickedWorkflowId || !workflows.some((w) => w.id === pickedWorkflowId)) {
      setPickedWorkflowId(workflows[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflows.map((w) => w.id).join("|")]);

  return {
    comfyUrl,
    iframeSrc,
    iframeKey,

    iframeRef,
    fileInputRef,

    status,
    running,
    iframeLoaded,

    bridgeReady,
    bridgeInfo,
    bridgeLast,

    pickedWorkflowId,
    setPickedWorkflowId,
    lastWorkflowName,

    start,
    stop,
    ping,
    pingBridge,
    reload,
    openBrowser,
    clearStatus,

    browseWorkflowJson,
    onWorkflowFilePicked,
    loadPreset,

    onIframeLoad,

    workflows,
  };
}
