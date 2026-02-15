import type { CSSProperties } from "react";

/**
 * toolStyles is intentionally BOTH:
 *  - callable: const styles = toolStyles()
 *  - and has helper functions: toolStyles.smallBtn(...)
 *
 * This keeps compatibility with older panels while avoiding a full refactor.
 */

export type ToolStyleBag = {
  panel: CSSProperties;
  title: CSSProperties;
  row: CSSProperties;
  label: CSSProperties;
  input: CSSProperties;
  textarea: CSSProperties;
  button: CSSProperties;
  buttonSecondary: CSSProperties;
  btnRow: CSSProperties;
  list: CSSProperties;
  listItem: CSSProperties;
  mono: CSSProperties;
  monoBox: CSSProperties;
  iframe: CSSProperties;
};

type SmallBtnFn = (active?: boolean) => CSSProperties;

type ToolStylesFn = (() => ToolStyleBag) & {
  smallBtn: SmallBtnFn;
  smallBtnDanger: SmallBtnFn;
};

const base: ToolStyleBag = {
  panel: { display: "flex", flexDirection: "column", gap: 12, padding: 12, height: "100%", overflow: "hidden" },
  title: { fontWeight: 700, fontSize: 14, letterSpacing: 0.5 },
  row: { display: "flex", flexDirection: "column", gap: 6 },
  label: { fontSize: 11, opacity: 0.8 },
  input: {
    background: "rgba(0,0,0,0.35)",
    border: "1px solid rgba(0,255,255,0.25)",
    borderRadius: 10,
    padding: "10px 12px",
    outline: "none",
    color: "rgba(255,255,255,0.92)",
  },
  textarea: {
    background: "rgba(0,0,0,0.35)",
    border: "1px solid rgba(0,255,255,0.25)",
    borderRadius: 14,
    padding: "10px 12px",
    outline: "none",
    color: "rgba(255,255,255,0.92)",
    resize: "vertical",
    minHeight: 220,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
    fontSize: 12,
    lineHeight: 1.4,
  },
  button: {
    background: "rgba(0, 200, 255, 0.15)",
    border: "1px solid rgba(0,255,255,0.35)",
    color: "rgba(255,255,255,0.92)",
    borderRadius: 10,
    padding: "8px 12px",
    cursor: "pointer",
    fontWeight: 600,
  },
  buttonSecondary: {
    background: "rgba(255,255,255,0.06)",
    border: "1px solid rgba(255,255,255,0.14)",
    color: "rgba(255,255,255,0.92)",
    borderRadius: 10,
    padding: "8px 12px",
    cursor: "pointer",
    fontWeight: 600,
  },
  btnRow: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" },
  list: { overflow: "auto", borderRadius: 12, border: "1px solid rgba(255,255,255,0.10)" },
  listItem: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "8px 10px",
    borderBottom: "1px solid rgba(255,255,255,0.08)",
    color: "rgba(255,255,255,0.92)",
    fontSize: 12,
  },
  mono: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
    fontSize: 12,
    lineHeight: 1.4,
    whiteSpace: "pre-wrap",
  },
  monoBox: {
    flex: 1,
    overflow: "auto",
    borderRadius: 12,
    border: "1px solid rgba(255,255,255,0.10)",
    background: "rgba(0,0,0,0.35)",
    padding: 12,
  },
  iframe: {
    width: "100%",
    height: "100%",
    flex: 1,
    minHeight: 0,
    border: "1px solid rgba(0,255,255,0.20)",
    borderRadius: 14,
    background: "rgba(0,0,0,0.6)",
  },
};

const smallBtnBase: CSSProperties = {
  background: "rgba(255,255,255,0.06)",
  border: "1px solid rgba(255,255,255,0.14)",
  color: "rgba(255,255,255,0.92)",
  borderRadius: 10,
  padding: "6px 10px",
  cursor: "pointer",
  fontWeight: 700,
  fontSize: 11,
  letterSpacing: 0.3,
};

const smallBtnDangerBase: CSSProperties = {
  ...smallBtnBase,
  border: "1px solid rgba(255,0,0,0.25)",
  background: "rgba(255,0,0,0.10)",
};

const smallBtnActive: CSSProperties = {
  border: "1px solid rgba(0,255,255,0.45)",
  background: "rgba(0, 200, 255, 0.18)",
};

function build(): ToolStyleBag {
  return base;
}

// Attach helpers for backward compatibility.
(build as any).smallBtn = (active?: boolean) => ({ ...smallBtnBase, ...(active ? smallBtnActive : {}) });
(build as any).smallBtnDanger = (active?: boolean) => ({ ...smallBtnDangerBase, ...(active ? smallBtnActive : {}) });

export const toolStyles = build as ToolStylesFn;
