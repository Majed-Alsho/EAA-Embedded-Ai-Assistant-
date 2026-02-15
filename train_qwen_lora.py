import os
import multiprocessing as mp
import torch

from datasets import load_dataset, Dataset
from transformers import TrainingArguments, Trainer, DataCollatorForLanguageModeling

from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template


# ==========================================
#   CONFIGURATION
# ==========================================
MODEL_ID   = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
DATA_FILE  = "eaa_master_train.jsonl"
OUTPUT_DIR = "lora/master_qwen"

MAX_SEQ_LENGTH = 2048
MAX_STEPS      = 500

# LoRA params
LORA_R = 16
LORA_ALPHA = 16


def _format_texts(messages_list, tokenizer):
    """No datasets.map. Pure Python formatting to avoid Windows spawn/pickle."""
    texts = []
    for convo in messages_list:
        # convo is a list of {"from": "...", "value": "..."} after your mapping,
        # or {"role": "...", "content": "..."} depending on your JSONL.
        # Your JSONL appears to be {"messages":[{role/content}...]} from your generator.
        text = tokenizer.apply_chat_template(
            convo,
            tokenize=False,
            add_generation_prompt=False,
        )
        texts.append(text)
    return texts


def _tokenize_texts(texts, tokenizer, batch_size=64):
    """Pure Python batched tokenization. No datasets multiprocessing."""
    input_ids = []
    attention_mask = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        enc = tokenizer(
            batch,
            truncation=True,
            max_length=MAX_SEQ_LENGTH,
            padding=False,
        )
        input_ids.extend(enc["input_ids"])
        attention_mask.extend(enc["attention_mask"])

    return Dataset.from_dict({
        "input_ids": input_ids,
        "attention_mask": attention_mask,
    })


def train():
    # Hard-disable parallelism + keep Windows stable
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    print("==================================================")
    print("🚀 INITIALIZING JARVIS TRAINING PROTOCOL")
    print("==================================================")
    print(f"Target Model: {MODEL_ID}")
    print(f"Dataset:      {DATA_FILE}")
    print(f"Output Dir:   {OUTPUT_DIR}")

    # 1) Load base model
    print("\n[1/5] Loading Qwen Base Model...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_ID,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )

    # 2) Attach LoRA
    print("[2/5] Attaching LoRA Adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_R,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=LORA_ALPHA,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    # 3) Apply chat template
    tokenizer = get_chat_template(
        tokenizer,
        chat_template="chatml",
        mapping={"role": "from", "content": "value", "user": "human", "assistant": "gpt"},
    )

    # 4) Load dataset (no map)
    print(f"[3/5] Loading Dataset ({DATA_FILE})...")
    raw = load_dataset("json", data_files=DATA_FILE, split="train")

    if "messages" not in raw.column_names:
        raise RuntimeError(
            f"Dataset is missing 'messages' column. Found: {raw.column_names}"
        )

    print("[4/5] Formatting Dataset (NO multiprocessing)...")
    messages_list = raw["messages"]
    texts = _format_texts(messages_list, tokenizer)

    print("[5/5] Tokenizing Dataset (NO multiprocessing)...")
    tokenized = _tokenize_texts(texts, tokenizer, batch_size=64)

    # Data collator pads to batch and creates labels for causal LM
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    args = TrainingArguments(
        output_dir="outputs/master_qwen",
        max_steps=MAX_STEPS,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        learning_rate=2e-4,
        weight_decay=0.01,
        lr_scheduler_type="linear",
        logging_steps=1,
        save_steps=500,
        report_to="none",
        seed=3407,

        # Windows stability
        dataloader_num_workers=0,
        remove_unused_columns=False,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized,
        data_collator=collator,
        tokenizer=tokenizer,
    )

    print("\n⚡ STARTING TRAINING ⚡")
    trainer.train()

    print("\n✅ Training Complete!")
    print(f"💾 Saving LoRA Adapter to: {OUTPUT_DIR}")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print("DONE. You can now run 'bake_brains.py'.")


if __name__ == "__main__":
    mp.freeze_support()
    train()
