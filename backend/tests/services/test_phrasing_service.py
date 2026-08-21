"""Alternate-phrasing parsing tests.

meta/llama-3.1-8b is unreliable at structured output for this task: across
observed calls it returned the tool call as plain text, echoed the schema
wrapper back, alternated between single and double quotes, and truncated
mid-JSON. Generation was switched to plain newline-separated lines, but the
lenient parsers are kept for responses that still arrive as a blob -- these
tests pin every shape actually seen from the live model.
"""
import pytest

from app.services import phrasing_service as ps


# ─── the expected shape: plain lines ─────────────────────────────────────────

def test_parses_plain_lines():
    out = ps._extract_lines("can i bring my dog\nare pets allowed\npet friendly?")
    assert out == ["can i bring my dog", "are pets allowed", "pet friendly?"]


def test_strips_numbering_and_bullets():
    out = ps._extract_lines("1. can i bring my dog\n- are pets allowed\n* pet friendly?")
    assert out == ["can i bring my dog", "are pets allowed", "pet friendly?"]


def test_drops_preamble_lines():
    out = ps._extract_lines("Here are 3 ways guests might ask:\ncan i bring my dog\nare pets allowed")
    assert "can i bring my dog" in out
    assert not any(o.lower().startswith("here are") for o in out)


def test_ignores_json_blob_so_json_parsers_handle_it():
    assert ps._extract_lines('{"name": "generate_phrasings", "parameters": {}}') == []


# ─── observed malformed shapes ───────────────────────────────────────────────

def test_handles_schema_wrapper_with_escaped_double_quotes():
    raw = '{"name": "generate_phrasings", "parameters": {"properties": {"phrasings": "[\\"can i bring my pet\\", \\"are pets allowed\\"]"}}}'
    assert ps._extract_after_key(raw) == ["can i bring my pet", "are pets allowed"]


def test_handles_single_quoted_array():
    """The same prompt yields double quotes on one call and single on the
    next; matching only double silently returned nothing for about half."""
    raw = '{"phrasings": "[\'can i bring my dog\', \'are pets allowed\']"}'
    assert ps._extract_after_key(raw) == ["can i bring my dog", "are pets allowed"]


def test_handles_truncated_json():
    """Observed: a 201-character response missing its final brace. The
    phrasings were all present; only the envelope was incomplete."""
    raw = '{"name": "generate_phrasings", "parameters": {"properties": {"phrasings": "[\\"can i bring my pet\\", \\"are pets allowed\\"'
    assert ps._extract_after_key(raw) == ["can i bring my pet", "are pets allowed"]


def test_schema_keys_are_never_returned_as_phrasings():
    """A naive 'grab every quoted string' fallback happily returned
    "name", "parameters" and "properties" as if they were guest questions."""
    raw = '{"name": "generate_phrasings", "parameters": {"properties": {"phrasings": "[\\"pet friendly?\\"]"}}}'
    out = ps._extract_after_key(raw)
    for junk in ("name", "parameters", "properties", "phrasings", "generate_phrasings"):
        assert junk not in out


def test_find_phrasings_walks_nested_dicts():
    assert ps._find_phrasings({"parameters": {"properties": {"phrasings": ["a question here"]}}}) == ["a question here"]


# ─── cleaning ────────────────────────────────────────────────────────────────

def test_clean_drops_duplicates_and_the_original_question():
    out = ps._clean(
        ["Can I bring my dog", "can i bring my dog!", "Do you allow pets?", "are pets allowed"],
        exclude="Do you allow pets?",
    )
    assert "are pets allowed" in out
    # Case/punctuation-insensitive dedupe, and the original question dropped.
    assert len(out) == 2


def test_clean_enforces_a_cap():
    assert len(ps._clean([f"question number {i} here" for i in range(50)], exclude=None)) <= ps.MAX_PHRASINGS


def test_clean_rejects_overlong_items():
    assert ps._clean(["x" * 200], exclude=None) == []


def test_clean_handles_junk_input():
    assert ps._clean(None, exclude=None) == []
    assert ps._clean(["", "  ", None], exclude=None) == []
