"""Regression test for a real, live-confirmed bug in _upcase_schema_types():
a JSON-Schema nullable union ("type": ["string", "null"]) -- the standard
way to mark an optional field, and exactly how concierge_draft.py's
CONCIERGE_TOOL declares reason_needs_human -- was passed through to Gemini
unmodified. Gemini's function-declaration schema is a proto Schema object
where `type` is a scalar, never a list, so every real call using
CONCIERGE_TOOL failed with a 400: "Proto field is not repeating, cannot
start list." Reproduced live against the real Gemini API before this fix.
"""
from app.adapters.llm.gemini import _upcase_schema_types, _anthropic_tool_to_gemini


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
