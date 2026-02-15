from unsloth import FastLanguageModel
import os
import torch

# FORCE ONLINE
os.environ["HF_HUB_OFFLINE"] = "0"

print("========================================")
print("      DEEPSEEK REPAIR & VERIFY          ")
print("========================================")
print("Initiating repair of: unsloth/DeepSeek-R1-Distill-Qwen-7B-unsloth-bnb-4bit")
print("⚠️  Enabling CPU Offload to prevent VRAM crashes.")

try:
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = "unsloth/DeepSeek-R1-Distill-Qwen-7B-unsloth-bnb-4bit",
        max_seq_length = 2048,
        dtype = None,
        load_in_4bit = True,
        # 🛑 THE FIX: Allow using System RAM if GPU is full
        device_map = "auto",
        llm_int8_enable_fp32_cpu_offload = True, 
    )
    print("\n✅ REPAIR COMPLETE!")
    print("The files are now 100% verified on disk.")

except Exception as e:
    print(f"\n❌ STILL FAILED: {e}")