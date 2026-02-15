// src/components/canvas/htmlProject.ts

export type HtmlProjectFile = {
  name: string; // e.g. index.html, styles.css, app.js
  content: string;
};

const CANVAS_SOURCE_PREFIX = "eaa-canvas:///";

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
  if (lower.endsWith(".py")) return "python"; // <--- ADDED THIS
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

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeIndexHtml(indexHtml: string, files: HtmlProjectFile[]) {
  // Remove local <link href="X.css"> and <script src="X.js"> for project files,
  // because we handle them via Blob loading or inlining.
  let out = indexHtml;

  for (const f of files) {
    const n = escapeRe(f.name);
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

/**
 * Runtime patch (The "Spy")
 */
function runtimePatch(): string {
  const sourceName = `${CANVAS_SOURCE_PREFIX}eaa_runtime_patch.js`;
  return `
<script>
(function(){
  // =========================
  // EAA Canvas Console & Network Bridge
  // =========================
  try {
    if (!window.__EAA_CANVAS_CONSOLE_BRIDGE__) {
      window.__EAA_CANVAS_CONSOLE_BRIDGE__ = true;

      function safeStr(x){
        try {
          if (typeof x === "string") return x;
          if (x instanceof Error) return (x.stack || (x.name + ": " + x.message));
          return JSON.stringify(x);
        } catch (e) {
          try { return String(x); } catch { return "[unprintable]"; }
        }
      }

      function post(level, parts, extra){
        try {
          var payload = {
            __eaa_canvas_console_v2: true,
            level: level,
            args: (parts || []).map(safeStr),
            ts: Date.now()
          };
          if (extra) {
             if (extra.stack) payload.stack = String(extra.stack);
             if (extra.where) payload.where = String(extra.where);
             if (extra.tag) payload.tag = String(extra.tag);
          }
          if (window.parent && window.parent !== window) {
            window.parent.postMessage(payload, "*");
          }
        } catch {}
      }

      // 1. Console Hooks
      var levels = ["log","warn","error"];
      for (var i=0;i<levels.length;i++){
        (function(level){
          var orig = (console && console[level]) ? console[level].bind(console) : function(){};
          console[level] = function(){
            try { post(level, Array.prototype.slice.call(arguments)); } catch {}
            try { return orig.apply(console, arguments); } catch {}
          };
        })(levels[i]);
      }

      // 2. Global Error Hooks
      window.addEventListener("error", function(e){
        try {
          var msg = e && e.message ? e.message : "Unknown error";
          var where = (e && e.filename) ? (e.filename + ":" + (e.lineno || 0) + ":" + (e.colno || 0)) : "";
          var stack = (e && e.error && e.error.stack) ? e.error.stack : "";
          post("error", ["[runtime error] " + msg], { stack: stack, where: where, tag: "runtime" });
        } catch {}
      });

      window.addEventListener("unhandledrejection", function(e){
        try {
          var r = e && e.reason;
          var stack = (r && r.stack) ? r.stack : "";
          post("error", ["[unhandled rejection]", safeStr(r)], { stack: stack, tag: "rejection" });
        } catch {}
      });

      // 3. Network Spy (Fetch)
      var _fetch = window.fetch;
      if (_fetch) {
        window.fetch = function(url, options) {
          var method = (options && options.method) ? options.method.toUpperCase() : "GET";
          var u = String(url);
          post("log", [method + " " + u + " (pending)"], { tag: "fetch" });
          
          var p = _fetch.apply(this, arguments);
          p.then(function(res){
             post("log", [method + " " + u + " " + res.status + " " + res.statusText], { tag: "fetch" });
          }, function(err){
             post("error", [method + " " + u + " FAILED", safeStr(err)], { tag: "fetch" });
          });
          return p;
        };
      }

      // 4. Network Spy (XHR)
      var _xhr = window.XMLHttpRequest;
      if (_xhr) {
        var _open = _xhr.prototype.open;
        _xhr.prototype.open = function(method, url) {
          this._eaa_method = method;
          this._eaa_url = url;
          try { return _open.apply(this, arguments); } catch(e) { throw e; }
        };
        var _send = _xhr.prototype.send;
        _xhr.prototype.send = function() {
          var self = this;
          var label = (self._eaa_method || "REQ") + " " + (self._eaa_url || "?");
          post("log", [label + " (pending)"], { tag: "xhr" });
          
          self.addEventListener("load", function(){
             post("log", [label + " " + self.status], { tag: "xhr" });
          });
          self.addEventListener("error", function(){
             post("error", [label + " FAILED"], { tag: "xhr" });
          });
          try { return _send.apply(this, arguments); } catch(e) { throw e; }
        };
      }
    }
  } catch {}

  // =========================
  // Inspector System
  // =========================
  (function(){
    var inspectMode = false;
    var overlay = document.createElement('div');
    overlay.style.position = 'fixed';
    overlay.style.pointerEvents = 'none';
    overlay.style.background = 'rgba(0, 234, 255, 0.2)';
    overlay.style.border = '2px solid #00eaff';
    overlay.style.zIndex = '999999';
    overlay.style.display = 'none';
    overlay.id = 'eaa-inspector-overlay';
    document.documentElement.appendChild(overlay);

    function handleMouseOver(e) {
      if (!inspectMode) return;
      var el = e.target;
      if (el === document.documentElement || el === document.body) {
        overlay.style.display = 'none';
        return;
      }
      var r = el.getBoundingClientRect();
      overlay.style.display = 'block';
      overlay.style.top = r.top + 'px';
      overlay.style.left = r.left + 'px';
      overlay.style.width = r.width + 'px';
      overlay.style.height = r.height + 'px';
    }

    function handleClick(e) {
      if (!inspectMode) return;
      e.preventDefault();
      e.stopPropagation();
      
      var el = e.target;
      var info = {
        tagName: el.tagName.toLowerCase(),
        id: el.id || '',
        className: el.className || '',
        innerText: (el.innerText || '').slice(0, 50)
      };

      window.parent.postMessage({
        __eaa_canvas_inspector_hit: true,
        info: info
      }, '*');

      inspectMode = false;
      overlay.style.display = 'none';
    }

    window.addEventListener('message', function(e) {
      var d = e.data;
      if (!d) return;
      if (d.type === 'EAA_TOGGLE_INSPECT') {
        inspectMode = !!d.value;
        if (!inspectMode) overlay.style.display = 'none';
      }
    });

    document.addEventListener('mouseover', handleMouseOver, true);
    document.addEventListener('click', handleClick, true);
  })();

  // =========================
  // Navigation & Scroll Locks
  // =========================
  function forceScroll(){
    try {
      document.documentElement.style.overflow = "auto";
      document.documentElement.style.height = "auto";
      if (document.body) {
        document.body.style.overflow = "auto";
        document.body.style.height = "auto";
      }
    } catch {}
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", forceScroll, { once: true });
  } else {
    forceScroll();
  }

  document.addEventListener("click", function(e){
    var t = e.target;
    if (!t) return;
    var a = t.closest ? t.closest("a") : null;
    if (!a) return;
    var href = (a.getAttribute("href") || "").trim();
    if (!href || href === "#") { e.preventDefault(); return; }
    if (href[0] === "#") {
      e.preventDefault();
      var id = href.slice(1);
      var el = document.getElementById(id);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (/^javascript:/i.test(href)) return;
    e.preventDefault();
    console.warn("[EAA] Navigation blocked: " + href);
  }, true);

  document.addEventListener("submit", function(e){
    e.preventDefault();
    console.warn("[EAA] Form submit blocked");
  }, true);
})();

//# sourceURL=${sourceName}
</script>
`.trim();
}

function buildBlobLoader(files: HtmlProjectFile[]): string {
  const jsFiles = files.filter((f) => {
    const n = f.name.toLowerCase();
    return n.endsWith(".js") || n.endsWith(".mjs");
  });

  if (jsFiles.length === 0) return "";

  const payload = JSON.stringify(
    jsFiles.map(f => ({
      name: f.name,
      content: f.content + `\n\n//# sourceURL=${CANVAS_SOURCE_PREFIX}${f.name}`
    }))
  );

  return `
<script>
(function() {
  var scripts = ${payload};
  scripts.forEach(function(f) {
    try {
      var blob = new Blob([f.content], { type: 'application/javascript' });
      var url = URL.createObjectURL(blob);
      var s = document.createElement('script');
      s.src = url;
      s.dataset.eaaName = f.name; 
      document.body.appendChild(s);
    } catch(e) {
      console.error("Failed to load script " + f.name, e);
    }
  });
})();
</script>
  `.trim();
}

function injectIntoHtml(indexHtml: string, cssText: string, blobLoaderHtml: string) {
  const styleBlock = cssText.trim() ? `\n<style>\n${cssText}\n</style>\n` : "\n";
  const patchBlock = `\n${runtimePatch()}\n`;
  const scriptsBlock = blobLoaderHtml.trim() ? `\n${blobLoaderHtml}\n` : "\n";

  let out = indexHtml;

  if (out.includes("</head>")) out = out.replace("</head>", `${styleBlock}</head>`);
  else out = `${styleBlock}${out}`;

  if (out.includes("</body>")) out = out.replace("</body>", `${patchBlock}${scriptsBlock}</body>`);
  else out = `${out}${patchBlock}${scriptsBlock}`;

  return out;
}

export function buildHtmlProject(files: HtmlProjectFile[]) {
  const indexRaw = getFile(files, "index.html")?.content ?? "<!doctype html><html><head></head><body></body></html>";

  const css = files
    .filter((f) => f.name.toLowerCase().endsWith(".css"))
    .map((f) => `/* ${f.name} */\n${f.content}\n`)
    .join("\n");

  const blobLoader = buildBlobLoader(files);
  const cleanedIndex = normalizeIndexHtml(indexRaw, files);
  
  return injectIntoHtml(cleanedIndex, css, blobLoader);
}

export function createDefaultHtmlProject(): HtmlProjectFile[] {
  // same as before (omitted for brevity, assume standard implementation)
  return [
    { name: "app.js", content: `console.log("App started");` },
    { name: "index.html", content: `<!DOCTYPE html><html><body><h1>Hello</h1></body></html>` },
    { name: "styles.css", content: `body{background:#111;color:#fff}` },
  ];
}