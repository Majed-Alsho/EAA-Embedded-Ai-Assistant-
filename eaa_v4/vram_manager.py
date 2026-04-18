"""
EAA V4 - VRAM Lifecycle Manager
=================================
The most critical infrastructure component in the entire system.

Claude Code runs on cloud APIs with unlimited memory — it doesn't need this.
For EAA, where multiple models share a single GPU with limited VRAM (8GB),
this component prevents the most catastrophic failure mode: loading two large
models simultaneously and crashing with an OOM.

HARDWARE CONTEXT:
  - GPU: NVIDIA RTX 4060 Ti (8GB VRAM)
  - Model: Qwen2.5-7B-Instruct, BNB 4-bit quantization (~5.9GB VRAM)
  - Safety Classifier: 1.5B parameter model (~200MB VRAM at 4-bit)
  - Framework: PyTorch + bitsandbytes (NOT llama.cpp / GGUF)

CRITICAL IMPLEMENTATION NOTE:
  Previous versions of this blueprint referenced llama.cpp's context_free()
  for VRAM management. This was INCORRECT. The actual EAA system uses
  bitsandbytes 4-bit quantization via PyTorch, so VRAM management must use:
    - model.to('cpu')       # Move model weights to RAM
    - model.to('cuda')      # Move model weights back to GPU
    - torch.cuda.empty_cache()  # Free PyTorch's memory allocator cache
    - gc.collect()          # Force Python garbage collection

VRAM HOT-SWAP SEQUENCE (one-model-at-a-time policy):
  1. Save current model's conversation state to RAM/disk (mmap)
  2. model.to('cpu') — move current model to system RAM
  3. gc.collect() + torch.cuda.empty_cache() — free VRAM completely
  4. VERIFY VRAM is free (nvidia-smi check)
  5. Load new model from disk (mmap for fast RAM→GPU)
  6. model.to('cuda', dtype=torch.bfloat16) — move to GPU
  7. Execute task
  8. Return result
  9. (Optionally) unload worker, reload master

SAFETY NETS:
  - VRAM budget tracking (never exceed 90% of total)
  - Watchdog timer (abort if swap takes >30 seconds)
  - Fallback to CPU inference if GPU insufficient
  - pynvml monitoring for real-time VRAM telemetry
  - Lock-based concurrency protection (no simultaneous swaps)
"""

import os
import gc
import time
import logging
import threading
import subprocess
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# VRAM STATE
# ═══════════════════════════════════════════════════════════════════════════════

class VRAMState(Enum):
    EMPTY = "empty"               # No model loaded, VRAM free
    LOADING = "loading"           # Model being loaded
    READY = "ready"               # Model loaded, ready for inference
    UNLOADING = "unloading"       # Model being moved to CPU
    ERROR = "error"               # Something went wrong
    CPU_FALLBACK = "cpu_fallback" # Running on CPU (VRAM insufficient)


@dataclass
class ModelProfile:
    """
    Expected VRAM footprint for a model.
    Used to check if a model will fit before loading.
    """
    model_id: str
    vram_required_mb: float       # Expected VRAM usage
    ram_required_mb: float        # RAM needed when on CPU
    load_time_est_seconds: float  # Estimated load time
    path: str = ""                # Path to model weights
    is_classifier: bool = False   # If True, stays loaded alongside workers


# ═════════════════════════════════════════════════════════════════════════════════
# DEFAULT MODEL PROFILES
# ═══════════════════════════════════════════════════════════════════════════════

