"""Agency M3: the marketing prompt test set, run in CI so quality does not drift.

1. Every case in fixtures/marketing_eval/cases.json reaches its expected brand-review verdict (deterministic checks).
2. Every marketing prompt (system text + tool schema) matches its snapshot in fixtures/marketing_eval/prompts.json.
   A prompt edit without a version bump fails here; after bumping core/prompt_versions.py, refresh the snapshot:
       python scripts/marketing_prompt_eval.py --snapshot
3. The live copywriter run (needs AI keys, never in CI) is the same script without flags.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from app.core.prompt_versions import get_version
from app.schemas.marketing import validate_content
from app.services import marketing_lint

_spec = importlib.util.spec_from_file_location(
    "marketing_prompt_eval", Path(__file__).parent.parent / "scripts" / "marketing_prompt_eval.py")
_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_script)
current_snapshot = _script.current_snapshot

FIXTURES = Path(__file__).parent / "fixtures" / "marketing_eval"
DATA = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", DATA["cases"], ids=[c["id"] for c in DATA["cases"]])
def test_each_case_reaches_its_verdict(case):
    payload = validate_content(case["kind"], case["payload"])          # every fixture is a valid draft of its kind
    findings = marketing_lint.check(case["kind"], payload, facts_text=DATA["facts"], competitors=DATA["competitors"])
    rules = {f["rule"] for f in findings}
    assert marketing_lint.blocking(findings) is case["blocking"], findings
    assert set(case["rules"]) <= rules, findings


def test_the_set_covers_every_blocking_rule_and_every_kind():
    blocking_rules = {r for c in DATA["cases"] if c["blocking"] for r in c["rules"]}
    assert {"unverified_number", "missing_fact", "contrast_reveal", "engagement_bait", "guarantee", "competitor_named",
            "count_mismatch", "comment_keyword_missing"} <= blocking_rules
    assert {c["kind"] for c in DATA["cases"]} >= {"post", "carousel", "promo", "reel"}


def test_prompts_match_their_snapshot():
    stored = json.loads((FIXTURES / "prompts.json").read_text(encoding="utf-8"))
    now = current_snapshot()
    for task, entry in now.items():
        old = stored.get(task)
        assert old is not None, f"{task}: no snapshot yet. Run: python scripts/marketing_prompt_eval.py --snapshot"
        if old["sha"] != entry["sha"]:
            assert old["version"] != entry["version"], (
                f"{task}: the prompt changed but its version is still {entry['version']}. Bump it in "
                "core/prompt_versions.py, then run: python scripts/marketing_prompt_eval.py --snapshot")
            pytest.fail(f"{task}: version bumped to {entry['version']}; refresh the snapshot "
                        "(python scripts/marketing_prompt_eval.py --snapshot)")
        assert old["version"] == entry["version"] == get_version(task), f"{task}: refresh the snapshot"


def test_a_silent_prompt_edit_changes_the_snapshot(monkeypatch):
    from app.services import marketing_prompts
    before = current_snapshot()
    monkeypatch.setattr(marketing_prompts, "REVIEW_SYSTEM", marketing_prompts.REVIEW_SYSTEM + " Be nice.")
    after = current_snapshot()
    assert after["marketing_review"]["sha"] != before["marketing_review"]["sha"]
    assert after["marketing_review"]["version"] == before["marketing_review"]["version"]   # -> the check above fails
    assert {k: v for k, v in after.items() if k != "marketing_review"} == \
        {k: v for k, v in before.items() if k != "marketing_review"}
