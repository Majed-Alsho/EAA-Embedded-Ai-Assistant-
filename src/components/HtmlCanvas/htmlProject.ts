import type { HtmlProjectFile } from "./types";

export function monacoLangFromName(name: string) {
  const lower = (name || "").toLowerCase();
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  if (lower.endsWith(".css")) return "css";
  if (lower.endsWith(".ts")) return "typescript";
  if (lower.endsWith(".tsx")) return "typescript";
  if (lower.endsWith(".jsx")) return "javascript";
  if (lower.endsWith(".js")) return "javascript";
  if (lower.endsWith(".mjs")) return "javascript";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".md")) return "markdown";
  return "plaintext";
}

export function getFile(files: HtmlProjectFile[], name: string) {
  return files.find((f) => f.name === name) ?? null;
}

export function setFileContent(files: HtmlProjectFile[], name: string, content: string) {
  let found = false;
  const next = files.map((f) => {
    if (f.name !== name) return f;
    found = true;
    return { ...f, content };
  });
  if (!found) next.push({ name, content });
  return next;
}

export function removeFile(files: HtmlProjectFile[], name: string) {
  return files.filter((f) => f.name !== name);
}

export function hasFile(files: HtmlProjectFile[], name: string) {
  return !!getFile(files, name);
}

export function renameFile(files: HtmlProjectFile[], oldName: string, newName: string) {
  const o = (oldName || "").trim();
  const n = (newName || "").trim();
  if (!o || !n) return { ok: false as const, files, error: "Bad name" };
  if (o === n) return { ok: true as const, files };

  if (!getFile(files, o)) return { ok: false as const, files, error: `Missing file: ${o}` };
  if (getFile(files, n)) return { ok: false as const, files, error: `File exists: ${n}` };

  const next = files.map((f) => (f.name === o ? { ...f, name: n } : f));
  return { ok: true as const, files: next };
}

function splitExt(name: string) {
  const idx = name.lastIndexOf(".");
  if (idx <= 0) return { base: name, ext: "" };
  return { base: name.slice(0, idx), ext: name.slice(idx) };
}

export function makeUniqueName(files: HtmlProjectFile[], desired: string) {
  const d = (desired || "").trim();
  if (!d) return "";

  if (!hasFile(files, d)) return d;

  const { base, ext } = splitExt(d);
  for (let i = 2; i < 500; i++) {
    const candidate = `${base}-${i}${ext}`;
    if (!hasFile(files, candidate)) return candidate;
  }
  return `${base}-${Date.now()}${ext}`;
}

export function duplicateFile(files: HtmlProjectFile[], name: string, desiredName?: string) {
  const src = getFile(files, name);
  if (!src) return { ok: false as const, files, error: `Missing file: ${name}`, created: "" };

  const { base, ext } = splitExt(src.name);
  const want = (desiredName || `${base}-copy${ext}`).trim();
  const created = makeUniqueName(files, want);

  const next = [...files, { name: created, content: src.content }];
  return { ok: true as const, files: next, created };
}

function normalizeIndexHtml(indexHtml: string, files: HtmlProjectFile[]) {
  // Strip <link href="*.css"> and <script src="*.js"> that point to project files,
  // because we inline all project CSS/JS into the preview.
  let out = indexHtml;

  for (const f of files) {
    const n = f.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

    if (f.name.toLowerCase().endsWith(".css")) {
      const re = new RegExp(`<link[^>]*href=["']${n}["'][^>]*>\\s*`, "gi");
      out = out.replace(re, "");
    }

    if (f.name.toLowerCase().endsWith(".js") || f.name.toLowerCase().endsWith(".mjs")) {
      const re = new RegExp(`<script[^>]*src=["']${n}["'][^>]*>\\s*<\\/script>\\s*`, "gi");
      out = out.replace(re, "");
    }
  }

  return out;
}

function injectIntoHtml(indexHtml: string, cssText: string, jsText: string, bridgeJs: string) {
  const styleBlock = cssText.trim() ? `\n<style>\n${cssText}\n</style>\n` : "\n";

  // Bridge must load BEFORE user JS so it catches early console/errors.
  const bridgeBlock = bridgeJs.trim() ? `\n<script>\n${bridgeJs}\n</script>\n` : "\n";

  // module keeps future imports viable
  const userScriptBlock = jsText.trim()
    ? `\n<script type="module">\n${jsText}\n</script>\n`
    : "\n";

  let out = indexHtml;

  if (out.includes("</head>")) out = out.replace("</head>", `${styleBlock}</head>`);
  else out = `${styleBlock}${out}`;

  if (out.includes("</body>")) out = out.replace("</body>", `${bridgeBlock}${userScriptBlock}</body>`);
  else out = `${out}${bridgeBlock}${userScriptBlock}`;

  return out;
}

/**
 * Bridge:
 * - console.* -> parent postMessage
 * - window error / unhandledrejection -> parent postMessage
 *
 * Parent filters using sessionId (sid).
 */
export function buildBridgeJs(sessionId: string) {
  const sid = JSON.stringify(sessionId);

  return `
(function(){
  const SID = ${sid};

  function safeToString(x){
    try {
      if (typeof x === "string") return x;
      if (x instanceof Error) return x.stack || x.message || String(x);
      return JSON.stringify(x);
    } catch {
      try { return String(x); } catch { return "[unprintable]"; }
    }
  }

  function send(kind, level, args){
    try {
      parent.postMessage({
        type: "EAA_HTML_BRIDGE",
        sid: SID,
        kind,
        level,
        args: (args || []).map(safeToString)
      }, "*");
    } catch {}
  }

  const orig = {
    log: console.log,
    warn: console.warn,
    error: console.error,
    info: console.info,
    debug: console.debug,
  };

  ["log","warn","error","info","debug"].forEach((k) => {
    const fn = orig[k] || console.log;
    console[k] = function(...args){
      send("console", k, args);
      return fn.apply(console, args);
    };
  });

  window.addEventListener("error", (ev) => {
    send("error", "error", [ev.message, ev.filename, String(ev.lineno), String(ev.colno)]);
  });

  window.addEventListener("unhandledrejection", (ev) => {
    send("rejection", "error", [safeToString(ev.reason)]);
  });
})();`.trim();
}

export function buildHtmlProject(files: HtmlProjectFile[], sessionId: string) {
  const index =
    getFile(files, "index.html")?.content ??
    "<!doctype html><html><head></head><body></body></html>";

  const css = files
    .filter((f) => f.name.toLowerCase().endsWith(".css"))
    .map((f) => `/* ${f.name} */\n${f.content}\n`)
    .join("\n");

  const js = files
    .filter((f) => f.name.toLowerCase().endsWith(".js") || f.name.toLowerCase().endsWith(".mjs"))
    .map((f) => `// ${f.name}\n${f.content}\n`)
    .join("\n");

  const cleanedIndex = normalizeIndexHtml(index, files);
  const bridgeJs = buildBridgeJs(sessionId);
  return injectIntoHtml(cleanedIndex, css, js, bridgeJs);
}

export function htmlToDataUrl(html: string) {
  return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`;
}
