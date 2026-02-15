// src/components/canvas/CanvasEditor.tsx
import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import Editor from "@monaco-editor/react";
import { useCanvas, HtmlViewport } from "./CanvasContext";
import { monacoLangFromName } from "./htmlProject";
import { VisualCanvasEditor } from "./VisualCanvas";
import { CanvasPreview } from "./CanvasPreview";

// Icons
const Icons = {
  Code: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="16 18 22 12 16 6"></polyline>
      <polyline points="8 6 2 12 8 18"></polyline>
    </svg>
  ),
  Play: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="5 3 19 12 5 21 5 3"></polygon>
    </svg>
  ),
  File: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
      <polyline points="13 2 13 9 20 9"></polyline>
    </svg>
  ),
  ChevronDown: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="6 9 12 15 18 9"></polyline>
    </svg>
  ),
  ChevronRight: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="9 18 15 12 9 6"></polyline>
    </svg>
  ),
  Search: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8"></circle>
      <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
    </svg>
  ),
};

// Returns width or null if fit
function viewportWidthPx(v: HtmlViewport) {
  if (v === "phone") return 375;
  if (v === "tablet") return 768;
  if (v === "windows") return 1280; 
  return null; // fit
}

type ConsoleKind = "log" | "warn" | "error";
type ConsoleView = "console" | "network";

type ConsoleEntry = {
  id: number;
  kind: ConsoleKind;
  label: string;
  text: string;
  stack?: string;
  where?: string;
  tag?: string;
  ts: number;
};

const MAX_CONSOLE = 300;
const CANVAS_SOURCE_PREFIX = "eaa-canvas:///";

function safeToText(v: any) {
  try {
    if (v == null) return String(v);
    if (typeof v === "string") return v;
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    if (v instanceof Error) return v.stack || `${v.name}: ${v.message}`;
    return JSON.stringify(v, null, 2);
  } catch {
    try { return String(v); } catch { return "[unprintable]"; }
  }
}

function kindFromLabel(label: string, base: ConsoleKind): ConsoleKind {
  const l = (label || "").toLowerCase();
  if (base === "warn" || l.includes("warn")) return "warn";
  if (base === "error" || l.includes("error") || l.includes("rejection") || l.includes("runtime") || l.includes("network") || l.includes("resource")) {
    return "error";
  }
  return "log";
}

function isNetworkEntry(e: Pick<ConsoleEntry, "label" | "tag">) {
  const l = (e.label || "").toLowerCase();
  const t = (e.tag || "").toLowerCase();
  return l.includes("network") || l.includes("resource") || t === "fetch" || t === "xhr" || t === "ws" || t === "resource";
}

function emojiFor(kind: ConsoleKind, label: string, tag?: string) {
  const l = (label || "").toLowerCase();
  const t = (tag || "").toLowerCase();

  if (l.includes("network") || l.includes("resource") || t.includes("fetch") || t.includes("xhr") || t.includes("ws") || t.includes("resource")) {
    return kind === "warn" ? "🌐⚠️" : "🌐❌";
  }

  if (kind === "warn") return "⚠️";
  if (kind === "error") {
    if (l.includes("runtime")) return "💥";
    if (l.includes("rejection")) return "🧨";
    return "❌";
  }
  return "💬";
}

function parseV2Payload(d: any) {
  const level = String(d?.level || "log").toLowerCase();
  const baseKind: ConsoleKind = level === "warn" ? "warn" : level === "error" ? "error" : "log";

  const rawArgs: any[] = Array.isArray(d?.args) ? d.args : [];
  const args = rawArgs.map(safeToText);

  const tag = d?.tag ? String(d.tag) : undefined;

  let label = baseKind;
  let textArgs = [...args];

  const tagLower = (tag || "").toLowerCase();
  if (tagLower === "fetch" || tagLower === "xhr" || tagLower === "ws") label = "network";
  else if (tagLower === "resource") label = "resource";
  else if (tagLower === "runtime") label = "runtime error";
  else if (tagLower === "rejection") label = "unhandled rejection";

  if (textArgs.length > 0) {
    const first = (textArgs[0] || "").toLowerCase();

    if (first.startsWith("[runtime error]")) {
      label = "runtime error";
      textArgs[0] = textArgs[0].replace(/^\[runtime error\]\s*/i, "");
    } else if (first.startsWith("[unhandled rejection]") || first === "[unhandled rejection]") {
      label = "unhandled rejection";
      textArgs.shift();
    }
  }

  const text = textArgs.join(" ").trim();
  const stack = d?.stack ? String(d.stack) : undefined;
  const where = d?.where ? String(d.where) : undefined;
  const ts = typeof d?.ts === "number" ? d.ts : Date.now();

  const kind = kindFromLabel(label, baseKind);

  return { kind, label, text, stack, where, ts, tag } as const;
}

