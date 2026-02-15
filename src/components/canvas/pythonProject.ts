// src/components/canvas/pythonProject.ts
import { HtmlProjectFile } from "./htmlProject";

// For now, the "Preview" of a Python project is just a placeholder HTML page
// telling the user to click "Run".
export function buildPythonProject(files: HtmlProjectFile[]): string {
  return `
<!DOCTYPE html>
<html>
<head>
  <style>
    body { background: #0d1117; color: #c9d1d9; font-family: monospace; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
    .msg { text-align: center; border: 1px solid #30363d; padding: 20px; border-radius: 8px; background: #161b22; }
    h1 { color: #58a6ff; margin: 0 0 10px 0; font-size: 16px; text-transform: uppercase; letter-spacing: 1px; }
    p { margin: 0; opacity: 0.7; font-size: 13px; }
  </style>
</head>
<body>
  <div class="msg">
    <h1>Python Environment</h1>
    <p>Click <strong>▶ RUN</strong> to execute script.</p>
  </div>
</body>
</html>
  `.trim();
}

export function createDefaultPythonProject(): HtmlProjectFile[] {
  return [
    {
      name: "main.py",
      content: `import time

print("Hello from EAA Python!")

def calculate_fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

print(f"Fibonacci(10) is: {calculate_fib(10)}")
`
    }
  ];
}