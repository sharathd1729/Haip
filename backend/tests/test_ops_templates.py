"""The ops WhatsApp template pack (app/services/ops_templates.py) is submitted to Meta for every tenant; a malformed template is
rejected there and alerts fall back to push. These checks catch the mistakes Meta rejects (or that break the button payloads)
before a tenant ever submits."""
import re

import pytest

from app.services import ops_templates
from app.services.ops_templates import ACK_INDEX, DECLINE_INDEX, PACK


@pytest.mark.parametrize("name", sorted(PACK))
def test_name_is_versioned_and_meta_safe(name):
    # A wording change ships as a new name (_v2), never an edit of an approved template; Meta allows lowercase + underscores.
    assert re.fullmatch(r"[a-z0-9_]+_v\d+", name), name


@pytest.mark.parametrize("name", sorted(PACK))
def test_utility_category(name):
    # Marketing-sounding templates get re-categorised (and billed) as marketing; ops alerts must stay utility.
    assert PACK[name]["category"] == "UTILITY"


@pytest.mark.parametrize("name", sorted(PACK))
def test_body_variables_are_sequential_and_match_the_example(name):
    body = next(c for c in PACK[name]["components"] if c["type"] == "BODY")
    numbers = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", body["text"])]
    assert numbers == list(range(1, len(numbers) + 1)), "Meta needs {{1}}..{{n}} in order, no gaps"
    examples = body["example"]["body_text"]
    assert len(examples) == 1 and len(examples[0]) == len(numbers), "one example value per variable"
    assert all(isinstance(v, str) and v for v in examples[0])


@pytest.mark.parametrize("name", sorted(PACK))
def test_ack_and_decline_buttons_sit_where_the_sender_expects(name):
    buttons = next(c for c in PACK[name]["components"] if c["type"] == "BUTTONS")["buttons"]
    assert all(b["type"] == "QUICK_REPLY" for b in buttons)
    assert buttons[ACK_INDEX]["text"] == "Acknowledge"
    assert buttons[DECLINE_INDEX]["text"] == "Can't take it"
    assert all(len(b["text"]) <= 25 for b in buttons), "Meta caps quick-reply button text at 25 characters"


def test_alert_and_escalation_share_one_variable_order():
    # The sender fills both templates with the same five values; a reordered body would put the wrong value in each slot.
    def slots(name):
        body = next(c for c in PACK[name]["components"] if c["type"] == "BODY")
        return len(re.findall(r"\{\{\d+\}\}", body["text"]))
    assert slots("ops_alert_v1") == slots("ops_escalation_v1") == 5
    assert ops_templates.__doc__ and "{{5}}" in ops_templates.__doc__
