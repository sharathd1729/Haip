"""
WhatsApp module bug-fix pass — template variable example gate.

Real bug ("templates not able to create"): the create form invited
{{1}}/{{2}}/{{3}} variable syntax in its own placeholder text but never
collected an example value for any of them, and nothing server-side
enforced one either. Meta's Template Management API rejects a component
containing {{n}} placeholders unless it also carries a matching example
(header_text / body_text) -- so any template using the variable syntax the
UI itself suggested always failed at Meta submission, with the actual
reason never surfaced anywhere in the app.

_missing_variable_examples is the server-side gate added to
submit_template as defense-in-depth (the create form now collects these
client-side, but a template created before that fix, or via direct API,
can still reach here without them).
"""
from app.api.v1.endpoints.messaging import _missing_variable_examples


class TestNoVariables:
    def test_plain_text_needs_no_example(self):
        components = [{"type": "BODY", "text": "Thanks for booking with us!"}]
        assert _missing_variable_examples(components) == []


class TestBodyVariables:
    def test_missing_body_example_is_flagged(self):
        components = [{"type": "BODY", "text": "Hi {{1}}, your stay is confirmed."}]
        missing = _missing_variable_examples(components)
        assert missing == ["body {{1}}"]

    def test_complete_body_example_passes(self):
        components = [{
            "type": "BODY", "text": "Hi {{1}}, your stay at {{2}} is confirmed.",
            "example": {"body_text": [["Priya", "White Caravan"]]},
        }]
        assert _missing_variable_examples(components) == []

    def test_partial_body_examples_still_flags_the_missing_ones(self):
        components = [{
            "type": "BODY", "text": "Hi {{1}}, your stay at {{2}} is confirmed.",
            "example": {"body_text": [["Priya"]]},  # {{2}} has no value
        }]
        missing = _missing_variable_examples(components)
        assert "body {{1}}" in missing or "body {{2}}" in missing

    def test_blank_example_value_still_flags(self):
        components = [{
            "type": "BODY", "text": "Hi {{1}}",
            "example": {"body_text": [[""]]},
        }]
        assert _missing_variable_examples(components) == ["body {{1}}"]


class TestHeaderVariables:
    def test_missing_header_example_is_flagged(self):
        components = [{"type": "HEADER", "format": "TEXT", "text": "Welcome to {{1}}"}]
        assert _missing_variable_examples(components) == ["header"]

    def test_complete_header_example_passes(self):
        components = [{
            "type": "HEADER", "format": "TEXT", "text": "Welcome to {{1}}",
            "example": {"header_text": ["Ratha Retreats"]},
        }]
        assert _missing_variable_examples(components) == []


class TestFooterAndButtonsNeverFlagged:
    def test_footer_and_buttons_are_never_checked(self):
        """Only HEADER/BODY carry {{n}} variables in Meta's template spec --
        a footer or button referencing "{{1}}" literally (unusual, but not
        this function's concern) must not be flagged."""
        components = [
            {"type": "FOOTER", "text": "Reply STOP to opt out"},
            {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Book now", "url": "https://example.com"}]},
        ]
        assert _missing_variable_examples(components) == []
