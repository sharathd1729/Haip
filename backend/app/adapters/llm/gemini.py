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

# Model aliases. gemini-2.5-flash is blocked outright for API keys tied to
# a newly-created GCP project -- confirmed live: "This model models/
# gemini-2.5-flash is no longer available to new users. Please update your
# code to use models/gemini-3.6-flash" (404, not a permissions/billing
# issue -- Google's own error, not a guess). gemini-3.6-flash confirmed
# reachable and present in this key's /v1beta/models listing.
GEMINI_FLASH      = "gemini-3.6-flash"       # default — current, works on new-project keys
GEMINI_FLASH_LITE = "gemini-3.1-flash-lite"  # cheap fallback for small/internal tasks (2.5-flash-lite: 404 on this key)
GEMINI_FLASH_PRO  = "gemini-3.6-flash"       # re-judge (same model, higher quality prompt)
GEMINI_PRO        = "gemini-3.6-flash"       # alias kept for compat
GEMINI_FLASH_8B   = GEMINI_FLASH_LITE        # legacy alias

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _build_url(model: str) -> str:
    # The key travels in a header, never the URL: httpx puts the full URL in
    # every HTTPStatusError message, and those get logged -- a ?key= URL
    # leaked the API key into log files that way.
    return f"{GEMINI_API_BASE}/{model}:generateContent"


def _auth_headers() -> dict:
    return {"x-goog-api-key": settings.GEMINI_API_KEY}


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
    schema = _fit_gemini_schema(_upcase_schema_types(tool.get("input_schema", {"type": "OBJECT", "properties": {}})))
    return {
        "function_declarations": [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": schema,
            }
        ]
    }


# JSON-Schema keys Gemini's Schema proto does not have (it answers 400 to them); `const` becomes a one-value enum.
_GEMINI_UNSUPPORTED = {"additionalProperties", "$schema", "$defs", "$id", "exclusiveMinimum", "exclusiveMaximum",
                       "uniqueItems", "multipleOf", "examples"}