function normalizeMessageData(data: any) {
  if (!data) return null;
  if (typeof data === "string") {
    const s = data.trim();
    if (!s) return null;
    if ((s.startsWith("{") && s.endsWith("}")) || (s.startsWith("[") && s.endsWith("]"))) {
      try { return JSON.parse(s); } catch { return null; }
    }
    return null;
  }
  return data;
}

type Loc = { file: string; line: number; col: number };

function stripCanvasPrefix(file: string) {
  let f = String(file || "").trim();
  f = f.replace(/[)\]]+$/g, "");
  if (f.startsWith(CANVAS_SOURCE_PREFIX)) f = f.slice(CANVAS_SOURCE_PREFIX.length);
  f = f.split("?")[0].split("#")[0];
  try { f = decodeURIComponent(f); } catch {}
  return f;
}

function extractLocs(where?: string, stack?: string): Loc[] {
  const out: Loc[] = [];
  const push = (file: string, line: number, col: number) => {
    if (!file || !Number.isFinite(line) || !Number.isFinite(col)) return;
    const f = stripCanvasPrefix(file);
    out.push({ file: f, line: Math.max(1, line), col: Math.max(1, col) });
  };

  if (where) {
    const m = String(where).match(/^(.*):(\d+):(\d+)$/);
    if (m) push(m[1], Number(m[2]), Number(m[3]));
  }

  if (stack) {
    const re = /(eaa-canvas:\/\/\/[^\s\)\]]+|[A-Za-z0-9_\-./]+):(\d+):(\d+)/g;
    const s = String(stack);
    let m: RegExpExecArray | null;
    while ((m = re.exec(s))) {
      push(m[1], Number(m[2]), Number(m[3]));
    }
  }

  const seen = new Set<string>();
  return out.filter((l) => {
    const k = `${l.file}:${l.line}:${l.col}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function isInlineIndexFile(file: string) {
  return /^index\.html\.inline\.\d+\.js$/i.test(file);
}

function parseInlineIndexNum(file: string) {
  const m = file.match(/^index\.html\.inline\.(\d+)\.js$/i);
  return m ? Number(m[1]) : null;
}

function clampLineColToContent(content: string, line: number, col: number) {
  const lines = String(content ?? "").split("\n");
  const maxLine = Math.max(1, lines.length);
  const l = Math.min(Math.max(1, line), maxLine);
  const lineText = lines[l - 1] ?? "";
  const maxCol = Math.max(1, lineText.length + 1);
  const c = Math.min(Math.max(1, col), maxCol);
  return { line: l, col: c, maxLine, maxCol };
}

function findBraceBlockJS(code: string, targetLine: number) {
  type Open = { line: number };
  const opens: Open[] = [];
  const pairs: { start: number; end: number }[] = [];

  let line = 1;
  let i = 0;
  let inSQ = false, inDQ = false, inTQ = false, inLC = false, inBC = false, esc = false;
  const s = String(code ?? "");
  const len = s.length;

  while (i < len) {
    const ch = s[i];
    const next = i + 1 < len ? s[i + 1] : "";

    if (ch === "\n") { line++; inLC = false; esc = false; i++; continue; }
    if (inLC) { i++; continue; }
    if (inBC) { if (ch === "*" && next === "/") { inBC = false; i += 2; continue; } i++; continue; }
    if (!inSQ && !inDQ && !inTQ) {
      if (ch === "/" && next === "/") { inLC = true; i += 2; continue; }
      if (ch === "/" && next === "*") { inBC = true; i += 2; continue; }
    }
    if (inSQ) { if (!esc && ch === "'") inSQ = false; esc = !esc && ch === "\\"; i++; continue; }
    if (inDQ) { if (!esc && ch === '"') inDQ = false; esc = !esc && ch === "\\"; i++; continue; }
    if (inTQ) { if (!esc && ch === "`") inTQ = false; esc = !esc && ch === "\\"; i++; continue; }

    if (ch === "'") { inSQ = true; i++; continue; }
    if (ch === '"') { inDQ = true; i++; continue; }
    if (ch === "`") { inTQ = true; i++; continue; }

    if (ch === "{") { opens.push({ line }); i++; continue; }
    if (ch === "}") { const o = opens.pop(); if (o) pairs.push({ start: o.line, end: line }); i++; continue; }
    i++;
  }

  let best: { start: number; end: number } | null = null;
  for (const p of pairs) {
    if (p.start <= targetLine && targetLine <= p.end) {
      if (!best) best = p;
      else {
        const bestSize = best.end - best.start;
        const pSize = p.end - p.start;
        if (pSize < bestSize) best = p;
      }
    }
  }
  return best;
}

