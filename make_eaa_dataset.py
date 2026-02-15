from pathlib import Path
import json
import random

EAA_DIR = Path(r"C:\Users\offic\EAA")
OUT = EAA_DIR / "train_data" / "eaa_train.jsonl"
OUT.parent.mkdir(parents=True, exist_ok=True)

APP = "EAA (Embedded AI Assistant)"
MODES = (
    "Normal = qwen2.5:7b-instruct\n"
    "Thinking = phi4-reasoning:plus\n"
    "Extended = phi4-reasoning:plus (extended thinking settings)"
)
RUN = "cd %USERPROFILE%\\EAA\nnpm run tauri dev"

facts = [
    ("What is my app called?", f"Your app is called {APP}."),
    ("What does EAA stand for?", "EAA stands for Embedded AI Assistant."),
    ("What are my 3 brain modes?", f"{MODES}"),
    ("How do I start the app?", f"Run:\n{RUN}"),
    ("Give me the exact start command, no extra text.", RUN),
    ("Where is the project folder?", r"C:\Users\offic\EAA"),
    ("What GPU do I have?", "NVIDIA GeForce RTX 4060 Ti."),
    ("How should you reply?", "Direct. Clear. No filler. No babysitting."),
]

# Variations (same facts, different wording)
prompts = [
    "Name the app.",
    "What’s the assistant called?",
    "Tell me the three modes.",
    "List the brain modes exactly.",
    "What model is used in Normal mode?",
    "What model is used in Thinking mode?",
    "What model is used in Extended mode?",
    "How do I run EAA in dev?",
    "What’s the command to start tauri dev?",
]

def answer(p: str) -> str:
    p_low = p.lower()
    if "name" in p_low or "called" in p_low:
        return f"{APP}."
    if "three" in p_low or "3" in p_low or "modes" in p_low:
        return MODES
    if "normal" in p_low:
        return "Normal = qwen2.5:7b-instruct"
    if "thinking" in p_low:
        return "Thinking = phi4-reasoning:plus"
    if "extended" in p_low:
        return "Extended = phi4-reasoning:plus (extended thinking settings)"
    if "start" in p_low or "run" in p_low or "tauri" in p_low or "dev" in p_low:
        return f"Run:\n{RUN}"
    return "EAA stands for Embedded AI Assistant. Be direct and helpful."

rows = []

# Seed core facts multiple times
for _ in range(60):
    p, r = random.choice(facts)
    rows.append({"prompt": p, "response": r})

# Add prompt variations
for _ in range(240):
    p = random.choice(prompts)
    rows.append({"prompt": p, "response": answer(p)})

# Write UTF-8 clean JSONL
with OUT.open("w", encoding="utf-8", newline="\n") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

print("WROTE", len(rows), "lines to", OUT)
