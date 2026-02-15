import React from "react";

type Props = { children: React.ReactNode };

type State = {
  hasError: boolean;
  error?: string;
  stack?: string;
};

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(err: unknown): State {
    const msg = err instanceof Error ? err.message : String(err);
    const stack = err instanceof Error ? err.stack : undefined;
    return { hasError: true, error: msg, stack };
  }

  componentDidCatch(err: unknown) {
    console.error("[EAA] UI crashed:", err);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div
        style={{
          height: "100vh",
          width: "100vw",
          padding: 24,
          boxSizing: "border-box",
          background: "#000",
          color: "#fff",
          fontFamily:
            "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
          overflow: "auto",
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 800, marginBottom: 12 }}>
          UI crashed (this is why you see a black screen).
        </div>
        <div style={{ opacity: 0.85, marginBottom: 12 }}>
          Copy the error below and send it to me.
        </div>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            background: "rgba(255,255,255,0.06)",
            padding: 12,
            borderRadius: 8,
            border: "1px solid rgba(255,255,255,0.12)",
          }}
        >
{String(this.state.error || "")}
{"\n\n"}
{String(this.state.stack || "")}
        </pre>
        <button
          onClick={() => location.reload()}
          style={{
            marginTop: 12,
            padding: "10px 14px",
            borderRadius: 8,
            border: "1px solid rgba(255,255,255,0.2)",
            background: "rgba(255,255,255,0.06)",
            color: "#fff",
            cursor: "pointer",
          }}
        >
          Reload
        </button>
      </div>
    );
  }
}
