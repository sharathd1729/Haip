"""WhatsApp template linter. It could not even be imported for months: one
malformed f-string made every POST /messaging/templates/lint a 500."""

from app.services.template_linter import lint_template, lint_to_dict


def test_the_linter_imports_and_runs():
    assert lint_template("Hello there", category="MARKETING") == []


def test_missing_sample_names_the_variable_with_double_braces():
    findings = lint_template("Hi {{1}}, welcome to {{2}}.", category="MARKETING")
    msgs = [f.message for f in findings if f.field_path.startswith("body.variable_")]
    assert msgs == [
        "Variable {{1}} has no sample value. Meta requires samples for all variables.",
        "Variable {{2}} has no sample value. Meta requires samples for all variables.",
    ]


def test_samples_silence_the_warning():
    findings = lint_template("Hi {{1}}, welcome to {{2}}.", category="MARKETING", sample_values={"1": "Priya", "2": "Ratha"})
    assert not [f for f in findings if f.field_path.startswith("body.variable_")]


def test_url_shortener_is_an_error():
    findings = lint_template("Book at https://bit.ly/abc", category="MARKETING")
    assert any(f.level == "error" and "shortener" in f.message.lower() for f in findings)


def test_promo_wording_in_a_utility_template():
    findings = lint_template("Big sale this weekend", category="UTILITY")
    assert any("promotional" in f.message.lower() for f in findings)
    assert lint_template("Big sale this weekend", category="MARKETING") == []


def test_lint_to_dict_shape():
    out = lint_to_dict(lint_template("Big sale", category="UTILITY"))
    assert out and set(out[0]) == {"level", "message", "field_path"}
