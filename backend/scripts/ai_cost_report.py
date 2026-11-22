"""AI cost report (docs/ai/AI_COST_SPEC.md step 0). READ-ONLY: one read-only transaction, SELECTs only. Prints counts and
money per task and per workspace, never a guest name, phone number or message text.

    docker compose -f docker-compose.prod.yml exec -T api python scripts/ai_cost_report.py [--days 30] [--tenant SLUG]
                                                                                            [--usd-inr 88]

Sources (names as in the code): usage_events (kind llm_call; meta.task / cost_usd / batch / attempts / ok /
cache_read_tokens / cache_write_tokens; input_units = fresh input tokens), calls (duration_seconds, inquiry_id,
ai_disposition, transcription_cost_usd), transcripts.raw_text (word counts only), ai_draft_outcomes (outcome "expired")
joined to the draft message's channel, insights.explanation (the AI Executive's last explanation per finding).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.getcwd())

# Jobs nobody waits on (candidates for Message Batches, half price).
BACKGROUND = {
    "call_analysis",
    "deep_reason",
    "call_scoring",
    "lead_summary",
    "chief_explain",
    "analyst_brief",
    "daily_briefing",
    "agent_performance_narrative",
    "agent_leads_feedback",
    "lead_stage_classify",
    "outcome_reason",
    "lead_followup_draft",
    "personal_call",
    "personal_digest",
    "personal_folder",
    "assessment_narrative",
    "sop_generate",
}
SUMMARY_AFTER_CALL_MIN = (
    20  # a lead_summary for the call's inquiry within this many minutes of its analysis = call-triggered
)


def _aware(dt):
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _cost(meta: dict) -> float:
    c = meta.get("cost_usd")
    return float(c) if c is not None else 0.0


class Money:
    def __init__(self, usd_inr: float, days: int):
        self.rate, self.month = usd_inr, 30.0 / days

    def __call__(self, usd: float) -> str:
        return f"${usd:,.2f} (₹{usd * self.rate:,.0f})"

    def monthly(self, usd: float) -> str:
        m = usd * self.month
        return f"₹{m * self.rate:,.0f}/month (${m:,.2f})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--tenant", help="one workspace slug (default: every workspace)")
    from app.services.llm_usage_report import DEFAULT_USD_INR

    ap.add_argument("--usd-inr", type=float, default=DEFAULT_USD_INR)
    args = ap.parse_args()

    from sqlalchemy import text

    from app.core.database import SessionLocal, set_tenant_context
    from app.models.ai_draft_outcome import AIDraftOutcome
    from app.models.call import Call
    from app.models.conversation import Message
    from app.models.insight import Insight
    from app.models.tenant import Tenant
    from app.models.transcript import Transcript
    from app.models.usage_event import UsageEvent

    money = Money(args.usd_inr, args.days)
    since = datetime.now(UTC) - timedelta(days=args.days)
    db = SessionLocal()
    try:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        q = db.query(Tenant.id, Tenant.slug)
        if args.tenant:
            q = q.filter(Tenant.slug == args.tenant)
        tenants = q.order_by(Tenant.slug).all()

        tasks: dict = defaultdict(Counter)
        per_tenant_cost: Counter = Counter()
        call_reads = []  # (tenant, call_id, analysis_n, deep_n, summary_n, cost, duration, words, disposition)
        short = {30: Counter(), 60: Counter(), "words25": Counter()}
        drafts = defaultdict(Counter)  # (slug, channel) -> outcome counts
        chief = defaultdict(Counter)  # (slug, task) -> day -> calls
        chief_cost: Counter = Counter()
        transcription = Counter()
        concierge_cost = 0.0
        concierge_drafts = 0

        for tid, slug in tenants:
            set_tenant_context(db, tid)  # every query below also filters by tenant: correct with or without RLS
            rows = (
                db.query(
                    UsageEvent.created_at,
                    UsageEvent.kind,
                    UsageEvent.units,
                    UsageEvent.input_units,
                    UsageEvent.meta,
                    UsageEvent.ref_type,
                    UsageEvent.ref_id,
                )
                .filter(UsageEvent.tenant_id == tid, UsageEvent.created_at >= since)
                .all()
            )
            by_call = defaultdict(list)
            summaries = defaultdict(list)  # inquiry_id -> [created_at, cost]
            for created, kind, units, inp, meta, ref_type, ref_id in rows:
                meta = meta or {}
                task = str(meta.get("task") or kind)
                c = _cost(meta)
                if kind == "transcription_call":
                    transcription["rows"] += 1
                    transcription["seconds"] += int(units or 0)
                    transcription["usd_rows"] += c
                    continue
                if kind != "llm_call":
                    tasks[f"{task} ({kind})"]["calls"] += 1
                    tasks[f"{task} ({kind})"]["usd"] += c
                    per_tenant_cost[slug] += c
                    continue
                t = tasks[task]
                t["calls"] += 1
                t["usd"] += c
                t["unknown_cost"] += meta.get("cost_usd") is None
                t["batch"] += bool(meta.get("batch"))
                t["input"] += int(inp or 0)
                t["cache_read"] += int(meta.get("cache_read_tokens") or 0)
                t["cache_write"] += int(meta.get("cache_write_tokens") or 0)
                attempts = int(meta.get("attempts") or 1)
                if attempts > 1:
                    t["retried"] += 1
                    t["retry_extra_usd"] += c * (attempts - 1) / attempts  # upper bound: a failed attempt is not billed
                if meta.get("ok") is False:
                    t["failed"] += 1
                    t["failed_usd"] += c
                per_tenant_cost[slug] += c
                created = _aware(created)
                if task in ("call_analysis", "deep_reason", "call_scoring") and ref_type == "call" and ref_id:
                    by_call[ref_id].append((task, created, c))
                elif task == "lead_summary" and ref_type == "inquiry" and ref_id:
                    summaries[ref_id].append((created, c))
                elif task.startswith("concierge_"):
                    concierge_cost += c
                    concierge_drafts += task == "concierge_draft" and meta.get("ok") is not False
                if task in ("chief_explain", "daily_briefing"):
                    chief[(slug, task)][created.date().isoformat()] += 1
                    chief_cost[(slug, task)] += c

            # ── reads per phone call, short calls ─────────────────────────────────────────────────────────────────
            ids = list(by_call)
            calls, words = {}, {}
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                for cid, dur, iid, disp in db.query(
                    Call.id, Call.duration_seconds, Call.inquiry_id, Call.ai_disposition
                ).filter(Call.tenant_id == tid, Call.id.in_(chunk)):
                    calls[cid] = (dur, iid, getattr(disp, "value", disp))
                for cid, raw in db.query(Transcript.call_id, Transcript.raw_text).filter(
                    Transcript.tenant_id == tid, Transcript.call_id.in_(chunk)
                ):
                    words[cid] = len((raw or "").split())
            for cid, reads in by_call.items():
                dur, iid, disp = calls.get(cid, (None, None, None))
                first = (
                    min(r[1] for r in reads if r[0] == "call_analysis")
                    if any(r[0] == "call_analysis" for r in reads)
                    else None
                )
                summ = [
                    s
                    for s in summaries.get(iid, [])
                    if first and first <= s[0] <= first + timedelta(minutes=SUMMARY_AFTER_CALL_MIN)
                ]
                cost = sum(r[2] for r in reads) + sum(s[1] for s in summ)
                n_an = sum(r[0] == "call_analysis" for r in reads)
                n_dr = sum(r[0] == "deep_reason" for r in reads)
                call_reads.append(
                    (slug, cid, n_an, n_dr, len(summ), cost, dur, words.get(cid), disp, sum(s[1] for s in summ))
                )
                read_cost = sum(r[2] for r in reads if r[0] in ("call_analysis", "deep_reason"))
                for limit in (30, 60):
                    if dur is not None and dur < limit:
                        short[limit]["calls"] += 1
                        short[limit]["usd"] += read_cost
                        short[limit]["summary_usd"] += sum(s[1] for s in summ)
                if words.get(cid) is not None and words[cid] < 25:
                    short["words25"]["calls"] += 1
                    short["words25"]["usd"] += read_cost

            # ── expired drafts by workspace and channel ───────────────────────────────────────────────────────────
            for outcome, channel, mmeta in (
                db.query(AIDraftOutcome.outcome, Message.channel, Message.channel_metadata)
                .join(Message, Message.id == AIDraftOutcome.draft_message_id)
                .filter(AIDraftOutcome.tenant_id == tid, AIDraftOutcome.created_at >= since)
            ):
                ch = str(getattr(channel, "value", channel) or "?").lower()
                if ch == "instagram" and isinstance(mmeta, dict) and mmeta.get("answers") == "comment":
                    ch = "instagram comment"
                drafts[(slug, ch)][outcome] += 1

            # ── transcription spend already stored on calls (before transcription_call rows existed) ──────────────
            got = (
                db.query(Call.duration_seconds, Call.transcription_cost_usd)
                .filter(Call.tenant_id == tid, Call.created_at >= since, Call.transcription_status == "done")
                .all()
            )
            transcription["calls"] += len(got)
            transcription["call_seconds"] += sum(int(d or 0) for d, _ in got)
            transcription["usd_calls"] += sum(float(c or 0) for _, c in got)

            explained = (
                db.query(Insight.explanation).filter(Insight.tenant_id == tid, Insight.explanation.isnot(None)).all()
            )
            chief[(slug, "findings_with_explanation")]["total"] = len(explained)
    finally:
        db.rollback()
        db.close()

    _print(
        args,
        money,
        tasks,
        per_tenant_cost,
        call_reads,
        short,
        drafts,
        chief,
        chief_cost,
        transcription,
        concierge_cost,
        concierge_drafts,
    )
    return 0


def _print(
    args,
    money,
    tasks,
    per_tenant_cost,
    call_reads,
    short,
    drafts,
    chief,
    chief_cost,
    transcription,
    concierge_cost,
    concierge_drafts,
) -> None:
    total = sum(t["usd"] for t in tasks.values())
    print(
        f"AI COST REPORT, last {args.days} days{' (' + args.tenant + ')' if args.tenant else ''}. Rate ₹{args.usd_inr}/$."
    )
    print(f"Total model cost: {money(total)}  =  {money.monthly(total)}")
    print("\n== 1. Per task (llm_call unless marked)")
    print(
        f"{'task':34} {'calls':>7} {'cost':>22} {'share':>6} {'batch':>6} {'cache hit':>9} {'retried':>7} {'failed':>6}"
    )
    for name, t in sorted(tasks.items(), key=lambda kv: -kv[1]["usd"]):
        denom = t["input"] + t["cache_read"] + t["cache_write"]
        hit = f"{t['cache_read'] / denom:.0%}" if denom else "-"
        batch = f"{t['batch'] / t['calls']:.0%}" if t["calls"] else "-"
        share = f"{t['usd'] / total:.0%}" if total else "-"
        print(
            f"{name[:34]:34} {t['calls']:>7} {money(t['usd']):>22} {share:>6} {batch:>6} {hit:>9} {t['retried']:>7} {t['failed']:>6}"
        )
        if t["unknown_cost"]:
            print(f"{'':34} ({t['unknown_cost']} calls with unknown cost, not included)")
    print("\nBy workspace: " + ", ".join(f"{s} {money(u)}" for s, u in per_tenant_cost.most_common()))

    retry_extra = sum(t["retry_extra_usd"] for t in tasks.values())
    failed_usd = sum(t["failed_usd"] for t in tasks.values())
    print(
        f"\n== 2. Retries and failures\nRetried calls' extra cost (upper bound): {money(retry_extra)}; failed calls still billed: {money(failed_usd)}"
    )

    print(
        "\n== 3. Paid reads per phone call (call_analysis + deep_reason + lead_summary within "
        f"{SUMMARY_AFTER_CALL_MIN} min of the analysis)"
    )
    if call_reads:
        n = len(call_reads)
        reads = [a + d + s for _, _, a, d, s, *_ in call_reads]
        dist = Counter(reads)
        print(
            f"Calls analysed: {n}; reads per call: avg {sum(reads) / n:.2f}; distribution "
            + ", ".join(f"{k} reads: {v}" for k, v in sorted(dist.items()))
        )
        print(
            f"Calls with a deep_reason re-check: {sum(1 for c in call_reads if c[3])} ({sum(1 for c in call_reads if c[3]) / n:.0%}); "
            f"with a call-triggered lead_summary: {sum(1 for c in call_reads if c[4])} ({sum(1 for c in call_reads if c[4]) / n:.0%})"
        )
        all_cost = sum(c[5] for c in call_reads)
        summary_cost = sum(c[9] for c in call_reads)
        print(
            f"Cost of the reads: {money(all_cost)} (avg {money(all_cost / n)} per call); of which call-triggered summaries {money(summary_cost)}"
        )
        no_value = [c for c in call_reads if c[8] in ("no_answer", "voicemail") or (c[6] is not None and c[6] < 60)]
        print(
            f"Call-triggered summaries after a no-answer / voicemail / <60 s call: {money(sum(c[9] for c in no_value))}"
        )

    print("\n== 4. call_analysis (+ deep_reason) on short calls (calls.duration_seconds; outbound includes ringing)")
    for limit in (30, 60):
        s = short[limit]
        print(
            f"Under {limit} s: {s['calls']} calls, reads {money(s['usd'])}, their summaries {money(s['summary_usd'])}"
        )
    print(f"Transcript under 25 words: {short['words25']['calls']} calls, reads {money(short['words25']['usd'])}")

    print("\n== 5. AI drafts by workspace and channel (ai_draft_outcomes)")
    per_draft = concierge_cost / concierge_drafts if concierge_drafts else 0.0
    expired_total = 0
    for (slug, ch), c in sorted(drafts.items()):
        tot = sum(c.values())
        expired_total += c["expired"]
        print(
            f"{slug:20} {ch:18} drafts {tot:>5}  expired {c['expired']:>5} ({c['expired'] / tot:.0%})  "
            f"sent as written {c['sent_verbatim']:>4}  edited {c['sent_edited']:>4}  rejected {c['rejected']:>4}"
        )
    print(
        f"Average concierge_* cost per draft: {money(per_draft)}; expired drafts' estimated cost: {money(expired_total * per_draft)}"
    )

    print("\n== 6. chief_explain / daily_briefing runs per workspace per day")
    for (slug, task), days in sorted(chief.items()):
        if task == "findings_with_explanation":
            continue
        runs = sum(days.values())
        print(
            f"{slug:20} {task:16} runs {runs:>4} on {len(days):>3} days, avg {runs / max(len(days), 1):.1f}/day, "
            f"max {max(days.values())}/day, cost {money(chief_cost[(slug, task)])}"
        )
    print(
        "Repeated text: not measurable from stored data (insights.explanation is overwritten in place, no history);"
        " chief.explain.due() already skips a finding whose numbers are unchanged."
    )

    print("\n== 7. Transcription (speech-to-text)")
    print(
        f"Calls transcribed: {transcription['calls']}, {transcription['call_seconds'] / 60:,.0f} call minutes, "
        f"stored cost (calls.transcription_cost_usd) {money(transcription['usd_calls'])}"
    )
    if transcription["rows"]:
        print(
            f"transcription_call rows: {transcription['rows']}, {transcription['seconds'] / 60:,.0f} audio minutes, {money(transcription['usd_rows'])}"
        )

    print("\n== 8. Waste candidates (monthly, at this period's volume)")
    bg_unbatched = sum(
        t["usd"] * (1 - t["batch"] / t["calls"]) for k, t in tasks.items() if k in BACKGROUND and t["calls"]
    )
    cands = [
        ("call_scoring (no caller expected)", tasks.get("call_scoring", Counter())["usd"]),
        ("reads on calls under 30 s", short[30]["usd"]),
        (
            "summaries after no-answer/voicemail/<60 s calls",
            sum(c[9] for c in call_reads if c[8] in ("no_answer", "voicemail") or (c[6] is not None and c[6] < 60)),
        ),
        ("expired drafts (estimated)", expired_total * per_draft),
        ("retry extra (upper bound)", retry_extra),
        ("failed calls billed", failed_usd),
        ("half of un-batched background jobs (if batched)", bg_unbatched / 2),
    ]
    for name, usd in cands:
        print(f"{name:50} {money(usd):>24}  {money.monthly(usd)}")


if __name__ == "__main__":
    raise SystemExit(main())
