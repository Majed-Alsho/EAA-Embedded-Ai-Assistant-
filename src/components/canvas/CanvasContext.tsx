// src/components/canvas/CanvasContext.tsx
import React, {
  createContext,
  forwardRef,
  useContext,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  buildHtmlProject,
  createDefaultHtmlProject,
  getFile,
  HtmlProjectFile,
  removeFile,
  setFileContent,
} from "./htmlProject";
import { buildDocProject, createDefaultDocProject } from "./docProject";
import { buildPythonProject, createDefaultPythonProject } from "./pythonProject";
import { safeParseLayout, uid, VLayout } from "./VisualCanvas";

// ==========================================
// Phase 1: The Universal Artifact Model
// ==========================================
export type ArtifactType = "html" | "visual" | "python" | "doc";

export type Artifact = {
  id: string;
  type: ArtifactType;
  title: string;
  lastModified: number;
  
  files: HtmlProjectFile[];
  activeFile: string;
  rendered: string;
  
  autoRender: boolean;
  viewport: HtmlViewport;
};

export type CanvasMode = "visual" | "html"; 
export type HtmlViewport = "fit" | "phone" | "tablet" | "windows";

export type CanvasApi = {
  showDefaultMock: () => void;
  setMode: (m: CanvasMode) => void;
  // BRIDGE METHODS
  getActiveCode: () => string;
  setActiveCode: (code: string) => void;
  getActiveFileName: () => string;
  // NAVIGATION
  getFileNames: () => string[];
  switchToFile: (name: string) => void;
  addFile: (name: string, content: string) => void;
  // NEW: GOD MODE (See everything)
  getAllFiles: () => HtmlProjectFile[];
};

type CanvasCtx = {
  canvasMode: CanvasMode;
  setCanvasMode: (m: CanvasMode) => void;

  // Artifact Management
  artifacts: Artifact[];
  activeArtifactId: string;
  createArtifact: (type: ArtifactType, title?: string) => void;
  switchArtifact: (id: string) => void;
  deleteArtifact: (id: string) => void;
  updateArtifactTitle: (id: string, title: string) => void;

  // Compat Shim
  DEFAULT_HTML_FILES: HtmlProjectFile[];
  htmlFiles: HtmlProjectFile[];
  setHtmlFiles: (action: React.SetStateAction<HtmlProjectFile[]>) => void;
  htmlActive: string;
  setHtmlActive: (n: string) => void;
  htmlAuto: boolean;
  setHtmlAuto: (b: boolean) => void;
  htmlDirty: boolean;
  setHtmlDirty: (b: boolean) => void;
  htmlRendered: string;
  setHtmlRendered: (s: string) => void;
  htmlSplitPreview: boolean;
  setHtmlSplitPreview: (b: boolean) => void;
  htmlActiveFile: HtmlProjectFile;
  htmlViewport: HtmlViewport;
  setHtmlViewport: (v: HtmlViewport) => void;
  updateActiveHtmlContent: (newText: string) => void;
  addHtmlFile: () => void;
  deleteHtmlFile: () => void;
  resetHtmlProject: () => void;
  manualRender: () => void;
  softCleanActiveFile: () => void;

  // Visual Canvas
  vLayout: VLayout;
  setVLayout: React.Dispatch<React.SetStateAction<VLayout>>;
  vTestMode: boolean;
  setVTestMode: (b: boolean) => void;
  vSnap: boolean;
  setVSnap: (b: boolean) => void;
  vGrid: boolean;
  setVGrid: (b: boolean) => void;
  vGridSize: number;
  setVGridSize: (n: number) => void;
  vRelPath: string;
  setVRelPath: (s: string) => void;
  vLiveSync: boolean;
  setVLiveSync: (b: boolean) => void;
  vPollMs: number;
  setVPollMs: (n: number) => void;
  saveLayoutToFile: () => Promise<void>;
  loadLayoutFromFile: (reason?: string) => Promise<void>;
  logLine: (s: string) => void;
};

const Ctx = createContext<CanvasCtx | null>(null);

export function useCanvas() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCanvas must be used under <CanvasProvider>");
  return v;
}

function clamp(n: number, a: number, b: number) {
  return Math.max(a, Math.min(b, n));
}

function extractReadFileBody(readOut: string): string {
  const endMarker = "\n===== end file =====";
  const end = readOut.lastIndexOf(endMarker);
  if (end < 0) return readOut;
  const firstNl = readOut.indexOf("\n");
  if (firstNl < 0) return readOut;
  return readOut.slice(firstNl + 1, end);
}

