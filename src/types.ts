// src/types.ts

/* =========================
   Global app types
========================= */

export type ToolsMode = "off" | "ask" | "auto";

export type RightTab =
  | "preview"
  | "canvas"
  | "logs"
  | "workspace"
  | "read"
  | "write"
  | "patch"
  | "sandbox"
  | "media";

export type CanvasMode = "visual" | "html";

export type ActionKind = "canvas" | "tool";

export type SuggestedAction = {
  id: string;
  label: string;
  kind: ActionKind;
};

/* =========================
   Visual Canvas types
========================= */

export type VItemType = "card" | "text" | "button";

export type VItem = {
  id: string;
  type: VItemType;
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
};

export type VLayout = {
  version: number;
  items: VItem[];
};

export type Guides = {
  v: number[]; // x positions
  h: number[]; // y positions
};

/* =========================
   HTML (Gemini-style) project types
========================= */

export type HtmlProjectFile = {
  name: string; // index.html, styles.css, app.js, etc.
  content: string;
};

/* =========================
   ComfyUI / Bridge types
========================= */

export type ComfyWorkflowPreset = {
  id: string;
  label: string;
  path: string; // absolute path on disk (Windows)
};

export type ComfyBridgeOptions = {
  comfyUrl?: string; // default: http://127.0.0.1:8188/
  workflows?: ComfyWorkflowPreset[]; // presets shown in UI
  logLine?: (s: string) => void; // optional logger

  // backend command names (keep default to current ones)
  cmdStart?: string; // default: eaa_start_comfyui
  cmdStop?: string; // default: eaa_stop_comfyui
  cmdPing?: string; // default: eaa_comfyui_ping
  cmdOpenUrl?: string; // default: eaa_open_url
  cmdReadAnyFile?: string; // default: eaa_read_any_file
};

export type ComfyBridgeApi = {
  // core config
  comfyUrl: string;
  comfyOrigin: string;

  // refs for UI
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
  fileInputRef: React.RefObject<HTMLInputElement | null>;

  // iframe render
  iframeSrc: string;
  iframeKey: number;

  // state
  status: string;
  running: boolean;
  iframeLoaded: boolean;

  bridgeReady: boolean;
  bridgeInfo: string;
  bridgeLast: string;

  lastWorkflowName: string;

  // presets
  workflows: ComfyWorkflowPreset[];
  pickedWorkflowId: string;
  setPickedWorkflowId: (id: string) => void;

  // actions
  start: () => Promise<void>;
  stop: () => Promise<void>;
  ping: () => Promise<void>;
  pingBridge: (timeoutMs?: number) => Promise<any>;
  reload: () => void;
  openInBrowser: () => Promise<void>;
  clearStatus: () => void;

  browseWorkflowJson: () => void;
  onWorkflowFilePicked: (file: File | null) => Promise<void>;
  loadPreset: (presetId?: string) => Promise<void>;

  // UI hook: call this from <iframe onLoad>
  onIframeLoad: () => void;
};
