// src/components/canvas/VisualCanvas.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";

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

export function uid() {
  return crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function clamp(n: number, a: number, b: number) {
  return Math.max(a, Math.min(b, n));
}

function roundTo(n: number, step: number) {
  if (step <= 0) return n;
  return Math.round(n / step) * step;
}

export function safeParseLayout(jsonText: string): VLayout {
  const parsed = JSON.parse(jsonText) as any;
  if (!parsed || !Array.isArray(parsed.items)) throw new Error("Bad JSON: missing items[]");

  const cleaned: VLayout = {
    version: Number(parsed.version ?? 1),
    items: parsed.items
      .filter((x: any) => x && typeof x === "object")
      .map((x: any) => ({
        id: String(x.id ?? uid()),
        type: x.type === "text" || x.type === "button" || x.type === "card" ? x.type : "card",
        text: String(x.text ?? ""),
        x: Number(x.x ?? 0),
        y: Number(x.y ?? 0),
        w: Number(x.w ?? 200),
        h: Number(x.h ?? 80),
      })),
  };

  return cleaned;
}

export function VisualCanvasView(props: {
  layout: VLayout;
  background?: string;
  showGrid?: boolean;
  gridSize?: number;
  guides?: Guides;
  selectedId?: string | null;
  showSelection?: boolean;
}) {
  const { layout, background, showGrid, gridSize, guides, selectedId, showSelection } = props;

  const stageStyle: React.CSSProperties = {
    position: "relative",
    flex: 1,
    minHeight: 0,
    border: "1px solid #1d2836",
    borderRadius: 16,
    overflow: "hidden",
    background: background ?? "#0b0f14",
    boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
  };

  if (showGrid && (gridSize ?? 0) > 0) {
    const g = gridSize ?? 16;
    stageStyle.backgroundImage = `
      linear-gradient(to right, rgba(255,255,255,0.06) 1px, transparent 1px),
      linear-gradient(to bottom, rgba(255,255,255,0.06) 1px, transparent 1px)
    `;
    stageStyle.backgroundSize = `${g}px ${g}px`;
    stageStyle.backgroundPosition = `0 0`;
  }

  return (
    <div style={stageStyle}>
      {/* Guides */}
      {guides?.v?.map((x, i) => (
        <div
          key={`gv-${i}`}
          style={{
            position: "absolute",
            left: x,
            top: 0,
            bottom: 0,
            width: 1,
            background: "rgba(59,130,246,0.9)",
            pointerEvents: "none",
          }}
        />
      ))}
      {guides?.h?.map((y, i) => (
        <div
          key={`gh-${i}`}
          style={{
            position: "absolute",
            top: y,
            left: 0,
            right: 0,
            height: 1,
            background: "rgba(59,130,246,0.9)",
            pointerEvents: "none",
          }}
        />
      ))}

      {layout.items.map((it) => {
        const isSelected = selectedId === it.id;

        const base: React.CSSProperties = {
          position: "absolute",
          left: it.x,
          top: it.y,
          width: it.w,
          height: it.h,
          borderRadius: 14,
          border: showSelection && isSelected ? "2px solid #3b82f6" : "1px solid #1d2836",
          background: "#0e1521",
          boxShadow: "0 6px 20px rgba(0,0,0,0.35)",
          display: "flex",
          alignItems: it.type === "card" ? "flex-start" : "center",
          justifyContent: it.type === "card" ? "flex-start" : "center",
          padding: it.type === "card" ? 14 : 0,
          userSelect: "none",
          overflow: "hidden",
          whiteSpace: "pre-wrap",
        };

        if (it.type === "button") {
          return (
            <div key={it.id} style={{ ...base, background: "#0b1220", fontWeight: 900, fontSize: 14 }}>
              {it.text || "Button"}
            </div>
          );
        }

        if (it.type === "text") {
          return (
            <div key={it.id} style={{ ...base, fontWeight: 900, fontSize: 16 }}>
              {it.text || "Text"}
            </div>
          );
        }

        return (
          <div
            key={it.id}
            style={{
              ...base,
              flexDirection: "column",
              gap: 10,
              alignItems: "flex-start",
              justifyContent: "flex-start",
            }}
          >
            <div style={{ fontWeight: 900, fontSize: 16 }}>Card</div>
            <div style={{ opacity: 0.85, fontSize: 13, lineHeight: 1.35 }}>{it.text || ""}</div>
          </div>
        );
      })}
    </div>
  );
}

type DragOp =
  | {
      kind: "move";
      id: string;
      startX: number;
      startY: number;
      origX: number;
      origY: number;
    }
  | {
      kind: "resize";
      id: string;
      handle: "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";
      startX: number;
      startY: number;
      origX: number;
      origY: number;
      origW: number;
      origH: number;
    };

export function VisualCanvasEditor(props: {
  layout: VLayout;
  setLayout: React.Dispatch<React.SetStateAction<VLayout>>;
  logLine: (s: string) => void;

  // persistence
  layoutRelPath: string;
  setLayoutRelPath: (s: string) => void;
  saveToFile: () => Promise<void>;
  loadFromFile: (reason?: string) => Promise<void>;

  // live sync polling
  liveSync: boolean;
  setLiveSync: (b: boolean) => void;
  pollMs: number;
  setPollMs: (n: number) => void;

  // controls
  testMode: boolean;
  setTestMode: (b: boolean) => void;

  snapEnabled: boolean;
  setSnapEnabled: (b: boolean) => void;

  gridEnabled: boolean;
  setGridEnabled: (b: boolean) => void;

  gridSize: number;
  setGridSize: (n: number) => void;
}) {
  const {
    layout,
    setLayout,
    logLine,
    layoutRelPath,
    setLayoutRelPath,
    saveToFile,
    loadFromFile,
    liveSync,
    setLiveSync,
    pollMs,
    setPollMs,
    testMode,
    setTestMode,
    snapEnabled,
    setSnapEnabled,
    gridEnabled,
    setGridEnabled,
    gridSize,
    setGridSize,
  } = props;

  const [selectedId, setSelectedId] = useState<string>(layout.items[0]?.id ?? "");
  const [guides, setGuides] = useState<Guides>({ v: [], h: [] });

  const [jsonModal, setJsonModal] = useState<null | "export" | "import">(null);
  const [jsonText, setJsonText] = useState<string>("");

  const dragRef = useRef<DragOp | null>(null);

  const selected = useMemo(
    () => layout.items.find((x) => x.id === selectedId) ?? null,
    [layout.items, selectedId]
  );

  useEffect(() => {
    if (!selectedId && layout.items[0]?.id) setSelectedId(layout.items[0].id);
    if (selectedId && !layout.items.some((x) => x.id === selectedId)) {
      setSelectedId(layout.items[0]?.id ?? "");
    }
  }, [layout.items, selectedId]);

  function updateItem(id: string, patch: Partial<VItem>) {
    setLayout((prev) => ({
      ...prev,
      items: prev.items.map((it) => (it.id === id ? { ...it, ...patch } : it)),
    }));
  }

  function addItem(type: VItemType) {
    const it: VItem =
      type === "card"
        ? { id: uid(), type, text: "Drag me. Resize me. Snap me.", x: 120, y: 120, w: 420, h: 160 }
        : type === "text"
        ? { id: uid(), type, text: "Text", x: 120, y: 120, w: 220, h: 44 }
        : { id: uid(), type, text: "Button", x: 120, y: 120, w: 180, h: 44 };

    setLayout((prev) => ({ ...prev, version: (prev.version ?? 0) + 1, items: [...prev.items, it] }));
    setSelectedId(it.id);
  }

  function deleteSelected() {
    if (!selected) return;
    setLayout((prev) => ({
      ...prev,
      version: (prev.version ?? 0) + 1,
      items: prev.items.filter((x) => x.id !== selected.id),
    }));
    setSelectedId((prev) => layout.items.find((x) => x.id !== prev)?.id ?? "");
  }

  function makeSnap(n: number) {
    return snapEnabled ? roundTo(n, gridSize) : n;
  }

  function computeGuidesForMove(movingId: string, x: number, y: number, w: number, h: number) {
    const threshold = 6;
    const others = layout.items.filter((it) => it.id !== movingId);

    const myX = { l: x, c: x + w / 2, r: x + w };
    const myY = { t: y, m: y + h / 2, b: y + h };

    const otherXs: number[] = [];
    const otherYs: number[] = [];

    for (const it of others) {
      otherXs.push(it.x, it.x + it.w / 2, it.x + it.w);
      otherYs.push(it.y, it.y + it.h / 2, it.y + it.h);
    }

    let bestDx = 0;
    let bestXGuide: number | null = null;
    let bestAbsX = Infinity;

    const candidatesX = [myX.l, myX.c, myX.r];
    for (const cx of candidatesX) {
      for (const ox of otherXs) {
        const d = ox - cx;
        const ad = Math.abs(d);
        if (ad <= threshold && ad < bestAbsX) {
          bestAbsX = ad;
          bestDx = d;
          bestXGuide = ox;
        }
      }
    }

    let bestDy = 0;
    let bestYGuide: number | null = null;
    let bestAbsY = Infinity;

    const candidatesY = [myY.t, myY.m, myY.b];
    for (const cy of candidatesY) {
      for (const oy of otherYs) {
        const d = oy - cy;
        const ad = Math.abs(d);
        if (ad <= threshold && ad < bestAbsY) {
          bestAbsY = ad;
          bestDy = d;
          bestYGuide = oy;
        }
      }
    }

    const snapped = { x, y };
    const g: Guides = { v: [], h: [] };

    if (bestXGuide != null) {
      snapped.x = x + bestDx;
      g.v.push(bestXGuide);
    }
    if (bestYGuide != null) {
      snapped.y = y + bestDy;
      g.h.push(bestYGuide);
    }

    return { snappedX: snapped.x, snappedY: snapped.y, guides: g };
  }

  function onItemPointerDown(e: React.PointerEvent, id: string) {
    if (testMode) return;
    const it = layout.items.find((x) => x.id === id);
    if (!it) return;

    setSelectedId(id);
    dragRef.current = {
      kind: "move",
      id,
      startX: e.clientX,
      startY: e.clientY,
      origX: it.x,
      origY: it.y,
    };

    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onHandlePointerDown(
    e: React.PointerEvent,
    id: string,
    handle: DragOp & { kind: "resize" }["handle"]
  ) {
    if (testMode) return;
    e.stopPropagation();

    const it = layout.items.find((x) => x.id === id);
    if (!it) return;

    setSelectedId(id);
    dragRef.current = {
      kind: "resize",
      id,
      handle,
      startX: e.clientX,
      startY: e.clientY,
      origX: it.x,
      origY: it.y,
      origW: it.w,
      origH: it.h,
    };

    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    const op = dragRef.current;
    if (!op) return;

    const dx = e.clientX - op.startX;
    const dy = e.clientY - op.startY;

    if (op.kind === "move") {
      const it = layout.items.find((x) => x.id === op.id);
      if (!it) return;

      let nx = op.origX + dx;
      let ny = op.origY + dy;

      nx = makeSnap(nx);
      ny = makeSnap(ny);

      const { snappedX, snappedY, guides: g } = computeGuidesForMove(op.id, nx, ny, it.w, it.h);
      nx = snappedX;
      ny = snappedY;

      setGuides(g);
      updateItem(op.id, { x: Math.round(nx), y: Math.round(ny) });
      return;
    }

    if (op.kind === "resize") {
      let x = op.origX;
      let y = op.origY;
      let w = op.origW;
      let h = op.origH;

      const minW = 80;
      const minH = 44;

      const hnd = op.handle;

      if (hnd.includes("e")) w = op.origW + dx;
      if (hnd.includes("s")) h = op.origH + dy;
      if (hnd.includes("w")) {
        x = op.origX + dx;
        w = op.origW - dx;
      }
      if (hnd.includes("n")) {
        y = op.origY + dy;
        h = op.origH - dy;
      }

      w = clamp(w, minW, 5000);
      h = clamp(h, minH, 5000);

      if (hnd.includes("w")) x = op.origX + (op.origW - w);
      if (hnd.includes("n")) y = op.origY + (op.origH - h);

      x = makeSnap(x);
      y = makeSnap(y);
      w = snapEnabled ? roundTo(w, gridSize) : w;
      h = snapEnabled ? roundTo(h, gridSize) : h;

      const { guides: g } = computeGuidesForMove(op.id, x, y, w, h);
      setGuides(g);

      updateItem(op.id, {
        x: Math.round(x),
        y: Math.round(y),
        w: Math.round(w),
        h: Math.round(h),
      });
    }
  }

  function onPointerUp() {
    dragRef.current = null;
    setGuides({ v: [], h: [] });
  }

  async function exportJSON() {
    const out = JSON.stringify(layout, null, 2);
    setJsonText(out);
    setJsonModal("export");
    try {
      await navigator.clipboard.writeText(out);
      logLine("[canvas] Exported layout JSON (copied to clipboard)");
    } catch {
      logLine("[canvas] Exported layout JSON (clipboard blocked — copy manually)");
    }
  }

  function openImport() {
    setJsonText("");
    setJsonModal("import");
  }

  function doImportFromText() {
    try {
      const cleaned = safeParseLayout(jsonText);
      setLayout(cleaned);
      setSelectedId(cleaned.items[0]?.id ?? "");
      setJsonModal(null);
      logLine("[canvas] Imported layout JSON");
    } catch (err) {
      logLine(`[canvas][error] import failed: ${String(err)}`);
    }
  }

  const styles: Record<string, React.CSSProperties | ((...args: any[]) => React.CSSProperties)> = {
    toolbar: {
      display: "flex",
      gap: 8,
      flexWrap: "wrap",
      alignItems: "center",
      justifyContent: "space-between",
      padding: 12,
      borderBottom: "1px solid #1d2836",
      background: "#0e1521",
    },
    toolbarLeft: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" },
    toolbarRight: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" },

    btn: (danger?: boolean, active?: boolean) => ({
      padding: "8px 10px",
      borderRadius: 12,
      border: "1px solid #2a3a50",
      background: danger ? "#2a1220" : active ? "#1b2a3f" : "#0b1220",
      color: "#e6edf3",
      cursor: "pointer",
      fontSize: 12,
      fontWeight: 900,
      opacity: 1,
    }),

    split: { flex: 1, minHeight: 0, display: "flex", gap: 12, padding: 12 },
    inspector: {
      width: 300,
      border: "1px solid #1d2836",
      borderRadius: 16,
      overflow: "hidden",
      background: "#0e1521",
      boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
      display: "flex",
      flexDirection: "column",
      minHeight: 0,
    },
    inspectorHeader: { padding: 12, borderBottom: "1px solid #1d2836", fontWeight: 900 },
    inspectorBody: { padding: 12, overflow: "auto" as const, minHeight: 0 },

    label: { fontSize: 12, fontWeight: 900, opacity: 0.85, marginTop: 10 },
    input: {
      width: "100%",
      marginTop: 6,
      padding: "10px 12px",
      borderRadius: 12,
      border: "1px solid #2a3a50",
      background: "#0b1220",
      color: "#e6edf3",
      outline: "none",
      fontSize: 12,
    },
    handle: (pos: string) => {
      const s = 10;
      const base: React.CSSProperties = {
        position: "absolute",
        width: s,
        height: s,
        borderRadius: 999,
        background: "#3b82f6",
        border: "2px solid rgba(0,0,0,0.5)",
        boxShadow: "0 6px 14px rgba(0,0,0,0.45)",
      };

      const map: Record<string, React.CSSProperties> = {
        nw: { left: -s / 2, top: -s / 2, cursor: "nwse-resize" },
        n: { left: "50%", top: -s / 2, transform: "translateX(-50%)", cursor: "ns-resize" },
        ne: { right: -s / 2, top: -s / 2, cursor: "nesw-resize" },
        e: { right: -s / 2, top: "50%", transform: "translateY(-50%)", cursor: "ew-resize" },
        se: { right: -s / 2, bottom: -s / 2, cursor: "nwse-resize" },
        s: { left: "50%", bottom: -s / 2, transform: "translateX(-50%)", cursor: "ns-resize" },
        sw: { left: -s / 2, bottom: -s / 2, cursor: "nesw-resize" },
        w: { left: -s / 2, top: "50%", transform: "translateY(-50%)", cursor: "ew-resize" },
      };

      return { ...base, ...(map[pos] ?? {}) };
    },

    modalBackdrop: {
      position: "absolute",
      inset: 0,
      background: "rgba(0,0,0,0.6)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: 18,
      zIndex: 50,
    },
    modal: {
      width: "min(860px, 96vw)",
      maxHeight: "min(720px, 92vh)",
      border: "1px solid #1d2836",
      borderRadius: 16,
      background: "#0e1521",
      boxShadow: "0 18px 50px rgba(0,0,0,0.6)",
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
    },
    modalHeader: {
      padding: 12,
      borderBottom: "1px solid #1d2836",
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      fontWeight: 900,
    },
    modalBody: { padding: 12, overflow: "auto" as const, minHeight: 0 },
    modalFooter: { padding: 12, borderTop: "1px solid #1d2836", display: "flex", gap: 8, flexWrap: "wrap" },
  };

  const btn = styles.btn as (danger?: boolean, active?: boolean) => React.CSSProperties;
  const handleStyle = styles.handle as (pos: string) => React.CSSProperties;

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1, position: "relative" }}>
      <div style={styles.toolbar as React.CSSProperties}>
        <div style={styles.toolbarLeft as React.CSSProperties}>
          <button style={btn(false, !testMode)} onClick={() => setTestMode(false)}>
            Edit
          </button>
          <button style={btn(false, testMode)} onClick={() => setTestMode(true)}>
            Test (normal)
          </button>

          <button style={btn()} onClick={() => addItem("card")} disabled={testMode}>
            + Card
          </button>
          <button style={btn()} onClick={() => addItem("text")} disabled={testMode}>
            + Text
          </button>
          <button style={btn()} onClick={() => addItem("button")} disabled={testMode}>
            + Button
          </button>

          <button style={btn(true)} onClick={() => deleteSelected()} disabled={testMode || !selected}>
            Delete
          </button>
        </div>

        <div style={styles.toolbarRight as React.CSSProperties}>
          <button style={btn(false, liveSync)} onClick={() => setLiveSync(!liveSync)}>
            Live Sync {liveSync ? "On" : "Off"}
          </button>

          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 900, opacity: 0.85 }}>Poll</span>
            <input
              style={{ ...(styles.input as React.CSSProperties), width: 90, marginTop: 0 }}
              type="number"
              value={pollMs}
              onChange={(e) => setPollMs(clamp(Number(e.target.value) || 200, 200, 5000))}
            />
            <span style={{ fontSize: 12, opacity: 0.75 }}>ms</span>
          </span>

          <button style={btn(false, snapEnabled)} onClick={() => setSnapEnabled(!snapEnabled)} disabled={testMode}>
            Snap {snapEnabled ? "On" : "Off"}
          </button>
          <button style={btn(false, gridEnabled)} onClick={() => setGridEnabled(!gridEnabled)}>
            Grid {gridEnabled ? "On" : "Off"}
          </button>

          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 900, opacity: 0.85 }}>Grid</span>
            <input
              style={{ ...(styles.input as React.CSSProperties), width: 90, marginTop: 0 }}
              type="number"
              value={gridSize}
              onChange={(e) => setGridSize(clamp(Number(e.target.value) || 1, 1, 128))}
            />
          </span>

          <button style={btn()} onClick={() => exportJSON()}>
            Export
          </button>
          <button style={btn()} onClick={() => openImport()}>
            Import
          </button>
        </div>
      </div>

      <div style={styles.split as React.CSSProperties}>
        {/* Stage */}
        <div
          style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", position: "relative" }}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <VisualCanvasView
            layout={layout}
            showGrid={gridEnabled}
            gridSize={gridSize}
            guides={testMode ? { v: [], h: [] } : guides}
            selectedId={testMode ? null : selectedId}
            showSelection={!testMode}
          />

          {/* Click/move/resize layer */}
          {!testMode && (
            <div style={{ position: "absolute", inset: 0 }}>
              {layout.items.map((it) => {
                const isSel = it.id === selectedId;
                return (
                  <div
                    key={it.id}
                    style={{
                      position: "absolute",
                      left: it.x,
                      top: it.y,
                      width: it.w,
                      height: it.h,
                      cursor: "grab",
                      pointerEvents: "auto",
                    }}
                    onPointerDown={(e) => onItemPointerDown(e, it.id)}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedId(it.id);
                    }}
                  >
                    {isSel &&
                      (["nw", "n", "ne", "e", "se", "s", "sw", "w"] as const).map((h) => (
                        <div
                          key={h}
                          style={handleStyle(h)}
                          onPointerDown={(e) => onHandlePointerDown(e, it.id, h)}
                          onClick={(e) => e.stopPropagation()}
                        />
                      ))}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Inspector */}
        {!testMode && (
          <div style={styles.inspector as React.CSSProperties}>
            <div style={styles.inspectorHeader as React.CSSProperties}>Inspector</div>
            <div style={styles.inspectorBody as React.CSSProperties}>
              <div style={{ fontSize: 12, opacity: 0.75 }}>
                Drag to move. Use handles to resize. Live Sync polls the JSON file and reloads automatically.
              </div>

              <div style={styles.label as React.CSSProperties}>Layout file (workspace-relative)</div>
              <input
                style={styles.input as React.CSSProperties}
                value={layoutRelPath}
                onChange={(e) => setLayoutRelPath(e.target.value)}
                placeholder="EAA_Sandbox/public/eaa_canvas_layout.json"
              />

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <button style={btn()} onClick={() => void saveToFile()}>
                  Save to file
                </button>
                <button style={btn()} onClick={() => void loadFromFile("manual")}>
                  Load from file
                </button>
              </div>

              {!selected ? (
                <div style={{ marginTop: 14, opacity: 0.85 }}>Select an item.</div>
              ) : (
                <>
                  <div style={styles.label as React.CSSProperties}>id</div>
                  <div style={{ ...(styles.input as React.CSSProperties), opacity: 0.85 }}>{selected.id}</div>

                  <div style={styles.label as React.CSSProperties}>type</div>
                  <div style={{ ...(styles.input as React.CSSProperties), opacity: 0.85 }}>{selected.type}</div>

                  <div style={styles.label as React.CSSProperties}>Text</div>
                  <input
                    style={styles.input as React.CSSProperties}
                    value={selected.text}
                    onChange={(e) => updateItem(selected.id, { text: e.target.value })}
                  />

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <div>
                      <div style={styles.label as React.CSSProperties}>W</div>
                      <input
                        style={styles.input as React.CSSProperties}
                        type="number"
                        value={selected.w}
                        onChange={(e) =>
                          updateItem(selected.id, { w: clamp(Number(e.target.value) || 0, 80, 5000) })
                        }
                      />
                    </div>
                    <div>
                      <div style={styles.label as React.CSSProperties}>H</div>
                      <input
                        style={styles.input as React.CSSProperties}
                        type="number"
                        value={selected.h}
                        onChange={(e) =>
                          updateItem(selected.id, { h: clamp(Number(e.target.value) || 0, 44, 5000) })
                        }
                      />
                    </div>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <div>
                      <div style={styles.label as React.CSSProperties}>X</div>
                      <input
                        style={styles.input as React.CSSProperties}
                        type="number"
                        value={selected.x}
                        onChange={(e) => updateItem(selected.id, { x: Math.round(Number(e.target.value) || 0) })}
                      />
                    </div>
                    <div>
                      <div style={styles.label as React.CSSProperties}>Y</div>
                      <input
                        style={styles.input as React.CSSProperties}
                        type="number"
                        value={selected.y}
                        onChange={(e) => updateItem(selected.id, { y: Math.round(Number(e.target.value) || 0) })}
                      />
                    </div>
                  </div>

                  <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button style={btn(true)} onClick={() => deleteSelected()}>
                      Delete item
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Export/Import modal */}
      {jsonModal ? (
        <div style={styles.modalBackdrop as React.CSSProperties} onClick={() => setJsonModal(null)}>
          <div style={styles.modal as React.CSSProperties} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader as React.CSSProperties}>
              <div>{jsonModal === "export" ? "Export Layout JSON" : "Import Layout JSON"}</div>
              <button style={btn(true)} onClick={() => setJsonModal(null)}>
                Close
              </button>
            </div>

            <div style={styles.modalBody as React.CSSProperties}>
              <textarea
                style={{
                  width: "100%",
                  minHeight: 240,
                  padding: 12,
                  borderRadius: 12,
                  border: "1px solid #2a3a50",
                  background: "#0b1220",
                  color: "#e6edf3",
                  outline: "none",
                  fontSize: 12,
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                  resize: "vertical",
                }}
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                placeholder={jsonModal === "import" ? "Paste JSON here…" : ""}
                readOnly={jsonModal === "export"}
              />
            </div>

            <div style={styles.modalFooter as React.CSSProperties}>
              {jsonModal === "export" ? (
                <button
                  style={btn()}
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(jsonText);
                      logLine("[canvas] Copied export JSON to clipboard");
                    } catch {
                      logLine("[canvas] Clipboard blocked — copy manually");
                    }
                  }}
                >
                  Copy
                </button>
              ) : (
                <button style={btn()} onClick={() => doImportFromText()}>
                  Import
                </button>
              )}
              <div style={{ fontSize: 12, opacity: 0.75 }}>
                Tip: AI can edit the JSON file on disk, and Live Sync will reload it.
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
