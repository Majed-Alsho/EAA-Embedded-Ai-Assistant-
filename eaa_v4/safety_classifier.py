"""
EAA V4 - AI Safety Classifier
==============================
Uses a small resident 1.5B model to perform deep intent analysis on
DelegationTasks that the RuleEngine flags as REVIEW_REQUIRED.

WHY A SEPARATE CLASSIFIER?
  The RuleEngine uses regex patterns and tool categories for fast, deterministic
  decisions. But some operations are context-dependent: "delete temp files" is
  fine in a build directory but dangerous in /etc/. A 7B model is too expensive
  to keep loaded for classification alone, so we use a dedicated 1.5B model.

  The classifier stays resident in VRAM (~200MB at BNB 4-bit) alongside any
  active worker because:
  1. It's tiny — fits in the safety margin (8GB - 5.9GB = 2.1GB free)
  2. It needs fast response — loading/unloading for each check adds 3s latency
  3. Classification is prompt-based — no fine-tuning needed, just a system prompt

CLASSIFICATION LEVELS:
  - safe:       The operation is benign and can proceed
  - suspicious: The operation could be harmful in certain contexts
  - dangerous:  The operation is likely harmful and should be blocked

HOW IT WORKS:
  The classifier receives a structured prompt with:
  1. The tool name and arguments
  2. The worker that requested it
  3. The reason given for the request
  4. Context from the conversation (optional)

  It outputs a JSON verdict with:
  - label: "safe" / "suspicious" / "dangerous"
  - confidence: 0.0-1.0
  - reasoning: Brief explanation

VRAM INTEGRATION:
  The classifier uses VRAMManager.load_classifier() / unload_classifier()
  for lifecycle management. The model reference is stored here and shared
  with VRAMManager to avoid double-loading.

FALLBACK:
  If the classifier model is not available (not downloaded, OOM, etc.),
  the system falls back to rule-based-only mode. This means REVIEW_REQUIRED
  tasks will always be sent to dry-run (conservative but safe).
"""

import json
import time
import logging
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION RESULTS
# ═══════════════════════════════════════════════════════════════════════════════

class SafetyLabel(Enum):
    """Classification result from the safety classifier."""
    SAFE = "safe"                  # Operation is benign
    SUSPICIOUS = "suspicious"      # Could be harmful in certain contexts
    DANGEROUS = "dangerous"        # Likely harmful, should be blocked


@dataclass
class ClassificationResult:
    """
    Result of the AI safety classifier.
    Contains the verdict plus metadata.
    """
    label: SafetyLabel
    confidence: float               # 0.0 - 1.0
    reasoning: str = ""             # Brief explanation
    model_used: str = ""            # Which model produced this
    latency_ms: float = 0.0         # Classification time
    fallback_used: bool = False     # True if heuristic fallback was used

    def to_dict(self) -> Dict:
        return {
            "label": self.label.value,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "model_used": self.model_used,
            "latency_ms": round(self.latency_ms, 1),
            "fallback_used": self.fallback_used,
        }

    @property
    def label_str(self) -> str:
        return self.label.value


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFIER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ClassifierConfig:
    """Configuration for the Safety Classifier."""
    model_id: str = "qwen2.5-1.5b-safety-classifier"
    model_path: str = ""                    # Local path (empty = use model_id)
    max_tokens: int = 128                   # Max tokens for classification output
    temperature: float = 0.1                # Low temp for deterministic output
    confidence_threshold: float = 0.6       # Below this → default to suspicious
    timeout_seconds: int = 10               # Max time for classification
    enable_heuristic_fallback: bool = True  # Use regex fallback if model unavailable
    batch_size: int = 8                     # Classify up to N tasks in one prompt


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════

