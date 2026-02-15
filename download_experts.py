from unsloth import FastLanguageModel
import os

# FORCE ONLINE to ensure downloads work
os.environ["HF_HUB_OFFLINE"] = "0"

# --- THE FEDERATION ROSTER ---
# 1. Master: You already have this (Qwen 2.5 7B Instruct)
# 2. Logic Expert: DeepSeek R1 (Distilled Qwen 7B)
# 3. Code Expert: Qwen 2.5 Coder (7B Instruct)

MODELS_TO_DOWNLOAD = [
    "unsloth/DeepSeek-R1-Distill-Qwen-7B-unsloth-bnb-4bit",
    "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"
]

print("========================================")
print("      FEDERATION RECRUITMENT DRIVE      ")
print("========================================")

for model_id in MODELS_TO_DOWNLOAD:
    print(f"\n⬇️  Downloading: {model_id}...")
    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name = model_id,
            max_seq_length = 2048,
            dtype = None,
            load_in_4bit = True,
        )
        print(f"✅ INSTALLED: {model_id}")
    except Exception as e:
        print(f"❌ FAILED: {model_id}")
        print(f"Error: {e}")

print("\n========================================")
print("Recruitment Complete. You are ready for the Federation.")