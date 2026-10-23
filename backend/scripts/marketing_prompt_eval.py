"""Marketing prompt test set (agency M3): snapshot the prompts, or grade the live copywriter.  Writes NO database rows.

    python scripts/marketing_prompt_eval.py --snapshot          refresh tests/fixtures/marketing_eval/prompts.json
                                                                (after bumping core/prompt_versions.py)
    python scripts/marketing_prompt_eval.py                     live: write each brief in cases.json with the standard
    python scripts/marketing_prompt_eval.py --premium           copywriter (or the premium one), then grade every draft
                                                                with the deterministic checks and the critic

The live run calls the AI providers (needs their keys; run it inside the API container), uses the dummy business in
cases.json and prints one line per draft. Exit code 1 if any draft is blocked or below the critic's bar, so it can
gate a prompt change by hand. CI runs only tests/test_marketing_prompt_eval.py (no AI calls).
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures",
                        "marketing_eval")


def _prompts() -> dict:
    """task -> (system text, [tool schemas]) for every marketing prompt with a version."""
    from app.schemas.marketing import CONTENT_KINDS
    from app.services import marketing_brand_dna as dna
    from app.services import marketing_guest_reviews as guest_reviews
    from app.services import marketing_prompts as p
    from app.services import marketing_insights_report as insights_report
    from app.services import marketing_reputation as reputation
    from app.services import marketing_tagging as tagging
    return {
        "marketing_audit": (p.AUDIT_SYSTEM, [p.AUDIT_TOOL]),
        "marketing_plan": (p.PLAN_SYSTEM, [p.PLAN_TOOL]),
        "marketing_content": (p.CONTENT_SYSTEM, [p.content_tool(k) for k in CONTENT_KINDS]),
        "marketing_research": (p.RESEARCH_SYSTEM, [p.RESEARCH_TOOL]),
        "marketing_review": (p.REVIEW_SYSTEM, [p.REVIEW_TOOL]),
        "marketing_brand_dna": (dna.SYSTEM, [dna._tool()]),
        "marketing_review_reply": (guest_reviews.SYSTEM, [guest_reviews._tool()]),
        "marketing_ota_copy": (p.OTA_SYSTEM, [reputation.ota_tool(k) for k in ("airbnb", "booking", "makemytrip")]),
        "marketing_tagging": (tagging.SYSTEM, [tagging.tool()]),
        "marketing_insights": (insights_report.SYSTEM, [insights_report.tool()]),
    }


def current_snapshot() -> dict:
    from app.core.prompt_versions import get_version
    out = {}
    for task, (system, tools) in _prompts().items():
        body = system + "\n" + json.dumps(tools, sort_keys=True, ensure_ascii=False)
        out[task] = {"version": get_version(task), "sha": hashlib.sha256(body.encode("utf-8")).hexdigest()}
    return out


def write_snapshot() -> None:
    path = os.path.join(FIXTURES, "prompts.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(current_snapshot(), fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {path}")


def live(premium: bool) -> int:
    from app.schemas.marketing import AIBrandReview, validate_content
    from app.services import marketing_ai_service as ai
    from app.services import marketing_lint
    from app.services import marketing_prompts as p
    from app.services import marketing_review_service as review

    with open(os.path.join(FIXTURES, "cases.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    rules = p.rules("handoff")
    task = "marketing_content_premium" if premium else "marketing_content"
    failures = 0
    for brief in data["briefs"]:
        user = (f"Business facts:\n{data['facts']}\n\nKind: {brief['kind']}\nTitle: {brief['title']}\n"
                f"Brief: {brief['idea']}\n\nThe photo library has no described photos yet; describe each slot plainly.")
        try:
            draft, raw, _ = ai._call(task, None, p.CONTENT_SYSTEM.format(**rules), user, p.content_tool(brief["kind"]))
            draft.pop("hook_options", None)
            payload = validate_content(brief["kind"], {k: v for k, v in draft.items() if k != "kind"})
        except Exception as exc:  # noqa: BLE001  report and keep going
            print(f"FAIL  {brief['kind']:9} {brief['title']}: no usable draft ({str(exc)[:160]})")
            failures += 1
            continue
        findings = marketing_lint.check(brief["kind"], payload, facts_text=data["facts"],
                                        competitors=data["competitors"])
        labelled = "\n".join(f"[{w}] {t}" for w, t in marketing_lint.segments(brief["kind"], payload))
        try:
            answer, _, _ = ai._call("marketing_review", None, p.REVIEW_SYSTEM.format(**rules),
                                    f"Business facts:\n{data['facts']}\n\nDraft ({brief['kind']}):\n{labelled}",
                                    p.REVIEW_TOOL)
            scores = (AIBrandReview.model_validate(answer).scores or None)
            scores = scores.model_dump() if scores else None
        except Exception as exc:  # noqa: BLE001
            scores = None
            print(f"      critic unavailable: {str(exc)[:160]}")
        weak = review.weak_points(scores)
        blocked = marketing_lint.blocking(findings)
        ok = not blocked and not weak
        failures += 0 if ok else 1
        print(f"{'ok   ' if ok else 'FAIL '} {brief['kind']:9} {brief['title']}: model={raw.get('model')} "
              f"scores={scores} weak={weak} high={[f['rule'] for f in findings if f['severity'] == 'high']}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--snapshot", action="store_true", help="refresh the prompt snapshot used by CI")
    parser.add_argument("--premium", action="store_true", help="live run with the premium copywriter")
    args = parser.parse_args()
    if args.snapshot:
        write_snapshot()
        return
    sys.exit(live(args.premium))


if __name__ == "__main__":
    main()