CLASSIFIER_SYSTEM_PROMPT = """You are a safety classifier for an AI agent system.
Your job is to analyze tool invocations and determine if they are safe,
suspicious, or dangerous.

## Classification Criteria:

### SAFE (label: "safe")
- Read operations (file reads, web searches, system info)
- Write operations to non-sensitive paths (project files, temp files)
- Code execution in sandboxed or test environments
- Standard development operations (git status, lint, format)

### SUSPICIOUS (label: "suspicious")
- Write operations to system paths or config files
- Shell commands with variables or wildcards
- Network requests to unknown endpoints
- Process management operations
- Database write operations (INSERT, UPDATE, DELETE)
- Code execution that accesses the filesystem or network
- Operations that modify environment variables

### DANGEROUS (label: "dangerous")
- Any form of file deletion (rm, del, remove)
- Shell commands with sudo/admin privileges
- Operations on security-sensitive files (.ssh, .gnupg, .env, credentials)
- System shutdown/reboot/format commands
- Mass file operations (recursive delete, bulk rename)
- Code execution with eval/exec/subprocess
- Any operation that could cause data loss or system instability

## Output Format:
You MUST respond with ONLY a JSON object in this exact format:
{"label": "safe|suspicious|dangerous", "confidence": 0.0-1.0, "reasoning": "brief explanation"}

Do NOT include any text outside the JSON object.
"""

SINGLE_CLASSIFICATION_PROMPT = """Classify this tool invocation:

Tool: {tool_name}
Worker: {worker_id}
Arguments: {args_json}
Reason: {reason}

Respond with JSON: {{"label": "safe|suspicious|dangerous", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}
"""

BATCH_CLASSIFICATION_PROMPT = """Classify each of these tool invocations. For each one, output a JSON object.

{tasks_text}

Output a JSON array with one object per task:
[{{"index": 0, "label": "safe|suspicious|dangerous", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}, ...]
"""


# ═══════════════════════════════════════════════════════════════════════════════
# HEURISTIC FALLBACK CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════════

