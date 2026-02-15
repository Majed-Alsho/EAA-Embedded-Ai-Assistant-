from huggingface_hub import snapshot_download
import os

# FORCE ONLINE
os.environ["HF_HUB_OFFLINE"] = "0"

MODELS_TO_FIX = [
    "unsloth/DeepSeek-R1-Distill-Qwen-7B-unsloth-bnb-4bit",
    "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit"
]

print("========================================")
print("      VRAM-FREE BRAIN REPAIR            ")
print("========================================")

for model_id in MODELS_TO_FIX:
    print(f"\n🔍 Checking files for: {model_id}")
    print("   (This uses Internet, but NO GPU Memory)")
    
    try:
        path = snapshot_download(
            repo_id=model_id,
            revision="main",
            force_download=False, # Only download missing files
            local_files_only=False
        )
        print(f"✅ SUCCESS! Files located at: {path}")
    except Exception as e:
        print(f"❌ DOWNLOAD FAILED: {e}")

print("\n========================================")
print("Repair Complete. You can now run the agent.")