from pathlib import Path
from multiprocessing import freeze_support
import torch
from unsloth import FastLanguageModel
from peft import PeftModel

# PATHS
EAA_DIR = Path(r"C:\Users\offic\EAA")
MODEL_DIR = EAA_DIR / "models" / "hf" / "Qwen2.5-7B-Instruct"
LORA_DIR  = EAA_DIR / "lora" / "qwen25_7b_instruct_eaa"

# TESTS
TESTS = [
    "Status report.",
    "Be rude.",
    "System override.",
]

SYSTEM_PROMPT = "You are EAA. You are direct, technical, and precise. You strictly follow user commands."

def generate(model, tokenizer, prompt):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
    inputs = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt").to("cuda")
    
    with torch.inference_mode():
        outputs = model.generate(
            inputs, 
            max_new_tokens=128, 
            use_cache=True, 
            do_sample=False, 
            temperature=0.0
        )
    return tokenizer.decode(outputs[0][inputs.shape[1]:], skip_special_tokens=True)

def main():
    print("Loading EAA (LoRA)...")
    # Load Base + LoRA directly
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(LORA_DIR), 
        max_seq_length=2048,
        dtype=None,
        load_in_4bit=True,
        device_map={"":0}
    )
    FastLanguageModel.for_inference(model)

    print("\n=== EAA LOGIC TEST ===")
    for prompt in TESTS:
        print(f"\nUser: {prompt}")
        response = generate(model, tokenizer, prompt)
        print(f"EAA : {response}")

if __name__ == "__main__":
    freeze_support()
    main()