export function CanvasEditor(props: { onOpenPreview: () => void }) {
  const [activeTab, setActiveTab] = useState<"code" | "preview">("code");

  const {
    canvasMode,
    htmlFiles,
    htmlActive,
    setHtmlActive,
    htmlActiveFile,
    htmlAuto,
    setHtmlAuto,
    htmlSplitPreview,
    setHtmlSplitPreview,
    updateActiveHtmlContent,
    addHtmlFile,
    deleteHtmlFile,
    manualRender,
    htmlRendered,
    logLine,
    htmlViewport,
    setHtmlViewport,
    vLayout,
    setVLayout,
    vTestMode,
    setVTestMode,
    vSnap,
    setVSnap,
    vGrid,
    setVGrid,
    vGridSize,
    setVGridSize,
    vRelPath,
    setVRelPath,
    vLiveSync,
    setVLiveSync,
    vPollMs,
    setVPollMs,
    saveLayoutToFile,
    loadLayoutFromFile,
  } = useCanvas();

  const editorRef = useRef<any>(null);
  const monacoRef = useRef<any>(null);
  const decoRef = useRef<string[]>([]);
  const pendingJumpRef = useRef<{ file: string; line: number; col: number; block?: { start: number; end: number } } | null>(null);

  const [consoleEntries, setConsoleEntries] = useState<ConsoleEntry[]>([]);
  const [consolePaused, setConsolePaused] = useState(false);
  const [consoleCollapsed, setConsoleCollapsed] = useState(false);
  const [consoleView, setConsoleView] = useState<ConsoleView>("console");
  const [showLog, setShowLog] = useState(true);
  const [showWarn, setShowWarn] = useState(true);
  const [showError, setShowError] = useState(true);

  const [inspectMode, setInspectMode] = useState(false);

  const pausedRef = useRef(false);
  const idRef = useRef(1);
  const consoleScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    pausedRef.current = consolePaused;
  }, [consolePaused]);

  useEffect(() => {
    const msg = { type: "EAA_TOGGLE_INSPECT", value: inspectMode };
    const iframes = document.querySelectorAll("iframe");
    iframes.forEach((f) => {
      f.contentWindow?.postMessage(msg, "*");
    });
  }, [inspectMode, htmlRendered]);

  useEffect(() => {
    function onMsg(ev: MessageEvent) {
      const raw = (ev as any)?.data;
      const d: any = normalizeMessageData(raw);
      if (!d) return;

      if (d.__eaa_canvas_inspector_hit === true) {
        const info = d.info;
        setInspectMode(false);
        logLine(`[inspector] Clicked <${info.tagName} id="${info.id}" class="${info.className}">`);
        
        if (info.id) {
          jumpToSearch(`id="${info.id}"`);
        } else if (info.className) {
          jumpToSearch(`class="${info.className.split(" ")[0]}"`);
        } else {
          jumpToSearch(`<${info.tagName}`);
        }
        return;
      }

      if (d.__eaa_canvas_console_v2 === true) {
        if (pausedRef.current) return;
        const parsed = parseV2Payload(d);
        const entry: ConsoleEntry = {
          id: idRef.current++,
          kind: parsed.kind,
          label: parsed.label,
          text: parsed.text,
          stack: parsed.stack,
          where: parsed.where,
          tag: parsed.tag,
          ts: parsed.ts,
        };
        setConsoleEntries((prev) => {
          const next = [...prev, entry];
          if (next.length > MAX_CONSOLE) next.splice(0, next.length - MAX_CONSOLE);
          return next;
        });
      }
    }

    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const jumpToSearch = (query: string) => {
    if (htmlActive !== "index.html") setHtmlActive("index.html");
    setActiveTab("code");

    requestAnimationFrame(() => {
      const ed = editorRef.current;
      const monaco = monacoRef.current;
      if (!ed || !monaco) return;

      const model = ed.getModel();
      if (!model) return;

      const matches = model.findMatches(query, false, false, false, null, true);
      if (matches && matches.length > 0) {
        const m = matches[0];
        const range = m.range;
        
        ed.revealRangeInCenter(range);
        ed.setSelection(range);
        
        decoRef.current = ed.deltaDecorations(decoRef.current, [
          { range: range, options: { isWholeLine: true, className: "eaaJumpLine" } }
        ]);
      } else {
        logLine(`[inspector] Could not find "${query}" in code.`);
      }
    });
  };

  useEffect(() => {
    const el = consoleScrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [consoleEntries, consoleCollapsed, consoleView]);

  const counts = useMemo(() => {
    let c = 0;
    let n = 0;
    for (const e of consoleEntries) {
      if (isNetworkEntry(e)) n++;
      else c++;
    }
    return { console: c, network: n };
  }, [consoleEntries]);

  const filteredEntries = useMemo(() => {
    return consoleEntries
      .filter((e) => {
        const net = isNetworkEntry(e);
        return consoleView === "network" ? net : !net;
      })
      .filter((e) => {
        if (e.kind === "log") return showLog;
        if (e.kind === "warn") return showWarn;
        return showError;
      });
  }, [consoleEntries, consoleView, showLog, showWarn, showError]);

  const lang = monacoLangFromName(htmlActiveFile.name);
  const vw = viewportWidthPx(htmlViewport);
  const isWindows = htmlViewport === "windows";
  
  // NEW: Check if this is a Python file
  const isPython = htmlActiveFile.name.toLowerCase().endsWith(".py");

  const fileSet = useMemo(() => new Set(htmlFiles.map((f) => f.name)), [htmlFiles]);

  const doDecorateAndJump = useCallback(
    (jump: { file: string; line: number; col: number; block?: { start: number; end: number } }) => {
      const ed = editorRef.current;
      const monaco = monacoRef.current;
      if (!ed || !monaco) return;

      try { decoRef.current = ed.deltaDecorations(decoRef.current, []); } catch {}

      const content = htmlFiles.find((f) => f.name === jump.file)?.content ?? "";
      const clamped = clampLineColToContent(content, jump.line, jump.col);
      const line = clamped.line;
      const col = clamped.col;

      if (jump.block && jump.block.start <= jump.block.end && jump.block.end - jump.block.start <= 300) {
        const bs = Math.max(1, Math.min(jump.block.start, clamped.maxLine));
        const be = Math.max(1, Math.min(jump.block.end, clamped.maxLine));
        const rBlock = new monaco.Range(bs, 1, be, 1);
        const rLine = new monaco.Range(line, 1, line, 1);

        decoRef.current = ed.deltaDecorations([], [
          { range: rBlock, options: { isWholeLine: true, className: "eaaJumpBlock" } },
          { range: rLine, options: { isWholeLine: true, className: "eaaJumpLine" } },
        ]);
        ed.revealRangeInCenter(rLine);
        ed.setSelection(new monaco.Range(line, col, line, col));
        ed.setPosition({ lineNumber: line, column: col });
        return;
      }

      const r = new monaco.Range(line, 1, line, 1);
      decoRef.current = ed.deltaDecorations([], [{ range: r, options: { isWholeLine: true, className: "eaaJumpLine" } }]);
      ed.revealRangeInCenter(r);
      ed.setSelection(new monaco.Range(line, col, line, col));
      ed.setPosition({ lineNumber: line, column: col });
    },
    [htmlFiles]
  );

  const resolveJump = useCallback(
    (e: ConsoleEntry) => {
      const locs = extractLocs(e.where, e.stack);
      for (const l of locs) {
        const f = l.file;
        if (fileSet.has(f)) {
          const content = htmlFiles.find((x) => x.name === f)?.content ?? "";
          const ext = (f.split(".").pop() || "").toLowerCase();
          const isJS = ext === "js" || ext === "mjs" || ext === "ts" || ext === "tsx" || ext === "jsx";
          const block = isJS ? findBraceBlockJS(content, l.line) : null;
          return { file: f, line: l.line, col: l.col, block: block ? { start: block.start, end: block.end } : undefined };
        }
        if (isInlineIndexFile(f) && fileSet.has("index.html")) {
          const n = parseInlineIndexNum(f);
          if (!n) continue;
          const indexContent = htmlFiles.find((x) => x.name === "index.html")?.content ?? "";
          const re = /(<script(?![^>]*\bsrc=)[^>]*>)([\s\S]*?)(<\/script>)/gi;
          let m: RegExpExecArray | null;
          let i = 0;
          while ((m = re.exec(indexContent))) {
            i++;
            if (i !== n) continue;
            const open = m[1];
            const body = m[2];
            const openStartIndex = m.index;
            const bodyStartIndex = openStartIndex + open.length;
            const beforeBody = indexContent.slice(0, bodyStartIndex);
            const bodyStartLine = beforeBody.split("\n").length;
            const mappedLine = bodyStartLine + (l.line - 1);
            const mappedCol = l.col;
            const blockInBody = findBraceBlockJS(body, l.line);
            const mappedBlock = blockInBody
              ? { start: bodyStartLine + (blockInBody.start - 1), end: bodyStartLine + (blockInBody.end - 1) }
              : undefined;
            return { file: "index.html", line: mappedLine, col: mappedCol, block: mappedBlock };
          }
        }
      }
      return null;
    },
    [fileSet, htmlFiles]
  );

  const jumpToEntry = useCallback(
    (e: ConsoleEntry) => {
      const j = resolveJump(e);
      if (!j) return;
      setActiveTab("code");
      pendingJumpRef.current = j;
      if (htmlActive !== j.file) setHtmlActive(j.file);
      if (htmlActive === j.file) {
        requestAnimationFrame(() => {
          const pj = pendingJumpRef.current;
          if (pj && pj.file === j.file) {
            doDecorateAndJump(pj);
            pendingJumpRef.current = null;
          }
        });
      }
    },
    [resolveJump, htmlActive, setHtmlActive, doDecorateAndJump]
  );

  useEffect(() => {
    const pj = pendingJumpRef.current;
    if (!pj) return;
    if (canvasMode !== "html") return;
    if (activeTab !== "code") return;
    if (htmlActiveFile.name !== pj.file) return;
    requestAnimationFrame(() => {
      const pj2 = pendingJumpRef.current;
      if (!pj2) return;
      if (htmlActiveFile.name !== pj2.file) return;
      doDecorateAndJump(pj2);
      pendingJumpRef.current = null;
    });
  }, [htmlActiveFile.name, htmlActiveFile.content, activeTab, canvasMode, doDecorateAndJump]);

  const styles = useMemo(() => {
    const cLog = "#00eaff";
    const cWarn = "#facc15";
    const cErr = "#ff5f56";

    return {
      root: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" as const, backgroundColor: "#020208", color: "#e6edf3" },
      toolbar: { height: 56, borderBottom: "1px solid #1d2836", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px", backgroundColor: "#0b1015" },
      toolbarGroup: { display: "flex", alignItems: "center", gap: 12 },
      fileName: { fontSize: 14, fontWeight: 500, color: "#00eaff", textShadow: "0 0 10px rgba(0,234,255,0.3)" },
      fileBadge: { fontSize: 11, padding: "2px 6px", borderRadius: 4, backgroundColor: "#1d2836", color: "#94a3b8", marginLeft: 8 },
      togglePill: { display: "flex", backgroundColor: "#080b10", borderRadius: 8, padding: 4, border: "1px solid #1d2836" },
      toggleBtn: (isActive: boolean): React.CSSProperties => ({ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: 6, border: "none", backgroundColor: isActive ? "#1d2836" : "transparent", color: isActive ? "#00eaff" : "#636d83", fontSize: 13, fontWeight: 500, cursor: "pointer", transition: "all 0.2s", boxShadow: isActive ? "0 0 15px rgba(0, 234, 255, 0.1)" : "none" }),
      viewportBtn: (isActive: boolean): React.CSSProperties => ({ padding: "6px 12px", fontSize: 11, borderRadius: 4, border: isActive ? "1px solid #00eaff" : "1px solid transparent", backgroundColor: isActive ? "rgba(0, 234, 255, 0.1)" : "transparent", color: isActive ? "#00eaff" : "#94a3b8", cursor: "pointer", fontWeight: 700, letterSpacing: "0.5px", transition: "all 0.2s" }),
      contentArea: { flex: 1, display: "flex", overflow: "hidden", position: "relative" as const },
      codeLayout: { flex: 1, display: "flex", width: "100%", minHeight: 0, minWidth: 0 },
      sidebar: { width: 220, borderRight: "1px solid #1d2836", backgroundColor: "#0b1015", display: "flex", flexDirection: "column" as const, minHeight: 0 },
      sidebarHeader: { padding: "12px 16px", fontSize: 12, fontWeight: 600, color: "#94a3b8", textTransform: "uppercase" as const, letterSpacing: "0.5px" },
      fileList: { flex: "0 0 auto", maxHeight: 220, overflowY: "auto" as const },
      fileItem: (isActive: boolean): React.CSSProperties => ({ padding: "8px 16px", fontSize: 13, color: isActive ? "#00eaff" : "#94a3b8", backgroundColor: isActive ? "rgba(0, 234, 255, 0.05)" : "transparent", cursor: "pointer", display: "flex", alignItems: "center", gap: 8, borderLeft: isActive ? "3px solid #00eaff" : "3px solid transparent" }),
      editorPane: { flex: 1, display: "flex", flexDirection: "column" as const, backgroundColor: "#020208", minWidth: 0 },
      actionsBar: { height: 40, borderBottom: "1px solid #1d2836", display: "flex", alignItems: "center", padding: "0 12px", gap: 8, backgroundColor: "#0b1015" },
      actionBtn: (active?: boolean): React.CSSProperties => ({ padding: "4px 10px", fontSize: 12, borderRadius: 6, border: "1px solid #1d2836", backgroundColor: active ? "rgba(0, 234, 255, 0.1)" : "transparent", color: active ? "#00eaff" : "#94a3b8", cursor: "pointer", transition: "all 0.2s", userSelect: "none" }),
      consoleWrap: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" as const, borderTop: "1px solid #1d2836" },
      consoleTop: { padding: "8px 10px", display: "flex", flexDirection: "column" as const, alignItems: "stretch", gap: 8, borderBottom: "1px solid #1d2836", backgroundColor: "#080b10" },
      consoleHeaderRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, minWidth: 0 },
      consoleTitleRow: { display: "flex", alignItems: "center", gap: 8, minWidth: 0 },
      consoleTitle: { fontSize: 11, fontWeight: 1000, letterSpacing: "0.6px", color: "#94a3b8", textTransform: "uppercase" as const, whiteSpace: "nowrap" as const, overflow: "hidden" as const, textOverflow: "ellipsis" as const },
      miniBtn: { display: "inline-flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 6, border: "1px solid #1d2836", background: "transparent", color: "#94a3b8", cursor: "pointer", flex: "0 0 auto" },
      consoleTabsPill: { display: "flex", width: "100%", backgroundColor: "#0b1015", borderRadius: 999, padding: 4, border: "1px solid #1d2836", gap: 4 },
      consoleTabBtn: (active: boolean): React.CSSProperties => ({ flex: 1, padding: "6px 10px", fontSize: 12, borderRadius: 999, border: "1px solid transparent", backgroundColor: active ? "rgba(0, 234, 255, 0.10)" : "transparent", color: active ? "#00eaff" : "#94a3b8", cursor: "pointer", fontWeight: 900, letterSpacing: "0.2px", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, userSelect: "none" }),
      consoleBtns: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" as const, width: "100%" },
      pillBtn: (active: boolean, tone: "log" | "warn" | "error"): React.CSSProperties => { const color = tone === "log" ? cLog : tone === "warn" ? cWarn : cErr; return { padding: "3px 8px", fontSize: 11, borderRadius: 999, border: `1px solid ${active ? color : "#1d2836"}`, background: active ? `rgba(255,255,255,0.04)` : "transparent", color: active ? color : "#94a3b8", cursor: "pointer", fontWeight: 1000, letterSpacing: "0.4px", userSelect: "none" }; },
      consoleList: { flex: 1, minHeight: 0, overflowY: "auto" as const, padding: 10, display: "flex", flexDirection: "column" as const, gap: 8 },
      entry: (kind: ConsoleKind, clickable: boolean): React.CSSProperties => { const bg = kind === "log" ? "rgba(0,234,255,0.06)" : kind === "warn" ? "rgba(250,204,21,0.10)" : "rgba(255,95,86,0.12)"; const left = kind === "log" ? "rgba(0,234,255,0.55)" : kind === "warn" ? "rgba(250,204,21,0.70)" : "rgba(255,95,86,0.80)"; return { border: "1px solid rgba(255,255,255,0.08)", borderLeft: `3px solid ${left}`, borderRadius: 10, background: bg, padding: "8px 8px", cursor: clickable ? "pointer" : "default", transition: "transform 0.06s ease" }; },
      entryHead: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 6 },
      entryLabel: { fontSize: 11, fontWeight: 1000, letterSpacing: "0.5px", color: "#e6edf3", opacity: 0.95, display: "flex", alignItems: "center", gap: 6 },
      entryTime: { fontSize: 10, color: "#94a3b8", fontWeight: 900, opacity: 0.9 },
      entryBody: { fontSize: 12, lineHeight: 1.35, color: "#e6edf3", whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const, fontFamily: "'JetBrains Mono', Consolas, monospace", opacity: 0.95 },
      entryMeta: { marginTop: 6, fontSize: 11, lineHeight: 1.25, color: "#94a3b8", whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const, fontFamily: "'JetBrains Mono', Consolas, monospace", opacity: 0.9 },
    };
  }, []);

  if (canvasMode === "visual") {
    return (
      <div style={styles.root}>
        <div style={styles.toolbar}>
          <div style={styles.toolbarGroup}>
            <span style={styles.fileName}>Visual Layout</span>
            <span style={styles.fileBadge}>JSON</span>
          </div>
          <div style={styles.toolbarGroup}>
            <div style={styles.togglePill}>
              <button style={styles.toggleBtn(false)}>
                <Icons.Code /> Logic
              </button>
              <button style={styles.toggleBtn(true)}>
                <Icons.Play /> Visual
              </button>
            </div>
          </div>
        </div>
        <VisualCanvasEditor
          layout={vLayout} setLayout={setVLayout} logLine={logLine} layoutRelPath={vRelPath} setLayoutRelPath={setVRelPath} saveToFile={saveLayoutToFile} loadFromFile={loadLayoutFromFile} liveSync={vLiveSync} setLiveSync={setVLiveSync} pollMs={vPollMs} setPollMs={setVPollMs} testMode={vTestMode} setTestMode={setVTestMode} snapEnabled={vSnap} setSnapEnabled={setVSnap} gridEnabled={vGrid} setGridEnabled={setVGrid} gridSize={vGridSize} setVGridSize={setVGridSize}
        />
      </div>
    );
  }

  const Sidebar = (
    <div style={styles.sidebar}>
      <style>{`
        .eaaJumpLine { background: rgba(0, 234, 255, 0.14) !important; border-left: 3px solid rgba(0, 234, 255, 0.90) !important; }
        .eaaJumpBlock { background: rgba(0, 234, 255, 0.06) !important; border-left: 3px solid rgba(0, 234, 255, 0.35) !important; }
      `}</style>

      <div style={styles.sidebarHeader}>Project Files</div>
      <div style={styles.fileList}>
        {htmlFiles.map((f) => (
          <div key={f.name} style={styles.fileItem(f.name === htmlActive)} onClick={() => setHtmlActive(f.name)}>
            <Icons.File /> {f.name}
          </div>
        ))}
      </div>

      <div style={styles.consoleWrap}>
        <div style={styles.consoleTop}>
          <div style={styles.consoleHeaderRow}>
            <div style={styles.consoleTitleRow}>
              <button style={styles.miniBtn} onClick={() => setConsoleCollapsed((c) => !c)} title={consoleCollapsed ? "Expand" : "Collapse"}>
                {consoleCollapsed ? <Icons.ChevronRight /> : <Icons.ChevronDown />}
              </button>
              <div style={styles.consoleTitle}>
                {consoleView === "console" ? `Console (${counts.console})` : `Network (${counts.network})`}
                {consolePaused ? " — PAUSED" : ""}
              </div>
            </div>
          </div>
          <div style={styles.consoleTabsPill}>
            <button style={styles.consoleTabBtn(consoleView === "console")} onClick={() => setConsoleView("console")} title="Console">
              <span>Console</span>
            </button>
            <button style={styles.consoleTabBtn(consoleView === "network")} onClick={() => setConsoleView("network")} title="Network">
              <span>Network</span>
            </button>
          </div>
          <div style={styles.consoleBtns}>
            <button style={styles.actionBtn(consolePaused)} onClick={() => setConsolePaused((p) => !p)} title="Pause/Resume">{consolePaused ? "Resume" : "Pause"}</button>
            <button style={styles.actionBtn(false)} onClick={() => setConsoleEntries([])} title="Clear console">Clear</button>
            <button style={styles.pillBtn(showLog, "log")} onClick={() => setShowLog((v) => !v)} title="Toggle logs">LOG</button>
            <button style={styles.pillBtn(showWarn, "warn")} onClick={() => setShowWarn((v) => !v)} title="Toggle warnings">WARN</button>
            <button style={styles.pillBtn(showError, "error")} onClick={() => setShowError((v) => !v)} title="Toggle errors">ERROR</button>
          </div>
        </div>

        {!consoleCollapsed && (
          <div ref={consoleScrollRef} style={styles.consoleList}>
            {filteredEntries.length === 0 ? (
              <div style={{ color: "#94a3b8", fontSize: 12, fontWeight: 800, opacity: 0.9 }}>No console output yet.</div>
            ) : (
              filteredEntries.map((e) => {
                const clickable = !!resolveJump(e);
                return (
                  <div key={e.id} style={styles.entry(e.kind, clickable)} onClick={() => clickable && jumpToEntry(e)} title={clickable ? "Click to jump to source" : undefined}>
                    <div style={styles.entryHead}>
                      <div style={styles.entryLabel}>
                        <span>{emojiFor(e.kind, e.label, e.tag)}</span>
                        <span style={{ textTransform: "uppercase" }}>{e.label}</span>
                        {e.tag ? (<span style={{ fontSize: 10, fontWeight: 1000, color: "#94a3b8", opacity: 0.9 }}>({e.tag})</span>) : null}
                      </div>
                      <div style={styles.entryTime}>{new Date(e.ts).toLocaleTimeString()}</div>
                    </div>
                    <div style={styles.entryBody}>{e.text || "(no message)"}</div>
                    {(e.where || e.stack) && (<div style={styles.entryMeta}>{e.where ? `at ${e.where}\n` : ""}{e.stack ? e.stack : ""}</div>)}
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>

      <div style={{ padding: 10, borderTop: "1px solid #1d2836" }}>
        <button style={styles.actionBtn()} onClick={addHtmlFile}>+ File</button>
        <button style={{ ...styles.actionBtn(), marginLeft: 8, color: "#ff5f56" }} onClick={deleteHtmlFile}>Del</button>
      </div>
    </div>
  );

  return (
    <div style={styles.root}>
      <div style={styles.toolbar}>
        <div style={styles.toolbarGroup}>
          <span style={styles.fileName}>{htmlActiveFile.name}</span>
          <span style={styles.fileBadge}>{lang}</span>
        </div>
        <div style={styles.toolbarGroup}>
          <div style={styles.togglePill}>
            <button style={styles.viewportBtn(htmlViewport === "phone")} onClick={() => setHtmlViewport("phone")}>PHONE</button>
            <button style={styles.viewportBtn(htmlViewport === "tablet")} onClick={() => setHtmlViewport("tablet")}>TABLET</button>
            <button style={styles.viewportBtn(htmlViewport === "windows")} onClick={() => setHtmlViewport("windows")}>WINDOWS</button>
            <button style={styles.viewportBtn(htmlViewport === "fit")} onClick={() => setHtmlViewport("fit")}>FIT</button>
          </div>
        </div>
        <div style={styles.togglePill}>
          <button style={styles.toggleBtn(activeTab === "code")} onClick={() => setActiveTab("code")}><Icons.Code /> Code</button>
          <button style={styles.toggleBtn(activeTab === "preview")} onClick={() => setActiveTab("preview")}><Icons.Play /> Preview</button>
        </div>
      </div>

      <div style={styles.contentArea}>
        <div style={styles.codeLayout}>
          {Sidebar}
          <div style={styles.editorPane}>
            {activeTab === "code" ? (
              <>
                <div style={styles.actionsBar}>
                  
                  {/* NEW LOGIC: If Python, show RUN. If HTML/Doc, show Auto-Render */}
                  {isPython ? (
                    <button 
                      style={{ ...styles.actionBtn(false), color: "#facc15", borderColor: "rgba(250, 204, 21, 0.4)" }} 
                      onClick={manualRender}
                      title="Run Python Script"
                    >
                      <Icons.Play /> RUN SCRIPT
                    </button>
                  ) : (
                    <>
                      <button style={styles.actionBtn(htmlAuto)} onClick={() => setHtmlAuto(!htmlAuto)}>
                        Auto-Render: {htmlAuto ? "ON" : "OFF"}
                      </button>
                      {!htmlAuto && (
                        <button style={styles.actionBtn()} onClick={manualRender}>
                          Render Now
                        </button>
                      )}
                    </>
                  )}

                  {/* INSPECT BUTTON */}
                  <div style={{ marginLeft: 8, borderLeft: "1px solid #1d2836", paddingLeft: 8 }}>
                    <button 
                      style={styles.actionBtn(inspectMode)} 
                      onClick={() => setInspectMode(!inspectMode)}
                      title="Inspect Element (Click in preview to jump to code)"
                    >
                      <Icons.Search /> Inspect
                    </button>
                  </div>

                  <div style={{ flex: 1 }} />
                  <button style={styles.actionBtn(htmlSplitPreview)} onClick={() => setHtmlSplitPreview(!htmlSplitPreview)}>Split View {htmlSplitPreview ? "ON" : "OFF"}</button>
                </div>

                <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 0, minWidth: 0 }}>
                  <div style={{ minWidth: 0, display: "flex", flexDirection: "column", flex: htmlSplitPreview && isWindows ? "0 0 20%" : "1 1 0", maxWidth: htmlSplitPreview && isWindows ? 520 : undefined, minHeight: 0 }}>
                    <Editor
                      value={htmlActiveFile.content}
                      language={lang}
                      theme="vs-dark"
                      onChange={(v) => updateActiveHtmlContent(v ?? "")}
                      onMount={(editor, monaco) => { editorRef.current = editor; monacoRef.current = monaco; }}
                      options={{ minimap: { enabled: false }, fontSize: 13, fontFamily: "'JetBrains Mono', Consolas, monospace", wordWrap: "on", smoothScrolling: true, automaticLayout: true, tabSize: 2, padding: { top: 16 } }}
                    />
                  </div>
                  {htmlSplitPreview && (
                    <div style={{ minWidth: 0, borderLeft: "1px solid #1d2836", backgroundColor: "#080b10", backgroundImage: "radial-gradient(#1d2836 1px, transparent 1px)", backgroundSize: "20px 20px", overflow: "hidden", padding: 14, display: "flex", justifyContent: isWindows ? "stretch" : "center", alignItems: isWindows ? "stretch" : "center", flex: isWindows ? "1 1 0" : undefined, flexBasis: !isWindows ? (vw ? `${vw + 40}px` : "50%") : undefined, maxWidth: !isWindows ? "60%" : undefined }}>
                      <iframe title="Split Preview" sandbox="allow-scripts allow-forms allow-modals allow-popups" style={isWindows ? { flex: 1, width: "100%", height: "100%", border: "2px solid #00eaff", borderRadius: 12, background: "#fff", boxShadow: "0 0 30px rgba(0, 234, 255, 0.15)", overflow: "hidden" } : { width: vw ? `${vw}px` : "100%", height: vw ? "90%" : "100%", border: vw ? "2px solid #00eaff" : "0", background: "#fff", borderRadius: vw ? 8 : 0, boxShadow: vw ? "0 0 30px rgba(0, 234, 255, 0.15)" : "none", transition: "all 0.3s", flexShrink: 1 }} srcDoc={htmlRendered} />
                    </div>
                  )}
                </div>
              </>
            ) : (
              <CanvasPreview />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}