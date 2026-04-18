"""
model_registry.py — Model Registry (Phase 5)

Tracks registered models, their VRAM footprints, and loading metadata.
Used by the VRAM lifecycle manager for model hot-swapping.

Each model entry includes:
    - Model name and file path
    - Quantization type and bit width
    - Expected VRAM footprint
    - Load status

Reference: Blueprint Section 13 — VRAM Lifecycle Management
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class QuantType(Enum):
    """Model quantization types."""
    FP32 = "fp32"
    FP16 = "fp16"
    INT8 = "int8"
    INT4 = "int4"
    BNB_INT4 = "bnb_int4"
    BNB_INT8 = "bnb_int8"
    GPTQ_INT4 = "gptq_int4"
    AWQ_INT4 = "awq_int4"


# Approximate VRAM footprints per parameter count and quantization
# (in GB, conservative estimates)
VRAM_FOOTPRINT_TABLE = {
    # (params_B, QuantType): VRAM_GB
    (1.5, QuantType.INT4): 0.9,
    (1.5, QuantType.INT8): 1.6,
    (3, QuantType.INT4): 1.8,
    (3, QuantType.INT8): 3.2,
    (7, QuantType.INT4): 4.2,
    (7, QuantType.INT8): 7.5,
    (7, QuantType.BNB_INT4): 4.5,
    (7, QuantType.BNB_INT8): 7.8,
    (7, QuantType.FP16): 14.0,
    (14, QuantType.INT4): 8.4,
    (14, QuantType.INT8): 15.0,
    (32, QuantType.INT4): 19.2,
    (70, QuantType.INT4): 42.0,
}


@dataclass
class ModelInfo:
    """Metadata for a registered model."""
    name: str
    path: str
    params_b: float           # Billions of parameters
    quant: QuantType = QuantType.BNB_INT4
    vram_footprint_gb: float = 0.0  # Auto-calculated if 0
    is_loaded: bool = False
    load_time: float = 0.0   # Timestamp when loaded
    description: str = ""

    def __post_init__(self):
        if self.vram_footprint_gb <= 0:
            self.vram_footprint_gb = self._estimate_vram()

    def _estimate_vram(self) -> float:
        """Estimate VRAM footprint from the lookup table."""
        # Try exact match
        key = (self.params_b, self.quant)
        if key in VRAM_FOOTPRINT_TABLE:
            return VRAM_FOOTPRINT_TABLE[key]

        # Interpolate: find nearest param count for same quant
        matching = [
            (p, vram) for (p, q), vram in VRAM_FOOTPRINT_TABLE.items()
            if q == self.quant
        ]
        if not matching:
            # Fallback: rough estimate (0.6 GB per B for INT4)
            return self.params_b * 0.6

        # Linear interpolation from nearest
        matching.sort(key=lambda x: abs(x[0] - self.params_b))
        nearest_params, nearest_vram = matching[0]
        ratio = self.params_b / nearest_params if nearest_params > 0 else 1
        return nearest_vram * ratio

    @property
    def is_resident(self) -> bool:
        """Resident models stay in VRAM (small enough)."""
        # Models under 1GB can be resident alongside another
        return self.vram_footprint_gb < 1.0


class ModelRegistry:
    """
    Registry of all available models with VRAM footprint tracking.

    Used by VRAMLifecycleManager to plan model swaps and prevent OOM.
    """

    def __init__(self, total_vram_gb: float = 8.0):
        self._models: Dict[str, ModelInfo] = {}
        self._loaded: Dict[str, ModelInfo] = {}
        self.total_vram_gb = total_vram_gb

        # Safety classifier is always resident
        self._resident_models: Dict[str, ModelInfo] = {}

    def register(self, info: ModelInfo) -> None:
        """Register a model in the registry."""
        self._models[info.name] = info

    def unregister(self, name: str) -> bool:
        """Remove a model from the registry. Fails if loaded."""
        if name in self._loaded:
            return False
        self._models.pop(name, None)
        self._resident_models.pop(name, None)
        return True

    def get(self, name: str) -> Optional[ModelInfo]:
        """Get model info by name."""
        return self._models.get(name)

    def get_loaded_model(self, name: str) -> Optional[ModelInfo]:
        """Get a loaded model by name."""
        return self._loaded.get(name)

    def register_as_resident(self, name: str) -> bool:
        """
        Mark a model as always-resident (stays in VRAM).

        Only small models (safety classifier, etc.) should be resident.
        Returns False if model is too large or not registered.
        """
        info = self._models.get(name)
        if info is None:
            return False
        if not info.is_resident:
            return False
        self._resident_models[name] = info
        return True

    def get_resident_vram(self) -> float:
        """Total VRAM used by resident models."""
        return sum(m.vram_footprint_gb for m in self._resident_models.values())

    def get_available_vram(self) -> float:
        """Available VRAM excluding resident models."""
        return self.total_vram_gb - self.get_resident_vram()

    def can_fit(self, name: str) -> bool:
        """Check if a model can fit in available VRAM."""
        info = self._models.get(name)
        if info is None:
            return False
        return info.vram_footprint_gb <= self.get_available_vram()

    def mark_loaded(self, name: str) -> bool:
        """Mark a model as currently loaded in VRAM."""
        info = self._models.get(name)
        if info is None:
            return False
        info.is_loaded = True
        self._loaded[name] = info
        return True

    def mark_unloaded(self, name: str) -> bool:
        """Mark a model as unloaded from VRAM."""
        info = self._loaded.pop(name, None)
        if info is None:
            return False
        info.is_loaded = False
        return True

    @property
    def current_loaded(self) -> List[str]:
        """Names of currently loaded models."""
        return list(self._loaded.keys())

    @property
    def all_models(self) -> Dict[str, ModelInfo]:
        """All registered models."""
        return dict(self._models)

    @property
    def resident_models(self) -> Dict[str, ModelInfo]:
        """Always-resident models."""
        return dict(self._resident_models)

    def get_swap_plan(self, target_name: str) -> Dict[str, any]:
        """
        Plan a model swap to load target model.

        Returns a plan dict with:
            - unload: list of models to unload first
            - load: the target model name
            - fits: whether it will fit after unloading
            - available_after: estimated available VRAM after unload
        """
        target = self._models.get(target_name)
        if target is None:
            return {"unload": [], "load": target_name, "fits": False, "error": "unknown model"}

        resident_vram = self.get_resident_vram()
        loaded_vram = sum(m.vram_footprint_gb for m in self._loaded.values())

        needed = target.vram_footprint_gb
        available = self.total_vram_gb - resident_vram

        if needed <= available:
            # Fits if we unload current non-resident models
            to_unload = list(self._loaded.keys())
            return {
                "unload": to_unload,
                "load": target_name,
                "fits": True,
                "available_after": available - needed,
            }
        else:
            return {
                "unload": list(self._loaded.keys()),
                "load": target_name,
                "fits": False,
                "error": "insufficient VRAM even after unloading all models",
                "needed_gb": needed,
                "available_gb": available,
            }
