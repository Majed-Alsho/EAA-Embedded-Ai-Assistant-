// src/components/canvas/docProject.ts

import { HtmlProjectFile } from "./htmlProject";

// A lightweight Markdown-to-HTML parser (Zero-Dependency)
// Handles: Headers, Lists, Code Blocks, Bold, Links
function parseMarkdown(md: string): string {
  let html = md ?? "";

  // Escape HTML characters first to prevent injection
  html = html
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Code Blocks (```)
  html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');

  // Inline Code (`)
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Headers
  html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>');
  html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>');
  html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>');

  // Bold / Italic
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // Lists
  html = html.replace(/^\* (.*$)/gm, '<ul><li>$1</li></ul>');
  html = html.replace(/^- (.*$)/gm, '<ul><li>$1</li></ul>');
  // Fix nested uls (simple hack)
  html = html.replace(/<\/ul>\s*<ul>/g, '');

  // Blockquotes
  html = html.replace(/^> (.*$)/gm, '<blockquote>$1</blockquote>');

  // Links [text](url)
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

  // Paragraphs (newlines become <br> or <p>)
  html = html.replace(/\n\n/g, '</p><p>');
  html = html.replace(/\n/g, '<br />');

  // Wrap in p
  return `<p>${html}</p>`;
}

export function buildDocProject(files: HtmlProjectFile[]): string {
  // Docs usually just have one main file, e.g. "README.md" or "plan.md"
  // We find the active markdown file or default to the first one.
  const mainFile = files.find(f => f.name.endsWith('.md')) || files[0];
  const content = mainFile ? mainFile.content : "# No document found";

  const bodyHtml = parseMarkdown(content);

  // We inject a nice "Google Docs" style CSS
  return `
<!DOCTYPE html>
<html>
<head>
  <style>
    body {
      background: #fdfdfd;
      color: #1f2937;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Georgia, serif;
      line-height: 1.6;
      padding: 40px;
      max-width: 800px;
      margin: 0 auto;
    }
    /* Dark mode support if iframe matches system */
    @media (prefers-color-scheme: dark) {
      body { background: #0d1117; color: #c9d1d9; }
      a { color: #58a6ff; }
      code { background: #161b22 !important; border-color: #30363d !important; }
      blockquote { border-left-color: #30363d !important; color: #8b949e !important; }
      hr { border-color: #30363d !important; }
    }

    h1, h2, h3 { color: inherit; margin-top: 1.5em; margin-bottom: 0.5em; font-weight: 700; line-height: 1.25; }
    h1 { font-size: 2.25em; border-bottom: 1px solid rgba(0,0,0,0.1); padding-bottom: 0.3em; }
    h2 { font-size: 1.75em; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 0.3em; }
    h3 { font-size: 1.5em; }
    
    p { margin-bottom: 1em; }
    
    a { color: #0969da; text-decoration: none; }
    a:hover { text-decoration: underline; }

    code {
      font-family: "ui-monospace", "SFMono-Regular", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 0.9em;
      background: #f6f8fa;
      padding: 0.2em 0.4em;
      border-radius: 6px;
    }
    
    pre {
      background: #f6f8fa;
      padding: 16px;
      overflow: auto;
      border-radius: 6px;
      margin-bottom: 1.2em;
    }
    pre code { background: transparent; padding: 0; }

    blockquote {
      margin: 0 0 1em;
      padding: 0 1em;
      color: #57606a;
      border-left: 0.25em solid #d0d7de;
    }

    ul, ol { padding-left: 2em; margin-bottom: 1em; }
    li { margin-bottom: 0.25em; }
    li + li { margin-top: 0.25em; }

    img { max-width: 100%; box-sizing: border-box; }
  </style>
</head>
<body>
  ${bodyHtml}
</body>
</html>
  `.trim();
}

export function createDefaultDocProject(): HtmlProjectFile[] {
  return [
    {
      name: "plan.md",
      content: `# Project Plan

This is a **markdown document**.

## Features to build
* [x] Artifact System
* [x] HTML Preview
* [ ] Python Runner
* [ ] AI Integration

## Code Example
\`\`\`js
console.log("Hello Docs!");
\`\`\`

> "Gemini Canvas is a state, not a scroll."
`
    }
  ];
}