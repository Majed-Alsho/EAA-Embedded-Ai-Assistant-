import torch
import os
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# --- CONFIGURATION ---
# We use abspath to ensure Windows finds the local folder correctly
# preventing the "HFValidationError"
model_path = os.path.abspath("my_custom_qwen")

# --- PART 1: THE EYES (Simulated YouTube Scanner) ---
# In a real production app, we would use the 'youtube-transcript-api' library here.
# For now, we simulate what that script gives us: A list of the creator's recent content.
def scan_creator_channel(creator_name):
    print(f"--- Scanning YouTube Channel for: {creator_name} ---")
    print("... Analyzing recent uploads ...")
    print("... Extracting video topics ...")
    print("... Identifying Niche ...")
    
    # This is the data the Python script 'sees' on the channel
    # Let's pretend we scanned a creator named 'PlantDadSteve'
    channel_data = {
        "creator": creator_name,
        "video_titles": [
            "How to save your dying Monstera",
            "Best soil mix for indoor plants",
            "Stop watering your succulents!",
            "Top 5 rare plants for 2026",
            "My morning routine with 500 plants"
        ],
        "subscriber_count": "45,000",
        "niche_detected": "Indoor Gardening / Home Decor"
    }
    return channel_data

# --- PART 2: THE BRAIN (Your Fine-Tuned AI) ---
def generate_workbook_section(model, tokenizer, data):
    # We construct a prompt that forces the AI to use the "Shadow Operator" style
    # using the data we just 'scanned'.
    
    prompt = f"""
    You are an expert Shadow Operator in the style of Iman Gadzhi.
    
    Based on the following creator data, write 'SECTION 6: THE MONETISATION GAMEPLAN' for their workbook.
    
    Creator: {data['creator']}
    Niche: {data['niche_detected']}
    Recent Content: {', '.join(data['video_titles'])}
    Followers: {data['subscriber_count']}
    
    Include:
    1. The Audit (The hidden transformation)
    2. The Opportunity (Top 3 topics to monetize based on their video titles)
    3. Product Suggestion (Live Workshop idea)
    
    Write in the direct, punchy style of the Shadow Operator workbooks.
    """
    
    messages = [
        {"role": "system", "content": "You are a Shadow Operator AI. You write high-converting workbook sections."},
        {"role": "user", "content": prompt}
    ]
    
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    model_inputs = tokenizer([text], return_tensors="pt").to("cuda")

    generated_ids = model.generate(
        model_inputs.input_ids,
        max_new_tokens=1024,
        temperature=0.7
    )
    
    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]
    
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print(f"Looking for model at: {model_path}")
    
    if not os.path.exists(model_path):
        print("\nERROR: Model folder not found!")
        print(f"Could not find: {model_path}")
        print("Please make sure you have run the 'merge_qwen.py' script first.")
        exit()

    print("Loading your Shadow Operator Brain...")
    
    try:
        # Load Model
        base_model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="auto"
        )
        tokenizer = AutoTokenizer.from_pretrained(model_path)

        # 1. SCAN
        target_creator = "PlantDadSteve" # You can change this
        scanned_data = scan_creator_channel(target_creator)

        # 2. GENERATE
        print(f"\n--- Generating Workbook for {target_creator} ---")
        workbook_content = generate_workbook_section(base_model, tokenizer, scanned_data)
        
        print("\n" + "="*50)
        print(workbook_content)
        print("="*50)
        
        # Save to file
        with open(f"{target_creator}_Gameplan.txt", "w", encoding="utf-8") as f:
            f.write(workbook_content)
        print(f"Saved gameplan to {target_creator}_Gameplan.txt")

    except Exception as e:
        print(f"\nAn error occurred while loading or running: {e}")