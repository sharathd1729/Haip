"""Regression test for a real, live-confirmed bug in _upcase_schema_types():
a JSON-Schema nullable union ("type": ["string", "null"]) -- the standard
way to mark an optional field, and exactly how concierge_draft.py's
CONCIERGE_TOOL declares reason_needs_human -- was passed through to Gemini
unmodified. Gemini's function-declaration schema is a proto Schema object
where `type` is a scalar, never a list, so every real call using
CONCIERGE_TOOL failed with a 400: "Proto field is not repeating, cannot
start list." Reproduced live against the real Gemini API before this fix.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.llm.gemini import _upcase_schema_types, _anthropic_tool_to_gemini, GeminiAdapter


class TestUpcaseSchemaTypes:
    def test_plain_scalar_type_upcased(self):
        assert _upcase_schema_types({"type": "string"}) == {"type": "STRING"}

    def test_nullable_union_converts_to_scalar_type_plus_nullable_flag(self):
        result = _upcase_schema_types({"type": ["string", "null"]})
        assert result == {"type": "STRING", "nullable": True}

    def test_nullable_union_order_reversed(self):
        result = _upcase_schema_types({"type": ["null", "string"]})
        assert result == {"type": "STRING", "nullable": True}

    def test_nested_property_with_nullable_union(self):
        schema = {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "reason_needs_human": {"type": ["string", "null"]},
            },
            "required": ["reply"],
        }
        result = _upcase_schema_types(schema)
        assert result["properties"]["reason_needs_human"] == {"type": "STRING", "nullable": True}
        assert result["properties"]["reply"] == {"type": "STRING"}

    def test_multi_type_non_null_union_collapses_to_first_type(self):
        """No Gemini equivalent for a true multi-type union -- collapses
        rather than crashing the whole request."""
        result = _upcase_schema_types({"type": ["string", "number"]})
        assert result["type"] == "STRING"
        assert "nullable" not in result


class TestAnthropicToolToGemini:
    def test_concierge_tool_shape_converts_without_raising(self):
        """The exact CONCIERGE_TOOL shape from concierge_draft.py -- this is
        the real payload that produced the live 400 before the fix."""
        tool = {
            "name": "concierge_reply",
            "description": "Draft a WhatsApp reply for the guest",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reply": {"type": "string"},
                    "confidence": {"type": "number"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                    "needs_human": {"type": "boolean"},
                    "reason_needs_human": {"type": ["string", "null"]},
                },
                "required": ["reply", "confidence", "needs_human"],
            },
        }
        result = _anthropic_tool_to_gemini(tool)
        params = result["function_declarations"][0]["parameters"]
        assert params["properties"]["reason_needs_human"] == {"type": "STRING", "nullable": True}


class TestFitGeminiSchema:
    """Live 400 (24 Oct 2026): bounds on arrays of objects (the plan's calendar, maxItems 62) made Gemini reject
    the whole request. They move into the description; scalar arrays keep theirs."""

    def _params(self, schema):
        return _anthropic_tool_to_gemini({"name": "t", "input_schema": schema})["function_declarations"][0]["parameters"]

    def test_object_array_bounds_move_to_description(self):
        p = self._params({"type": "object", "properties": {
            "calendar": {"type": "array", "maxItems": 62, "items": {"type": "object", "properties": {"d": {"type": "string"}}}},
            "hooks": {"type": "array", "minItems": 5, "maxItems": 5, "description": "Hooks.",
                      "items": {"type": "object", "properties": {"t": {"type": "string", "maxLength": 80}}}},
            "tags": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
        }})
        cal, hooks, tags = (p["properties"][k] for k in ("calendar", "hooks", "tags"))
        assert "maxItems" not in cal and cal["description"] == "(at most 62 items)"
        assert "minItems" not in hooks and hooks["description"] == "Hooks. (exactly 5 items)"
        assert hooks["items"]["properties"]["t"]["maxLength"] == 80     # scalar constraints are kept
        assert tags["maxItems"] == 6

    def test_unsupported_keys_dropped_and_const_becomes_enum(self):
        p = self._params({"type": "object", "additionalProperties": False, "properties": {
            "kind": {"type": "string", "const": "post"},
            "additionalProperties": {"type": "string"},   # a property with that NAME is kept
            "n": {"type": "integer", "exclusiveMinimum": 0},
        }})
        assert "additionalProperties" not in {k for k in p if k != "properties"}
        assert p["properties"]["kind"] == {"type": "STRING", "enum": ["post"]}
        assert p["properties"]["additionalProperties"] == {"type": "STRING"}
        assert p["properties"]["n"] == {"type": "INTEGER"}

    def test_every_marketing_tool_has_no_bounded_object_array(self):
        from app.services import marketing_prompts as P
        from app.services.marketing_strategy import brief_tool, deck_tool

        def walk(n):
            if isinstance(n, dict):
                if n.get("type") == "ARRAY" and (n.get("items") or {}).get("type") == "OBJECT":
                    assert "maxItems" not in n and "minItems" not in n
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)
        tools = [P.AUDIT_TOOL, P.PLAN_TOOL, P.RESEARCH_TOOL, P.REVIEW_TOOL, brief_tool(), deck_tool(),
                 *(P.content_tool(k) for k in P.CONTENT_MODELS)]
        for t in tools:
            walk(_anthropic_tool_to_gemini(t))


def _candidate_response(finish_reason: str, text: str = "", output_tokens: int = 10):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={
        "candidates": [{
            "finishReason": finish_reason,
            "content": {"parts": [{"text": text}] if text else []},
        }],
        "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": output_tokens},
    })
    return resp


_TOOL = {
    "name": "concierge_reply",
    "description": "Draft a reply",
    "input_schema": {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]},
}


class TestMalformedFunctionCallFallbackChain:
    """Real bug, reported live: a guest question reproducibly made Gemini
    return MALFORMED_FUNCTION_CALL on both the original call and the
    retry, then the text-JSON fallback truncated mid-response because it
    was given the same tight token budget as the native function-calling
    attempt -- which doesn't have to spend output tokens spelling out
    JSON structure (keys/braces/quotes) the way text mode does."""

    @pytest.mark.asyncio
    async def test_retry_also_malformed_falls_back_to_json_mode_with_padded_token_budget(self):
        # 1st call (native FC): malformed. 2nd call (FC retry): also
        # malformed. 3rd call (JSON-mode fallback): succeeds.
        responses = [
            _candidate_response("MALFORMED_FUNCTION_CALL"),
            _candidate_response("MALFORMED_FUNCTION_CALL"),
            _candidate_response("STOP", text='{"reply": "Sure, here are the details!"}'),
        ]
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=responses)
            result = await GeminiAdapter().complete(
                system_prompt="You are a concierge.", user_message="Hi",
                tools=[_TOOL], max_tokens=400,
            )

        assert result["tool_use"] == {"reply": "Sure, here are the details!"}
        # The 3rd call is the JSON-mode fallback -- its payload's
        # maxOutputTokens must be padded above the original 400, not equal
        # to it (that equality is exactly what caused the live truncation).
        third_call_payload = instance.post.call_args_list[2].kwargs["json"]
        assert third_call_payload["generationConfig"]["maxOutputTokens"] == 700

    @pytest.mark.asyncio
    async def test_retry_http_error_does_not_crash_and_still_reaches_json_fallback(self):
        """A non-200 on the retry attempt must not raise or hang -- it
        previously fell through completely silently; now it's logged, but
        either way the pipeline must still reach the JSON-mode fallback
        rather than blow up."""
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.text = "internal error"
        responses = [
            _candidate_response("MALFORMED_FUNCTION_CALL"),
            error_resp,
            _candidate_response("STOP", text='{"reply": "Recovered via fallback."}'),
        ]
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=responses)
            result = await GeminiAdapter().complete(
                system_prompt="You are a concierge.", user_message="Hi",
                tools=[_TOOL], max_tokens=400,
            )

        assert result["tool_use"] == {"reply": "Recovered via fallback."}


def test_billed_output_counts_thinking_tokens():
    """gemini-3.6-flash thinks before answering and Google bills those tokens as output; leaving them out undercounted
    every usage_events cost estimate (live, 24 Oct 2026: ~1-3k thinking tokens a call)."""
    from app.adapters.llm.gemini import _billed_output
    assert _billed_output({"candidatesTokenCount": 400, "thoughtsTokenCount": 1200}) == 1600
    assert _billed_output({"candidatesTokenCount": 400}) == 400
    assert _billed_output({}) == 0
