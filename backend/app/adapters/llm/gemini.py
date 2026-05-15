"""
Google Gemini 1.5 Flash adapter — free tier.

Free limits (as of 2025):
  - 15 requests / min
  - 1,000,000 tokens / day
  - 1,500 requests / day

When tools are provided (e.g. judge_call), we use Gemini's JSON mode and
ask it to respond strictly in the tool's input_schema format.
This avoids needing to convert Anthropic tool definitions to Gemini
function declarations.
"""
import json
import re
import httpx
from typing import Optional
from app.adapters.llm.base import LLMAdapter
from app.core.config import settings
import structlog

log = structlog.get_logger()

# Model aliases — using gemini-2.5-flash family (works on free/new API keys)
GEMINI_FLASH      = "gemini-2.5-flash"       # default — fast, free, capable
GEMINI_FLASH_LITE = "gemini-2.5-flash-lite"  # lighter / faster for classify
GEMINI_FLASH_PRO  = "gemini-2.5-flash"       # re-judge (same model, higher quality prompt)
GEMINI_PRO        = "gemini-2.5-flash"       # alias kept for compat
GEMINI_FLASH_8B   = GEMINI_FLASH_LITE        # legacy alias

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _build_url(model: str) -> str:
    return f"{GEMINI_API_BASE}/{model}:generateContent?key={settings.GEMINI_API_KEY}"


def _tool_to_json_instruction(tool: dict) -> str:
    """Convert an Anthropic-style tool definition into a JSON-mode instruction (legacy fallback)."""
    schema = tool.get("input_schema", {})
    schema_str = json.dumps(schema, indent=2)
    return (
        f"\n\nIMPORTANT: You MUST respond with ONLY a valid JSON object "
        f"that matches this exact schema. No markdown, no explanation, no code fences.\n"
        f"Schema:\n{schema_str}"
    )


def _anthropic_tool_to_gemini(tool: dict) -> dict:
    """
    Convert an Anthropic-style tool definition to Gemini's function_declarations format.
    Anthropic: {"name": str, "description": str, "input_schema": {type, properties, required}}
    Gemini REST: {"function_declarations": [{"name": str, "description": str, "parameters": {...}}]}

    Gemini requires property types to be uppercase ("STRING", "NUMBER", "BOOLEAN", "ARRAY", "OBJECT").
    """
    schema = _upcase_schema_types(tool.get("input_schema", {"type": "OBJECT", "properties": {}}))
    return {
        "function_declarations": [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": schema,
            }
        ]
    }


