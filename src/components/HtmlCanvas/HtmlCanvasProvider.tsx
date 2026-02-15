import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import Editor from "@monaco-editor/react";
import type { HtmlProjectFile } from "./types";
import { createDefaultHtmlProject } from "./defaultProject";
import {
  buildHtmlProject,
  duplicateFile,
  getFile,
  htmlToDataUrl,
  monacoLangFromName,
  removeFile,
  renameFile,
  setFileContent,
} from "./htmlProject";
import { clamp } from "../../utils/math";
import { extractReadFileBody } from "../../utils/readMarkers";

type ConsoleLine = { t: number; text: string };

type CommandItem = {
  id: string;
  label: string;
  run: () => void;
};

type PaletteItem =
  | { kind: "file"; key: string; name: string }
  | { kind: "cmd"; key: string; cmd: CommandItem };

type Ctx = {
  files: HtmlProjectFile[];
  setFiles: React.Dispatch<React.SetStateAction<HtmlProjectFile[]>>;
  active: string;
  setActive: (name: string) => void;

  auto: boolean;
  setAuto: React.Dispatch<React.SetStateAction<boolean>>;
  dirty: boolean;
  setDirty: React.Dispatch<React.SetStateAction<boolean>>;

  rendered: string;
  renderNow: (reason: string) => void;

  splitPreview: boolean;
  setSplitPreview: React.Dispatch<React.SetStateAction<boolean>>;
  splitRatio: number;
  setSplitRatio: React.Dispatch<React.SetStateAction<number>>;

  showConsole: boolean;
  setShowConsole: React.Dispatch<React.SetStateAction<boolean>>;
  consoleLines: ConsoleLine[];
  clearConsole: () => void;

  lastRuntimeError: string;
  clearRuntimeError: () => void;

  projectRelPath: string;
  setProjectRelPath: React.Dispatch<React.SetStateAction<string>>;

  exportRelPath: string;
  setExportRelPath: React.Dispatch<React.SetStateAction<string>>;

  previewSrc: string;

  addFile: () => void;
  deleteActiveFile: () => void;
  resetProject: () => void;
  updateActiveContent: (txt: string) => void;

  renameActiveFile: () => void;
  duplicateActiveFile: () => void;

  saveProject: () => Promise<void>;
  loadProject: (reason?: string) => Promise<void>;
  exportHtmlFile: () => Promise<void>;

  activeFile: HtmlProjectFile;
  editorLanguage: string;
};

const HtmlCanvasContext = createContext<Ctx | null>(null);

export function useHtmlCanvas() {
  const v = useContext(HtmlCanvasContext);
  if (!v) throw new Error("useHtmlCanvas must be used inside HtmlCanvasProvider");
  return v;
}