function createNewArtifact(type: ArtifactType, title: string): Artifact {
  let files = createDefaultHtmlProject();
  let activeFile = "index.html";
  let rendered = "";

  if (type === "doc") {
    files = createDefaultDocProject();
    activeFile = "plan.md";
    rendered = buildDocProject(files);
  } else if (type === "python") {
    files = createDefaultPythonProject();
    activeFile = "main.py";
    rendered = buildPythonProject(files);
  } else {
    rendered = buildHtmlProject(files);
  }

  return {
    id: uid(),
    type,
    title,
    lastModified: Date.now(),
    files,
    activeFile,
    rendered,
    autoRender: type === "html",
    viewport: type === "phone" ? "phone" : "windows"
  };
}

const STATE_FILE = "canvas_state_v1.json";

export const CanvasProvider = forwardRef<
  CanvasApi,
  { logLine: (s: string) => void; children: React.ReactNode }
>(function CanvasProvider({ logLine, children }, ref) {
  
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("html");
  const [htmlSplitPreview, setHtmlSplitPreview] = useState<boolean>(false);
  const [isLoaded, setIsLoaded] = useState(false);

  const [artifacts, setArtifacts] = useState<Artifact[]>(() => [
    createNewArtifact("html", "My First App")
  ]);
  const [activeArtifactId, setActiveArtifactId] = useState<string>(() => artifacts[0].id);

  // 1. LOAD on Mount
  useEffect(() => {
    async function loadState() {
      try {
        const raw = await invoke<string>("eaa_read_file", { relPath: STATE_FILE });
        const body = extractReadFileBody(raw);
        if (!body) throw new Error("Empty state file");
        
        const data = JSON.parse(body);
        if (data && Array.isArray(data.artifacts) && data.artifacts.length > 0) {
          setArtifacts(data.artifacts);
          if (data.activeArtifactId) {
            setActiveArtifactId(data.activeArtifactId);
          } else {
            setActiveArtifactId(data.artifacts[0].id);
          }
          logLine("[system] Loaded canvas state from disk.");
        }
      } catch (err) {
        logLine("[system] No previous state found (or failed to load). Starting fresh.");
      } finally {
        setIsLoaded(true); 
      }
    }
    loadState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. SAVE on Change (Debounced)
  useEffect(() => {
    if (!isLoaded) return; 

    const t = setTimeout(() => {
      const state = {
        activeArtifactId,
        artifacts
      };
      invoke("eaa_write_file", { 
        relPath: STATE_FILE, 
        content: JSON.stringify(state, null, 2) 
      }).catch(err => console.error("Auto-save failed", err));
    }, 1000); 

    return () => clearTimeout(t);
  }, [artifacts, activeArtifactId, isLoaded]);


  const activeArt = useMemo(() => 
    artifacts.find(a => a.id === activeArtifactId) || artifacts[0], 
  [artifacts, activeArtifactId]);

  function updateActiveArtifact(patch: Partial<Artifact> | ((prev: Artifact) => Partial<Artifact>)) {
    setArtifacts(prev => prev.map(a => {
      if (a.id !== activeArtifactId) return a;
      const changes = typeof patch === 'function' ? patch(a) : patch;
      return { ...a, ...changes, lastModified: Date.now() };
    }));
  }

  function createArtifact(type: ArtifactType, title?: string) {
    const newArt = createNewArtifact(type, title || "Untitled Project");
    setArtifacts(prev => [...prev, newArt]);
    setActiveArtifactId(newArt.id);
    logLine(`[system] Created new ${type} artifact: ${newArt.title}`);
  }

  function switchArtifact(id: string) {
    if (artifacts.some(a => a.id === id)) {
      setActiveArtifactId(id);
    }
  }

  function deleteArtifact(id: string) {
    if (artifacts.length <= 1) {
      logLine("[system] Cannot delete the last artifact.");
      return;
    }
    const idx = artifacts.findIndex(a => a.id === id);
    if (idx === -1) return;
    
    const art = artifacts[idx];
    if (!window.confirm(`Are you sure you want to delete "${art.title}"?`)) return;

    let newActive = activeArtifactId;
    if (id === activeArtifactId) {
      const fallback = artifacts[idx - 1] || artifacts[idx + 1];
      newActive = fallback.id;
    }

    setArtifacts(prev => prev.filter(a => a.id !== id));
    setActiveArtifactId(newActive);
    logLine(`[system] Deleted artifact: ${art.title}`);
  }

  function updateArtifactTitle(id: string, title: string) {
    setArtifacts(prev => prev.map(a => a.id === id ? { ...a, title } : a));
  }

  // Compat Proxies
  const DEFAULT_HTML_FILES = useMemo(() => createDefaultHtmlProject(), []);
  const htmlFiles = activeArt.files;
  
  function setHtmlFilesCompat(action: React.SetStateAction<HtmlProjectFile[]>) {
    updateActiveArtifact(prevArt => {
      const newFiles = typeof action === 'function' ? action(prevArt.files) : action;
      return { files: newFiles };
    });
  }

  const htmlActive = activeArt.activeFile;
  function setHtmlActive(n: string) { updateActiveArtifact({ activeFile: n }); }

  const htmlAuto = activeArt.autoRender;
  function setHtmlAuto(b: boolean) { updateActiveArtifact({ autoRender: b }); }

  const htmlRendered = activeArt.rendered;
  function setHtmlRendered(s: string) { updateActiveArtifact({ rendered: s }); }

  const htmlViewport = activeArt.viewport;
  function setHtmlViewport(v: HtmlViewport) { updateActiveArtifact({ viewport: v }); }

  const htmlDirty = false; 
  function setHtmlDirty(b: boolean) { }

  const htmlActiveFile = useMemo(() => {
    const f = getFile(htmlFiles, htmlActive);
    return f ?? htmlFiles[0] ?? { name: "index.html", content: "" };
  }, [htmlFiles, htmlActive]);

  // ==========================================
  // AUTO RENDER LOGIC
  // ==========================================
  useEffect(() => {
    if (activeArt.type === 'doc') {
      setHtmlRendered(buildDocProject(htmlFiles));
    } else if (activeArt.type === 'python') {
      setHtmlRendered(buildPythonProject(htmlFiles));
    } else {
      setHtmlRendered(buildHtmlProject(htmlFiles));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeArt.id, isLoaded]); 

  useEffect(() => {
    if (canvasMode !== "html") return;
    if (!htmlAuto) return;

    const t = window.setTimeout(() => {
      let out = "";
      if (activeArt.type === 'doc') {
        out = buildDocProject(htmlFiles);
      } else if (activeArt.type === 'python') {
        return; 
      } else {
        out = buildHtmlProject(htmlFiles);
      }

      if (out !== htmlRendered) {
        setHtmlRendered(out);
      }
    }, 200);

    return () => window.clearTimeout(t);
  }, [canvasMode, htmlAuto, htmlFiles, htmlRendered, activeArt.type]);

  function updateActiveHtmlContent(newText: string) {
    setHtmlFilesCompat((prev) => setFileContent(prev, htmlActiveFile.name, newText));
  }

  function addHtmlFile() {
    const name = window.prompt("New file name:", activeArt.type === 'python' ? 'utils.py' : 'page.html');
    if (!name) return;
    const trimmed = name.trim();
    if (getFile(htmlFiles, trimmed)) return;
    setHtmlFilesCompat((prev) => [...prev, { name: trimmed, content: "" }]);
    setHtmlActive(trimmed);
  }

  function deleteHtmlFile() {
    const name = htmlActiveFile.name;
    if (name === "index.html" || name === "plan.md" || name === "main.py") return; 
    if (!window.confirm(`Delete ${name}?`)) return;
    const next = removeFile(htmlFiles, name);
    setHtmlFilesCompat(next);
    setHtmlActive(next[0]?.name ?? "index.html");
  }

  function resetHtmlProject() {
    if (!window.confirm("Reset project?")) return;
    if (activeArt.type === 'doc') {
        const defs = createDefaultDocProject();
        updateActiveArtifact({ files: defs, activeFile: "plan.md", rendered: buildDocProject(defs) });
    } else if (activeArt.type === 'python') {
        const defs = createDefaultPythonProject();
        updateActiveArtifact({ files: defs, activeFile: "main.py", rendered: buildPythonProject(defs) });
    } else {
        const defs = createDefaultHtmlProject();
        updateActiveArtifact({ files: defs, activeFile: "index.html", rendered: buildHtmlProject(defs) });
    }
  }

  function softCleanActiveFile() { /* ... */ }
  
  async function manualRender() {
    if (activeArt.type === 'python') {
        logLine("[python] Running script...");
        setHtmlRendered(`
          <html><body style="background:#0d1117;color:#8b949e;font-family:monospace;padding:20px;">
          <div>Running...</div>
          </body></html>
        `);

        try {
          const code = htmlActiveFile.content;
          const output = await invoke<string>("eaa_run_python", { code });
          logLine(output); 
          setHtmlRendered(`
            <html><body style="background:#0d1117;color:#e6edf3;font-family:monospace;padding:20px;">
            <div style="opacity:0.6;margin-bottom:10px;font-size:12px;">EXIT CODE: 0</div>
            <pre style="white-space:pre-wrap;">${output}</pre>
            </body></html>
          `);
        } catch (err) {
          const msg = String(err);
          logLine(`[python] Error: ${msg}`);
          setHtmlRendered(`
            <html><body style="background:#0d1117;color:#ff5f56;font-family:monospace;padding:20px;">
            <div style="font-weight:bold;margin-bottom:10px;">EXECUTION FAILED</div>
            <pre style="white-space:pre-wrap;">${msg}</pre>
            </body></html>
          `);
        }
        return;
    }

    let out = "";
    if (activeArt.type === 'doc') out = buildDocProject(htmlFiles);
    else out = buildHtmlProject(htmlFiles);
    setHtmlRendered(out);
    logLine(`[html] Rendered (${htmlFiles.length} files)`);
  }

  // Visual Canvas
  const [vLayout, setVLayout] = useState<VLayout>(() => ({
    version: 1, items: [ { id: uid(), type: "card", text: "Visual Canvas", x: 120, y: 180, w: 520, h: 180 } ]
  }));
  const [vTestMode, setVTestMode] = useState(false);
  const [vSnap, setVSnap] = useState(true);
  const [vGrid, setVGrid] = useState(true);
  const [vGridSize, setVGridSize] = useState(16);
  const [vRelPath, setVRelPath] = useState("EAA_Sandbox/public/eaa_canvas_layout.json");
  const [vLiveSync, setVLiveSync] = useState(true);
  const [vPollMs, setVPollMs] = useState(800);
  const lastFileJsonRef = useRef<string>("");
  const lastPollErrAtRef = useRef<number>(0);
  const lastPollErrMsgRef = useRef<string>("");

  async function saveLayoutToFile() { 
    const rel = vRelPath.trim();
    if (!rel) return;
    try {
      const out = JSON.stringify(vLayout, null, 2);
      await invoke<string>("eaa_write_file", { relPath: rel, content: out });
      lastFileJsonRef.current = out;
    } catch (err) { logLine(`[error] ${String(err)}`); }
  }
  
  async function loadLayoutFromFile(reason?: string) {
    const rel = vRelPath.trim();
    if (!rel) return;
    try {
      const readOut = await invoke<string>("eaa_read_file", { relPath: rel });
      const body = extractReadFileBody(String(readOut ?? ""));
      const cleaned = safeParseLayout(body);
      setVLayout(cleaned);
      lastFileJsonRef.current = JSON.stringify(cleaned, null, 2);
    } catch (err) { /* ignore */ }
  }
  
  useEffect(() => {
    if (!vLiveSync || canvasMode !== "visual") return;
    const t = setInterval(() => void loadLayoutFromFile("poll"), clamp(vPollMs, 200, 5000));
    return () => clearInterval(t);
  }, [vLiveSync, vPollMs, vRelPath, canvasMode]);

  // ==========================================
  // THE BRIDGE: EXPOSING METHODS TO PARENT
  // ==========================================
  
  const activeFileRef = useRef(htmlActiveFile);
  const filesRef = useRef(htmlFiles);
  useEffect(() => { activeFileRef.current = htmlActiveFile; }, [htmlActiveFile]);
  useEffect(() => { filesRef.current = htmlFiles; }, [htmlFiles]);

  // Refs for setters
  const updateContentRef = useRef(updateActiveHtmlContent);
  const setHtmlActiveRef = useRef(setHtmlActive);
  const setHtmlFilesRef = useRef(setHtmlFilesCompat);

  useEffect(() => { updateContentRef.current = updateActiveHtmlContent; }, [updateActiveHtmlContent]);
  useEffect(() => { setHtmlActiveRef.current = setHtmlActive; }, [setHtmlActive]);
  useEffect(() => { setHtmlFilesRef.current = setHtmlFilesCompat; }, [setHtmlFilesCompat]);

  useImperativeHandle(ref, () => ({
    showDefaultMock() { createArtifact("html", "Default Mock"); },
    setMode(m: CanvasMode) { setCanvasMode(m); },
    
    getActiveCode: () => activeFileRef.current.content,
    getActiveFileName: () => activeFileRef.current.name,
    setActiveCode: (code: string) => updateContentRef.current(code),

    getFileNames: () => filesRef.current.map(f => f.name),
    switchToFile: (name: string) => {
        if (filesRef.current.some(f => f.name === name)) {
            setHtmlActiveRef.current(name);
        }
    },
    addFile: (name: string, content: string) => {
        setHtmlFilesRef.current(prev => {
            if (getFile(prev, name)) return prev;
            return [...prev, { name, content }];
        });
        setHtmlActiveRef.current(name); 
    },
    
    // NEW: GOD MODE (Get All Files)
    getAllFiles: () => filesRef.current,
  }));

  const value: CanvasCtx = {
    canvasMode, setCanvasMode,
    artifacts, activeArtifactId, createArtifact, switchArtifact, deleteArtifact, updateArtifactTitle,
    DEFAULT_HTML_FILES, htmlFiles, setHtmlFiles: setHtmlFilesCompat, htmlActive, setHtmlActive, htmlAuto, setHtmlAuto, htmlDirty, setHtmlDirty, htmlRendered, setHtmlRendered, htmlSplitPreview, setHtmlSplitPreview, htmlActiveFile, htmlViewport, setHtmlViewport,
    updateActiveHtmlContent, addHtmlFile, deleteHtmlFile, resetHtmlProject, manualRender, softCleanActiveFile,
    vLayout, setVLayout, vTestMode, setVTestMode, vSnap, setVSnap, vGrid, setVGrid, vGridSize, setVGridSize, vRelPath, setVRelPath, vLiveSync, setVLiveSync, vPollMs, setVPollMs, saveLayoutToFile, loadLayoutFromFile, logLine,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
});

export function CanvasModeButtons() {
  const { canvasMode, setCanvasMode, activeArtifactId, artifacts, switchArtifact, createArtifact, deleteArtifact, updateArtifactTitle } = useCanvas();

  const btn = (active: boolean): React.CSSProperties => ({
    padding: "6px 12px", borderRadius: 8, border: "none", background: active ? "#1d2836" : "transparent", color: active ? "#00eaff" : "#94a3b8", cursor: "pointer", fontSize: 13, fontWeight: 600, transition: "all 0.2s", boxShadow: active ? "0 0 10px rgba(0, 234, 255, 0.2)" : "none", display: "flex", alignItems: "center", gap: 6
  });

  const activeArt = artifacts.find(a => a.id === activeArtifactId);

  const handleRename = () => {
    if (!activeArt) return;
    const newTitle = window.prompt("Rename project:", activeArt.title);
    if (newTitle && newTitle.trim()) {
      updateArtifactTitle(activeArt.id, newTitle.trim());
    }
  };

  return (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <div style={{ display: "flex", gap: 4, background: "#0b1015", borderRadius: 10, padding: 4, border: "1px solid #1d2836" }}>
        <button style={btn(canvasMode === "html")} onClick={() => setCanvasMode("html")}>Code</button>
        <button style={btn(canvasMode === "visual")} onClick={() => setCanvasMode("visual")}>Visual</button>
      </div>

      {canvasMode === "html" && (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <div style={{ height: 20, width: 1, background: "#1d2836" }} />
            
            <select 
                value={activeArtifactId} 
                onChange={(e) => switchArtifact(e.target.value)}
                style={{ background: "#0b1015", color: "#e6edf3", border: "1px solid #1d2836", borderRadius: 6, padding: "4px 8px", fontSize: 12, maxWidth: 150 }}
            >
                {artifacts.map(a => <option key={a.id} value={a.id}>{a.title} ({a.type})</option>)}
            </select>

            <button 
                onClick={handleRename}
                style={{ ...btn(false), fontSize: 10, padding: "4px 8px" }}
                title="Rename Project"
            >
                ✏️
            </button>

            <button onClick={() => createArtifact("html", `Web App ${artifacts.length + 1}`)} style={{ ...btn(false), fontSize: 10, padding: "4px 8px" }} title="New Website">
                +WEB
            </button>
            <button onClick={() => createArtifact("doc", `Doc ${artifacts.length + 1}`)} style={{ ...btn(false), fontSize: 10, padding: "4px 8px" }} title="New Document">
                +DOC
            </button>
            <button onClick={() => createArtifact("python", `Script ${artifacts.length + 1}`)} style={{ ...btn(false), color: "#facc15", fontSize: 10, padding: "4px 8px" }} title="New Python Script">
                +PY
            </button>

            <button 
                onClick={() => deleteArtifact(activeArtifactId)}
                style={{ ...btn(false), color: "#ff5f56", fontSize: 10, padding: "4px 8px", marginLeft: 4 }}
                title="Delete Current Project"
            >
                DEL
            </button>
        </div>
      )}
    </div>
  );
}