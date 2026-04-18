"""
EAA V4 - Extensible AI Agent (Two-Tier Architecture)
=====================================================
Reverse-engineered from Claude Code's architecture, adapted for
local HMoE deployment on RTX 4060 Ti (8GB VRAM).

Phase 0: Two-Tier Router + Dry-Run Protocol
  - router.py: Master/Worker dynamic routing
  - workers.py: Worker lifecycle management
  - dry_run.py: Dry-Run Protocol (pre-execution approval)
  - plan_formatter.py: Delegation plan display & modification
  - vram_manager.py: PyTorch/BNB VRAM lifecycle management
"""
