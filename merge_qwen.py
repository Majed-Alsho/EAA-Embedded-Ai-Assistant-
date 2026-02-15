import os
import argparse
from pathlib import Path
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


# Default base model (matches your setup)
DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

# Default output folder
DEFAULT_OUT_DIR = "./my_custom_qwen"

# Default places to look if --adapter isn't provided
DEFAULT_SEARCH_DIRS = [
    "./outputs_shadow",
    "./outputs_master",
    "./outputs",
    "./lora",
    ".",  # last resort
]

# Stuff to ignore when scanning recursively
IGNORE_DIR_NAMES = {
    ".git", ".vscode", "__pycache__", "node_modules",
    ".venv", ".venv-hf", "cache", "datasets", "unsloth_compiled_cache",
    "_unsloth_sentencepiece_temp",
}


def _is_ignored(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    return any(name.lower() in parts for name in IGNORE_DIR_NAMES)


def _normalize_adapter_path(p: str) -> Path:
    """
    Accepts either:
      - a folder containing adapter_model.safetensors/bin
      - OR a direct path to adapter_model.safetensors/bin
    Returns the adapter folder.
    """
    path = Path(p).expanduser().resolve()

    if path.is_file() and path.name in ("adapter_model.safetensors", "adapter_model.bin"):
        return path.parent

    return path


def _has_adapter_files(folder: Path) -> bool:
    return (folder / "adapter_model.safetensors").exists() or (folder / "adapter_model.bin").exists()


def find_adapters(search_roots):
    """
    Recursively search for adapter_model.safetensors/bin under given roots.
    Returns list of tuples: (adapter_folder, mtime) sorted newest-first.
    """
    found = {}

    for root in search_roots:
        root_path = Path(root).expanduser().resolve()
        if not root_path.exists():
            continue

        for p in root_path.rglob("*"):
            if _is_ignored(p):
                continue

            if p.name in ("adapter_model.safetensors", "adapter_model.bin"):
                adapter_dir = p.parent
                try:
                    ts = p.stat().st_mtime
                except OSError:
                    continue

                # keep newest mtime for that adapter directory
                if adapter_dir not in found or ts > found[adapter_dir]:
                    found[adapter_dir] = ts

    # newest first
    return sorted(found.items(), key=lambda x: x[1], reverse=True)


def merge_model(base_model_name: str, adapter_dir: Path, out_dir: Path):
    print("=== Starting Model Merge ===")
    print(f"Base Model:     {base_model_name}")
    print(f"Adapter Folder: {adapter_dir}")
    print(f"Output Folder:  {out_dir}")
    print()

    if not adapter_dir.exists():
        raise FileNotFoundError(f"Adapter folder does not exist: {adapter_dir}")

    if not _has_adapter_files(adapter_dir):
        raise FileNotFoundError(
            f"No adapter_model.safetensors/bin found in: {adapter_dir}"
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    print("1) Loading base model (this can take a bit)...")
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )

    print("2) Loading LoRA adapter...")
    model = PeftModel.from_pretrained(base_model, str(adapter_dir))

    print("3) Merging weights...")
    model = model.merge_and_unload()

    print("4) Saving merged model...")
    model.save_pretrained(str(out_dir), safe_serialization=True)

    print("5) Saving tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)
    tokenizer.save_pretrained(str(out_dir))

    print()
    print("SUCCESS ✅")
    print(f"Merged model saved to: {out_dir}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Merge Qwen base model + LoRA adapter into a standalone model.")
    parser.add_argument("--base", default=DEFAULT_BASE_MODEL, help="Base model name or local path")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR, help="Output folder for merged model")
    parser.add_argument("--adapter", default=None, help="Adapter folder (or path to adapter_model.safetensors/bin)")
    parser.add_argument("--scan", action="store_true", help="Ignore --adapter and auto-pick newest adapter found")
    args = parser.parse_args()

    base_model_name = args.base
    out_dir = Path(args.out).expanduser().resolve()

    chosen_adapter_dir = None

    if args.scan or not args.adapter:
        print("Scanning for adapters (adapter_model.safetensors/bin)...")
        adapters = find_adapters(DEFAULT_SEARCH_DIRS)

        if not adapters:
            print("\nERROR: No adapters found under these folders:")
            for d in DEFAULT_SEARCH_DIRS:
                print(" -", Path(d).expanduser().resolve())
            print("\nTip: you can pass one directly:")
            print(r'  python .\merge_qwen.py --adapter ".\outputs_shadow\checkpoint-750"')
            return

        print("\nFound adapters (newest first):")
        for i, (folder, ts) in enumerate(adapters[:15], start=1):
            tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
            print(f"{i:>2}. {folder}   (mtime {tstr})")

        chosen_adapter_dir = adapters[0][0]
        print(f"\nUsing newest adapter: {chosen_adapter_dir}\n")
    else:
        chosen_adapter_dir = _normalize_adapter_path(args.adapter)

    try:
        merge_model(base_model_name, chosen_adapter_dir, out_dir)
    except Exception as e:
        print("ERROR:", e)


if __name__ == "__main__":
    main()
