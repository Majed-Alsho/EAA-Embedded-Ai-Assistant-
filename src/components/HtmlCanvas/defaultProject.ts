import type { HtmlProjectFile } from "./types";

export function createDefaultHtmlProject(): HtmlProjectFile[] {
  const index = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0" />
  <title>EAA | Embedded AI Assistant</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <div class="bg">
    <header class="top">
      <div class="brand">
        <span class="dot"></span>
        <span class="name">EAA</span>
      </div>

      <nav class="nav">
        <button class="navbtn">OVERVIEW</button>
        <button class="navbtn">INTELLIGENCE</button>
        <button class="navbtn">GENERATIVE</button>
      </nav>

      <button id="dl" class="dl">DOWNLOAD v1.0</button>
    </header>

    <main class="wrap">
      <section class="card">
        <div class="pill">LOCAL SERVER • ONLINE</div>

        <h1 class="title">
          <span>AI THAT</span>
          <span class="grad">SHIPS WORK</span>
        </h1>

        <p class="sub">
          A local desktop assistant built with Tauri + React. It's ChatGPT inside your app, but with permission to touch files,
          run checks, preview UI, and generate media.
        </p>

        <div class="row">
          <button id="explore" class="btn pri">EXPLORE FEATURES</button>
          <button id="docs" class="btn">VIEW DOCS</button>
        </div>

        <div id="out" class="out"></div>
      </section>
    </main>
  </div>

  <script src="app.js"></script>
</body>
</html>`;

  const css = `:root{
  --bg:#070a0f;
  --fg:#e6edf3;
  --muted:rgba(230,237,243,.70);
  --line:rgba(255,255,255,.12);
  --glass:rgba(13,18,28,.75);
  --shadow:0 18px 60px rgba(0,0,0,.55);
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;
  font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;
  background:var(--bg);
  color:var(--fg);
  overflow:hidden;
}
.bg{
  height:100%;
  width:100%;
  background:
    radial-gradient(1200px 800px at 50% 40%, rgba(0,255,204,.10), transparent 55%),
    radial-gradient(1000px 700px at 55% 55%, rgba(189,0,255,.10), transparent 55%),
    radial-gradient(900px 600px at 35% 60%, rgba(0,140,255,.10), transparent 60%),
    linear-gradient(180deg, #070a0f, #04060b);
}
.top{
  height:64px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding:0 28px;
}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:.4px}
.brand .dot{
  width:10px;height:10px;border-radius:3px;background:rgba(0,255,204,.9);
  box-shadow:0 0 18px rgba(0,255,204,.55);
}
.nav{display:flex;gap:18px;align-items:center}
.navbtn{
  background:transparent;border:none;color:rgba(230,237,243,.75);
  font-weight:800;font-size:12px;letter-spacing:.6px;
  padding:10px 12px;border-radius:999px;cursor:pointer;
}
.navbtn:hover{background:rgba(255,255,255,.06);color:rgba(230,237,243,.95)}
.dl{
  background:rgba(13,18,28,.75);
  border:1px solid rgba(255,255,255,.14);
  color:var(--fg);
  padding:10px 14px;border-radius:12px;
  font-weight:900;letter-spacing:.4px;
  box-shadow:0 10px 30px rgba(0,0,0,.35);
  cursor:pointer;
}
.dl:hover{transform:translateY(-1px)}
.wrap{
  height:calc(100% - 64px);
  display:flex;
  align-items:center;
  justify-content:center;
  padding:28px;
}
.card{
  width:min(920px,92vw);
  border-radius:20px;
  padding:26px 26px 20px;
  border:1px solid rgba(255,255,255,.12);
  background:linear-gradient(135deg, rgba(0,255,204,.10), rgba(189,0,255,.10));
  box-shadow:var(--shadow);
  position:relative;
  overflow:hidden;
}
.pill{
  position:relative;
  display:inline-flex;align-items:center;gap:8px;
  padding:6px 10px;border-radius:999px;
  border:1px solid rgba(0,255,204,.35);
  background:rgba(0,0,0,.22);
  font-weight:900;font-size:12px;letter-spacing:.5px;
  width:max-content;
}
.title{
  position:relative;
  margin:18px 0 10px;
  font-size:64px;
  line-height:1.0;
  letter-spacing:1px;
}
.grad{
  display:inline-block;
  background:linear-gradient(90deg, rgba(0,255,204,1), rgba(0,140,255,1), rgba(189,0,255,1));
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.sub{
  position:relative;
  margin:0 0 18px;
  max-width:680px;
  color:var(--muted);
  line-height:1.5;
}
.row{position:relative;display:flex;gap:12px;flex-wrap:wrap}
.btn{
  border:1px solid rgba(255,255,255,.14);
  background:rgba(10,14,22,.65);
  color:var(--fg);
  padding:10px 14px;
  border-radius:12px;
  font-weight:900;
  cursor:pointer;
}
.btn:hover{transform:translateY(-1px)}
.btn.pri{
  border-color:rgba(0,255,204,.35);
  box-shadow:0 0 0 1px rgba(0,255,204,.18) inset;
}
.out{
  position:relative;
  margin-top:14px;
  min-height:18px;
  color:rgba(230,237,243,.85);
  font-weight:700;
  font-size:13px;
}`;

  const js = `document.getElementById("explore")?.addEventListener("click", () => {
  console.log("Explore clicked");
  const out = document.getElementById("out");
  if (out) out.textContent = "Explore clicked at " + new Date().toLocaleTimeString();
});

document.getElementById("docs")?.addEventListener("click", () => {
  console.warn("Docs clicked");
  const out = document.getElementById("out");
  if (out) out.textContent = "Docs clicked at " + new Date().toLocaleTimeString();
});

document.getElementById("dl")?.addEventListener("click", () => {
  console.error("Download is a demo button (no backend).");
  const out = document.getElementById("out");
  if (out) out.textContent = "Download pressed (demo)";
});`;

  return [
    { name: "app.js", content: js },
    { name: "index.html", content: index },
    { name: "styles.css", content: css },
  ];
}