class HeuristicClassifier:
    """
    Regex-based fallback classifier when the AI model is unavailable.
    Conservative: defaults to "suspicious" for anything uncertain.
    """

    # Patterns that suggest dangerous intent
    DANGEROUS_PATTERNS = [
        (r"rm\s+(-\w*\s+)?(/|~|\*)", "file deletion pattern detected"),
        (r"sudo\s", "sudo privilege escalation detected"),
        (r"(del|remove|erase)\s+", "file deletion command detected"),
        (r"format\s", "disk format detected"),
        (r"shutdown|reboot|halt", "system shutdown/reboot detected"),
        (r"eval\s*", "dynamic code execution detected"),
        (r"exec\s*\(", "dynamic code execution detected"),
        (r"subprocess\.(call|run|Popen)", "subprocess execution detected"),
        (r"os\.system\s*\(", "OS command execution detected"),
        (r"\.ssh|\.gnupg|\.aws|credentials|\.env", "sensitive path detected"),
        (r"(DROP|TRUNCATE)\s+(TABLE|DATABASE)", "database destruction detected"),
        (r">\s*/dev/", "direct device write detected"),
        (r"chmod\s+777", "insecure permissions detected"),
        (r"fork\s*\(\s*\)", "process forking detected"),
    ]

    # Patterns that suggest safe intent
    SAFE_PATTERNS = [
        (r"read_file", "file read operation"),
        (r"(read|cat|head|tail|less|more)\s+", "read operation"),
        (r"list_files|file_exists|glob|grep", "file query operation"),
        (r"(ls|dir|list)\s+", "directory listing"),
        (r"(grep|find|search)\s+", "search operation"),
        (r"(status|info|version|help)\s*", "status/info query"),
        (r"(git\s+status|git\s+log|git\s+diff)", "git read operation"),
        (r"(print|echo|write|log)\s+", "output operation"),
        (r"web_search|web_fetch|calculator|datetime", "safe utility operation"),
        (r"system_info|process_list|git_status|git_diff|git_log", "safe system query"),
    ]

    def classify(
        self,
        tool_name: str,
        tool_args: Dict,
        worker_id: str = "",
        reason: str = "",
    ) -> ClassificationResult:
        """Classify using heuristic patterns."""
        args_text = json.dumps(tool_args, default=str).lower()
        full_text = f"{tool_name} {args_text} {reason}".lower()

        # Check dangerous patterns first (these always take priority)
        for pattern, desc in self.DANGEROUS_PATTERNS:
            if re.search(pattern, full_text, re.IGNORECASE):
                return ClassificationResult(
                    label=SafetyLabel.DANGEROUS,
                    confidence=0.85,
                    reasoning=f"Heuristic: {desc}",
                    model_used="heuristic",
                    fallback_used=True,
                )

        # Check if tool_name itself is in the known-safe tools set
        SAFE_TOOL_NAMES = {
            "read_file", "list_files", "file_exists", "glob", "grep",
            "web_search", "web_fetch", "system_info", "process_list",
            "datetime", "calculator", "git_status", "git_diff", "git_log",
            "git_branch", "pdf_read", "pdf_info", "docx_read", "xlsx_read",
            "browser_screenshot", "browser_get_text", "code_lint", "code_test",
            "memory_recall", "memory_list", "memory_search",
            "json_parse", "csv_read", "hash_text", "hash_file",
            "schedule_list", "schedule_info", "screenshot", "clipboard_read",
        }
        if tool_name in SAFE_TOOL_NAMES:
            return ClassificationResult(
                label=SafetyLabel.SAFE,
                confidence=0.9,
                reasoning=f"Heuristic: tool '{tool_name}' is a known-safe read-only tool",
                model_used="heuristic",
                fallback_used=True,
            )

        # Check safe patterns in full text
        safe_count = 0
        for pattern, desc in self.SAFE_PATTERNS:
            if re.search(pattern, full_text, re.IGNORECASE):
                safe_count += 1

        if safe_count >= 1:
            return ClassificationResult(
                label=SafetyLabel.SAFE,
                confidence=0.7,
                reasoning=f"Heuristic: {safe_count} safe pattern(s) matched",
                model_used="heuristic",
                fallback_used=True,
            )

        # Default: suspicious (conservative)
        return ClassificationResult(
            label=SafetyLabel.SUSPICIOUS,
            confidence=0.5,
            reasoning="Heuristic: no specific pattern matched, defaulting to suspicious",
            model_used="heuristic",
            fallback_used=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN SAFETY CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════════

class SafetyClassifier:
    """
    AI-powered safety classifier for DelegationTasks.

    Uses a 1.5B model (stays resident in VRAM ~200MB) to classify
    the intent of tool invocations that the RuleEngine flags as ambiguous.

    The classifier operates in two modes:
    1. AI mode: Uses the 1.5B model for deep analysis
    2. Fallback mode: Uses HeuristicClassifier when model unavailable

    Usage:
        classifier = SafetyClassifier()
        classifier.load_model(model)  # Pass PyTorch model from VRAMManager
        result = classifier.classify(
            tool_name="shell",
            tool_args={"command": "pip install numpy"},
            worker_id="shadow",
        )
        if result.label == SafetyLabel.SAFE:
            # Proceed
    """

    def __init__(self, config: Optional[ClassifierConfig] = None):
        self.config = config or ClassifierConfig()
        self._model = None
        self._tokenizer = None
        self._heuristic = HeuristicClassifier()
        self._is_loaded = False
        self._use_fallback = self.config.enable_heuristic_fallback

        # Stats
        self._total_classifications = 0
        self._ai_classifications = 0
        self._fallback_classifications = 0
        self._classification_log: List[Dict] = []
        self._label_counts = {
            SafetyLabel.SAFE: 0,
            SafetyLabel.SUSPICIOUS: 0,
            SafetyLabel.DANGEROUS: 0,
        }

        logger.info(
            f"[Classifier] Initialized: model={self.config.model_id}, "
            f"fallback={self.config.enable_heuristic_fallback}"
        )

    def load_model(self, model=None, tokenizer=None):
        """
        Set the AI model reference (loaded by VRAMManager).
        The classifier does NOT load the model itself — VRAMManager
        handles VRAM allocation and the model reference is shared.
        """
        if model is not None:
            self._model = model
        if tokenizer is not None:
            self._tokenizer = tokenizer
        self._is_loaded = self._model is not None
        self._use_fallback = not self._is_loaded

        if self._is_loaded:
            logger.info("[Classifier] AI model connected, ready for classification")
        else:
            if self.config.enable_heuristic_fallback:
                logger.info("[Classifier] No AI model, using heuristic fallback")
            else:
                logger.warning("[Classifier] No AI model and fallback disabled!")

    @property
    def is_loaded(self) -> bool:
        """Whether the AI model is available."""
        return self._is_loaded

    @property
    def is_using_fallback(self) -> bool:
        """Whether we're using heuristic fallback."""
        return self._use_fallback

    def classify(
        self,
        tool_name: str,
        tool_args: Dict,
        worker_id: str = "",
        reason: str = "",
    ) -> ClassificationResult:
        """
        Classify a single tool invocation.

        Args:
            tool_name: Name of the tool
            tool_args: Tool arguments
            worker_id: Worker making the request
            reason: Reason given for the request

        Returns:
            ClassificationResult with label, confidence, and reasoning
        """
        self._total_classifications += 1
        start = time.time()

        # Use AI model if available
        if self._is_loaded and self._model is not None:
            result = self._classify_with_model(
                tool_name, tool_args, worker_id, reason
            )
            self._ai_classifications += 1
        elif self.config.enable_heuristic_fallback:
            result = self._heuristic.classify(
                tool_name, tool_args, worker_id, reason
            )
            self._fallback_classifications += 1
        else:
            # No model and no fallback — conservative default
            result = ClassificationResult(
                label=SafetyLabel.SUSPICIOUS,
                confidence=0.5,
                reasoning="No classifier available, defaulting to suspicious",
                model_used="none",
                fallback_used=False,
            )
            self._fallback_classifications += 1

        result.latency_ms = (time.time() - start) * 1000
        result.model_used = result.model_used or self.config.model_id

        # Track stats
        self._label_counts[result.label] += 1

        # Log
        self._classification_log.append({
            "timestamp": time.time(),
            "tool": tool_name,
            "worker": worker_id,
            "label": result.label.value,
            "confidence": result.confidence,
            "model": result.model_used,
            "latency_ms": result.latency_ms,
        })
        if len(self._classification_log) > 2000:
            self._classification_log = self._classification_log[-1000:]

        return result

    def classify_batch(
        self,
        tasks: List[Dict],
    ) -> List[ClassificationResult]:
        """
        Classify a batch of tasks efficiently.

        Args:
            tasks: List of dicts with keys:
                   tool_name, tool_args, worker_id, reason

        Returns:
            List of ClassificationResult (one per task)
        """
        if not tasks:
            return []

        # For small batches, classify individually (simpler)
        if len(tasks) <= self.config.batch_size:
            return [
                self.classify(
                    tool_name=t.get("tool_name", ""),
                    tool_args=t.get("tool_args", {}),
                    worker_id=t.get("worker_id", ""),
                    reason=t.get("reason", ""),
                )
                for t in tasks
            ]

        # For larger batches, try batch classification with AI
        if self._is_loaded and self._model:
            results = self._classify_batch_with_model(tasks)
            # Fill in any missing results
            while len(results) < len(tasks):
                idx = len(results)
                results.append(
                    self._heuristic.classify(
                        tasks[idx].get("tool_name", ""),
                        tasks[idx].get("tool_args", {}),
                        tasks[idx].get("worker_id", ""),
                        tasks[idx].get("reason", ""),
                    )
                )
            return results
        else:
            return [
                self._heuristic.classify(
                    t.get("tool_name", ""),
                    t.get("tool_args", {}),
                    t.get("worker_id", ""),
                    t.get("reason", ""),
                )
                for t in tasks
            ]

    def _classify_with_model(
        self,
        tool_name: str,
        tool_args: Dict,
        worker_id: str,
        reason: str,
    ) -> ClassificationResult:
        """
        Classify using the AI model.

        This constructs a prompt, sends it to the 1.5B model,
        and parses the JSON response.
        """
        try:
            prompt = SINGLE_CLASSIFICATION_PROMPT.format(
                tool_name=tool_name,
                worker_id=worker_id,
                args_json=json.dumps(tool_args, default=str),
                reason=reason or "not specified",
            )

            # Build messages for chat model
            messages = [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            # Generate response
            response_text = self._generate(messages)

            if not response_text:
                return self._fallback_classify(tool_name, tool_args, worker_id, reason)

            # Parse JSON response
            result = self._parse_classification_response(response_text)

            if result is None:
                return self._fallback_classify(tool_name, tool_args, worker_id, reason)

            return result

        except Exception as e:
            logger.error(f"[Classifier] AI classification failed: {e}")
            return self._fallback_classify(tool_name, tool_args, worker_id, reason)

    def _classify_batch_with_model(
        self, tasks: List[Dict]
    ) -> List[ClassificationResult]:
        """Classify a batch using a single model call."""
        try:
            tasks_text = ""
            for i, t in enumerate(tasks):
                tasks_text += f"\n--- Task {i} ---\n"
                tasks_text += f"Tool: {t.get('tool_name', '')}\n"
                tasks_text += f"Worker: {t.get('worker_id', '')}\n"
                tasks_text += f"Arguments: {json.dumps(t.get('tool_args', {}), default=str)}\n"
                tasks_text += f"Reason: {t.get('reason', 'not specified')}\n"

            prompt = BATCH_CLASSIFICATION_PROMPT.format(tasks_text=tasks_text)
            messages = [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            response_text = self._generate(messages)
            if not response_text:
                return [self._fallback_classify(**t) for t in tasks]

            return self._parse_batch_response(response_text, len(tasks))

        except Exception as e:
            logger.error(f"[Classifier] Batch classification failed: {e}")
            return [self._fallback_classify(**t) for t in tasks]

    def _generate(self, messages: List[Dict]) -> Optional[str]:
        """
        Generate a response from the model.
        This is a placeholder — in production, it uses the actual
        PyTorch model + tokenizer from VRAMManager.
        """
        if self._model is None or self._tokenizer is None:
            return None

        try:
            # Apply chat template if available
            if hasattr(self._tokenizer, 'apply_chat_template'):
                text = self._tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            else:
                # Simple concatenation fallback
                text = "\n".join(
                    f"{'System' if m['role'] == 'system' else 'User'}: {m['content']}"
                    for m in messages
                )
                text += "\nAssistant:"

            # Tokenize
            inputs = self._tokenizer(text, return_tensors="pt")
            if self._is_loaded:
                inputs = inputs.to(self._model.device)

            # Generate
            with _no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    do_sample=self.config.temperature > 0,
                    pad_token_id=self._tokenizer.eos_token_id,
                )

            # Decode
            new_tokens = outputs[0][inputs['input_ids'].shape[-1]:]
            response = self._tokenizer.decode(new_tokens, skip_special_tokens=True)
            return response.strip()

        except Exception as e:
            logger.error(f"[Classifier] Generation failed: {e}")
            return None

    def _parse_classification_response(
        self, text: str
    ) -> Optional[ClassificationResult]:
        """Parse the model's JSON response into a ClassificationResult."""
        # Try to extract JSON from the response
        # Model might wrap in markdown code blocks
        json_match = re.search(r'\{[^}]+\}', text, re.DOTALL)
        if not json_match:
            # Try the full text
            json_match = re.search(r'.*', text, re.DOTALL)

        if not json_match:
            return None

        try:
            data = json.loads(json_match.group(0))

            label_str = data.get("label", "suspicious").lower()
            confidence = float(data.get("confidence", 0.5))
            reasoning = str(data.get("reasoning", ""))

            # Validate label
            try:
                label = SafetyLabel(label_str)
            except ValueError:
                label = SafetyLabel.SUSPICIOUS
                reasoning += f" (invalid label '{label_str}', defaulting to suspicious)"

            # Clamp confidence
            confidence = max(0.0, min(1.0, confidence))

            # If confidence too low, escalate to suspicious
            if confidence < self.config.confidence_threshold and label == SafetyLabel.SAFE:
                label = SafetyLabel.SUSPICIOUS
                reasoning += " (low confidence, escalated to suspicious)"

            return ClassificationResult(
                label=label,
                confidence=confidence,
                reasoning=reasoning,
                model_used=self.config.model_id,
            )

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"[Classifier] Failed to parse response: {e}")
            return None

    def _parse_batch_response(
        self, text: str, expected_count: int
    ) -> List[ClassificationResult]:
        """Parse a batch JSON response."""
        # Try to extract JSON array
        array_match = re.search(r'\[.*\]', text, re.DOTALL)
        if not array_match:
            return []

        try:
            items = json.loads(array_match.group(0))
            results = []

            for item in items:
                label_str = item.get("label", "suspicious").lower()
                try:
                    label = SafetyLabel(label_str)
                except ValueError:
                    label = SafetyLabel.SUSPICIOUS

                results.append(ClassificationResult(
                    label=label,
                    confidence=float(item.get("confidence", 0.5)),
                    reasoning=str(item.get("reasoning", "")),
                    model_used=self.config.model_id,
                ))

            return results

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"[Classifier] Failed to parse batch response: {e}")
            return []

    def _fallback_classify(
        self,
        tool_name: str,
        tool_args: Dict,
        worker_id: str = "",
        reason: str = "",
    ) -> ClassificationResult:
        """Use heuristic fallback."""
        result = self._heuristic.classify(tool_name, tool_args, worker_id, reason)
        return result

    def get_stats(self) -> Dict:
        """Get classifier statistics."""
        total = self._total_classifications
        return {
            "model_loaded": self._is_loaded,
            "using_fallback": self._use_fallback,
            "model_id": self.config.model_id,
            "total_classifications": total,
            "ai_classifications": self._ai_classifications,
            "fallback_classifications": self._fallback_classifications,
            "ai_usage_rate": (
                f"{self._ai_classifications / max(1, total) * 100:.1f}%"
            ),
            "label_distribution": {
                label.value: count
                for label, count in self._label_counts.items()
            },
            "recent_classifications": self._classification_log[-10:],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: no_grad context (avoids import if torch not available)
# ═══════════════════════════════════════════════════════════════════════════════

class _no_grad:
    """Fallback no_grad context when torch is not available."""
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# Try to import the real torch.no_grad
try:
    from torch import no_grad as _torch_no_grad
    _no_grad = _torch_no_grad
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ═══════════════════════════════════════════════════════════════════════════════

def create_classifier(
    model: Any = None,
    tokenizer: Any = None,
    use_fallback: bool = True,
) -> SafetyClassifier:
    """
    Create a SafetyClassifier with optional model connection.

    Args:
        model: PyTorch model (from VRAMManager)
        tokenizer: Tokenizer for the model
        use_fallback: Enable heuristic fallback if model unavailable
    """
    config = ClassifierConfig(
        enable_heuristic_fallback=use_fallback,
    )
    classifier = SafetyClassifier(config=config)

    if model is not None or tokenizer is not None:
        classifier.load_model(model=model, tokenizer=tokenizer)

    return classifier


__all__ = [
    "SafetyLabel",
    "ClassificationResult",
    "ClassifierConfig",
    "HeuristicClassifier",
    "SafetyClassifier",
    "create_classifier",
]
