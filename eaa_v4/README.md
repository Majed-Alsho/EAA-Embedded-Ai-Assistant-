# EAA V4 - Embedded AI Assistant (Reverse-Engineered Claude Code)

> Fully local, hierarchical MoE agent framework running on a single RTX 4060 Ti (8GB VRAM) with Qwen2.5-7B-Instruct (BNB 4-bit).

## Architecture

```
Master (Jarvis) - Orchestrator
├── Qwen-Coder      - Code generation specialist
├── Shadow          - Review & critique specialist
├── DeepSeek R1     - Chain-of-thought reasoning
└── Browser Use     - Web navigation & automation
```

## Phases (0-7 Complete)

### Phase 0 - Core Foundation
- `router.py` - Hierarchical MoE routing (Jarvis delegates to workers)
- `workers.py` - Worker model management and lifecycle
- `dry_run.py` - Safe code execution preview before applying changes
- `plan_formatter.py` - Structured plan output formatting
- `vram_manager.py` - GPU memory tracking and allocation

### Phase 1 - Permission System
- `permissions.py` - Permission checking framework
- `permission_rules.py` - Configurable permission rules
- `safety_classifier.py` - AI-powered safety classification

### Phase 2 - File Operations
- `smart_edit.py` - Intelligent file editing with conflict detection
- `file_state.py` - File state tracking and snapshots
- `rollback.py` - One-click rollback to previous states
- `history_index.py` - File change history indexing

### Phase 3 - Context Management
- `context_manager.py` - Multi-layer context cascade
- `token_tracker.py` - Real-time token usage monitoring
- `conversation_compactor.py` - Smart conversation compression
- `system_memory.py` - Persistent system-level memory

### Phase 4 - Prompt Engineering
- `prompt_assembler.py` - Dynamic prompt construction
- `prompt_cache.py` - Prompt caching for efficiency
- `memory_loader.py` - YAML frontmatter memory loading
- `tool_instructions.py` - Tool use instruction templates

### Phase 5 - Plugin System & Model Registry
- `plugin_config.py` - Plugin configuration management
- `plugin_manager.py` - Plugin lifecycle and hot-loading
- `model_registry.py` - Multi-model registration and switching
- `vram_lifecycle.py` - GPU memory lifecycle management

### Phase 6 - Self-Healing Loop (NEW)
- `error_handler.py` - 3-tier token recovery cascade + JSONDecodeError intercept
- `validation_hooks.py` - py_compile syntax hook + Transient UI Spinner
- `concurrent_isolation.py` - Sibling-aware task isolation

### Phase 7 - Cross-Session Memory (NEW)
- `session_transcript.py` - JSONL persistence + token-aware /resume (6K hard cap)
- `session_memory.py` - Rolling Markdown notes, zero-API-call compaction
- `memory_extractor.py` - Background heuristic extraction + 4K sliding window
- `prompt_history.py` - Global project-level command history

## File Map

```
eaa_v4/
├── session_transcript.py      ← Phase 7
├── session_memory.py          ← Phase 7
├── memory_extractor.py        ← Phase 7
├── prompt_history.py          ← Phase 7
├── error_handler.py           ← Phase 6
├── validation_hooks.py        ← Phase 6
├── concurrent_isolation.py    ← Phase 6
├── plugin_config.py           ← Phase 5
├── plugin_manager.py          ← Phase 5
├── model_registry.py          ← Phase 5
├── vram_lifecycle.py          ← Phase 5
├── prompt_cache.py            ← Phase 4
├── prompt_assembler.py        ← Phase 4
├── memory_loader.py           ← Phase 4
├── tool_instructions.py       ← Phase 4
├── context_manager.py         ← Phase 3
├── token_tracker.py           ← Phase 3
├── conversation_compactor.py  ← Phase 3
├── system_memory.py           ← Phase 3
├── smart_edit.py              ← Phase 2
├── file_state.py              ← Phase 2
├── rollback.py                ← Phase 2
├── history_index.py           ← Phase 2
├── permissions.py             ← Phase 1
├── permission_rules.py        ← Phase 1
├── safety_classifier.py       ← Phase 1
├── router.py                  ← Phase 0
├── workers.py                 ← Phase 0
├── dry_run.py                 ← Phase 0
├── plan_formatter.py          ← Phase 0
├── vram_manager.py            ← Phase 0
└── tests/
    ├── test_phase0.py         (57 tests)
    ├── test_phase1.py         (94 tests)
    ├── test_phase2.py         (75 tests)
    ├── test_phase3.py         (tests)
    ├── test_phase4.py         (139 tests)
    ├── test_phase5.py         (133 tests)
    ├── test_phase6.py         (70 tests)  ← NEW
    └── test_phase7.py         (56 tests)  ← NEW
```

## Test Suite

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific phase
python tests/test_phase6.py
python tests/test_phase7.py
```

**Total: 626+ tests across all phases**

## Hardware

- GPU: NVIDIA RTX 4060 Ti (8GB VRAM)
- Model: Qwen2.5-7B-Instruct (BitsAndBytes 4-bit quantization)
- Framework: Hierarchical Mixture of Experts (MoE)

## Key Design Principles

1. **Self-Healing**: Errors wrapped as `is_error: true` tool results fed back to LLM
2. **3-Tier Recovery**: Double tokens → Inject continuation → Escalate to Master
3. **Zero-API Compaction**: Rolling Markdown notes instead of LLM summarization
4. **Token-Aware Resume**: 6K token hard cap for cross-session continuity
5. **Sliding Window Extraction**: 4K chunks with 1K overlap for memory extraction
