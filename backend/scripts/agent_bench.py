"""Agent test bench runner (tau-bench style). NEVER run in CI; CI runs tests/test_agent_bench.py (scripted model).

    python scripts/agent_bench.py --tenant rathaa                  scripted model, one run per scenario (a smoke check)
    python scripts/agent_bench.py --tenant rathaa --live -k 5      the REAL LLM router, 5 runs per scenario, pass^k
    python scripts/agent_bench.py --tenant rathaa --live -k 5 --prompt cand.jinja --compare-with reports/<old>.json
    options: --only id1,id2 · --tags quote,discount · --playbook pb.json · --judge (advisory tone check) · --out DIR

Safety: the bench builds its OWN throwaway SQLite database (--bench-db, default ./agent_bench.db, recreated every run) and
points DATABASE_URL at it BEFORE importing the app, so it can never read or write a real workspace. Every WhatsApp/Instagram
send, staff alert and push is captured in-process; nothing leaves the machine except the model calls in --live mode (they
need the provider keys: run it inside the API container). The world = tests/fixtures/agent_bench/<tenant>.json scenarios +
Rathaa's catalogue published + the sales playbook (or --playbook, a JSON export of GET /ai/sales-playbook).

Grading is code only (app/services/agent_bench.grade): regex / structured checks per scenario. pass^k = a scenario passes
only if ALL k runs pass; the overall figure is the share of scenarios that do. --judge adds an LLM opinion on tone, labelled
"advisory": it never changes pass/fail.

Comparing a prompt version (harness2-style): run the current prompt and save the report, run the candidate with --prompt on
the same scenarios and k with --compare-with the first report. Adopt the candidate only if no scenario's pass^k drops, the
overall pass^k is not lower, and the owner approves; then copy it over app/prompts/concierge_reply.jinja and bump
core/prompt_versions.py in the same commit. Docs: docs/ai/AGENT_BENCH.md.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _isolate(bench_db: str) -> None:
    """The bench never touches a real database: point the app at the throwaway file before anything imports it."""
    path = Path(bench_db.replace("sqlite:///", "")) if bench_db.startswith("sqlite:///") else None
    if path is None:
        raise SystemExit("--bench-db must be a sqlite:/// URL (the bench never uses a shared database)")
    if path.exists():
        path.unlink()
    os.environ["DATABASE_URL"] = bench_db
    os.environ.setdefault("JWT_SECRET", "agent-bench-only")
    if not os.environ.get("ENCRYPTION_KEY"):
        from cryptography.fernet import Fernet
        os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()


def _select(scenarios: list, only: str, tags: str) -> list:
    if only:
        want = set(only.split(","))
        scenarios = [s for s in scenarios if s["id"] in want]
    if tags:
        want_t = set(tags.split(","))
        scenarios = [s for s in scenarios if want_t & set(s.get("tags", []))]
    return scenarios


def _judge(text: str) -> dict:
    """Advisory only: does the reply read like a warm, concise host? Never part of pass/fail."""
    import asyncio
    from app.adapters.llm import get_llm
    tool = {"name": "tone", "description": "Judge the tone of a hospitality WhatsApp reply",
            "input_schema": {"type": "object", "properties": {"tone_ok": {"type": "boolean"}, "note": {"type": "string"}},
                             "required": ["tone_ok"]}}
    try:
        res = asyncio.run(get_llm("quick_classify").complete(
            system_prompt="You judge tone only: warm, natural, concise, no corporate phrases. Ignore facts and prices.",
            user_message=text or "(empty)", tools=[tool]))
        return res.get("tool_use") or {}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}


def _markdown(report: dict, old: dict | None) -> str:
    olds = {s["id"]: s for s in (old or {}).get("scenarios", [])}
    head = "| scenario | pass^k | runs passed |" + (" previous pass^k |" if old else "") + " failing checks |"
    lines = [f"# Agent bench: {report['meta']['tenant']} ({'live' if report['meta']['live'] else 'scripted'}, k={report['meta']['k']})",
             "", f"Prompt: {report['meta']['prompt']} · started {report['meta']['started']}",
             f"Overall pass^k: **{report['overall']['pass_k']:.0%}** · pass@1: {report['overall']['pass_at_1']:.0%}"
             + (f" · previous pass^k {old['overall']['pass_k']:.0%}" if old else ""), "", head,
             "|" + "---|" * (head.count("|") - 1)]
    for s in report["scenarios"]:
        fails = sorted({c["check"] for r in s["runs"] for c in r["checks"] if not c["ok"]})
        prev = olds.get(s["id"])
        row = f"| {s['id']} | {'yes' if s['pass_k'] else 'no'} | {s['passed_runs']}/{len(s['runs'])} |"
        if old:
            row += f" {'-' if prev is None else ('yes' if prev['pass_k'] else 'no')} |"
        lines.append(row + f" {', '.join(fails) or '-'} |")
    if old:
        regressed = [s["id"] for s in report["scenarios"] if olds.get(s["id"], {}).get("pass_k") and not s["pass_k"]]
        verdict = "ADOPTABLE (owner to approve)" if not regressed and report["overall"]["pass_k"] >= old["overall"]["pass_k"] \
            else f"DO NOT ADOPT (regressed: {', '.join(regressed) or 'overall pass^k lower'})"
        lines += ["", f"Verdict vs previous: **{verdict}**"]
    if report["meta"]["judge"]:
        lines += ["", "Tone (LLM judge, ADVISORY, not graded):"] + [
            f"- {s['id']}: {s.get('tone')}" for s in report["scenarios"] if s.get("tone")]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", default="rathaa", help="scenario set: tests/fixtures/agent_bench/<tenant>.json")
    ap.add_argument("--live", action="store_true", help="call the real LLM router (never in CI)")
    ap.add_argument("-k", type=int, default=1, help="runs per scenario (pass^k)")
    ap.add_argument("--only", default="", help="comma-separated scenario ids")
    ap.add_argument("--tags", default="", help="comma-separated tags")
    ap.add_argument("--prompt", default="", help="candidate concierge_reply.jinja to bench instead of the current one")
    ap.add_argument("--playbook", default="", help="JSON sales playbook (an export of GET /ai/sales-playbook)")
    ap.add_argument("--compare-with", default="", help="a previous report.json to compare against")
    ap.add_argument("--judge", action="store_true", help="advisory LLM tone judge (live only, never graded)")
    ap.add_argument("--bench-db", default="sqlite:///./agent_bench.db")
    ap.add_argument("--out", default="agent_bench_reports")
    args = ap.parse_args()
    _isolate(args.bench_db)

    from contextlib import ExitStack
    from unittest.mock import patch

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.main  # noqa: F401  (imports every model, like the test suite, so every table is created)
    from app.core.database import Base
    from app.services import agent_bench, sales_playbook
    from app.schemas.sales_playbook import SalesPlaybook

    engine = create_engine(args.bench_db, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    scenarios = _select(agent_bench.load_scenarios(BACKEND / "tests" / "fixtures" / "agent_bench" / f"{args.tenant}.json"),
                        args.only, args.tags)
    world = agent_bench.build_world(db)
    if args.playbook:
        sales_playbook.update(db, world.tenant, None, SalesPlaybook.model_validate(json.loads(Path(args.playbook).read_text("utf-8"))
                                                                                     .get("playbook", {})), actor="agent_bench")
        db.commit()
    from app.core.prompt_versions import PROMPT_VERSIONS
    prompt_label = args.prompt or PROMPT_VERSIONS["concierge_reply"]
    report = {"meta": {"tenant": args.tenant, "live": args.live, "k": args.k, "prompt": prompt_label, "judge": args.judge,
                       "started": datetime.now(timezone.utc).isoformat()}, "scenarios": []}
    with ExitStack() as stack:
        if args.prompt:
            from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
            from app.workers.tasks import concierge_draft as cd
            env = Environment(loader=ChoiceLoader([DictLoader({"concierge_reply.jinja": Path(args.prompt).read_text("utf-8")}),
                                                   FileSystemLoader(str(cd.PROMPTS_DIR))]))
            stack.enter_context(patch.object(cd, "_jinja_env", env))
        for s in scenarios:
            runs = []
            for _ in range(max(1, args.k)):
                t0 = time.monotonic()
                out = agent_bench.run_scenario(db, world, s, llm_factory=(lambda: None) if args.live else None)
                checks = agent_bench.grade(s, out)
                runs.append({"passed": agent_bench.passed(checks), "checks": checks, "draft": out["draft"],
                             "reasons": out["reasons"], "seconds": round(time.monotonic() - t0, 2)})
            row = {"id": s["id"], "tags": s.get("tags", []), "runs": runs, "passed_runs": sum(r["passed"] for r in runs),
                   "pass_k": all(r["passed"] for r in runs)}
            if args.judge and args.live:
                row["tone"] = _judge(runs[-1]["draft"] or "")
            report["scenarios"].append(row)
            print(f"{'PASS' if row['pass_k'] else 'FAIL'}  {s['id']}  ({row['passed_runs']}/{len(runs)})")
    n = len(report["scenarios"]) or 1
    report["overall"] = {"pass_k": sum(s["pass_k"] for s in report["scenarios"]) / n,
                         "pass_at_1": sum(s["passed_runs"] / len(s["runs"]) for s in report["scenarios"]) / n}
    old = json.loads(Path(args.compare_with).read_text("utf-8")) if args.compare_with else None
    out_dir = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), "utf-8")
    (out_dir / "report.md").write_text(_markdown(report, old), "utf-8")
    print(f"\npass^k {report['overall']['pass_k']:.0%} · pass@1 {report['overall']['pass_at_1']:.0%} · report: {out_dir}")
    db.close()
    return 0 if report["overall"]["pass_k"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
