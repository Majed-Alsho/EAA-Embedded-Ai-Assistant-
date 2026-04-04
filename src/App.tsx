import React, { useMemo, useRef, useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

// ✅ Import the logo
import logoImg from "./assets/logo.png";

// Hooks
import { useComfyBridge } from "./hooks/useComfyBridge";
import { useAI } from "./hooks/useAI";

// Tool Panels
import { LogsPanel } from "./components/tools/Logs/LogsPanel";
import { WorkspacePanel } from "./components/tools/Workspace/WorkspacePanel";
import { ReadPanel } from "./components/tools/Read/ReadPanel";
import { WritePanel } from "./components/tools/Write/WritePanel";
import { PatchPanel } from "./components/tools/Patch/PatchPanel";
import { MediaPanel } from "./components/tools/Media/MediaPanel";

// Canvas
import { CanvasProvider, CanvasApi, CanvasModeButtons } from "./components/canvas/CanvasContext";
import { CanvasPreview } from "./components/canvas/CanvasPreview";
import { CanvasEditor } from "./components/canvas/CanvasEditor";

// ✅ Import Connection Hub
import ConnectionHub from "./components/ConnectionHub";

type ToolsMode = "off" | "ask" | "auto";
type RightTab = | "preview" | "canvas" | "logs" | "read" | "workspace" | "write" | "patch" | "media";
type ActionKind = "canvas" | "tool";
type SuggestedAction = { id: string; label: string; kind: ActionKind };
type ChatMessage = { id: number; role: "user" | "ai" | "system"; text: string; model?: string; hasCode?: boolean; };

// ✅ NEW: Type for a Chat Session
type ChatSession = { id: string; name: string; messages: ChatMessage[]; };
// Simple ID generator
const generateId = () => '_' + Math.random().toString(36).substr(2, 9);

// --- ⚡ VISUAL: Background Lightning Effect Component ---
const NeuralStorm = ({ active }: { active: boolean }) => (
  <div className={`neural-storm ${active ? "storm-active" : ""}`}>
    <div className="storm-layer nebula"></div>
    <div className="storm-layer grid-overlay"></div>
    <div className="storm-layer light-beam"></div>
    <div className="storm-layer particulate-matter"></div>
  </div>
);

export default function App() {
  const [toolsMode, setToolsMode] = useState<ToolsMode>("ask");
  const [rightTab, setRightTab] = useState<RightTab>("canvas");
  
  // ✅ STATE FLOW: Loading (isBusy=true) -> Hub (showHub=true) -> App
  const [isBusy, setIsBusy] = useState(true);
  const [showHub, setShowHub] = useState(false);

  const [rightFullscreen, setRightFullscreen] = useState(false);
  const [defaultToolPath, setDefaultToolPath] = useState<string>("EAA_Sandbox/src/SandboxApp.tsx");
  const canvasRef = useRef<CanvasApi | null>(null);
  const appContainerRef = useRef<HTMLDivElement>(null); // ✅ REF FOR MOUSE TRACKING

  const [inputVal, setInputVal] = useState("");

  // ✅ UPDATED: State for managing multiple chat sessions
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([
      { id: 'default', name: 'New Project', messages: [{ id: 1, role: "system", text: "EAA Neural Interface Online." }] }
  ]);
  const [activeChatId, setActiveChatId] = useState<string>('default');

  // ✅ NEW: Ref for the chat container to control scrolling
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // ✅ NEW: MOUSE TRACKING FOR ALIVE EFFECT
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
        if (!appContainerRef.current) return;
        const x = e.clientX / window.innerWidth;
        const y = e.clientY / window.innerHeight;
        appContainerRef.current.style.setProperty('--mouse-x', x.toString());
        appContainerRef.current.style.setProperty('--mouse-y', y.toString());
    };
    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  // ✅ NEW: Get messages for the currently active chat
  const activeMessages = useMemo(() => {
      return chatSessions.find(c => c.id === activeChatId)?.messages || [];
  }, [chatSessions, activeChatId]);

  // ✅ NEW: Function to scroll to the bottom of the chat
  const scrollToBottom = useCallback(() => {
      if (chatContainerRef.current) {
          chatContainerRef.current.scrollTo({ top: chatContainerRef.current.scrollHeight, behavior: 'smooth' });
      }
  }, []);

  // ✅ NEW: Automatically scroll when messages change
  useEffect(() => { scrollToBottom(); }, [activeMessages, scrollToBottom]);

  // ✅ NEW: Functions to create and delete chat sessions
  const createNewChat = () => {
      const newId = generateId();
      const newChat: ChatSession = {
          id: newId,
          name: `Project ${chatSessions.length + 1}`,
          messages: [{ id: Date.now(), role: "system", text: "EAA Neural Interface Online." }]
      };
      setChatSessions(prev => [...prev, newChat]);
      setActiveChatId(newId);
  };

  const deleteChat = (idToDelete: string, e: React.MouseEvent) => {
      e.stopPropagation(); // Stop click from selecting the chat
      setChatSessions(prev => {
          const filtered = prev.filter(c => c.id !== idToDelete);
          // If active chat is deleted, switch to another one
          if (idToDelete === activeChatId) setActiveChatId(filtered.length > 0 ? filtered[0].id : '');
          return filtered;
      });
      // Always keep at least one chat
      if (chatSessions.length <= 1) createNewChat();
  };

  // VAD & Media states (kept exactly as you had them)
  const [voiceMode, setVoiceMode] = useState(false);
  const voiceModeRef = useRef(false);
  const [micStatus, setMicStatus] = useState<"idle" | "listening" | "processing">("idle");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<BlobPart[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  const [logs, setLogs] = useState<string>("Initializing neural pathways...\n");
  function logLine(s: string) { setLogs((x) => x + s + (s.endsWith("\n") ? "" : "\n")); }

  const { generate, isGenerating } = useAI(logLine);
  const WORKFLOW_PATHS = useMemo(() => [
      { id: "ltx_text_to_img", label: "LTX — Text → Image", path: String.raw`C:\Users\offic\EAA\ltx_picture_no_picture_workflow.json` },
  ], []);
  const comfy = useComfyBridge({ logLine, workflows: WORKFLOW_PATHS });

  const suggestedActions = useMemo<SuggestedAction[]>(() => [
      { id: "canvas_show_mock", label: "Show UI", kind: "canvas" },
      { id: "list_workspace", label: "Files", kind: "tool" },
      { id: "open_logs", label: "Logs", kind: "tool" },
  ], []);

  // Auto-Connect Logic
  useEffect(() => {
    let attempts = 0;
    const checkBrainHealth = async () => {
      try {
        logLine(`[system] Connecting to Brain... (${attempts + 1})`);
        const dataStr = await invoke<string>("eaa_check_brain_health");
          const data = JSON.parse(dataStr);
          if (true) {
          if (data.status === "online") {
            // ✅ Success: Stop Loading, Show Hub
            setIsBusy(false);
            setShowHub(true);
            logLine("[system] 🟢 EAA Brain Connected.");
            return;
          }
        }
      } catch (e) {}
      attempts++;
      if (attempts < 60) setTimeout(checkBrainHealth, 1000);
      else {
          logLine("[error] 🔴 Brain unreachable.");
          // Still allow entrance to hub to debug
          setIsBusy(false);
          setShowHub(true);
      }
    };
    checkBrainHealth();
  }, []);

  // VAD Logic (kept exactly as you had it)
  async function startListeningLoop() {
    setMicStatus("listening");
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;
        const mediaRecorder = new MediaRecorder(stream);
        mediaRecorderRef.current = mediaRecorder;
        audioChunksRef.current = [];
        mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
        mediaRecorder.onstop = () => processAudioRecording();
        const audioCtx = new window.AudioContext();
        const analyser = audioCtx.createAnalyser();
        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(analyser);
        analyser.fftSize = 256;
        audioContextRef.current = audioCtx;
        analyserRef.current = analyser;
        sourceRef.current = source;
        mediaRecorder.start();
        monitorSilence(analyser);
    } catch (err) {
        setVoiceMode(false); voiceModeRef.current = false; setMicStatus("idle");
    }
  }

  function monitorSilence(analyser: AnalyserNode) {
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    let silenceStart = Date.now();
    let hasSpoken = false;
    const checkVolume = () => {
        if (!analyserRef.current) return; 
        analyser.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b) / dataArray.length;
        if (avg > 15) { silenceStart = Date.now(); hasSpoken = true; }
        if (voiceModeRef.current && hasSpoken && (Date.now() - silenceStart > 1500)) {
             if (mediaRecorderRef.current?.state === "recording") mediaRecorderRef.current.stop();
             if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
             return;
        }
        if (voiceModeRef.current) animationFrameRef.current = requestAnimationFrame(checkVolume);
    };
    checkVolume();
  }

  async function processAudioRecording() {
     setMicStatus("processing");
     if (streamRef.current) { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null; }
     if (audioContextRef.current) audioContextRef.current.close();
     const audioBlob = new Blob(audioChunksRef.current, { type: "audio/wav" });
     const formData = new FormData();
     formData.append("file", audioBlob, "voice_cmd.wav");
     try {
        const res = await fetch("http://127.0.0.1:8000/v1/audio/transcriptions", { method: "POST", body: formData });
        const data = await res.json();
        const text = data.text;
        if (text && !text.includes("[ERROR]") && text.trim().length > 0) {
            await handleSend(text, true);
            await new Promise(r => setTimeout(r, 2000));
        }
     } catch (err) { console.error(err); } finally {
        if (voiceModeRef.current) startListeningLoop(); else setMicStatus("idle");
     }
  }

  function toggleVoiceMode() {
      const nextState = !voiceMode;
      setVoiceMode(nextState);
      voiceModeRef.current = nextState;
      if (!nextState) {
          setMicStatus("idle");
          if (mediaRecorderRef.current?.state !== "inactive") mediaRecorderRef.current?.stop();
          if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
          if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      } else { startListeningLoop(); }
  }

  useEffect(() => {
      return () => {
          if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
          if (audioContextRef.current) audioContextRef.current.close();
          if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      }
  }, []);

  async function handleAction(a: SuggestedAction) {
    if (isBusy || showHub) return; // Prevent action in hub or load
    if (a.id === "canvas_show_mock") { setRightTab("canvas"); canvasRef.current?.showDefaultMock(); return; }
    if (a.id === "open_logs") { setRightTab("logs"); invoke("eaa_open_logs_folder"); return; }
    if (a.id === "run_tests") {
      setRightTab("logs");
      try { const out = await invoke<string>("eaa_run_tests"); logLine(out); } catch (err) { logLine(String(err)); }
      return;
    }
    if (a.id === "list_workspace") { setRightTab("workspace"); return; }
    setRightTab("logs");
  }

  // ✅ UPDATED: handleSend now updates the active chat session
  async function handleSend(overrideText?: string, useVoice: boolean = false) {
    const text = overrideText || inputVal.trim();
    if (!text) return;
    if (!activeChatId) createNewChat(); // Create a chat if none exists

    const userMsg: ChatMessage = { id: Date.now(), role: "user", text };
    // Add user message to the active session
    setChatSessions(prev => prev.map(s => s.id === activeChatId ? { ...s, messages: [...s.messages, userMsg] } : s));
    setInputVal("");

    const aiMsgId = Date.now() + 1;
    // Add AI placeholder to the active session
    setChatSessions(prev => prev.map(s => s.id === activeChatId ? { ...s, messages: [...s.messages, { id: aiMsgId, role: "ai", text: "", model: "..." }] } : s));
    
    // ... (Context preparation logic kept as is) ...
    const api = canvasRef.current;
    const files = api ? api.getAllFiles() : [];
    const activeName = api ? api.getActiveFileName() : "";
    const projectContext = files.map(f => `=== FILE: ${f.name} ${f.name === activeName ? "(Active)" : ""} ===\n${f.content}`).join("\n\n");
    const systemPrompt = `You are editing a project. FILES:\n${projectContext}\nUSER REQUEST: ${text}`;

    await fetch("http://127.0.0.1:8000/v1/chat/completions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: [{ role: "system", content: systemPrompt }, { role: "user", content: text }], stream: true, use_voice: useVoice })
    }).then(async (response) => {
        if (!response.body) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let fullText = "";
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            fullText += decoder.decode(value);
            // ✅ Update the specific message within the active session
            setChatSessions(prev => prev.map(s => 
                s.id === activeChatId 
                ? { ...s, messages: s.messages.map(m => m.id === aiMsgId ? { ...m, text: fullText, model: "EAA-v1", hasCode: fullText.includes("```") } : m) } 
                : s
            ));
        }
    });
  }

  function handleApplyCode(text: string) {
    // ... (kept exactly as you had it) ...
    const codeBlockMatch = text.match(/```(\w*)\n([\s\S]*?)```/);
    if (codeBlockMatch && codeBlockMatch[2]) {
        const lang = codeBlockMatch[1].toLowerCase().trim();
        const code = codeBlockMatch[2];
        const api = canvasRef.current;
        if (!api) return;
        if (lang === "python" || lang === "py") {
            const files = api.getFileNames();
            if (!files.includes("main.py")) { api.addFile("main.py", code); logLine("[bridge] Created main.py."); } 
            else { api.switchToFile("main.py"); api.setActiveCode(code); logLine("[bridge] Updated main.py."); }
        } else if (lang === "html") { api.switchToFile("index.html"); api.setActiveCode(code); logLine("[bridge] Updated index.html.");
        } else if (lang === "css") {
            const files = api.getFileNames();
            if (!files.includes("styles.css")) api.addFile("styles.css", "");
            api.switchToFile("styles.css"); api.setActiveCode(code); logLine("[bridge] Updated styles.css.");
        } else { api.setActiveCode(code); logLine(`[bridge] Updated ${api.getActiveFileName()}.`); }
    } else { logLine("[bridge] Could not parse code block."); }
  }

  const renderMessageContent = (msg: ChatMessage) => {
    // ... (kept exactly as you had it) ...
    if (msg.role !== "ai") return msg.text;
    let thinkMatch = msg.text.match(/<think>([\s\S]*?)(?:<\/think>|$)/i);
    if (!thinkMatch) thinkMatch = msg.text.match(/\(thinking\)\s*([\s\S]*?)(?=\n\n|\n[A-Z]|$)/i);
    const hasThought = !!thinkMatch;
    let cleanText = msg.text;
    if (hasThought) cleanText = msg.text.replace(thinkMatch![0], "").trim();
    return (
      <>
        {hasThought && (
          <details open className="thought-details" style={{ marginBottom: 12 }}>
            <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: "bold", color: "#818cf8", marginBottom: 6, userSelect: "none" }}>
              🧠 Thought Process
            </summary>
            <div className="thought-box">{thinkMatch![1].trim()}</div>
          </details>
        )}
        <div style={{ whiteSpace: "pre-wrap" }}>{cleanText || (hasThought ? "..." : msg.text)}</div>
      </>
    );
  };

  const tabsList = [
    { id: "preview", label: "Preview" }, { id: "canvas", label: "Canvas" }, { id: "logs", label: "Logs" },
    { id: "read", label: "Read" }, { id: "workspace", label: "Files" }, { id: "write", label: "Write" },
    { id: "patch", label: "Patch" }, { id: "media", label: "Media" },
  ] as const;

  // 1. LOADING SCREEN
  if (isBusy) {
    return (
        <div className="loading-screen" ref={appContainerRef}>
            <NeuralStorm active={true} />
            <img src={logoImg} className="loading-logo" alt="EAA Loading" />
            <div className="loading-bar-track"><div className="loading-bar-fill"></div></div>
            <h2 className="loading-text">SYSTEM INITIALIZATION</h2>
            <div className="loading-logs">
                {logs.split('\n').slice(-1)[0]}
            </div>
        </div>
    );
  }

  // 2. CONNECTION HUB (Selection Screen)
  if (showHub) {
      return (
          <div className="app-container">
            <NeuralStorm active={true} />
            <ConnectionHub onSelectLocal={() => setShowHub(false)} />
          </div>
      );
  }

  // 3. MAIN APP
  return (
    <div className={`app-container ${isGenerating ? "surged" : ""}`} ref={appContainerRef}>
      {/* Background Visual Layer */}
      <NeuralStorm active={isGenerating} />
      
      <div className="topbar">
        <div className="brand">
          <img src={logoImg} alt="EAA" className="brand-logo-small" />
          <div className="brand-text-col">
            <div className="brand-title">EAA FEDERATION</div>
            <div className="brand-sub">Neural Interface</div>
          </div>
        </div>
        <div className="mode-group">
          <button className={`mode-btn ${toolsMode === "off" ? "active" : ""}`} onClick={() => setToolsMode("off")}>OFF</button>
          <button className={`mode-btn ${toolsMode === "ask" ? "active" : ""}`} onClick={() => setToolsMode("ask")}>ASK</button>
          <button className={`mode-btn ${toolsMode === "auto" ? "active" : ""}`} onClick={() => setToolsMode("auto")}>AUTO</button>
        </div>
      </div>

      <div className="main-layout">
        {!rightFullscreen && (
          <aside className="sidebar-left glass-panel">
            {/* ✅ NEW: Sidebar Controls for New Chat */}
            <div className="sidebar-controls">
                <button className="sidebar-btn shimmer-btn" onClick={createNewChat}>+ New Project</button>
            </div>
            <div className="panel-header">Project History</div>
            {/* ✅ UPDATED: Chat List with active state and delete buttons */}
            <div className="left-list">
              {chatSessions.map(session => (
                  <div key={session.id} className={`chat-item ${session.id === activeChatId ? 'active' : ''}`} onClick={() => setActiveChatId(session.id)}>
                      <span style={{whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{session.name}</span>
                      <button className="delete-chat-btn" onClick={(e) => deleteChat(session.id, e)}>✕</button>
                  </div>
              ))}
            </div>
          </aside>
        )}

        {!rightFullscreen && (
          <main className="center-stage">
            {/* ✅ UPDATED: Chat container with ref for auto-scrolling */}
            <div className="chat-scroll" ref={chatContainerRef}>
              {activeMessages.map(m => (
                <div key={m.id} className={`msg-wrapper ${m.role === "user" ? "user" : "ai"}`}>
                    {m.role === "ai" && m.model && <div className="model-badge">{m.model.replace("EAA-", "")}</div>}
                    <div className={`bubble ${m.role === "user" ? "user" : "ai"}`}>
                        {renderMessageContent(m)}
                        {m.role === "ai" && m.hasCode && <button className="chip electric-chip" onClick={() => handleApplyCode(m.text)}>⚡ APPLY TO CANVAS</button>}
                    </div>
                </div>
              ))}
              {isGenerating && <div className="bubble ai pulse-animate" style={{ fontStyle: "italic", opacity: 0.7 }}>Thinking...</div>}
              {activeMessages.length === 1 && (
                  <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                    {suggestedActions.map((a) => <button key={a.id} className="chip" onClick={() => void handleAction(a)}>{a.label}</button>)}
                  </div>
              )}
            </div>
            
            <div className="input-dock glass-dock">
              <button className={`voice-btn ${voiceMode ? 'active' : ''} ${micStatus}`} onClick={toggleVoiceMode} title="Voice Mode" disabled={showHub}>
                  {voiceMode ? (micStatus === "listening" ? "●" : "...") : "🎙️"}
              </button>
              <input className="input-field electric-input" placeholder="Enter command..." value={inputVal} onChange={(e) => setInputVal(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && !isGenerating && !showHub && handleSend()} disabled={isGenerating || showHub} />
              <button className="send-btn neon-btn" onClick={() => handleSend()} disabled={isGenerating || showHub}>Send</button>
            </div>
          </main>
        )}

        <CanvasProvider ref={canvasRef} logLine={logLine}>
          <aside className={`sidebar-right ${rightFullscreen ? "fullscreen" : ""} glass-panel`}>
            <div className="tabs-container">
                {tabsList.map((t) => (
                    <button key={t.id} className={`tab-btn ${rightTab === t.id ? "active" : ""}`} onClick={() => setRightTab(t.id as RightTab)}>
                        {t.label}
                    </button>
                ))}
                <button className={`tab-btn ${rightFullscreen ? "active" : ""}`} onClick={() => setRightFullscreen(x => !x)} style={{marginLeft:"auto"}}>
                    {rightFullscreen ? "Exit" : "Full"}
                </button>
                <CanvasModeButtons />
            </div>
            <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              {rightTab === "preview" && <CanvasPreview />}
              {rightTab === "canvas" && <CanvasEditor onOpenPreview={() => setRightTab("preview")} />}
              {rightTab === "logs" && <LogsPanel logs={logs} setLogs={setLogs} isBusy={isBusy} setIsBusy={setIsBusy} logLine={logLine} />}
              {rightTab === "workspace" && (
                <WorkspacePanel
                  isBusy={isBusy}
                  setIsBusy={setIsBusy}
                  logLine={logLine}
                  onOpenFile={(p) => {
                    setDefaultToolPath(p);
                    setRightTab("read");
                  }}
                />
              )}
              {rightTab === "read" && <ReadPanel isBusy={isBusy} setIsBusy={setIsBusy} logLine={logLine} defaultPath={defaultToolPath} />}
              {rightTab === "write" && <WritePanel isBusy={isBusy} setIsBusy={setIsBusy} logLine={logLine} defaultPath={defaultToolPath} />}
              {rightTab === "patch" && <PatchPanel isBusy={isBusy} setIsBusy={setIsBusy} logLine={logLine} defaultPath={defaultToolPath} />}
              {rightTab === "media" && <MediaPanel comfy={comfy} isBusy={isBusy} />}
            </div>
          </aside>
        </CanvasProvider>
      </div>
    </div>
  );
}