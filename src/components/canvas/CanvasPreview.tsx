// src/components/canvas/CanvasPreview.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useCanvas } from "./CanvasContext";
import { VisualCanvasView } from "./VisualCanvas";

// Exact viewport widths based on user request (Phone, Tablet, Desktop/Windows)
function viewportWidthPx(v: "fit" | "phone" | "tablet" | "windows") {
  if (v === "phone") return 375;
  if (v === "tablet") return 768;
  if (v === "windows") return 1280;
  return null; // fit = 100%
}

function SafeIframe(props: {
  srcDoc: string;
  title: string;
  viewport: "fit" | "phone" | "tablet" | "windows";
  onWeirdNav?: () => void;
  iframeRef?: React.RefObject<HTMLIFrameElement | null>;
}) {
  const { srcDoc, title, viewport, onWeirdNav, iframeRef } = props;

  const [frameKey, setFrameKey] = useState(1);
  const expectedLoadRef = useRef(true);

  useEffect(() => {
    expectedLoadRef.current = true;
    setFrameKey((k) => k + 1);
  }, [srcDoc]);

  const w = viewportWidthPx(viewport);

  const iframeStyle: React.CSSProperties = {
    width: w ? `${w}px` : "100%",
    maxWidth: "100%",
    height: w ? "95%" : "100%",
    border: w ? "2px solid #00eaff" : "0",
    borderRadius: w ? 8 : 0,
    background: "#fff",
    boxShadow: w ? "0 0 40px rgba(0, 234, 255, 0.15)" : "none",
    transition: "all 0.3s ease",
    flexShrink: 1,
  };

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        minWidth: 0,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        overflow: "hidden",
        backgroundColor: "#020208",
        backgroundImage: "radial-gradient(#1d2836 1px, transparent 1px)",
        backgroundSize: "20px 20px",
      }}
    >
      <iframe
        ref={iframeRef as any}
        key={frameKey}
        title={title}
        sandbox="allow-scripts allow-forms allow-modals allow-popups"
        style={iframeStyle}
        srcDoc={srcDoc}
        onLoad={() => {
          if (!expectedLoadRef.current) {
            onWeirdNav?.();
            expectedLoadRef.current = true;
            setFrameKey((k) => k + 1);
            return;
          }
          expectedLoadRef.current = false;
        }}
      />
    </div>
  );
}

function joinArgs(args: any[]): string {
  try {
    return (args || []).map((s) => String(s)).join(" ");
  } catch {
    return "[unprintable]";
  }
}

export function CanvasPreview() {
  const { canvasMode, htmlRendered, logLine, vLayout, htmlViewport } = useCanvas();

  // We filter messages to ONLY the active iframe instance
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    const handler = (ev: MessageEvent) => {
      const frameWin = iframeRef.current?.contentWindow;
      if (!frameWin) return;
      if (ev.source !== frameWin) return;

      const data: any = ev.data;
      if (!data || data.__eaa_canvas_v1 !== true) return;

      if (data.type === "console") {
        const level = String(data.level || "log");
        const args = Array.isArray(data.args) ? data.args : [];
        const msg = joinArgs(args);
        logLine(`[canvas][preview][console.${level}] ${msg}`);
        return;
      }

      if (data.type === "error") {
        const msg = String(data.message || "Unknown error");
        const file = String(data.filename || "");
        const line = Number(data.lineno || 0);
        const col = Number(data.colno || 0);
        logLine(`[canvas][preview][runtime error] ${msg}${file ? ` @ ${file}:${line}:${col}` : ""}`);
        if (data.stack) logLine(String(data.stack));
        return;
      }

      if (data.type === "rejection") {
        const msg = String(data.message || "Unhandled rejection");
        logLine(`[canvas][preview][unhandled rejection] ${msg}`);
        if (data.stack) logLine(String(data.stack));
        return;
      }

      if (data.type === "ready") {
        return;
      }
    };

    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [logLine]);

  const containerStyle: React.CSSProperties = useMemo(
    () => ({
      flex: 1,
      minHeight: 0,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      backgroundColor: "#020208",
    }),
    []
  );

  if (canvasMode === "visual") {
    return (
      <div style={containerStyle}>
        <VisualCanvasView
          layout={vLayout}
          showGrid={false}
          showSelection={false}
          selectedId={null}
          guides={{ v: [], h: [] }}
          background="#080b10"
        />
      </div>
    );
  }

  return (
    <div style={containerStyle}>
      <SafeIframe
        title="EAA HTML Preview"
        srcDoc={htmlRendered}
        viewport={htmlViewport}
        iframeRef={iframeRef}
        onWeirdNav={() => logLine("[html][preview] Navigation detected -> reset back to srcDoc")}
      />
    </div>
  );
}
