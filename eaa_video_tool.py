import os
import sys
import subprocess
import time
import requests
import json
import gc
import torch

# CONFIG
EAA_DIR = r"C:\Users\offic\EAA"
VIDEO_INSTALL_DIR = os.path.join(EAA_DIR, "Video", "ComfyUI")
WORKFLOW_FILENAME = "ltx_video_workflow.json"
WORKFLOW_PATH = os.path.join(EAA_DIR, WORKFLOW_FILENAME)
SERVER_URL = "http://127.0.0.1:8188"

def clear_vram():
    """Aggressively clears VRAM for rendering."""
    print("[VIDEO] 🧹 Clearing VRAM...")
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except: pass

def wait_for_server(timeout=120):
    print("[VIDEO] Waiting for ComfyUI server...", end="")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(SERVER_URL)
            if response.status_code == 200:
                print(" Online!")
                return True
        except:
            time.sleep(1)
            print(".", end="", flush=True)
    return False

def generate_transient_video(prompt):
    """
    1. Finds ComfyUI & Workflow
    2. Injects Prompt
    3. Renders & Cleans up
    """
    comfy_path = os.path.join(VIDEO_INSTALL_DIR, "main.py")
    if not os.path.exists(comfy_path):
        return f"Error: Could not find 'main.py' at {comfy_path}"
    
    if not os.path.exists(WORKFLOW_PATH):
        return f"Error: '{WORKFLOW_FILENAME}' not found in {EAA_DIR}"

    clear_vram()
    print(f"[VIDEO] 🚀 Booting Engine from: {comfy_path}")
    cwd = os.path.dirname(comfy_path)
    
    # Use the specific python used by ComfyUI if available
    python_exe = sys.executable 
    cmd = [python_exe, comfy_path, "--lowvram", "--preview-method", "none", "--dont-print-server"]
    process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    try:
        if not wait_for_server():
            raise Exception("Server timeout. ComfyUI did not start.")

        with open(WORKFLOW_PATH, 'r', encoding='utf-8') as f:
            workflow = json.load(f)

        # Inject Prompt into CLIPTextEncode (Node 2)
        text_node_id = "2" 
        for key, value in workflow.items():
            if value.get("class_type") == "CLIPTextEncode":
                if "bad" not in value.get("inputs", {}).get("text", "").lower():
                    text_node_id = key
                    break

        print(f"[VIDEO] Injecting prompt into Node {text_node_id}: '{prompt}'")
        workflow[text_node_id]["inputs"]["text"] = prompt

        # SEND REQUEST
        p = {"prompt": workflow}
        response = requests.post(f"{SERVER_URL}/prompt", json=p)
        if response.status_code != 200:
             raise Exception(f"ComfyUI Error: {response.text}")
             
        prompt_id = response.json().get('prompt_id')
        print(f"[VIDEO] 🎨 Rendering Job {prompt_id} queued...")

        # WAIT FOR RESULT
        output_dir = os.path.join(cwd, "output")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        initial_files = set(os.listdir(output_dir))
        
        # Poll for completion
        for i in range(300): 
            time.sleep(5)
            if i % 12 == 0: gc.collect()
            if i > 0 and i % 6 == 0:
                print(f"[VIDEO] ... still rendering ({i*5}s elapsed) ...")

            current_files = set(os.listdir(output_dir))
            new_files = current_files - initial_files
            if new_files:
                newest = list(new_files)[0]
                if newest.endswith((".mp4", ".png", ".gif", ".webp")):
                    return f"Render Complete: {os.path.join(output_dir, newest)}"
        
        return "Timeout: Video render took too long."

    except Exception as e:
        return f"Error: {e}"
        
    finally:
        print("[VIDEO] 🛑 Shutting down engine to restore VRAM...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except:
            process.kill()
        clear_vram()

if __name__ == "__main__":
    comfy_path = os.path.join(VIDEO_INSTALL_DIR, "main.py")
    if os.path.exists(comfy_path):
        print(f"✅ FOUND ComfyUI: {comfy_path}")
    else:
        print(f"❌ NOT FOUND at: {comfy_path}")