def _fit_gemini_schema(node):
    """Reduce an (already upcased) schema to what Gemini function declarations accept.

    Confirmed live (24 Oct 2026, Marketing Studio weekly plan): Gemini answers a bare 400 "Request contains an
    invalid argument." when an array of OBJECTS carries minItems/maxItems -- the plan's calendar (maxItems 62) and
    the shoot brief (shots 3-20, hooks 5, posting_plan 2-16) failed, maxItems <= 20 passed, the same schema without
    the bounds passed. Each bound multiplies the decoder's states. So those bounds move into the description (the
    model still sees them) and the caller's Pydantic model enforces them on the result. Arrays of scalars keep theirs.
    """
    if isinstance(node, list):
        return [_fit_gemini_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in _GEMINI_UNSUPPORTED:
            continue
        if k == "const":
            out["enum"] = [v]
        elif k == "properties" and isinstance(v, dict):
            out[k] = {name: _fit_gemini_schema(sub) for name, sub in v.items()}
        else:
            out[k] = _fit_gemini_schema(v)
    items = out.get("items")
    if out.get("type") == "ARRAY" and isinstance(items, dict) and items.get("type") == "OBJECT":
        lo, hi = out.pop("minItems", None), out.pop("maxItems", None)
        if lo is not None or hi is not None:
            bound = (f"exactly {lo}" if lo == hi else f"{lo} to {hi}" if lo is not None and hi is not None
                     else f"at least {lo}" if lo is not None else f"at most {hi}")
            out["description"] = (out.get("description", "") + f" ({bound} items)").strip()
    return out


def _upcase_schema_types(schema: dict) -> dict:
    """Recursively convert JSON Schema type strings to Gemini's uppercase format.

    Gemini's function-declaration schema is a proto (OpenAPI 3.0-subset)
    Schema object -- `type` is a single scalar, never a list. A JSON-Schema
    union like `"type": ["string", "null"]` (the standard way to mark an
    optional/nullable field, and how CONCIERGE_TOOL's own
    reason_needs_human is written) crashed with a real, confirmed-live 400:
    "Proto field is not repeating, cannot start list." Gemini's own
    equivalent of "nullable string" is `type: STRING, nullable: true`, so a
    [T, "null"] union converts to exactly that. A union of more than one
    non-null type has no Gemini equivalent -- collapse to the first
    non-null type rather than fail the whole request.
    """
    if not isinstance(schema, dict):
        return schema
    result = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            result[k] = v.upper()
        elif k == "type" and isinstance(v, list):
            non_null = [t for t in v if isinstance(t, str) and t.lower() != "null"]
            if non_null:
                result[k] = non_null[0].upper()
            if "null" in [t.lower() for t in v if isinstance(t, str)]:
                result["nullable"] = True
        elif isinstance(v, dict):
            result[k] = _upcase_schema_types(v)
        elif isinstance(v, list):
            result[k] = [_upcase_schema_types(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


def _billed_output(usage: dict) -> int:
    """Output tokens Google bills: the answer plus the model's thinking. candidatesTokenCount alone left out the
    thinking, often 1-3k tokens a call on gemini-3.6-flash (live, 24 Oct 2026), so usage_events undercounted cost."""
    return (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)


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

    def __init__(self, default_model: str = GEMINI_FLASH):
        self._default_model = default_model

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
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
        model = model or self._default_model
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
            resp = await client.post(url, json=payload, headers=_auth_headers())
            if resp.status_code != 200:
                # 2,000 chars so Google's `details` / `fieldViolations` (when it sends them) are not cut off.
                log.error("gemini_api_error",
                          status=resp.status_code, body=resp.text[:2000], model=gemini_model,
                          tools=[t.get("name") for t in tools or []])
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
                resp2 = await client2.post(retry_url, json=payload_copy, headers=_auth_headers())
            if resp2.status_code != 200:
                # Previously silent -- a non-200 here fell straight through to
                # the text fallback with zero indication why the retry itself
                # didn't even get a response to check finishReason on.
                log.warning("gemini_fc_retry_http_error", status=resp2.status_code,
                            body=resp2.text[:300], model=retry_model)
            if resp2.status_code == 200:
                data2 = resp2.json()
                cands2 = data2.get("candidates", [])
                retry_finish_reason = cands2[0].get("finishReason") if cands2 else None
                if retry_finish_reason == "MALFORMED_FUNCTION_CALL":
                    # Confirmed live: the retry model itself is reachable and
                    # healthy (verified independently), it just also failed
                    # to produce a valid function call for this specific
                    # prompt -- a genuinely harder case for Gemini's FC
                    # parser, not a broken retry mechanism. Logged so this is
                    # distinguishable from a retry that never got a response.
                    log.warning("gemini_fc_retry_also_malformed", model=retry_model)
                if cands2 and retry_finish_reason != "MALFORMED_FUNCTION_CALL":
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
                        "output_tokens": _billed_output(usage_meta2),
                        "model": retry_model,
                    }
            # Retry 2: plain text JSON fallback (no FC, no JSON mode)
            log.warning("gemini_fc_retry_failed_using_text_fallback", model=gemini_model)
            return await self._complete_json_fallback(
                system_prompt=system_prompt,
                user_message=user_message,
                gemini_model=gemini_model,
                tool=tools[0],
                # Confirmed live: this path was truncating mid-JSON (a raw
                # response cut off at `"reply": "Each caravan fits`) when
                # given the same budget as the native function-calling
                # attempt. Native FC doesn't spend output tokens on JSON
                # punctuation/keys the way this text-mode fallback has to --
                # it has to spell out the entire {"reply": ..., "confidence":
                # ..., "citations": [...], "needs_human": ..., "reason_needs_
                # human": ...} structure as literal text on top of the same
                # reply content, so the same budget that's fine for FC mode
                # genuinely isn't enough here. Padded, not doubled -- this
                # path is already a last resort, no need to also make it the
                # slowest/most expensive one.
                max_tokens=max_tokens + 300,
            )

        # Usage metadata
        usage_meta = data.get("usageMetadata", {})
        input_tokens  = usage_meta.get("promptTokenCount", 0)
        output_tokens = _billed_output(usage_meta)

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
            resp = await client.post(url, json=payload, headers=_auth_headers())
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
                 output_tokens=_billed_output(usage_meta),
                 parsed=bool(tool_use))
        return {
            "content":       raw_text,
            "tool_use":      tool_use,
            "input_tokens":  usage_meta.get("promptTokenCount", 0),
            "output_tokens": _billed_output(usage_meta),
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
        "gemini-3.6-flash":           GEMINI_FLASH,
        # gemini-2.5-flash itself is blocked for new-project keys (see the
        # GEMINI_FLASH comment above) -- remap it forward rather than let it
        # 404 for any caller still passing the old literal.
        "gemini-2.5-flash":           GEMINI_FLASH,
        # Legacy — remap old names to working equivalents
        "gemini-2.0-flash":           GEMINI_FLASH,
        "gemini-2.0-flash-lite":      GEMINI_FLASH_LITE,
        "gemini-1.5-flash":           GEMINI_FLASH,
        "gemini-1.5-flash-8b":        GEMINI_FLASH_LITE,
        "gemini-1.5-pro":             GEMINI_FLASH_PRO,
    }
    # A real Gemini model name passes through. Only Claude aliases / unknown names fall back to GEMINI_FLASH: the old
    # catch-all silently ran gemini-3.6-flash for every newer name (e.g. gemini-3.1-flash-lite), live 25 Oct 2026.
    return _MAP.get(model_alias) or (model_alias if model_alias.startswith("gemini-") else GEMINI_FLASH)
