from unsloth import FastLanguageModel
import os
import sys

# 1. Force Online Mode to ensure we can reach the server
os.environ["HF_HUB_OFFLINE"] = "0"

print("========================================")
print("      EAA BRAIN DOWNLOADER              ")
print("========================================")
print("Initiating full download of: unsloth/Qwen2.5-7B-Instruct-bnb-4bit")
print("⚠️  SIZE: Approx 5.5 GB")
print("⚠️  STATUS: Please wait. If this freezes, restart the script.")
print("----------------------------------------")

try:
    # This function automatically handles the download and caching
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
        max_seq_length = 2048,
        dtype = None,
        load_in_4bit = True,
    )
    print("\n========================================")
    print("✅ DOWNLOAD COMPLETE!")
    print("========================================")
    print("The model is now permanently saved to your disk.")
    print("You can now run 'run_eaa_agent.py' safely.")

except Exception as e:
    print(f"\n❌ DOWNLOAD FAILED: {e}")
    print("Tip: Check your internet connection and try running this script again.")