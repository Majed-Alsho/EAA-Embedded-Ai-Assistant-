import React, { useEffect, useMemo, useRef, useState } from "react";

export type ViewportMode = "fit" | "phone" | "tablet" | "desktop";

const PRESETS: Record<Exclude<ViewportMode, "fit">, { w: number; h: number; label: string }> = {
  phone: { w: 390, h: 844, label: "Phone" },     // iPhone-ish
  tablet: { w: 820, h: 1180, label: "Tablet" },  // iPad-ish
  desktop: { w: 1280, h: 720, label: "Desktop" }, // nice baseline
};

function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const update = () => {
      const r = el.getBoundingClientRect();
      setSize({ w: Math.max(0, r.width), h: Math.max(0, r.height) });
    };

    update();

    // ResizeObserver is supported in modern WebViews; fallback to window resize if needed.
    let ro: ResizeObserver | null = null;
    try {
      ro = new ResizeObserver(() => update());
      ro.observe(el);
    } catch {
      window.addEventListener("resize", update);
    }

    return () => {
      if (ro) ro.disconnect();
      else window.removeEventListener("resize", update);
    };
  }, []);

  return { ref, size };
}

export function ViewportControls(props: { mode: ViewportMode; setMode: (m: ViewportMode) => void }) {
  const { mode, setMode } = props;

  const btn = (active: boolean): React.CSSProperties => ({
    padding: "6px 10px",
    borderRadius: 999,
    border: "1px solid #2a3a50",
    background: active ? "#1b2a3f" : "#0b1220",
    color: "#e6edf3",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 900,
    userSelect: "none",
    whiteSpace: "nowrap",
  });

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <button style={btn(mode === "fit")} onClick={() => setMode("fit")}>
        Fit
      </button>
      <button style={btn(mode === "phone")} onClick={() => setMode("phone")}>
        Phone
      </button>
      <button style={btn(mode === "tablet")} onClick={() => setMode("tablet")}>
        Tablet
      </button>
      <button style={btn(mode === "desktop")} onClick={() => setMode("desktop")}>
        Desktop
      </button>
    </div>
  );
}

function SafeIframe(props: {
  srcDoc: string;
  title: string;
  onWeirdNav?: () => void;
  sandbox?: string;
}) {
  const { srcDoc, title, onWeirdNav, sandbox } = props;

  const [frameKey, setFrameKey] = useState(1);
  const expectedLoadRef = useRef(true);

  useEffect(() => {
    expectedLoadRef.current = true;
    setFrameKey((k) => k + 1);
  }, [srcDoc]);

  return (
    <iframe
      key={frameKey}
      title={title}
      sandbox={sandbox ?? "allow-scripts allow-forms allow-modals allow-popups"}
      style={{
        width: "100%",
        height: "100%",
        border: 0,
        background: "#0b0f14",
      }}
      srcDoc={srcDoc}
      onLoad={() => {
        // If we didn’t expect this load, the page navigated itself (common: href="/" loads your app UI inside iframe)
        if (!expectedLoadRef.current) {
          onWeirdNav?.();
          expectedLoadRef.current = true;
          setFrameKey((k) => k + 1);
          return;
        }
        expectedLoadRef.current = false;
      }}
    />
  );
}

/**
 * Renders an iframe with REAL viewport dimensions (Phone/Tablet/Desktop),
 * then scales it to fit the available panel so media queries behave correctly.
 */
export function ViewportFrame(props: {
  srcDoc: string;
  title: string;
  mode: ViewportMode;
  onWeirdNav?: () => void;
  borderRadius?: number;
}) {
  const { srcDoc, title, mode, onWeirdNav, borderRadius = 14 } = props;
  const { ref, size } = useElementSize<HTMLDivElement>();

  const preset = mode === "fit" ? null : PRESETS[mode];

  const computed = useMemo(() => {
    if (!preset) return { scale: 1, scaledW: 0, scaledH: 0 };

    const pad = 12; // breathing room
    const availW = Math.max(0, size.w - pad * 2);
    const availH = Math.max(0, size.h - pad * 2);

    const scale = Math.min(availW / preset.w, availH / preset.h, 1);
    const scaledW = Math.max(1, Math.floor(preset.w * scale));
    const scaledH = Math.max(1, Math.floor(preset.h * scale));
    return { scale, scaledW, scaledH };
  }, [preset, size.w, size.h]);

  return (
    <div
      ref={ref}
      style={{
        width: "100%",
        height: "100%",
        minHeight: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      {mode === "fit" ? (
        <div style={{ width: "100%", height: "100%", overflow: "hidden", borderRadius, background: "#0b0f14" }}>
          <SafeIframe title={title} srcDoc={srcDoc} onWeirdNav={onWeirdNav} />
        </div>
      ) : (
        <div
          style={{
            width: computed.scaledW,
            height: computed.scaledH,
            borderRadius,
            overflow: "hidden",
            background: "#0b0f14",
            boxShadow: "0 10px 30px rgba(0,0,0,.35)",
          }}
        >
          <div
            style={{
              width: preset!.w,
              height: preset!.h,
              transform: `scale(${computed.scale})`,
              transformOrigin: "top left",
            }}
          >
            <SafeIframe title={title} srcDoc={srcDoc} onWeirdNav={onWeirdNav} />
          </div>
        </div>
      )}
    </div>
  );
}
