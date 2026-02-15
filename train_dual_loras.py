import os
import torch
from datasets import load_dataset
from transformers import TrainingArguments
from unsloth import FastLanguageModel
from trl import SFTTrainer, DataCollatorForCompletionOnlyLM

# CONFIG
EAA_DIR = r"C:\Users\offic\EAA"
MODEL_ID = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"

def train_lora(name, dataset_file, output_dir):
    print(f"\n=== TRAINING {name.upper()} QWEN BRAIN ===")
    
    # This line triggers the download if the model is missing
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_ID,
        max_seq_length=2048,
        dtype=None,
        load_in_4bit=True,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=32,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    # Use Qwen's Native Chat Format (ChatML)
    tokenizer = FastLanguageModel.get_chat_template(tokenizer, chat_template="chatml")
    
    dataset = load_dataset("json", data_files=dataset_file, split="train")

    def formatting_prompts_func(examples):
        convos = examples["messages"]
        texts = [tokenizer.apply_chat_template(convo, tokenize=False, add_generation_prompt=False) for convo in convos]
        return { "text" : texts }

    dataset = dataset.map(formatting_prompts_func, batched=True)

    # Masking to prevent echoing
    response_template = "<|im_start|>assistant\n"
    collator = DataCollatorForCompletionOnlyLM(response_template, tokenizer=tokenizer)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=2048,
        data_collator=collator,
        args=TrainingArguments(
            per_device_train_batch_size=1,
            gradient_accumulation_steps=4,
            warmup_steps=5,
            num_train_epochs=1,
            learning_rate=2e-4,
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
            logging_steps=10,
            optim="adamw_8bit",
            output_dir=f"outputs_{name}",
        ),
    )

    trainer.train()
    print(f"Saving {name} to {output_dir}")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    
    del model, trainer
    torch.cuda.empty_cache()

if __name__ == "__main__":
    # Ensure dirs exist
    os.makedirs(f"{EAA_DIR}\\lora\\master_qwen", exist_ok=True)
    os.makedirs(f"{EAA_DIR}\\lora\\shadow_qwen", exist_ok=True)

    # Train Master
    train_lora("master", f"{EAA_DIR}\\train_data\\master_train.jsonl", f"{EAA_DIR}\\lora\\master_qwen")
    
    # Train Shadow
    train_lora("shadow", f"{EAA_DIR}\\train_data\\shadow_train.jsonl", f"{EAA_DIR}\\lora\\shadow_qwen")
    
    print("\n[EAA] DUAL QWEN TRAINING COMPLETE.")