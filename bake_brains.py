import os
import torch
from unsloth import FastLanguageModel

LORA_DIR = "lora/master_qwen"
OUTPUT_DIR = "lora/master_qwen_merged"

def bake():
    print(f"🍳 EAA BAKERY: WINDOWS MODE")
    print(f"Loading Adapter: {LORA_DIR}")

    # 1. Load
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = LORA_DIR,
        max_seq_length = 2048,
        dtype = None,
        load_in_4bit = True,
    )

    # 2. Save as Merged 16-bit (Foolproof method)
    # This creates a larger folder, but it ALWAYS works on Windows.
    print(f"Saving merged model to: {OUTPUT_DIR}...")
    model.save_pretrained_merged(
        OUTPUT_DIR, 
        tokenizer, 
        save_method = "merged_16bit",
    )
    print("✅ DONE. Model merged.")

if __name__ == "__main__":
    bake()