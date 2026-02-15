# brain_manager.py
import os
import gc
import time
import threading
import logging
from typing import Optional, Dict

import torch

# 1. Try Importing Unsloth (Your Existing Engine)
try:
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import get_chat_template
    HAS_UNSLOTH = True
except ImportError:
    HAS_UNSLOTH = False

# 2. Try Importing Llama.cpp (The New Engine for GGUF)
try:
    from llama_cpp import Llama
    HAS_LLAMA = True
except ImportError:
    HAS_LLAMA = False

# 🔇 Silence Warnings
logging.getLogger("transformers").setLevel(logging.ERROR)


class BrainManager:
    def __init__(self):
        self.current_model = None
        self.current_tokenizer = None
        self.current_model_id = None
        self.current_adapter = "default"
        self._loaded_adapters = set()
        self._locks: Dict[str, threading.Lock] = {}
        
        # New Flag to track which engine is running
        self.is_gguf = False

        # Use explicit cuda:0 when CUDA is available
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.offline_default = True

    def lock_for(self, model_id: str) -> threading.Lock:
        if model_id not in self._locks:
            self._locks[model_id] = threading.Lock()
        return self._locks[model_id]

    def _clear_vram(self):
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

    def unload(self):
        """Forcefully removes the current brain from VRAM"""
        if self.current_model is not None:
            print(f"[MEMORY] 🧹 Unloading {self.current_model_id}...")
            try:
                # GGUF models need specific closing
                if self.is_gguf:
                    self.current_model.close()
                
                del self.current_model
                del self.current_tokenizer
            except Exception:
                pass

            self.current_model = None
            self.current_tokenizer = None
            self.current_model_id = None
            self.current_adapter = "default"
            self.is_gguf = False
            self._loaded_adapters = set()

            for _ in range(3):
                self._clear_vram()
                time.sleep(0.5)
            print("[MEMORY] ✅ VRAM Cleared.")

    def _set_offline(self, offline: bool):
        os.environ["HF_HUB_OFFLINE"] = "1" if offline else "0"

    def _ensure_adapter(self, adapter_path: str, adapter_name: str):
        # Adapters are only for Unsloth/PyTorch models
        if self.is_gguf: 
            return 

        if not adapter_path:
            return
        if adapter_name in self._loaded_adapters:
            self.current_model.set_adapter(adapter_name)
            self.current_adapter = adapter_name
            return

        print(f"[MEMORY] 🎭 Loading Adapter: {adapter_name}")
        self.current_model.load_adapter(adapter_path, adapter_name=adapter_name)
        self.current_model.set_adapter(adapter_name)
        self.current_adapter = adapter_name
        self._loaded_adapters.add(adapter_name)

    def _disable_adapters(self):
        if self.is_gguf: return
        try:
            self.current_model.disable_adapters()
        except Exception:
            pass
        self.current_adapter = "default"

    def _assert_model_device_is_consistent(self, model):
        if self.is_gguf: return
        """
        Unsloth/Triton will crash if any tensors are on CPU while you expect CUDA.
        """
        if not self.device.startswith("cuda"):
            return

        # Check a handful of params quickly
        bad = None
        for name, p in model.named_parameters():
            if p.device.type != "cuda":
                bad = (name, str(p.device))
                break

        if bad:
            raise RuntimeError(
                f"[DEVICE ERROR] Model is partially on CPU ({bad[0]} on {bad[1]}).\n"
                f"Fix: stop CPU offload. Force device_map={{'':0}} and/or reduce max_seq_length.\n"
                f"Your current setup cannot run Unsloth fast kernels with mixed CPU/GPU."
            )

    def load(self, model_id: str, adapter_path: Optional[str] = None, adapter_name: str = "default"):
        # CASE 1: model already loaded
        if self.current_model is not None and self.current_model_id == model_id:
            if not self.is_gguf and adapter_path:
                if self.current_adapter != adapter_name:
                    print(f"[MEMORY] 🎭 Switching Adapter -> {adapter_name}")
                    try:
                        self._ensure_adapter(adapter_path, adapter_name)
                    except Exception as e:
                        print(f"[ERROR] Adapter switch failed: {e}")
            elif not self.is_gguf:
                if self.current_adapter != "default":
                    print("[MEMORY] 🎭 Disabling adapters -> DEFAULT")
                    self._disable_adapters()
            return self.current_model, self.current_tokenizer

        # CASE 2: load new model
        self.unload()
        print(f"[MEMORY] 🧠 Loading {model_id}...")

        # -----------------------------------------------
        # NEW: GGUF PATH (The Shadow Brain)
        # -----------------------------------------------
        if model_id.lower().endswith(".gguf"):
            if not HAS_LLAMA:
                print("[ERROR] You need to install llama-cpp-python to use .gguf files")
                return None, None
            
            try:
                # -1 means offload ALL layers to GPU
                self.current_model = Llama(
                    model_path=model_id,
                    n_ctx=4096,
                    n_gpu_layers=-1, 
                    verbose=False
                )
                self.current_tokenizer = None # GGUF handles tokenization internally
                self.current_model_id = model_id
                self.is_gguf = True
                
                print(f"[MEMORY] ✅ {model_id} (GGUF) Active.")
                return self.current_model, None
            except Exception as e:
                print(f"[CRITICAL ERROR] Could not load GGUF {model_id}: {e}")
                return None, None

        # -----------------------------------------------
        # OLD: UNSLOTH PATH (Master, Logic, Coder)
        # -----------------------------------------------
        try:
            self._set_offline(self.offline_default)

            device_map = {"": 0} if self.device.startswith("cuda") else {"": "cpu"}

            # Context window 8192 is heavy. If you still get OOM, drop to 4096.
            model, tokenizer = FastLanguageModel.from_pretrained(
                model_name=model_id,
                max_seq_length=8192,
                dtype=None,
                load_in_4bit=True,
                device_map=device_map,
                local_files_only=True,
            )

            model = FastLanguageModel.for_inference(model)
            tokenizer = get_chat_template(tokenizer, chat_template="chatml")

            # Fail fast if anything ended up on CPU while CUDA expected
            self._assert_model_device_is_consistent(model)

            self.current_model = model
            self.current_tokenizer = tokenizer
            self.current_model_id = model_id
            self.current_adapter = "default"
            self.is_gguf = False
            self._loaded_adapters = set()

            if adapter_path:
                self._ensure_adapter(adapter_path, adapter_name)

            print(f"[MEMORY] ✅ {model_id} Active.")
            return self.current_model, self.current_tokenizer

        except Exception as e:
            print(f"[CRITICAL ERROR] Could not load {model_id}: {e}")
            self._set_offline(False)
            self.unload()
            return None, None
        finally:
            self._set_offline(False)

    def _embed_device(self, model) -> torch.device:
        if self.is_gguf: return "cpu" # irrelevant for gguf
        try:
            return model.get_input_embeddings().weight.device
        except Exception:
            return next(model.parameters()).device

    def safe_generate(self, model, input_ids, streamer=None, **gen_kwargs):
        # NOTE: This is only for Unsloth models
        if self.is_gguf: return 
        
        kwargs = dict(
            max_new_tokens=gen_kwargs.get("max_new_tokens", 512),
            temperature=gen_kwargs.get("temperature", 0.7),
            do_sample=gen_kwargs.get("temperature", 0.7) > 0.0,
        )

        for k in ("top_p", "top_k", "repetition_penalty"):
            if k in gen_kwargs and gen_kwargs[k] is not None:
                kwargs[k] = gen_kwargs[k]
        if streamer is not None:
            kwargs["streamer"] = streamer

        target_device = self._embed_device(model)
        if torch.is_tensor(input_ids) and input_ids.device != target_device:
            input_ids = input_ids.to(target_device)

        for k, v in list(kwargs.items()):
            if torch.is_tensor(v) and v.device != target_device:
                kwargs[k] = v.to(target_device)

        with torch.inference_mode():
            return model.generate(input_ids=input_ids, **kwargs)

    def generate_text(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        adapter_path: Optional[str] = None,
        adapter_name: str = "default",
        max_new_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        with self.lock_for(model_id):
            model, tokenizer = self.load(model_id, adapter_path=adapter_path, adapter_name=adapter_name)
            if model is None:
                return "System Error: Brain failed to load."

            # --------------------------
            # PATH A: GGUF GENERATION (Shadow)
            # --------------------------
            if self.is_gguf:
                # ✅ FIX: Some GGUF models crash if you use "system" role.
                # We merge the system prompt into the user prompt to trick it.
                messages = [
                    {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}
                ]
                
                output = self.current_model.create_chat_completion(
                    messages=messages,
                    max_tokens=max_new_tokens,
                    temperature=temperature,
                    stream=False
                )
                return output['choices'][0]['message']['content']

            # --------------------------
            # PATH B: UNSLOTH GENERATION (Master/Experts)
            # --------------------------
            msgs = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            input_ids = tokenizer.apply_chat_template(
                msgs,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
            )

            # Put input_ids on the embedding device
            input_ids = input_ids.to(self._embed_device(model))

            outputs = self.safe_generate(
                model=model,
                input_ids=input_ids,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
            )

            new_tokens = outputs[0][input_ids.shape[-1]:]
            text = tokenizer.decode(new_tokens, skip_special_tokens=True)
            return text.strip()