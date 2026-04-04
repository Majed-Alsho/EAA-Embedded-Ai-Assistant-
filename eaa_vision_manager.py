"""
EAA VISION MANAGER
==================
Same logic as BrainManager - load when needed, unload when done.
Keeps VRAM free until vision is actually required.

Supports:
- LLaVA (llava-1.5-7b-hf) - ~4GB VRAM
- Qwen2-VL (Qwen2-VL-2B-Instruct) - ~2GB VRAM (recommended)
- BakLLaVA - ~4GB VRAM
"""

import os
import gc
import time
import torch
from typing import Optional, Tuple
from pathlib import Path

class VisionManager:
    """
    Just like BrainManager - lazy loading for vision models.
    Load only when analyze_image is called, unload when done.
    """

    def __init__(self, base_dir: str = None):
        self.current_model = None
        self.current_processor = None
        self.current_model_id = None
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

        # Default models directory
        self.base_dir = base_dir or os.path.join(os.getcwd(), "models")

        # Available vision models (in order of preference)
        self.available_models = {
            "qwen2-vl-2b": {
                "hf_id": "Qwen/Qwen2-VL-2B-Instruct",
                "vram_needed": "2.5GB",
                "recommended": True,
            },
            "llava-1.5-7b": {
                "hf_id": "llava-hf/llava-1.5-7b-hf",
                "vram_needed": "4.5GB",
                "recommended": False,
            },
            "llava-v1.6-mistral": {
                "hf_id": "llava-hf/llava-v1.6-mistral-7b-hf",
                "vram_needed": "5GB",
                "recommended": False,
            },
        }

        print(f"[VISION] Manager initialized. Device: {self.device}")

    def _clear_vram(self):
        """Clear VRAM just like BrainManager"""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

    def unload(self):
        """Unload vision model - same as BrainManager.unload()"""
        if self.current_model is not None:
            print(f"[VISION] 🧹 Unloading {self.current_model_id}...")

            del self.current_model
            del self.current_processor

            self.current_model = None
            self.current_processor = None
            self.current_model_id = None

            for _ in range(3):
                self._clear_vram()
                time.sleep(0.5)

            print("[VISION] ✅ VRAM Cleared.")

    def load(self, model_name: str = "qwen2-vl-2b") -> Tuple[any, any]:
        """
        Load a vision model - same pattern as BrainManager.load()
        Returns (model, processor) tuple
        """
        # Already loaded?
        if self.current_model is not None and self.current_model_id == model_name:
            print(f"[VISION] ✅ {model_name} already loaded.")
            return self.current_model, self.current_processor

        # Unload previous model first
        self.unload()

        # Get model info
        if model_name not in self.available_models:
            print(f"[VISION] ❌ Unknown model: {model_name}")
            print(f"[VISION] Available: {list(self.available_models.keys())}")
            return None, None

        model_info = self.available_models[model_name]
        hf_id = model_info["hf_id"]

        print(f"[VISION] 🧠 Loading {model_name} ({hf_id})...")
        print(f"[VISION] 📊 VRAM needed: ~{model_info['vram_needed']}")

        try:
            # Check if Qwen2-VL (special handling)
            if "qwen" in model_name.lower():
                return self._load_qwen2vl(hf_id, model_name)

            # Default: LLaVA-style models
            return self._load_llava(hf_id, model_name)

        except Exception as e:
            print(f"[VISION] ❌ Failed to load {model_name}: {e}")
            self.unload()
            return None, None

    def _load_qwen2vl(self, hf_id: str, model_name: str) -> Tuple[any, any]:
        """Load Qwen2-VL model (most efficient)"""
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
        from qwen_vl_utils import process_vision_info

        # Load model with 4-bit quantization to save VRAM
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            hf_id,
            torch_dtype="auto",
            device_map="auto",
            load_in_4bit=True,  # Save VRAM
        )

        processor = AutoProcessor.from_pretrained(hf_id)

        self.current_model = model
        self.current_processor = processor
        self.current_model_id = model_name

        print(f"[VISION] ✅ {model_name} loaded and ready!")
        return model, processor

    def _load_llava(self, hf_id: str, model_name: str) -> Tuple[any, any]:
        """Load LLaVA-style models"""
        from transformers import LlavaNextProcessor, LlavaNextForConditionalGeneration

        processor = LlavaNextProcessor.from_pretrained(hf_id)

        model = LlavaNextForConditionalGeneration.from_pretrained(
            hf_id,
            torch_dtype=torch.float16,
            device_map="auto",
            load_in_4bit=True,  # Save VRAM
        )

        self.current_model = model
        self.current_processor = processor
        self.current_model_id = model_name

        print(f"[VISION] ✅ {model_name} loaded and ready!")
        return model, processor

    def analyze(self, image_path: str, question: str = "Describe this image", model_name: str = "qwen2-vl-2b") -> str:
        """
        Analyze an image - loads model, analyzes, then optionally unloads.

        Args:
            image_path: Path to image file
            question: What to ask about the image
            model_name: Which vision model to use

        Returns:
            Analysis result as string
        """
        # Check image exists
        if not os.path.exists(image_path):
            return f"Error: Image not found at {image_path}"

        # Load model
        model, processor = self.load(model_name)
        if model is None:
            return "Error: Could not load vision model"

        try:
            print(f"[VISION] 🔍 Analyzing: {image_path}")
            print(f"[VISION] ❓ Question: {question}")

            # Qwen2-VL style
            if "qwen" in model_name.lower():
                return self._analyze_qwen2vl(model, processor, image_path, question)

            # LLaVA style
            return self._analyze_llava(model, processor, image_path, question)

        except Exception as e:
            return f"Error during analysis: {e}"

    def _analyze_qwen2vl(self, model, processor, image_path: str, question: str) -> str:
        """Analyze using Qwen2-VL"""
        from qwen_vl_utils import process_vision_info

        # Prepare messages
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image_path},
                    {"type": "text", "text": question},
                ],
            }
        ]

        # Process
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(model.device)

        # Generate
        with torch.no_grad():
            generated_ids = model.generate(**inputs, max_new_tokens=512)

        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]

        result = processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False
        )[0]

        return result

    def _analyze_llava(self, model, processor, image_path: str, question: str) -> str:
        """Analyze using LLaVA-style models"""
        from PIL import Image

        # Load image
        image = Image.open(image_path)

        # Prepare prompt
        conversation = [
            {"role": "user", "content": [
                {"type": "image"},
                {"type": "text", "text": question},
            ]},
        ]
        prompt = processor.apply_chat_template(conversation, add_generation_prompt=True)

        # Process
        inputs = processor(images=image, text=prompt, return_tensors="pt").to(model.device)

        # Generate
        with torch.no_grad():
            output = model.generate(**inputs, max_new_tokens=512)

        result = processor.decode(output[0], skip_special_tokens=True)

        # Clean up - remove the prompt from output
        if question in result:
            result = result.split(question)[-1].strip()

        return result

    def list_models(self) -> dict:
        """List available vision models"""
        return self.available_models

    def get_status(self) -> dict:
        """Get current status"""
        return {
            "loaded": self.current_model is not None,
            "model_id": self.current_model_id,
            "device": self.device,
            "available": list(self.available_models.keys()),
        }


