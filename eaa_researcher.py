import asyncio
import json
import os
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, TypeVar

import torch
from pydantic import BaseModel

from browser_use import Agent, Browser, Tools
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion

from brain_manager import BrainManager

# ===========================
# CONFIG
# ===========================
BRAIN_ID = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
brain_manager = BrainManager()
T = TypeVar("T", bound=BaseModel)

# --- Prove the pipeline works first (no captcha, fast, pure JSON) ---
BTC_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"

# --- If you insist on Google, you almost always need a real profile ---
# Set these to your Chrome user data dir + profile name (optional).
# Example Windows user_data_dir:
#   r"C:\Users\YOURNAME\AppData\Local\Google\Chrome\User Data"
USER_DATA_DIR = None          # <- set to a string path to reuse cookies (recommended for Google)
PROFILE_DIRECTORY = "Default" # or "Profile 1", etc.

# If you're getting bot-flagged hard, set a normal UA.
USER_AGENT = None  # e.g. "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ... Chrome/122.0.0.0 Safari/537.36"

# Browser-use timeouts can also be controlled via env vars. (Docs list these)
# These are action timeouts, not the "page readiness" warning, but they help on slow pages. :contentReference[oaicite:3]{index=3}
os.environ.setdefault("TIMEOUT_NavigateToUrlEvent", "45")
os.environ.setdefault("TIMEOUT_ClickElementEvent", "30")
os.environ.setdefault("TIMEOUT_TypeTextEvent", "90")
os.environ.setdefault("TIMEOUT_ScrollEvent", "20")


# ===========================
# OUTPUT REPAIR (Qwen-safe)
# ===========================
def _strip_fences_and_artifacts(text: str) -> str:
    text = (text or "").strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    if "<|im_start|>assistant" in text:
        text = text.split("<|im_start|>assistant")[-1].strip()

    return text


def _extract_first_json_object(text: str) -> dict:
    text = _strip_fences_and_artifacts(text)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found. Output starts with:\n{text[:300]}")

    return json.loads(text[start : end + 1])


