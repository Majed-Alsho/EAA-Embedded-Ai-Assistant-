# C:\Users\offic\EAA\test_lora.py
import os
from pathlib import Path
import torch

os.environ["TOKENIZERS_PARALLELISM"] = "false"

EAA_DIR = Path(r"C:\Users\offic\EAA")
MODEL_DIR = EAA_DIR / "models" / "hf" / "Qwen2.5-7B-Instruct"
LORA_DIR  = EAA_DIR / "lora" / "qwen25_7b_instruct_eaa"

import unsloth  # noqa: F401
from unsloth import FastLanguageModel
from peft import PeftModel

def main():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available.")

    torch.cuda.empty_cache()

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(MODEL_DIR),
        max_seq_length=768,
        dtype=None,
        load_in_4bit=True,
        device_map={"": 0},
        local_files_only=True,
    )

    model = PeftModel.from_pretrained(model, str(LORA_DIR), is_trainable=False, local_files_only=True)
    model = FastLanguageModel.for_inference(model)

    messages = [
        {"role": "system", "content": "You are EAA. Be direct and helpful."},
        {"role": "user", "content": "What is my app called and what are my 3 brain modes?"},
    ]

    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda")

    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=160,
            do_sample=False,
            num_beams=1,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id,
        )

    new_tokens = out[0][inputs["input_ids"].shape[-1]:]
    print(tokenizer.decode(new_tokens, skip_special_tokens=True).strip())

if __name__ == "__main__":
    main()
