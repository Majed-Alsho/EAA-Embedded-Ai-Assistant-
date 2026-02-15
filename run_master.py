import os
import sys
import warnings
import torch
import uvicorn
from threading import Thread
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template
from transformers import TextIteratorStreamer

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ==========================================
#   DIAGNOSTIC CONFIG
# ==========================================
EAA_DIR = r"C:\Users\offic\EAA"
MODEL_ID = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
MASTER_LORA = os.path.join(EAA_DIR, "lora", "master_qwen")

# STRICT SYSTEM PROMPT (To test compliance)
MASTER_SYS = (
    "You are the Master Control Program. "
    "CORE DIRECTIVES: 1. ACKNOWLEDGE intent. 2. CHECK risks. "
    "3. GATEKEEPER: If High Risk, STOP. "
    "STYLE: Military brevity."
)

MAX_SEQ = 2048
MAX_NEW = 512

# GLOBAL STATE
current_model = None
current_tokenizer = None

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    messages: List[dict]
    model: Optional[str] = None
    stream: bool = False

def load_master():
    global current_model, current_tokenizer
    
    if current_model is not None: return

    print(f"\n[DIAGNOSTIC] 🛡️ Loading MASTER BRAIN ONLY...")
    print(f"[PATH] {MASTER_LORA}")

    try:
        # 1. Load Base
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=MODEL_ID,
            max_seq_length=MAX_SEQ,
            dtype=None,
            load_in_4bit=True,
            device_map="auto",
        )

        # 2. Force Load Master Adapter
        if os.path.exists(MASTER_LORA):
            print("[STATUS] Found Adapter. Attaching...")
            model.load_adapter(MASTER_LORA)
        else:
            print(f"[CRITICAL FAILURE] Master Adapter NOT FOUND at {MASTER_LORA}")
            print("You are running raw Qwen (Generic Mode).")

        current_model = FastLanguageModel.for_inference(model)
        current_tokenizer = get_chat_template(tokenizer, chat_template="chatml")
        print("[STATUS] System Online.")

    except Exception as e:
        print(f"[ERROR] Crash during load: {e}")
        sys.exit(1)

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    load_master()
    
    user_input = req.messages[-1]['content']
    print(f"\n[USER]: {user_input}")

    # Build Prompt
    messages = [
        {"role": "system", "content": MASTER_SYS},
        {"role": "user", "content": user_input}
    ]
    
    inputs = current_tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
    ).to("cuda")

    streamer = TextIteratorStreamer(current_tokenizer, skip_prompt=True, skip_special_tokens=True)
    
    generation_kwargs = dict(
        input_ids=inputs,
        streamer=streamer,
        max_new_tokens=MAX_NEW,
        temperature=0.3, # Low temp for strict testing
    )

    thread = Thread(target=current_model.generate, kwargs=generation_kwargs)
    thread.start()

    def stream_generator():
        full_text = ""
        for new_text in streamer:
            full_text += new_text
            yield new_text
        print(f"[MASTER]: {full_text.strip()}")

    return StreamingResponse(stream_generator(), media_type="text/plain")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)