def _looks_like_url(s: str) -> bool:
    s = (s or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://") or "." in s


def _coerce_action_item(action_name: str, params: Any) -> dict:
    """
    browser-use action format is:
      {"some_action": {"param": "value"}}
    Qwen often returns:
      {"navigate": "https://..."}
    or:
      {"click_element": 12}
    Fix those.
    """
    if params is None:
        params = {}

    # Common key renames inside params dict
    if isinstance(params, dict):
        if "element_index" in params and "index" not in params:
            params["index"] = params.pop("element_index")
        if "content" in params and "text" not in params:
            params["text"] = params.pop("content")
        if "newTab" in params and "new_tab" not in params:
            params["new_tab"] = params.pop("newTab")

    # If params is a string, wrap it
    if isinstance(params, str):
        if _looks_like_url(params):
            # best guess for navigate/open_tab/go_to_url
            return {action_name: {"url": params}}
        return {action_name: {"text": params}}

    # If params is a number, likely an element index for click
    if isinstance(params, int):
        return {action_name: {"index": params}}

    # If params is already a dict, accept it
    if isinstance(params, dict):
        return {action_name: params}

    # Fallback
    return {action_name: {"text": str(params)}}


def _normalize_to_schema(data: dict, output_format: type[T]) -> dict:
    """
    Make local-model outputs compatible with browser-use's Pydantic schemas.
    Fixes:
      - actions -> action
      - action dict -> [action dict]
      - Qwen "navigate": "url" -> {"navigate":{"url":"url"}}
      - Qwen "click_element": 12 -> {"click_element":{"index":12}}
      - Drop unknown top-level keys if schema forbids extras
    """
    if not isinstance(data, dict):
        return data

    # Some models output "actions" instead of "action"
    if "action" not in data and "actions" in data:
        data["action"] = data.pop("actions")

    # Some models nest fields under current_state
    if "current_state" in data and isinstance(data["current_state"], dict):
        cs = data.pop("current_state")
        for k in ("thinking", "evaluation_previous_goal", "memory", "next_goal"):
            if k not in data and k in cs:
                data[k] = cs.get(k)

    # Ensure action is a list
    actions = data.get("action", [])
    if isinstance(actions, dict):
        actions = [actions]
    elif isinstance(actions, str):
        actions = [{"done": {"text": actions}}]
    elif not isinstance(actions, list):
        actions = [{"done": {"text": str(actions)}}]

    fixed_actions = []
    for a in actions:
        if isinstance(a, str):
            fixed_actions.append({"done": {"text": a}})
            continue

        if not isinstance(a, dict) or not a:
            continue

        # If model used {"type": "...", ...} shape, convert to {"...": {...}}
        if "type" in a and isinstance(a["type"], str):
            action_name = a["type"].strip()
            params = {k: v for k, v in a.items() if k != "type"}
            fixed_actions.append(_coerce_action_item(action_name, params))
            continue

        # If multiple keys, keep the first (agent will retry if needed)
        action_name = next(iter(a.keys()))
        params = a[action_name]
        fixed_actions.append(_coerce_action_item(action_name, params))

    if not fixed_actions:
        fixed_actions = [{"done": {"text": "No valid actions produced."}}]

    data["action"] = fixed_actions

    # Fill required fields if present in schema
    fields = getattr(output_format, "model_fields", {}) or {}
    for k in ("evaluation_previous_goal", "memory", "next_goal"):
        if k in fields and k not in data:
            data[k] = ""

    # Drop unknown top-level keys if schema forbids extras
    allowed = set(fields.keys()) if fields else set(data.keys())
    data = {k: v for k, v in data.items() if k in allowed}

    return data


# ===========================
# LLM BRIDGE
# ===========================
@dataclass
class EAALocalChat(BaseChatModel):
    model: str = BRAIN_ID
    _loaded_model: Any = field(default=None, init=False, repr=False)
    _tokenizer: Any = field(default=None, init=False, repr=False)
    _bad_json_count: int = field(default=0, init=False, repr=False)

    @property
    def provider(self) -> str:
        return "eaa-local"

    @property
    def name(self) -> str:
        return self.model

    def _ensure_loaded(self) -> None:
        if self._loaded_model is None or self._tokenizer is None:
            self._loaded_model, self._tokenizer = brain_manager.load(self.model)
            try:
                self._loaded_model.eval()
            except Exception:
                pass

    def _device(self) -> torch.device:
        m = self._loaded_model
        try:
            return next(m.parameters()).device
        except Exception:
            return getattr(m, "device", torch.device("cpu"))

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        output_format: type[T] | None = None,
        **kwargs: Any,
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        self._ensure_loaded()
        model = self._loaded_model
        tok = self._tokenizer

        # browser-use BaseMessage exposes .role and .text
        eaa_messages = [{"role": m.role, "content": m.text} for m in messages]

        # Extra guardrails for local models: JSON only, no markdown.
        # Keep it short; include_tool_call_examples will provide the real action examples.
        system_guard = {
            "role": "system",
            "content": (
                "Output MUST be a single valid JSON object, no markdown, no commentary. "
                "If an action takes parameters, the value must be a JSON object (not a string)."
            ),
        }
        if not eaa_messages or eaa_messages[0]["role"] != "system":
            eaa_messages = [system_guard] + eaa_messages

        prompt_ids = tok.apply_chat_template(
            eaa_messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )
        attention_mask = torch.ones_like(prompt_ids)

        max_new_tokens = int(kwargs.get("max_new_tokens", 512))

        lock_ctx = nullcontext()
        lock_for = getattr(brain_manager, "lock_for", None)
        if callable(lock_for):
            lock_ctx = lock_for(self.model)

        pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
        eos_id = tok.eos_token_id

        def _run_gen() -> str:
            with lock_ctx, torch.inference_mode():
                device = self._device()
                input_ids = prompt_ids.to(device)
                attn = attention_mask.to(device)

                out = model.generate(
                    input_ids=input_ids,
                    attention_mask=attn,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    temperature=0.0,
                    pad_token_id=pad_id,
                    eos_token_id=eos_id,
                    use_cache=True,
                )

                new_tokens = out[0, input_ids.shape[-1] :]
                return tok.decode(new_tokens, skip_special_tokens=True).strip()

        raw = await asyncio.to_thread(_run_gen)
        raw = _strip_fences_and_artifacts(raw)

        if output_format is None:
            return ChatInvokeCompletion(completion=raw, usage=None)

        # Structured output path
        try:
            data = _extract_first_json_object(raw)
            data = _normalize_to_schema(data, output_format)
            parsed = output_format.model_validate(data)
            self._bad_json_count = 0
            return ChatInvokeCompletion(completion=parsed, usage=None)

        except Exception:
            # Let it retry once or twice; after that, stop the death-spiral with a "done".
            self._bad_json_count += 1
            if self._bad_json_count >= 3:
                fallback = {"memory": "", "action": [{"done": {"text": raw[:1500] or "LLM returned invalid JSON."}}]}
                fallback = _normalize_to_schema(fallback, output_format)
                parsed = output_format.model_validate(fallback)
                return ChatInvokeCompletion(completion=parsed, usage=None)
            raise


# ===========================
# RUNNER
# ===========================
async def run_research_task(user_query: str, show_browser: bool = True) -> str:
    llm = EAALocalChat()

    # Tools: keep the core set; always exclude screenshot when not using vision.
    tools = Tools(exclude_actions=["screenshot"])

    # Browser parameters: user_data_dir/profile_directory/user_agent are supported. :contentReference[oaicite:4]{index=4}
    browser = Browser(
        headless=not show_browser,
        user_data_dir=USER_DATA_DIR,
        profile_directory=PROFILE_DIRECTORY,
        user_agent=USER_AGENT,
        # Make the agent less trigger-happy on dynamic pages.
        minimum_wait_page_load_time=1.0,
        wait_for_network_idle_page_load_time=2.0,
        wait_between_actions=0.8,
    )

    # IMPORTANT: Google blocks bots. Use BTC_PRICE_URL first to validate your stack.
    # Then try search engines that are less aggressive than Google.
    initial_actions = [{"open_tab": {"url": BTC_PRICE_URL}}]

    agent = Agent(
        task=user_query,
        llm=llm,
        browser=browser,
        tools=tools,
        use_vision=False,
        flash_mode=True,
        include_tool_call_examples=True,
        use_judge=False,
        enable_planning=False,
        max_failures=8,
        max_actions_per_step=3,
        initial_actions=initial_actions,
        extend_system_message=(
            "If you see anti-bot / captcha pages, do NOT try to solve them. "
            "Instead: open a different source site or use a public JSON API endpoint."
        ),
    )

    try:
        await browser.start()
        history = await agent.run()

        result = history.final_result()
        if result:
            return result

        # If no result, dump the useful debug signals.
        errs = history.errors()
        outs = history.model_outputs()
        acts = history.model_actions()

        last_err = next((e for e in reversed(errs) if e), None)
        last_out = next((o for o in reversed(outs) if o), None)
        last_act = next((a for a in reversed(acts) if a), None)

        debug = []
        debug.append("Agent finished but returned no summary.")
        if last_err:
            debug.append(f"\nLAST ERROR:\n{last_err}")
        if last_act:
            debug.append(f"\nLAST MODEL ACTIONS:\n{last_act}")
        if last_out:
            debug.append(f"\nLAST MODEL OUTPUT (raw):\n{str(last_out)[:1200]}")

        return "\n".join(debug)

    finally:
        try:
            await browser.stop()
        except Exception:
            pass


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "Get the current BTC price in USD and return it."
    print(asyncio.run(run_research_task(q, show_browser=True)))