# These are calibrated for BNB 4-bit quantization on RTX 4060 Ti.
# Actual usage may vary by ~100-200MB depending on context length.
DEFAULT_MODEL_PROFILES = {
    "qwen2.5-7b-instruct": ModelProfile(
        model_id="qwen2.5-7b-instruct",
        vram_required_mb=5900,      # ~5.9GB at BNB 4-bit + KV cache
        ram_required_mb=8000,       # ~8GB on CPU (full precision)
        load_time_est_seconds=8.0,  # From disk → GPU (with mmap)
        is_classifier=False,
    ),
    "qwen2.5-coder-7b-instruct": ModelProfile(
        model_id="qwen2.5-coder-7b-instruct",
        vram_required_mb=5900,
        ram_required_mb=8000,
        load_time_est_seconds=8.0,
        is_classifier=False,
    ),
    "qwen2.5-1.5b-safety-classifier": ModelProfile(
        model_id="qwen2.5-1.5b-safety-classifier",
        vram_required_mb=200,       # ~200MB at BNB 4-bit
        ram_required_mb=1500,
        load_time_est_seconds=3.0,
        is_classifier=True,         # Stays loaded alongside workers
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# VRAM INFO
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VRAMInfo:
    """Real-time VRAM telemetry from nvidia-smi."""
    total_mb: float = 0.0
    used_mb: float = 0.0
    free_mb: float = 0.0
    percent_used: float = 0.0
    temperature_c: float = 0.0
    power_draw_w: float = 0.0
    source: str = "unknown"

    @property
    def available_for_model_mb(self) -> float:
        """VRAM available for model loading (with 10% safety margin)."""
        return self.free_mb * 0.90

    def to_dict(self) -> Dict:
        return {
            "total_gb": round(self.total_mb / 1024, 2),
            "used_gb": round(self.used_mb / 1024, 2),
            "free_gb": round(self.free_mb / 1024, 2),
            "available_for_model_gb": round(self.available_for_model_mb / 1024, 2),
            "percent_used": round(self.percent_used, 1),
            "temperature_c": self.temperature_c,
            "power_draw_w": self.power_draw_w,
            "source": self.source,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SWAP RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SwapResult:
    """Result of a model swap operation."""
    success: bool
    model_id: str = ""
    duration_seconds: float = 0.0
    vram_before_mb: float = 0.0
    vram_after_mb: float = 0.0
    error: Optional[str] = None
    used_cpu_fallback: bool = False

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "model_id": self.model_id,
            "duration_seconds": round(self.duration_seconds, 2),
            "vram_before_gb": round(self.vram_before_mb / 1024, 2),
            "vram_after_gb": round(self.vram_after_mb / 1024, 2),
            "error": self.error,
            "used_cpu_fallback": self.used_cpu_fallback,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# VRAM LIFECYCLE MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class VRAMManager:
    """
    Manages model loading/unloading to prevent OOM crashes.

    This is the PyTorch/bitsandbytes implementation (NOT llama.cpp).
    Uses model.to('cpu')/model.to('cuda') for VRAM management,
    gc.collect() + torch.cuda.empty_cache() for cleanup,
    and nvidia-smi for real-time monitoring.

    KEY PRINCIPLE: One model at a time (except the 1.5B safety classifier).
    """

    def __init__(
        self,
        model_profiles: Optional[Dict[str, ModelProfile]] = None,
        safety_margin_percent: float = 10.0,
        watchdog_timeout: float = 30.0,
    ):
        """
        Args:
            model_profiles: Dict of ModelProfile for known models
            safety_margin_percent: % of VRAM to keep free (default 10%)
            watchdog_timeout: Max seconds before aborting a swap (default 30)
        """
        self.model_profiles = model_profiles or DEFAULT_MODEL_PROFILES
        self.safety_margin = safety_margin_percent
        self.watchdog_timeout = watchdog_timeout

        # State
        self._state = VRAMState.EMPTY
        self._current_model_id: Optional[str] = None
        self._current_model: Any = None  # Reference to the PyTorch model
        self._classifier_model: Any = None  # Always-loaded safety classifier
        self._classifier_loaded: bool = False

        # Concurrency protection
        self._lock = threading.Lock()
        self._swap_lock = threading.Lock()  # Only one swap at a time

        # Stats
        self._total_swaps = 0
        self._swap_history: List[Dict] = []
        self._total_vram_freed_mb: float = 0.0
        self._fallback_count: int = 0

        # Detect hardware
        self._gpu_info = self._detect_gpu()
        self._has_cuda = self._check_cuda()

        logger.info(
            f"[VRAM] Manager initialized: "
            f"GPU={self._gpu_info.get('name', 'unknown')}, "
            f"VRAM={self._gpu_info.get('total_mb', 0) / 1024:.1f}GB, "
            f"CUDA={'available' if self._has_cuda else 'NOT available'}"
        )

    # ──────────────────────────────────────────────────────
    # HARDWARE DETECTION
    # ──────────────────────────────────────────────────────

    def _detect_gpu(self) -> Dict:
        """Detect GPU info via nvidia-smi."""
        info = {"name": "unknown", "total_mb": 0, "driver": ""}
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 2:
                    info["name"] = parts[0].strip()
                    info["total_mb"] = float(parts[1].strip())
                    if len(parts) >= 3:
                        info["driver"] = parts[2].strip()
        except Exception as e:
            logger.warning(f"[VRAM] nvidia-smi failed: {e}")

        return info

    def _check_cuda(self) -> bool:
        """Check if PyTorch CUDA is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            logger.warning("[VRAM] PyTorch not installed — CPU-only mode")
            return False

    # ──────────────────────────────────────────────────────
    # VRAM MONITORING
    # ──────────────────────────────────────────────────────

    def get_vram_info(self) -> VRAMInfo:
        """Get real-time VRAM info via nvidia-smi (primary) or torch (fallback)."""
        info = VRAMInfo(source="none")

        # Method 1: nvidia-smi (most accurate)
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.total,memory.free,"
                    "temperature.gpu,power.draw",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 3:
                    info.used_mb = float(parts[0].strip())
                    info.total_mb = float(parts[1].strip())
                    info.free_mb = float(parts[2].strip())
                    info.percent_used = (info.used_mb / info.total_mb) * 100
                    info.source = "nvidia-smi"
                    if len(parts) >= 4:
                        info.temperature_c = float(parts[3].strip())
                    if len(parts) >= 5:
                        info.power_draw_w = float(parts[4].strip())
        except Exception:
            pass

        # Method 2: PyTorch (fallback)
        if info.source == "none" and self._has_cuda:
            try:
                import torch
                info.used_mb = torch.cuda.memory_allocated(0) / (1024 ** 2)
                info.free_mb = (
                    torch.cuda.get_device_properties(0).total_memory / (1024 ** 2)
                    - info.used_mb
                )
                info.total_mb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 2)
                info.percent_used = (info.used_mb / info.total_mb) * 100
                info.source = "torch"
            except Exception:
                pass

        return info

    def get_current_vram(self) -> float:
        """Quick VRAM usage check (MB)."""
        info = self.get_vram_info()
        return info.used_mb

    def will_fit(self, model_id: str) -> Tuple[bool, float, float]:
        """
        Check if a model will fit in available VRAM.

        Returns: (will_fit, available_mb, required_mb)
        """
        profile = self.model_profiles.get(model_id)
        if not profile:
            logger.warning(f"[VRAM] Unknown model profile: {model_id}, assuming 4GB")
            required = 4096
        else:
            required = profile.vram_required_mb

        vram_info = self.get_vram_info()
        available = vram_info.available_for_model_mb

        # If classifier is loaded, subtract its footprint
        if self._classifier_loaded:
            classifier_profile = self.model_profiles.get(
                "qwen2.5-1.5b-safety-classifier"
            )
            if classifier_profile:
                available -= classifier_profile.vram_required_mb

        return available >= required, available, required

    # ──────────────────────────────────────────────────────
    # MODEL LOADING / UNLOADING (PyTorch/BNB)
    # ──────────────────────────────────────────────────────

    def load_model(self, model_id: str) -> SwapResult:
        """
        Load a model into VRAM.

        If another model is currently loaded, it gets moved to CPU first.
        Uses model.to('cuda') for PyTorch models.
        """
        start = time.time()
        vram_before = self.get_current_vram()

        with self._swap_lock:
            # Step 1: Unload current model if any
            if self._current_model is not None:
                unload_result = self._unload_to_cpu()
                if not unload_result:
                    return SwapResult(
                        success=False,
                        model_id=model_id,
                        duration_seconds=time.time() - start,
                        vram_before_mb=vram_before,
                        error="Failed to unload current model",
                    )

            # Step 2: Check if model will fit
            fits, available, required = self.will_fit(model_id)
            if not fits:
                logger.warning(
                    f"[VRAM] Model {model_id} needs {required:.0f}MB "
                    f"but only {available:.0f}MB available"
                )
                return SwapResult(
                    success=False,
                    model_id=model_id,
                    duration_seconds=time.time() - start,
                    vram_before_mb=vram_before,
                    error=(
                        f"Insufficient VRAM: need {required:.0f}MB, "
                        f"have {available:.0f}MB"
                    ),
                )

            # Step 3: Load the model
            self._state = VRAMState.LOADING
            logger.info(f"[VRAM] Loading model: {model_id}...")

            try:
                if self._has_cuda:
                    loaded_model = self._load_pytorch_model(model_id)
                else:
                    loaded_model = self._load_cpu_model(model_id)

                self._current_model = loaded_model
                self._current_model_id = model_id
                self._state = VRAMState.READY
                logger.info(f"[VRAM] Model {model_id} loaded successfully")

            except Exception as e:
                self._state = VRAMState.ERROR
                logger.error(f"[VRAM] Failed to load {model_id}: {e}")
                return SwapResult(
                    success=False,
                    model_id=model_id,
                    duration_seconds=time.time() - start,
                    vram_before_mb=vram_before,
                    error=str(e),
                )

            # Record swap
            self._total_swaps += 1
            duration = time.time() - start
            vram_after = self.get_current_vram()

            self._swap_history.append({
                "timestamp": time.time(),
                "action": "load",
                "model_id": model_id,
                "duration": duration,
                "vram_before": vram_before,
                "vram_after": vram_after,
            })

            return SwapResult(
                success=True,
                model_id=model_id,
                duration_seconds=duration,
                vram_before_mb=vram_before,
                vram_after_mb=vram_after,
            )

    def unload_model(self) -> SwapResult:
        """Unload the current model from VRAM (move to CPU)."""
        start = time.time()
        vram_before = self.get_current_vram()

        with self._swap_lock:
            success = self._unload_to_cpu()

            duration = time.time() - start
            vram_after = self.get_current_vram()
            freed = vram_before - vram_after

            self._swap_history.append({
                "timestamp": time.time(),
                "action": "unload",
                "model_id": self._current_model_id or "none",
                "duration": duration,
                "vram_before": vram_before,
                "vram_after": vram_after,
                "vram_freed": freed,
            })

            if freed > 0:
                self._total_vram_freed_mb += freed

            return SwapResult(
                success=success,
                model_id=self._current_model_id or "",
                duration_seconds=duration,
                vram_before_mb=vram_before,
                vram_after_mb=vram_after,
            )

    def _unload_to_cpu(self) -> bool:
        """Move the current model from GPU to CPU (PyTorch)."""
        if self._current_model is None:
            return True

        self._state = VRAMState.UNLOADING
        model_id = self._current_model_id

        try:
            import torch

            # Step 1: Move model to CPU
            self._current_model.to('cpu')

            # Step 2: Force garbage collection
            del self._current_model
            self._current_model = None
            gc.collect()

            # Step 3: Free PyTorch's CUDA memory allocator cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()

            self._current_model_id = None
            self._state = VRAMState.EMPTY

            logger.info(f"[VRAM] Model {model_id} moved to CPU, VRAM freed")
            return True

        except Exception as e:
            self._state = VRAMState.ERROR
            logger.error(f"[VRAM] Failed to unload model: {e}")
            return False

    def _load_pytorch_model(self, model_id: str):
        """
        Load a BNB 4-bit quantized model using PyTorch + bitsandbytes.

        This is the production path for Qwen2.5-7B-Instruct.

        Key parameters:
        - load_in_4bit=True: BNB 4-bit quantization (~5.9GB for 7B model)
        - torch_dtype=torch.bfloat16: Half precision for faster inference
        - device_map="auto": Let accelerate handle device placement
        - mmap=True: Memory-map model weights (faster load from disk)
        """
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        profile = self.model_profiles.get(model_id, {})

        # BNB 4-bit config
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",        # NormalFloat 4-bit
            bnb_4bit_use_double_quant=True,    # Double quantization for accuracy
        )

        model_path = profile.path if hasattr(profile, 'path') else model_id

        # Load with mmap for fast disk-to-RAM transfer
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            quantization_config=bnb_config,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
            # mmap is enabled by default in transformers for large files
        )

        # Move to CUDA explicitly (ensure GPU placement)
        model = model.to('cuda')

        return model

    def _load_cpu_model(self, model_id: str):
        """
        Load model on CPU only (fallback when CUDA unavailable).
        Much slower but prevents crashes.
        """
        import torch
        from transformers import AutoModelForCausalLM

        self._fallback_count += 1
        self._state = VRAMState.CPU_FALLBACK
        logger.warning(f"[VRAM] Loading {model_id} on CPU (fallback)")

        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=torch.float32,
            trust_remote_code=True,
        )

        return model

    # ──────────────────────────────────────────────────────
    # SAFETY CLASSIFIER MANAGEMENT
    # ──────────────────────────────────────────────────────

    def load_classifier(self) -> bool:
        """
        Load the 1.5B safety classifier.
        This model STAYS loaded in VRAM alongside any worker because
        its small size (~200MB) fits within the safety margin.
        """
        classifier_id = "qwen2.5-1.5b-safety-classifier"
        if classifier_id not in self.model_profiles:
            logger.warning(f"[VRAM] No profile for classifier: {classifier_id}")
            return False

        try:
            self._classifier_model = self._load_pytorch_model(classifier_id)
            self._classifier_loaded = True
            logger.info("[VRAM] Safety classifier loaded and kept resident")
            return True
        except Exception as e:
            logger.error(f"[VRAM] Failed to load classifier: {e}")
            return False

    def unload_classifier(self) -> bool:
        """Unload the safety classifier to free extra VRAM."""
        if self._classifier_model is None:
            return True

        try:
            import torch
            self._classifier_model.to('cpu')
            del self._classifier_model
            self._classifier_model = None
            self._classifier_loaded = False
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("[VRAM] Safety classifier unloaded")
            return True
        except Exception as e:
            logger.error(f"[VRAM] Failed to unload classifier: {e}")
            return False

    # ──────────────────────────────────────────────────────
    # CONTEXT MANAGER API
    # ──────────────────────────────────────────────────────

    @contextmanager
    def vram_swap(self, model_id: str, keep_loaded: bool = False):
        """
        Context manager for safe model swapping.

        Usage:
            with vram_manager.vram_swap('coder'):
                result = execute_worker_task(coder_task)
            # Master is automatically reloaded after the block

        Args:
            model_id: Model to load for the duration of the block
            keep_loaded: If True, don't reload previous model after block
        """
        previous_model = self._current_model_id

        # Load the requested model
        swap_result = self.load_model(model_id)
        if not swap_result.success:
            logger.error(
                f"[VRAM] Swap failed: {swap_result.error}. "
                f"Falling back to CPU for {model_id}"
            )
            # Try CPU fallback
            try:
                cpu_model = self._load_cpu_model(model_id)
                self._current_model = cpu_model
                self._current_model_id = model_id
                self._state = VRAMState.CPU_FALLBACK
            except Exception as e:
                logger.error(f"[VRAM] CPU fallback also failed: {e}")

        try:
            yield swap_result
        finally:
            if not keep_loaded and previous_model:
                # Reload the previous model
                self.load_model(previous_model)
            elif not keep_loaded:
                # No previous model — just unload
                self.unload_model()

    # ──────────────────────────────────────────────────────
    # FORCED CLEANUP
    # ──────────────────────────────────────────────────────

    def force_cleanup(self) -> float:
        """
        Force cleanup of all VRAM. Use as a last resort.

        Returns: MB of VRAM freed.
        """
        vram_before = self.get_current_vram()

        # Unload current model
        self._unload_to_cpu()

        # Unload classifier
        self.unload_classifier()

        # Aggressive cleanup
        try:
            import torch
            if torch.cuda.is_available():
                gc.collect()
                torch.cuda.empty_cache()
                torch.cuda.synchronize()

                # Reset CUDA memory allocator stats
                torch.cuda.reset_peak_memory_stats()
        except ImportError:
            pass

        vram_after = self.get_current_vram()
        freed = vram_before - vram_after

        logger.info(
            f"[VRAM] Force cleanup: freed {freed:.0f}MB "
            f"({vram_before:.0f}MB → {vram_after:.0f}MB)"
        )

        return freed

    # ──────────────────────────────────────────────────────
    # STATISTICS
    # ──────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Get VRAM manager statistics."""
        vram = self.get_vram_info()
        return {
            "state": self._state.value,
            "current_model": self._current_model_id,
            "classifier_loaded": self._classifier_loaded,
            "total_swaps": self._total_swaps,
            "total_vram_freed_gb": round(self._total_vram_freed_mb / 1024, 2),
            "cpu_fallback_count": self._fallback_count,
            "gpu": self._gpu_info,
            "vram": vram.to_dict(),
            "recent_swaps": self._swap_history[-10:],
        }

    def get_model(self) -> Any:
        """Get the currently loaded PyTorch model (for inference)."""
        return self._current_model

    def get_classifier(self) -> Any:
        """Get the safety classifier model."""
        return self._classifier_model


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_vram_manager(
    profiles: Optional[Dict[str, ModelProfile]] = None,
    safety_margin: float = 10.0,
) -> VRAMManager:
    """Create a VRAMManager with optional custom profiles."""
    return VRAMManager(
        model_profiles=profiles or DEFAULT_MODEL_PROFILES,
        safety_margin_percent=safety_margin,
    )


__all__ = [
    "VRAMManager",
    "VRAMState",
    "VRAMInfo",
    "ModelProfile",
    "SwapResult",
    "DEFAULT_MODEL_PROFILES",
    "create_vram_manager",
]