function safeLSGet(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function safeLSSet(key: string, val: string) {
  try {
    localStorage.setItem(key, val);
  } catch {}
}

export function HtmlCanvasProvider(props: { children: React.ReactNode; logLine: (s: string) => void }) {
  const { children, logLine } = props;

  const defaultFiles = useMemo(() => createDefaultHtmlProject(), []);
  const [files, setFiles] = useState<HtmlProjectFile[]>(() => createDefaultHtmlProject());
  const [active, setActiveState] = useState<string>(() => "app.js");

  const [auto, setAuto] = useState(true);
  const [dirty, setDirty] = useState(false);

  const [splitPreview, setSplitPreview] = useState<boolean>(() => safeLSGet("eaa_html_canvas.split") === "1");
  const [splitRatio, setSplitRatio] = useState<number>(() => {
    const v = Number(safeLSGet("eaa_html_canvas.ratio") ?? "0.55");
    return Number.isFinite(v) ? clamp(v, 0.2, 0.8) : 0.55;
  });

  const [showConsole, setShowConsole] = useState<boolean>(() => safeLSGet("eaa_html_canvas.console") === "1");
  const [consoleLines, setConsoleLines] = useState<ConsoleLine[]>([]);
  const [lastRuntimeError, setLastRuntimeError] = useState<string>("");

  // disk persistence (project JSON)
  const [projectRelPath, setProjectRelPath] = useState("EAA_Sandbox/public/eaa_html_project.json");

  // export target (real runnable html file somewhere in workspace)
  const [exportRelPath, setExportRelPath] = useState("EAA_Sandbox/public/eaa_html_canvas/index.html");

  // stable session id
  const sessionIdRef = useRef<string>(
    (() => {
      try {
        return crypto.randomUUID();
      } catch {
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      }
    })()
  );
  const sessionId = sessionIdRef.current;

  const [rendered, setRendered] = useState<string>(() => buildHtmlProject(defaultFiles, sessionId));

  const activeFile = useMemo(() => {
    return getFile(files, active) ?? files[0] ?? { name: "index.html", content: "" };
  }, [files, active]);

  const editorLanguage = useMemo(() => monacoLangFromName(activeFile.name), [activeFile.name]);
  const previewSrc = useMemo(() => htmlToDataUrl(rendered), [rendered]);

  function setActive(name: string) {
    setActiveState(name);
  }

  function pushConsole(text: string) {
    setConsoleLines((prev) => {
      const next = [...prev, { t: Date.now(), text }];
      if (next.length > 300) return next.slice(next.length - 300);
      return next;
    });
  }

  function clearConsole() {
    setConsoleLines([]);
  }

  function clearRuntimeError() {
    setLastRuntimeError("");
  }

  function renderNow(reason: string) {
    const out = buildHtmlProject(files, sessionId);
    setRendered(out);
    setDirty(false);
    logLine(`[html] Rendered (${reason})`);
    pushConsole(`[render] ${reason}`);
  }

  // persist UI prefs
  useEffect(() => safeLSSet("eaa_html_canvas.split", splitPreview ? "1" : "0"), [splitPreview]);
  useEffect(() => safeLSSet("eaa_html_canvas.ratio", String(splitRatio)), [splitRatio]);
  useEffect(() => safeLSSet("eaa_html_canvas.console", showConsole ? "1" : "0"), [showConsole]);

  // auto-render
  useEffect(() => {
    if (!auto) return;
    const t = window.setTimeout(() => {
      const out = buildHtmlProject(files, sessionId);
      setRendered(out);
      setDirty(false);
    }, 220);
    return () => window.clearTimeout(t);
  }, [files, auto, sessionId]);

  // bridge listener
  useEffect(() => {
    const onMsg = (ev: MessageEvent) => {
      const d: any = ev.data;
      if (!d || typeof d !== "object") return;
      if (d.type !== "EAA_HTML_BRIDGE") return;
      if (d.sid !== sessionId) return;

      const kind = String(d.kind || "");
      const level = String(d.level || "log");
      const args = Array.isArray(d.args) ? d.args : [];
      const msg = args.join(" ");

      if (kind === "console") {
        const line = `[${level}] ${msg}`;
        logLine(`[html] ${line}`);
        pushConsole(line);
        return;
      }
      if (kind === "error") {
        const line = `[runtime error] ${msg}`;
        logLine(`[html] ${line}`);
        pushConsole(line);
        setLastRuntimeError(msg);
        setShowConsole(true);
        return;
      }
      if (kind === "rejection") {
        const line = `[unhandled rejection] ${msg}`;
        logLine(`[html] ${line}`);
        pushConsole(line);
        setLastRuntimeError(msg);
        setShowConsole(true);
        return;
      }
    };

    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [logLine, sessionId]);

  function updateActiveContent(txt: string) {
    setFiles((prev) => setFileContent(prev, activeFile.name, txt));
    if (!auto) setDirty(true);
  }

  function addFile() {
    const name = window.prompt("New file name (e.g. extra.js / theme.css / page.html):", "extra.js");
    if (!name) return;
    const trimmed = name.trim();
    if (!trimmed) return;

    if (getFile(files, trimmed)) {
      logLine(`[html] File already exists: ${trimmed}`);
      pushConsole(`[info] File exists: ${trimmed}`);
      setActive(trimmed);
      return;
    }

    setFiles((prev) => [...prev, { name: trimmed, content: "" }]);
    setActive(trimmed);
    setDirty(true);
    pushConsole(`[add] ${trimmed}`);
  }

  function deleteActiveFile() {
    const name = activeFile.name;
    if (name === "index.html") {
      logLine("[html] Can't delete index.html");
      pushConsole("[warn] Can't delete index.html");
      return;
    }
    if (!window.confirm(`Delete ${name}?`)) return;

    const next = removeFile(files, name);
    setFiles(next);
    setActive(next[0]?.name ?? "index.html");
    setDirty(true);
    pushConsole(`[delete] ${name}`);
  }

  function renameActiveFile() {
    const from = activeFile.name;
    if (!from) return;

    const to = window.prompt("Rename file to:", from);
    if (!to) return;

    const res = renameFile(files, from, to);
    if (!res.ok) {
      pushConsole(`[error] rename: ${res.error}`);
      return;
    }

    setFiles(res.files);
    setActive(to.trim());
    setDirty(true);
    pushConsole(`[rename] ${from} -> ${to.trim()}`);
  }

  function duplicateActiveFile() {
    const src = activeFile.name;
    const res = duplicateFile(files, src);
    if (!res.ok) {
      pushConsole(`[error] duplicate: ${res.error}`);
      return;
    }
    setFiles(res.files);
    setActive(res.created);
    setDirty(true);
    pushConsole(`[dup] ${src} -> ${res.created}`);
  }

  function resetProject() {
    if (!window.confirm("Reset HTML project files back to default mock?")) return;
    setFiles(defaultFiles);
    setActive("app.js");
    setRendered(buildHtmlProject(defaultFiles, sessionId));
    setDirty(false);
    setLastRuntimeError("");
    pushConsole("[reset] default project");
    logLine("[html] Reset project to default");
  }

  async function saveProject() {
    const rel = projectRelPath.trim();
    if (!rel) {
      logLine("[html][error] Project relPath is empty");
      pushConsole("[error] Project relPath empty");
      return;
    }
    try {
      const json = JSON.stringify({ version: 1, files }, null, 2);
      const out = await invoke<string>("eaa_write_file", { relPath: rel, content: json });
      logLine(`[html] Saved project -> ${rel}`);
      pushConsole(`[save] ${rel}`);
      logLine(out);
    } catch (err) {
      logLine(`[html][error] save failed: ${String(err)}`);
      pushConsole(`[error] save failed: ${String(err)}`);
    }
  }

  async function loadProject(reason: string = "manual") {
    const rel = projectRelPath.trim();
    if (!rel) {
      logLine("[html][error] Project relPath is empty");
      pushConsole("[error] Project relPath empty");
      return;
    }
    try {
      const read = await invoke<string>("eaa_read_file", { relPath: rel });
      const body = extractReadFileBody(read).trim();
      const parsed = JSON.parse(body) as any;

      const nextFiles: HtmlProjectFile[] = Array.isArray(parsed?.files)
        ? parsed.files
            .map((f: any) => ({ name: String(f.name || ""), content: String(f.content || "") }))
            .filter((f: any) => f.name)
        : [];

      if (!nextFiles.length) throw new Error("Bad project JSON (missing files[])");

      setFiles(nextFiles);
      setActive(nextFiles[0]?.name ?? "index.html");

      const html = buildHtmlProject(nextFiles, sessionId);
      setRendered(html);
      setDirty(false);
      setLastRuntimeError("");

      logLine(`[html] Loaded project (${reason}) <- ${rel}`);
      pushConsole(`[load] ${rel} (${reason})`);
    } catch (err) {
      logLine(`[html][error] load failed: ${String(err)}`);
      pushConsole(`[error] load failed: ${String(err)}`);
    }
  }

  async function exportHtmlFile() {
    const rel = exportRelPath.trim();
    if (!rel) {
      logLine("[html][error] Export relPath is empty");
      pushConsole("[error] Export relPath empty");
      return;
    }
    try {
      const html = auto ? rendered : buildHtmlProject(files, sessionId);
      const out = await invoke<string>("eaa_write_file", { relPath: rel, content: html });
      logLine(`[html] Exported -> ${rel}`);
      pushConsole(`[export] ${rel}`);
      logLine(out);
    } catch (err) {
      logLine(`[html][error] export failed: ${String(err)}`);
      pushConsole(`[error] export failed: ${String(err)}`);
    }
  }

  const ctx: Ctx = {
    files,
    setFiles,
    active,
    setActive,

    auto,
    setAuto,
    dirty,
    setDirty,

    rendered,
    renderNow,

    splitPreview,
    setSplitPreview,
    splitRatio,
    setSplitRatio,

    showConsole,
    setShowConsole,
    consoleLines,
    clearConsole,

    lastRuntimeError,
    clearRuntimeError,

    projectRelPath,
    setProjectRelPath,

    exportRelPath,
    setExportRelPath,

    previewSrc,

    addFile,
    deleteActiveFile,
    resetProject,
    updateActiveContent,

    renameActiveFile,
    duplicateActiveFile,

    saveProject,
    loadProject,
    exportHtmlFile,

    activeFile,
    editorLanguage,
  };

  return <HtmlCanvasContext.Provider value={ctx}>{children}</HtmlCanvasContext.Provider>;
}

/* =========================
   UI pieces
========================= */

function Btn(props: { label: string; onClick: () => void; danger?: boolean; active?: boolean; disabled?: boolean }) {
  const { label, onClick, danger, active, disabled } = props;
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      style={{
        padding: "8px 10px",
        borderRadius: 10,
        border: "1px solid #2a3a50",
        background: danger ? "#2a1220" : active ? "#1b2a3f" : "#0e1521",
        color: "#e6edf3",
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: 12,
        fontWeight: 900,
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {label}
    </button>
  );
}

function ConsolePanel() {
  const c = useHtmlCanvas();
  if (!c.showConsole) return null;

  return (
    <div style={{ borderTop: "1px solid #1d2836", background: "#0b1220" }}>
      <div
        style={{
          padding: "10px 12px",
          display: "flex",
          gap: 10,
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: "1px solid #1d2836",
          background: "#0e1521",
        }}
      >
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ fontSize: 12, fontWeight: 900, opacity: 0.9 }}>Console</span>
          {c.lastRuntimeError && (
            <span style={{ fontSize: 12, fontWeight: 900, color: "#ffb4b4" }}>Runtime error captured</span>
          )}
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <Btn label="Clear" onClick={() => c.clearConsole()} />
          {c.lastRuntimeError && <Btn label="Clear Error" danger onClick={() => c.clearRuntimeError()} />}
          <Btn label="Hide" onClick={() => c.setShowConsole(false)} />
        </div>
      </div>

      <div
        style={{
          maxHeight: 180,
          overflow: "auto",
          padding: 10,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        }}
      >
        {c.consoleLines.length === 0 ? (
          <div style={{ fontSize: 12, opacity: 0.7 }}>No console output yet.</div>
        ) : (
          c.consoleLines.map((l, idx) => (
            <div key={idx} style={{ fontSize: 12, opacity: 0.9, padding: "2px 0", whiteSpace: "pre-wrap" }}>
              <span style={{ opacity: 0.55 }}>{new Date(l.t).toLocaleTimeString()} </span>
              {l.text}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function Palette(props: {
  open: boolean;
  query: string;
  setQuery: (s: string) => void;
  items: PaletteItem[];
  sel: number;
  setSel: (n: number) => void;
  onPick: (it: PaletteItem) => void;
  onClose: () => void;
}) {
  const { open, query, setQuery, items, sel, setSel, onPick, onClose } = props;
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [open]);

  if (!open) return null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.55)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: 80,
        zIndex: 9999,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: "min(900px, 92vw)",
          borderRadius: 16,
          border: "1px solid #2a3a50",
          background: "#0b1220",
          boxShadow: "0 30px 90px rgba(0,0,0,.6)",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: 12, borderBottom: "1px solid #1d2836", background: "#0e1521" }}>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSel(0);
            }}
            placeholder={`Type to search files. Use ">": commands.  (Esc to close)`}
            style={{
              width: "100%",
              padding: "10px 12px",
              borderRadius: 12,
              border: "1px solid #2a3a50",
              background: "#0b1220",
              color: "#e6edf3",
              outline: "none",
              fontSize: 13,
              fontWeight: 800,
            }}
          />
        </div>

        <div style={{ maxHeight: 420, overflow: "auto" }}>
          {items.length === 0 ? (
            <div style={{ padding: 14, fontSize: 12, opacity: 0.7 }}>No matches.</div>
          ) : (
            items.map((it, i) => {
              const active = i === sel;
              const title = it.kind === "file" ? it.name : it.cmd.label;
              const sub = it.kind === "file" ? "file" : "command";
              return (
                <div
                  key={it.key}
                  onMouseEnter={() => setSel(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    onPick(it);
                  }}
                  style={{
                    padding: "10px 12px",
                    borderBottom: "1px solid #111a27",
                    background: active ? "#112036" : "transparent",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 10,
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 900, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {title}
                    </div>
                    <div style={{ fontSize: 12, opacity: 0.6 }}>{sub}</div>
                  </div>
                  <div style={{ fontSize: 12, opacity: 0.55 }}>{it.kind === "file" ? "" : "↩"}</div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

export function HtmlCanvasEditor(props: { isBusy: boolean }) {
  const { isBusy } = props;
  const c = useHtmlCanvas();

  // draggable splitter
  const dragRef = useRef<{ dragging: boolean; startX: number; startRatio: number }>({
    dragging: false,
    startX: 0,
    startRatio: c.splitRatio,
  });

  function startDrag(e: React.MouseEvent) {
    dragRef.current.dragging = true;
    dragRef.current.startX = e.clientX;
    dragRef.current.startRatio = c.splitRatio;

    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current.dragging) return;
      const container = document.getElementById("eaa-html-split-container");
      if (!container) return;
      const w = container.getBoundingClientRect().width || 1;
      const dx = ev.clientX - dragRef.current.startX;
      const next = clamp(dragRef.current.startRatio + dx / w, 0.2, 0.8);
      c.setSplitRatio(next);
    };

    const onUp = () => {
      dragRef.current.dragging = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  // palette state
  const [palOpen, setPalOpen] = useState(false);
  const [palQuery, setPalQuery] = useState("");
  const [palSel, setPalSel] = useState(0);

  const commands: CommandItem[] = useMemo(
    () => [
      { id: "toggle-auto", label: `Toggle Auto (${c.auto ? "On" : "Off"})`, run: () => c.setAuto((x) => !x) },
      { id: "toggle-split", label: `Toggle Split (${c.splitPreview ? "On" : "Off"})`, run: () => c.setSplitPreview((x) => !x) },
      { id: "toggle-console", label: `Toggle Console (${c.showConsole ? "On" : "Off"})`, run: () => c.setShowConsole((x) => !x) },
      { id: "add", label: "Add file", run: () => c.addFile() },
      { id: "rename", label: "Rename active file", run: () => c.renameActiveFile() },
      { id: "dup", label: "Duplicate active file", run: () => c.duplicateActiveFile() },
      { id: "reset", label: "Reset project", run: () => c.resetProject() },
      { id: "render", label: "Render (manual)", run: () => c.renderNow("manual") },
    ],
    [c]
  );

  const paletteItems: PaletteItem[] = useMemo(() => {
    const q = palQuery.trim();
    const isCmd = q.startsWith(">");
    const needle = (isCmd ? q.slice(1) : q).trim().toLowerCase();

    if (isCmd) {
      return commands
        .filter((x) => x.label.toLowerCase().includes(needle))
        .map((cmd) => ({ kind: "cmd" as const, key: `cmd:${cmd.id}`, cmd }));
    }

    return c.files
      .filter((f) => f.name.toLowerCase().includes(needle))
      .map((f) => ({ kind: "file" as const, key: `file:${f.name}`, name: f.name }));
  }, [palQuery, commands, c.files]);

  function closePalette() {
    setPalOpen(false);
    setPalQuery("");
    setPalSel(0);
  }

  function pickPalette(it: PaletteItem) {
    if (it.kind === "file") {
      c.setActive(it.name);
      closePalette();
      return;
    }
    it.cmd.run();
    closePalette();
  }

  // keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isMac = navigator.platform.toLowerCase().includes("mac");
      const mod = isMac ? e.metaKey : e.ctrlKey;

      // Ctrl+P palette
      if (mod && (e.key === "p" || e.key === "P")) {
        e.preventDefault();
        setPalOpen(true);
        return;
      }

      // Ctrl+S save
      if (mod && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        void c.saveProject();
        return;
      }

      // Ctrl+Enter toggle split
      if (mod && e.key === "Enter") {
        e.preventDefault();
        c.setSplitPreview((x) => !x);
        return;
      }

      if (!palOpen) return;

      // palette nav
      if (e.key === "Escape") {
        e.preventDefault();
        closePalette();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setPalSel((x) => Math.min(x + 1, Math.max(0, paletteItems.length - 1)));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setPalSel((x) => Math.max(0, x - 1));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const it = paletteItems[palSel];
        if (it) pickPalette(it);
        return;
      }
    };

    window.addEventListener("keydown", onKey, { passive: false });
    return () => window.removeEventListener("keydown", onKey as any);
  }, [c, palOpen, paletteItems, palSel]);

  return (
    <>
      <Palette
        open={palOpen}
        query={palQuery}
        setQuery={setPalQuery}
        items={paletteItems}
        sel={palSel}
        setSel={setPalSel}
        onPick={pickPalette}
        onClose={closePalette}
      />

      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* top bar */}
        <div
          style={{
            padding: 12,
            borderBottom: "1px solid #1d2836",
            background: "#0e1521",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 12, fontWeight: 900, opacity: 0.9 }}>Files</span>
            <span style={{ fontSize: 12, opacity: 0.85 }}>Editing: {c.activeFile.name}</span>

            <Btn label={c.auto ? "Auto On" : "Auto Off"} active={c.auto} onClick={() => c.setAuto((x) => !x)} />
            {!c.auto && <Btn label="Render" onClick={() => c.renderNow("manual")} disabled={!c.dirty} />}

            <Btn label={c.splitPreview ? "Split On" : "Split Off"} active={c.splitPreview} onClick={() => c.setSplitPreview((x) => !x)} />
            <Btn label={c.showConsole ? "Console On" : "Console Off"} active={c.showConsole} onClick={() => c.setShowConsole((x) => !x)} />

            <Btn label="Ctrl+P" onClick={() => setPalOpen(true)} />
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <Btn label="+ File" onClick={() => c.addFile()} />
            <Btn label="Duplicate" onClick={() => c.duplicateActiveFile()} />
            <Btn label="Rename" onClick={() => c.renameActiveFile()} />
            <Btn label="Delete" danger onClick={() => c.deleteActiveFile()} />
            <Btn label="Reset" danger onClick={() => c.resetProject()} />
          </div>
        </div>

        {/* main */}
        <div style={{ flex: 1, minHeight: 0, display: "flex", overflow: "hidden" }}>
          {/* files column */}
          <div
            style={{
              width: 160,
              minWidth: 160,
              borderRight: "1px solid #1d2836",
              background: "#0b1220",
              padding: 10,
              display: "flex",
              flexDirection: "column",
              gap: 8,
              overflow: "auto",
            }}
          >
            {c.files.map((f) => (
              <button
                key={f.name}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "9px 10px",
                  borderRadius: 12,
                  border: "1px solid #1d2836",
                  background: f.name === c.active ? "#0e1521" : "#0b1220",
                  color: "#e6edf3",
                  cursor: "pointer",
                  fontWeight: 900,
                  fontSize: 12,
                }}
                onClick={() => c.setActive(f.name)}
              >
                {f.name}
              </button>
            ))}
          </div>

          {/* editor + preview */}
          <div id="eaa-html-split-container" style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", overflow: "hidden" }}>
            {/* left = editor */}
            <div style={{ width: c.splitPreview ? `${c.splitRatio * 100}%` : "100%", minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
              {c.lastRuntimeError && (
                <div style={{ padding: "10px 12px", background: "#2a1220", borderBottom: "1px solid #1d2836", color: "#ffd7d7" }}>
                  <div style={{ fontSize: 12, fontWeight: 900 }}>Runtime error</div>
                  <div style={{ fontSize: 12, opacity: 0.9, marginTop: 4, whiteSpace: "pre-wrap" }}>{c.lastRuntimeError}</div>
                </div>
              )}

              <div style={{ flex: 1, minHeight: 0, background: "#0b0f14", overflow: "hidden" }}>
                <Editor
                  height="100%"
                  language={c.editorLanguage}
                  theme="vs-dark"
                  value={c.activeFile.content}
                  onChange={(v) => c.updateActiveContent(v ?? "")}
                  options={{
                    minimap: { enabled: false },
                    wordWrap: "on",
                    fontSize: 12,
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    tabSize: 2,
                  }}
                />
              </div>

              {/* project actions */}
              <div style={{ padding: 12, borderTop: "1px solid #1d2836", background: "#0e1521" }}>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                  <span style={{ fontSize: 12, fontWeight: 900, opacity: 0.85 }}>Project JSON:</span>
                  <input
                    style={{
                      width: 420,
                      maxWidth: "100%",
                      padding: "9px 10px",
                      borderRadius: 12,
                      border: "1px solid #2a3a50",
                      background: "#0b1220",
                      color: "#e6edf3",
                      fontSize: 12,
                      outline: "none",
                    }}
                    value={c.projectRelPath}
                    onChange={(e) => c.setProjectRelPath(e.target.value)}
                  />
                  <Btn label="Save (Ctrl+S)" onClick={() => void c.saveProject()} disabled={isBusy} />
                  <Btn label="Load" onClick={() => void c.loadProject("manual")} disabled={isBusy} />
                </div>

                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginTop: 10 }}>
                  <span style={{ fontSize: 12, fontWeight: 900, opacity: 0.85 }}>Export HTML file:</span>
                  <input
                    style={{
                      width: 420,
                      maxWidth: "100%",
                      padding: "9px 10px",
                      borderRadius: 12,
                      border: "1px solid #2a3a50",
                      background: "#0b1220",
                      color: "#e6edf3",
                      fontSize: 12,
                      outline: "none",
                    }}
                    value={c.exportRelPath}
                    onChange={(e) => c.setExportRelPath(e.target.value)}
                  />
                  <Btn label="Export" onClick={() => void c.exportHtmlFile()} disabled={isBusy} />
                </div>

                <div style={{ marginTop: 8, fontSize: 12, opacity: 0.7 }}>
                  Shortcuts: Ctrl+P palette • Ctrl+S save • Ctrl+Enter split • Type ">" in palette for commands
                </div>
              </div>

              <ConsolePanel />
            </div>

            {/* splitter */}
            {c.splitPreview && (
              <div
                onMouseDown={startDrag}
                style={{
                  width: 10,
                  cursor: "col-resize",
                  background: "#0b1220",
                  borderLeft: "1px solid #1d2836",
                  borderRight: "1px solid #1d2836",
                }}
                title="Drag to resize"
              />
            )}

            {/* right = preview */}
            {c.splitPreview && (
              <div style={{ flex: 1, minWidth: 280, background: "#000", display: "flex" }}>
                <iframe title="split-preview" style={{ height: "100%", width: "100%", border: "none" }} src={c.previewSrc} />
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

export function HtmlCanvasPreview() {
  const c = useHtmlCanvas();
  return <iframe title="preview" style={{ flex: 1, minHeight: 0, border: "none" }} src={c.previewSrc} />;
}
