// CanvasEditor - Fixed Language Detection with PrismJS Auto-Detect
import React, { useEffect, useRef, useState, useCallback } from "react";
import Editor, { OnMount } from "@monaco-editor/react";
import Prism from "prismjs";
// Import language grammars for detection
import "prismjs/components/prism-python";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-go";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-css";
import "prismjs/components/prism-markup"; // HTML
import "prismjs/components/prism-elixir";
import { useCanvas } from "./CanvasContext";
import { CanvasPreview } from "./CanvasPreview";
import { AIAssistantPanel } from "./AIAssistantPanel";

// ==================== LANGUAGE DETECTION ====================
// Map detected language to Monaco language ID
function toMonacoLang(lang: string): string {
  const map: Record<string, string> = {
    elixir: "elixir",
    python: "python",
    javascript: "javascript",
    typescript: "typescript",
    html: "html",
    css: "css",
    json: "json",
    markdown: "markdown",
    rust: "rust",
    go: "go",
    sql: "sql",
    shell: "shell",
  };
  return map[lang] || "plaintext";
}

// Languages to try for Prism auto-detection (ordered by specificity)
const DETECT_LANGUAGES = [
  "elixir",
  "python",
  "rust", 
  "go",
  "typescript",
  "javascript",
  "sql",
  "bash",
  "json",
  "css",
  "markup", // HTML
];