# ============== CONVENIENCE FUNCTIONS (Like BrainManager) ==============

# Global instance (like brain_manager pattern)
_vision_manager = None

def get_vision_manager(base_dir: str = None) -> VisionManager:
    """Get or create the global VisionManager instance"""
    global _vision_manager
    if _vision_manager is None:
        _vision_manager = VisionManager(base_dir)
    return _vision_manager

def analyze_image(image_path: str, question: str = "Describe this image", model: str = "qwen2-vl-2b", unload_after: bool = True) -> str:
    """
    Convenience function to analyze an image.

    Args:
        image_path: Path to the image
        question: What to ask about the image
        model: Which vision model to use
        unload_after: If True, unloads model after analysis to free VRAM

    Returns:
        Analysis result as string
    """
    vm = get_vision_manager()
    try:
        result = vm.analyze(image_path, question, model)
        return result
    finally:
        if unload_after:
            vm.unload()


# ============== INTEGRATION WITH EAA TOOLS ==============

def create_vision_tool():
    """
    Create a vision tool that integrates with EAA's tool registry.
    This replaces the placeholder tool_analyze_image in eaa_agent_tools.py
    """
    def tool_analyze_image_v2(image_path: str, question: str = "Describe this image in detail") -> dict:
        """
        Analyze an image using vision AI. Loads model on demand, unloads after.

        Returns a dict compatible with ToolResult.
        """
        try:
            result = analyze_image(image_path, question, unload_after=True)
            return {
                "success": True,
                "output": result,
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e)
            }

    return tool_analyze_image_v2


# ============== TEST ==============

if __name__ == "__main__":
    print("=" * 50)
    print("  EAA VISION MANAGER TEST")
    print("=" * 50)

    vm = get_vision_manager()

    print("\nAvailable Models:")
    for name, info in vm.list_models().items():
        rec = "⭐ RECOMMENDED" if info["recommended"] else ""
        print(f"  - {name}: {info['hf_id']} ({info['vram_needed']}) {rec}")

    print(f"\nStatus: {vm.get_status()}")

    # Test with an image if provided
    import sys
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        question = sys.argv[2] if len(sys.argv) > 2 else "Describe this image"

        print(f"\nAnalyzing: {image_path}")
        print(f"Question: {question}")

        result = vm.analyze(image_path, question)
        print(f"\nResult:\n{result}")