def _upcase_schema_types(schema: dict) -> dict:
    """Recursively convert JSON Schema type strings to Gemini's uppercase format."""
    if not isinstance(schema, dict):
        return schema
    result = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            result[k] = v.upper()
        elif isinstance(v, dict):
            result[k] = _upcase_schema_types(v)
        elif isinstance(v, list):
            result[k] = [_upcase_schema_types(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


def _extract_json(text: str) -> dict:
    """
    Robustly extract the first JSON object from a string.
    Handles markdown fences, leading/trailing text, and truncated JSON.
    """
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()

    # Try full string first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the start of a JSON object and try raw_decode (handles trailing garbage)
    brace_pos = text.find("{")
    if brace_pos != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, brace_pos)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # Last resort: find outermost {...} with balanced braces
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    log.warning("gemini_json_parse_failed", raw=text[:500])
    return {}


class GeminiAdapter(LLMAdapter):
    """
    Calls the Gemini REST API via httpx (no SDK dependency).
    Works identically to ClaudeAdapter from the caller's perspective:
      returns {"content": str, "tool_use": dict | None, ...}
    """

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = GEMINI_FLASH,
        max_tokens: int = 4096,
        tools: Optional[list] = None,
    ) -> dict:
        """
        Call Gemini API.

        When tools are provided we use Gemini's native function-calling
        (tools + toolConfig) instead of responseMimeType JSON mode.
        Native FC avoids the aggressive token truncation that occurs with
        JSON mode on gemini-2.5-flash.
        """
        gemini_model = _map_model(model)
        url = _build_url(gemini_model)

        payload: dict = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": system_prompt + "\n\n" + user_message}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.1,
            },
        }

        # Native function calling — more reliable than JSON mode
        if tools:
            gemini_tools = [_anthropic_tool_to_gemini(t) for t in tools]
            payload["tools"] = gemini_tools
            payload["toolConfig"] = {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [t["name"] for t in tools],
                }
            }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                log.error("gemini_api_error",
                          status=resp.status_code, body=resp.text[:500], model=gemini_model)
                resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            log.error("gemini_no_candidates", data=data)
            return {"content": "", "tool_use": None, "model": gemini_model}

        finish_reason = candidates[0].get("finishReason", "UNKNOWN")
        parts = candidates[0].get("content", {}).get("parts", [])
        log.debug("gemini_response_parts", parts_count=len(parts), finish_reason=finish_reason,
                  part_keys=[list(p.keys()) for p in parts[:3]])

        # MALFORMED_FUNCTION_CALL: gemini-2.5-flash (a thinking model) occasionally fails
        # on complex FC schemas. Retry with a stable non-thinking model, then fallback to
        # plain-text JSON if that also fails.
        if finish_reason == "MALFORMED_FUNCTION_CALL" and tools:
            log.warning("gemini_malformed_fc_retry", model=gemini_model)
            # Retry 1: switch to gemini-flash-latest (stable non-thinking variant)
            retry_model = "gemini-flash-latest"
            retry_url = _build_url(retry_model)
            payload_copy = dict(payload)
            payload_copy["generationConfig"] = {**payload["generationConfig"], "temperature": 0.0}
            async with httpx.AsyncClient(timeout=120) as client2:
                resp2 = await client2.post(retry_url, json=payload_copy)
            if resp2.status_code == 200:
                data2 = resp2.json()
                cands2 = data2.get("candidates", [])
                if cands2 and cands2[0].get("finishReason") != "MALFORMED_FUNCTION_CALL":
                    log.info("gemini_fc_retry_succeeded", model=retry_model)
                    # Recurse with the retry result
                    parts = cands2[0].get("content", {}).get("parts", [])
                    usage_meta2 = data2.get("usageMetadata", {})
                    tool_use_retry = None
                    raw_retry = ""
                    for p in parts:
                        if "functionCall" in p:
                            tool_use_retry = p["functionCall"].get("args", {})
                            break
                        if "text" in p:
                            raw_retry += p["text"]
                    if tool_use_retry is None and raw_retry:
                        tool_use_retry = _extract_json(raw_retry)
                    return {
                        "content": raw_retry, "tool_use": tool_use_retry,
                        "input_tokens": usage_meta2.get("promptTokenCount", 0),
                        "output_tokens": usage_meta2.get("candidatesTokenCount", 0),
                        "model": retry_model,
                    }
            # Retry 2: plain text JSON fallback (no FC, no JSON mode)
            log.warning("gemini_fc_retry_failed_using_text_fallback", model=gemini_model)
            return await self._complete_json_fallback(
                system_prompt=system_prompt,
                user_message=user_message,
                gemini_model=gemini_model,
                tool=tools[0],
                max_tokens=max_tokens,
            )

        # Usage metadata
        usage_meta = data.get("usageMetadata", {})
        input_tokens  = usage_meta.get("promptTokenCount", 0)
        output_tokens = usage_meta.get("candidatesTokenCount", 0)

        cost_usd = 0.0
        log.info("gemini_call_completed",
                 model=gemini_model,
                 input_tokens=input_tokens,
                 output_tokens=output_tokens,
                 cost_usd=cost_usd)

        # Extract function call args (native FC response)
        tool_use = None
        raw_text = ""
        for part in parts:
            if "functionCall" in part:
                tool_use = part["functionCall"].get("args", {})
                break
            if "text" in part:
                raw_text += part["text"]

        # Fallback: if no function call, try to parse text as JSON
        if tools and tool_use is None and raw_text.strip():
            tool_use = _extract_json(raw_text.strip())

        return {
            "content":       raw_text,
            "tool_use":      tool_use,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "model":         gemini_model,
        }

    async def _complete_json_fallback(
        self,
        system_prompt: str,
        user_message: str,
        gemini_model: str,
        tool: dict,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Fallback for MALFORMED_FUNCTION_CALL: inject the schema into the prompt
        and use plain text mode to get a JSON response from Gemini.
        This avoids both JSON mode truncation and FC schema issues.
        """
        schema_instruction = _tool_to_json_instruction(tool)
        combined = system_prompt + schema_instruction + "\n\n" + user_message
        url = _build_url(gemini_model)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": combined}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                log.error("gemini_json_fallback_error", status=resp.status_code, body=resp.text[:300])
                resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        raw_text = "".join(p.get("text", "") for p in parts).strip()
        usage_meta = data.get("usageMetadata", {})
        tool_use = _extract_json(raw_text) if raw_text else None
        log.info("gemini_json_fallback_done", model=gemini_model,
                 output_tokens=usage_meta.get("candidatesTokenCount", 0),
                 parsed=bool(tool_use))
        return {
            "content":       raw_text,
            "tool_use":      tool_use,
            "input_tokens":  usage_meta.get("promptTokenCount", 0),
            "output_tokens": usage_meta.get("candidatesTokenCount", 0),
            "model":         gemini_model,
        }


def _map_model(model_alias: str) -> str:
    """Map Claude model aliases → Gemini equivalents."""
    _MAP = {
        # Haiku → Flash Lite (fast, cheap, classify)
        "claude-haiku-4-5-20251001":  GEMINI_FLASH,
        "claude-haiku":               GEMINI_FLASH,
        "haiku":                      GEMINI_FLASH,
        # Sonnet → Flash Pro (stronger, re-judge)
        "claude-sonnet-4-6":          GEMINI_FLASH_PRO,
        "claude-sonnet":              GEMINI_FLASH_PRO,
        "sonnet":                     GEMINI_FLASH_PRO,
        # Direct Gemini aliases (passthrough)
        "gemini-2.5-flash":           GEMINI_FLASH,
        "gemini-2.5-flash-lite":      GEMINI_FLASH_LITE,
        "gemini-flash-latest":        GEMINI_FLASH,
        # Legacy — remap old names to working equivalents
        "gemini-2.0-flash":           GEMINI_FLASH,
        "gemini-2.0-flash-lite":      GEMINI_FLASH_LITE,
        "gemini-1.5-flash":           GEMINI_FLASH,
        "gemini-1.5-flash-8b":        GEMINI_FLASH_LITE,
        "gemini-1.5-pro":             GEMINI_FLASH_PRO,
    }
    return _MAP.get(model_alias, GEMINI_FLASH)
