"""DeepSeek chat-model factory + structured-output helper.

The understanding layer (understand / resolve_params / diagnose) uses a
DeepSeek chat model for structured extraction. When no DEEPSEEK_API_KEY is
configured the nodes fall back to deterministic heuristics — the graph still
runs (and the offline smoke test needs no LLM).

Structured-output strategy
--------------------------
DeepSeek exposes two families of models:

* Non-reasoning chat models (e.g. ``deepseek-chat``) support OpenAI-style
  function calling, so ``with_structured_output(schema, method="function_calling")``
  works directly.
* Reasoning / "thinking" models (e.g. ``deepseek-v4-pro``) reject a forced
  ``tool_choice`` ("Thinking mode does not support this tool_choice"), so the
  function_calling / json_schema methods 400 on them. They also emit their
  chain-of-thought into a separate ``reasoning_content`` channel, and
  langchain's json_mode parser is brittle against that (it occasionally raises
  OutputParserException on partial/empty content).

The portable path that works reliably on *both* families is to ask the model
for a single JSON object (embedding the target schema + the literal word
"json" in the system prompt) via a plain ``.invoke()`` and parse the JSON
ourselves into the pydantic model. We try that first and fall back to
``with_structured_output(method="function_calling")`` so callers still get a
real result if a future model only supports tool calling.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from .config import Settings

T = TypeVar("T", bound=BaseModel)


def llm_available(settings: Settings) -> bool:
    return bool(settings.deepseek_api_key)


def get_chat_model(settings: Settings):
    """Construct a ChatDeepSeek model. Raises if the API key is missing.

    Note: langchain_deepseek's ChatDeepSeek exposes the endpoint kwarg as
    ``api_base`` (there is no ``base_url`` field), and ``model`` aliases the
    underlying ``model_name`` field. Both are passed here.
    """
    if not llm_available(settings):
        raise RuntimeError("DEEPSEEK_API_KEY is not set; cannot build a chat model.")
    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        api_base=settings.deepseek_base_url,
        temperature=0,
        max_retries=2,
    )


def _json_schema_system(schema: Type[T], system: str) -> str:
    """Augment the system prompt with the target JSON schema.

    Embedding the schema + the literal word "json" lets reasoning models
    produce schema-shaped output without a forced tool_choice.
    """
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return (
        f"{system}\n\n"
        "请只输出一个 JSON 对象(a single JSON object),且必须符合下面的 JSON schema。"
        "只填写明确出现的信息;缺失的字段留空字符串或省略,不要编造,不要输出任何解释或额外文字。\n"
        f"JSON schema:\n{schema_json}"
    )


def _coerce_text(content: Any) -> str:
    """Flatten a LangChain message content (str or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return "" if content is None else str(content)


def _parse_json_object(text: str) -> Optional[dict]:
    """Extract the first JSON object from raw model text, tolerating code
    fences and surrounding prose."""
    if not text or not text.strip():
        return None
    t = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end + 1]
    try:
        obj = json.loads(t)
    except Exception:  # noqa: BLE001
        return None
    return obj if isinstance(obj, dict) else None


def extract_structured(settings: Settings, schema: Type[T], system: str, user: str) -> Optional[T]:
    """Run a single structured-output call. Returns None if the LLM is
    unavailable or every strategy fails, so callers can fall back to heuristics.

    Strategy 1 (primary, works on reasoning + chat models): ask for a JSON
    object via a plain invoke and parse it ourselves.
    Strategy 2 (fallback): with_structured_output(function_calling).
    """
    if not llm_available(settings):
        return None
    try:
        model = get_chat_model(settings)
    except Exception:  # noqa: BLE001 — heuristic fallback on construction failure
        return None

    # 1) JSON-object prompt + manual parse: portable and robust against the
    #    reasoning-channel quirks of "thinking" models.
    try:
        response = model.invoke(
            [
                {"role": "system", "content": _json_schema_system(schema, system)},
                {"role": "user", "content": user},
            ]
        )
        data = _parse_json_object(_coerce_text(getattr(response, "content", response)))
        if data is not None:
            return schema.model_validate(data)
    except Exception:  # noqa: BLE001 — try the next strategy
        pass

    # 2) function_calling: works on non-reasoning chat models that support tools.
    try:
        structured = model.with_structured_output(schema, method="function_calling")
        result = structured.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        return result
    except Exception:  # noqa: BLE001 — heuristic fallback on any LLM failure
        return None