// Strong patterns for high-confidence detection
const STRONG_PATTERNS: Array<[RegExp, string, number]> = [
  // Elixir (very distinctive)
  [/^\s*defmodule\s+\w+/m, "elixir", 100],
  [/^\s*defp?\s+\w+.*\bdo\b/m, "elixir", 95],
  [/@moduledoc/m, "elixir", 100],
  [/@doc\s/m, "elixir", 90],
  [/^\s*use\s+\w+/m, "elixir", 70],
  [/^\s*alias\s+\w+/m, "elixir", 80],
  [/^\s*import\s+\w+/m, "elixir", 70],
  [/\|>/m, "elixir", 40], // pipe operator
  
  // Python (very distinctive)
  [/^\s*def\s+\w+\s*\([^)]*\)\s*:/m, "python", 95],
  [/^\s*class\s+\w+.*:/m, "python", 90],
  [/from\s+\w+\s+import/m, "python", 85],
  [/^\s*import\s+\w+\s*$/m, "python", 75],
  [/if\s+__name__\s*==\s*['"]__main__['"]/m, "python", 100],
  [/^\s*elif\s+/m, "python", 95],
  [/^\s*except\s*/m, "python", 90],
  [/^\s*finally\s*:/m, "python", 90],
  [/f["'][^"']*\{/m, "python", 80], // f-strings
  [/self\.\w+/m, "python", 60],
  [/lambda\s+\w+\s*:/m, "python", 85],
  
  // Rust (very distinctive)
  [/^\s*fn\s+\w+\s*[\(<]/m, "rust", 95],
  [/^\s*impl\s+\w+/m, "rust", 95],
  [/^\s*struct\s+\w+/m, "rust", 90],
  [/^\s*enum\s+\w+/m, "rust", 85],
  [/^\s*trait\s+\w+/m, "rust", 90],
  [/let\s+mut\s+/m, "rust", 90],
  [/let\s+\w+:\s*\w+/m, "rust", 75],
  [/macro_rules!/m, "rust", 100],
  [/println!\s*\(/m, "rust", 85],
  [/Option</m, "rust", 70],
  [/Result</m, "rust", 70],
  [/pub\s+fn/m, "rust", 85],
  
  // Go (very distinctive)
  [/^\s*package\s+\w+\s*$/m, "go", 100],
  [/^\s*func\s+(\(\w+\s+\*?\w+\)\s*)?\w+\s*\(/m, "go", 90],
  [/^\s*type\s+\w+\s+struct/m, "go", 95],
  [/^\s*type\s+\w+\s+interface/m, "go", 90],
  [/:=[^=]/m, "go", 50], // short declaration
  [/^\s*defer\s+/m, "go", 90],
  [/^\s*go\s+\w+\(/m, "go", 85],
  [/^\s*select\s*\{/m, "go", 85],
  [/^\s*chan\s+\w+/m, "go", 90],
  
  // TypeScript
  [/^\s*interface\s+\w+\s*\{/m, "typescript", 95],
  [/^\s*type\s+\w+\s*=/m, "typescript", 90],
  [/^\s*enum\s+\w+/m, "typescript", 85],
  [/^\s*namespace\s+\w+/m, "typescript", 80],
  [/:\s*(string|number|boolean|any|void|never)\s*[=\)\{;,]/m, "typescript", 75],
  [/<\w+>/m, "typescript", 30], // generics
  
  // JavaScript (less specific, lower priority)
  [/^\s*const\s+\w+\s*=\s*(async\s+)?\(/m, "javascript", 70],
  [/^\s*function\s+\w+\s*\(/m, "javascript", 75],
  [/=>\s*\{/m, "javascript", 40],
  [/^\s*export\s+(default\s+)?(function|class|const)/m, "javascript", 70],
  [/^\s*import\s+.*from\s*['"]/m, "javascript", 65],
  [/require\s*\(['"]/m, "javascript", 70],
  [/console\.(log|error|warn)\s*\(/m, "javascript", 60],
  
  // SQL (very distinctive)
  [/^\s*SELECT\s+.+\s+FROM/im, "sql", 100],
  [/^\s*INSERT\s+INTO/im, "sql", 100],
  [/^\s*UPDATE\s+.+\s+SET/im, "sql", 100],
  [/^\s*DELETE\s+FROM/im, "sql", 100],
  [/^\s*CREATE\s+(TABLE|INDEX|VIEW)/im, "sql", 100],
  [/^\s*ALTER\s+TABLE/im, "sql", 100],
  [/^\s*DROP\s+(TABLE|INDEX)/im, "sql", 100],
  [/JOIN\s+\w+\s+ON/im, "sql", 90],
  [/GROUP\s+BY/im, "sql", 85],
  [/ORDER\s+BY/im, "sql", 85],
  
  // Shell/Bash (distinctive patterns)
  [/^#!/m, "shell", 100],
  [/^\s*if\s*\[\[?/m, "shell", 90],
  [/^\s*then\s*$/m, "shell", 85],
  [/^\s*fi\s*$/m, "shell", 95],
  [/^\s*for\s+\w+\s+in/m, "shell", 80],
  [/^\s*done\s*$/m, "shell", 85],
  [/^\s*case\s+\w+\s+in/m, "shell", 90],
  [/^\s*esac\s*$/m, "shell", 95],
  [/\$\(\([^)]+\)\)/m, "shell", 70], // arithmetic
  [/\$\{[^}]+\}/m, "shell", 50], // variable expansion
  
  // HTML (strict - must have actual HTML structure)
  [/<!DOCTYPE\s+html/i, "html", 100],
  [/^\s*<html[\s>]/im, "html", 100],
  [/<head[\s>][\s\S]*<body[\s>]/i, "html", 90],
  [/<script[\s>]/i, "html", 40],
  [/<style[\s>]/i, "html", 40],
  
  // JSON (check for valid JSON structure)
  [/^\s*\{[\s\S]*\}\s*$/m, "json", 50],
  [/^\s*\[[\s\S]*\]\s*$/m, "json", 50],
];

function detectLanguage(code: string, filename?: string): string {
  const trimmed = code.trim();
  if (!trimmed) return "plaintext";

  console.log("[Detect] Analyzing code, length:", trimmed.length, "file:", filename);

  // Step 1: Check STRONG patterns first (content-based, high confidence)
  let bestMatch: { lang: string; score: number } | null = null;
  
  for (const [pattern, lang, score] of STRONG_PATTERNS) {
    if (pattern.test(trimmed)) {
      console.log(`[Detect] Pattern matched: ${lang} (score: ${score})`);
      if (!bestMatch || score > bestMatch.score) {
        bestMatch = { lang, score };
      }
    }
  }

  // If we have a high-confidence match from patterns, use it
  if (bestMatch && bestMatch.score >= 70) {
    console.log("[Detect] ✅ Using high-confidence match:", bestMatch.lang);
    return bestMatch.lang;
  }

  // Step 2: Use Prism's tokenization for detection
  try {
    for (const lang of DETECT_LANGUAGES) {
      const grammar = Prism.languages[lang];
      if (grammar) {
        try {
          const tokens = Prism.tokenize(trimmed, grammar);
          // Count meaningful tokens (not just strings)
          const meaningfulTokens = (tokens as any[]).filter((t: any) => typeof t !== "string").length;
          const totalLength = trimmed.length;
          const tokenDensity = meaningfulTokens / (totalLength / 100);
          
          if (meaningfulTokens > 3 && tokenDensity > 0.5) {
            console.log(`[Detect] Prism detected ${lang}: ${meaningfulTokens} tokens, density: ${tokenDensity.toFixed(2)}`);
            return lang;
          }
        } catch (e) {
          // Continue to next language
        }
      }
    }
  } catch (e) {
    console.log("[Detect] Prism detection failed:", e);
  }

  // Step 3: Use lower confidence pattern match if we have one
  if (bestMatch && bestMatch.score >= 40) {
    console.log("[Detect] ⚡ Using medium-confidence match:", bestMatch.lang);
    return bestMatch.lang;
  }

  // Step 4: Use filename extension as last resort
  if (filename) {
    const ext = filename.split(".").pop()?.toLowerCase();
    const extMap: Record<string, string> = {
      ex: "elixir", exs: "elixir",
      py: "python",
      js: "javascript", mjs: "javascript", cjs: "javascript",
      ts: "typescript", tsx: "typescript",
      html: "html", htm: "html",
      css: "css",
      json: "json",
      md: "markdown",
      rs: "rust",
      go: "go",
      sql: "sql",
      sh: "shell", bash: "shell",
    };
    if (ext && extMap[ext]) {
      console.log("[Detect] 📁 Fallback to extension:", ext, "->", extMap[ext]);
      return extMap[ext];
    }
  }

  console.log("[Detect] ❓ No match, falling back to plaintext");
  return "plaintext";
}

// Language display config
const LANG_CONFIG: Record<string, { icon: string; color: string; bg: string }> = {
  elixir: { icon: "💧", color: "#a78bfa", bg: "rgba(78,62,122,0.4)" },
  python: { icon: "🐍", color: "#60a5fa", bg: "rgba(55,118,171,0.4)" },
  javascript: { icon: "📜", color: "#fbbf24", bg: "rgba(247,223,30,0.4)" },
  typescript: { icon: "📘", color: "#3b82f6", bg: "rgba(49,120,198,0.4)" },
  html: { icon: "🌐", color: "#f87171", bg: "rgba(227,76,38,0.4)" },
  css: { icon: "🎨", color: "#818cf8", bg: "rgba(38,77,228,0.4)" },
  rust: { icon: "🦀", color: "#f4a261", bg: "rgba(222,165,132,0.4)" },
  go: { icon: "🐹", color: "#22d3ee", bg: "rgba(0,173,216,0.4)" },
  sql: { icon: "🗃️", color: "#2dd4bf", bg: "rgba(20,184,166,0.4)" },
  shell: { icon: "💻", color: "#4ade80", bg: "rgba(34,197,94,0.4)" },
  json: { icon: "📋", color: "#fbbf24", bg: "rgba(251,191,36,0.3)" },
  markdown: { icon: "📝", color: "#9ca3af", bg: "rgba(156,163,175,0.3)" },
  plaintext: { icon: "📄", color: "#888", bg: "rgba(255,255,255,0.1)" },
};

export function CanvasEditor(props: { onOpenPreview: () => void }) {
  const {
    htmlFiles,
    htmlActive,
    setHtmlActive,
    htmlActiveFile,
    htmlAuto,
    setHtmlAuto,
    htmlSplitPreview,
    setHtmlSplitPreview,
    updateActiveHtmlContent,
    logLine,
  } = useCanvas();

  const editorRef = useRef<any>(null);
  const monacoRef = useRef<any>(null);
  const [lang, setLang] = useState("plaintext");
  const [showAi, setShowAi] = useState(false);
  const [showErr, setShowErr] = useState<any>(null);
  const [fixing, setFixing] = useState(false);
  const detectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Detect language when content changes (with debounce)
  useEffect(() => {
    const code = htmlActiveFile?.content || "";
    const name = htmlActiveFile?.name || "";

    // Clear previous timeout
    if (detectTimeoutRef.current) {
      clearTimeout(detectTimeoutRef.current);
    }

    // Debounce detection to avoid performance issues
    detectTimeoutRef.current = setTimeout(() => {
      const detected = detectLanguage(code, name);
      setLang(detected);

      // Update Monaco model language
      if (editorRef.current && monacoRef.current) {
        const model = editorRef.current.getModel();
        if (model) {
          const monacoLang = toMonacoLang(detected);
          monacoRef.current.editor.setModelLanguage(model, monacoLang);
          console.log("[Editor] Monaco language set to:", monacoLang);
        }
      }
    }, 150);

    return () => {
      if (detectTimeoutRef.current) {
        clearTimeout(detectTimeoutRef.current);
      }
    };
  }, [htmlActiveFile?.content, htmlActiveFile?.name]);

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    console.log("[Editor] Mounted");
  };

  const doFix = async () => {
    if (fixing) return;
    setFixing(true);
    logLine("[AI] Fixing...");
    try {
      const res = await fetch("http://127.0.0.1:8000/v1/canvas/fix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: htmlActiveFile?.content, language: lang }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.fixed_code) {
          updateActiveHtmlContent(data.fixed_code);
          setShowErr(null);
          logLine("[AI] Fixed!");
        }
      }
    } catch (e) {
      logLine("[AI] Error: " + e);
    }
    setFixing(false);
  };

  const monacoLang = toMonacoLang(lang);
  const config = LANG_CONFIG[lang] || LANG_CONFIG.plaintext;
  const isHtml = lang === "html";

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", background: "#020208", color: "#e6edf3" }}>
      {/* Toolbar */}
      <div style={{ height: 56, borderBottom: "1px solid #1d2836", display: "flex", alignItems: "center", padding: "0 16px", gap: 12 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {htmlFiles.map((f) => (
            <div
              key={f.name}
              onClick={() => setHtmlActive(f.name)}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                cursor: "pointer",
                background: f.name === htmlActive ? "rgba(0,234,255,0.15)" : "transparent",
                color: f.name === htmlActive ? "#00eaff" : "#888",
                fontSize: 13,
              }}
            >
              📄 {f.name}
            </div>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <div
          style={{
            padding: "4px 12px",
            borderRadius: 6,
            background: config.bg,
            color: config.color,
            fontSize: 11,
            fontWeight: 700,
            textTransform: "uppercase",
          }}
        >
          {config.icon} {lang}
        </div>
        <button
          onClick={() => setShowAi(!showAi)}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            background: showAi ? "linear-gradient(135deg,#00eaff,#a855f7)" : "rgba(255,255,255,0.1)",
            color: showAi ? "#000" : "#e6edf3",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          🤖 AI
        </button>
        <button
          onClick={doFix}
          disabled={fixing}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            background: "linear-gradient(135deg,#00eaff,#00b4d8)",
            color: "#000",
            fontWeight: 600,
            cursor: "pointer",
            opacity: showErr ? 1 : 0.5,
          }}
        >
          🪠 {fixing ? "Fixing..." : "AI Fix"}
        </button>
        <button
          onClick={() => setHtmlAuto(!htmlAuto)}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            background: htmlAuto ? "rgba(34,197,94,0.2)" : "rgba(255,255,255,0.1)",
            color: htmlAuto ? "#22c55e" : "#e6edf3",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Auto: {htmlAuto ? "ON" : "OFF"}
        </button>
        <button
          onClick={() => setHtmlSplitPreview(!htmlSplitPreview)}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            background: htmlSplitPreview ? "rgba(0,234,255,0.2)" : "rgba(255,255,255,0.1)",
            color: htmlSplitPreview ? "#00eaff" : "#e6edf3",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          {htmlSplitPreview ? "Hide" : "Show"} Preview
        </button>
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <div style={{ flex: htmlSplitPreview ? 0.5 : 1, minWidth: 0 }}>
          <Editor
            height="100%"
            language={monacoLang}
            value={htmlActiveFile?.content || ""}
            onChange={(v) => updateActiveHtmlContent(v || "")}
            onMount={handleEditorMount}
            theme="vs-dark"
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              fontFamily: "JetBrains Mono,monospace",
              wordWrap: "on",
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 2,
              lineNumbers: "on",
              folding: true,
            }}
          />
        </div>
        {htmlSplitPreview && (
          <div style={{ flex: 1, borderLeft: "1px solid #1d2836" }}>
            {isHtml ? (
              <CanvasPreview />
            ) : (
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  background: "linear-gradient(135deg,#0a0a12,#12121a)",
                }}
              >
                <div style={{ fontSize: 64 }}>{config.icon}</div>
                <div style={{ fontSize: 18, fontWeight: 700, textTransform: "uppercase" }}>{lang}</div>
                <div style={{ fontSize: 12, color: "#666", marginTop: 8 }}>Code Editor Mode</div>
              </div>
            )}
          </div>
        )}
      </div>

      {showAi && (
        <AIAssistantPanel
          code={htmlActiveFile?.content || ""}
          language={lang}
          filename={htmlActiveFile?.name || "untitled"}
          onApplyCode={updateActiveHtmlContent}
          onClose={() => setShowAi(false)}
        />
      )}
    </div>
  );
}