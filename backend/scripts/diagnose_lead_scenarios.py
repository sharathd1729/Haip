"""
Read-only: count real cases for each lead scenario the owner decided on 1 Nov 2026, over the last N days (default 30),
and how many of them are on My day right now (work_queue_service.build, the ONE queue).

  S1  lost_came_back     Lost now, yet the guest wrote (live) or called after the close   -> should be Active, "Came back"
      reopened           leads reopened automatically (audit lead.auto_reopened), by trigger
  S3  campaign_replies   guests who replied to a WhatsApp campaign (any days after it), by their lead's stage now
  S4  bot_handover       the bot answered last but a person is needed (it flagged the reply / promised a call or quote /
                         an AI draft is held), and no person has contacted the guest since
  S10 unowned            open leads with a phone that nobody owns
  S8  date_passed_lost   autopilot "travel date passed -> Lost" while the guest had written in the 3 days before
  --  staff_alerts       team alerts (P3/P4) of the last 7 days: WhatsApp vs push, Meta 131049, per person

Nothing is written. Phones never print (names only, first word). Runs on code from before this change too (it reads the
new columns only when they exist), so run it on the VPS before deploying and again after:

  cd backend
  python scripts/diagnose_lead_scenarios.py --tenant-slug rathaa
  python scripts/diagnose_lead_scenarios.py --tenant-slug rathaa --days 30 --list 10
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, or_  # noqa: E402

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.audit_event import AuditEvent  # noqa: E402
from app.models.call import Call, CallDirection  # noqa: E402
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.inquiry_360 import InquiryStageLog  # noqa: E402
from app.models.lead_autopilot import LeadAutopilotEvent  # noqa: E402
from app.models.lead_workflow import PlaybookAction  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient  # noqa: E402
from app.services import work_queue_service, work_queue_signals  # noqa: E402

try:  # the shared pattern, once deployed; a copy so the "before" run works too
    from app.services.work_queue_handover import PROMISE  # noqa: E402
except ImportError:
    PROMISE = re.compile(
        r"\b(?:will|shall|'ll)\s+(?:be\s+)?(?:call(?:ing)?|ring|contact(?:ing)?|reach(?:ing)?\s+out|get(?:ting)?\s+back|"
        r"shar(?:e|ing)|send(?:ing)?)\b|\bget back to you\b|\bcall you (?:back|shortly|soon)\b",
        re.IGNORECASE,
    )

_NOT_LIVE = ("bridge_history", "chat_export")  # mirrored history / imported exports are not the guest writing again
ALERT_KEYS = ("new_lead_alert", "sla_escalation")


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _first(name) -> str:
    return ((name or "").strip().split(" ") or ["?"])[0] or "(no name)"


def _live_inbound():
    return [
        Message.direction == MessageDirection.INBOUND,
        Message.is_internal.isnot(True),
        or_(Message.sender_kind.is_(None), Message.sender_kind.notin_(_NOT_LIVE)),
    ]


def find(db, tenant, days: int) -> dict:
    tid = tenant.id
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    stages = {s.id: s for s in db.query(PipelineStage).filter_by(tenant_id=tid)}
    lost_ids = {i for i, s in stages.items() if s.is_closed_lost}
    queue = work_queue_service.build(db, tenant, None)
    on_queue = defaultdict(set)
    for item in queue["items"]:
        if item.get("guest_id"):
            on_queue[item["guest_id"]].add(item["kind"])
    names = {}

    def name(gid):
        if gid not in names:
            g = db.query(Guest.name).filter_by(id=gid, tenant_id=tid).first()
            names[gid] = _first(g[0] if g else None)
        return names[gid]

    def newest_stage(gid):
        inq = db.query(Inquiry).filter_by(tenant_id=tid, guest_id=gid).order_by(Inquiry.created_at.desc()).first()
        st = stages.get(inq.stage_id) if inq is not None else None
        return inq, (st.label if st else "(no lead)")

    out = {}

    # S1: Lost now, guest in touch after the close (contact inside the window)
    rows = []
    for inq in db.query(Inquiry).filter(Inquiry.tenant_id == tid, Inquiry.stage_id.in_(lost_ids or [""])).all():
        if not inq.guest_id:
            continue
        log = (
            db.query(InquiryStageLog)
            .filter_by(tenant_id=tid, inquiry_id=inq.id, to_stage=stages[inq.stage_id].key)
            .order_by(InquiryStageLog.changed_at.desc())
            .first()
        )
        closed_at = _aware(log.changed_at if log else inq.current_stage_entered_at)
        if closed_at is None:
            continue
        after = max(closed_at, start)
        msgs = (
            db.query(func.count(Message.id), func.max(Message.created_at))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .filter(
                Message.tenant_id == tid,
                Conversation.guest_id == inq.guest_id,
                Message.created_at > after,
                *_live_inbound(),
            )
            .one()
        )
        calls = (
            db.query(func.count(Call.id))
            .filter(
                Call.tenant_id == tid,
                Call.guest_id == inq.guest_id,
                Call.direction == CallDirection.INBOUND,
                Call.created_at > after,
            )
            .scalar()
        )
        if msgs[0] or calls:
            rows.append(
                {
                    "guest": name(inq.guest_id),
                    "closed_by": "system" if log and log.changed_by == "system" else "person",
                    "messages_after": msgs[0],
                    "calls_after": calls,
                    "on_my_day": ",".join(sorted(on_queue.get(inq.guest_id, ()))) or "no",
                }
            )
    out["lost_came_back"] = rows

    reopened = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tid, AuditEvent.action == "lead.auto_reopened", AuditEvent.created_at >= start)
        .all()
    )
    out["reopened"] = [
        {
            "trigger": (e.payload or {}).get("trigger"),
            "closed_by": (e.payload or {}).get("closed_by"),
            "inquiry_id": e.target_id,
        }
        for e in reopened
    ]

    # S3: campaign replies (the campaign report's matching: recipient phone = guest phone, inbound WhatsApp after the send)
    rows = []
    sent = (
        db.query(Recipient.phone, func.max(Recipient.sent_at))
        .filter(Recipient.tenant_id == tid, Recipient.sent_at.isnot(None))
        .group_by(Recipient.phone)
        .all()
    )
    for phone, sent_at in sent:
        g = db.query(Guest).filter_by(tenant_id=tid, phone=phone).first()
        if g is None:
            continue
        first = (
            db.query(func.min(Message.created_at))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .filter(
                Conversation.tenant_id == tid,
                Conversation.guest_id == g.id,
                Conversation.channel == ChannelType.WHATSAPP,
                Message.created_at >= sent_at,
                *_live_inbound(),
            )
            .scalar()
        )
        if first is None or _aware(first) < start:
            continue
        inq, stage = newest_stage(g.id)
        rows.append(
            {
                "guest": _first(g.name),
                "stage_now": stage,
                "days_after_send": (_aware(first) - _aware(sent_at)).days,
                "on_my_day": ",".join(sorted(on_queue.get(g.id, ()))) or "no",
            }
        )
    out["campaign_replies"] = rows

    # S4: the bot answered last but a person is needed
    trig = defaultdict(list)
    msgs = (
        db.query(
            Message.created_at,
            Message.body,
            Message.ai_needs_human_reason,
            Message.sent_autonomously,
            Conversation.guest_id,
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Guest, Guest.id == Conversation.guest_id)
        .filter(
            Message.tenant_id == tid,
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_ai_generated.is_(True),
            Message.is_internal.isnot(True),
            Message.created_at >= start,
            Guest.lead_identified_at.isnot(None),
            Guest.is_deleted.is_(False),
            or_(Message.sent_autonomously.is_(True), Message.was_approved.is_(None)),
        )
        .all()
    )
    for at, body, why, auto, gid in msgs:
        kind = ("flagged" if why else "promised" if PROMISE.search(body or "") else None) if auto else "draft_held"
        if kind:
            trig[gid].append((_aware(at), kind))
    first_at = {g: min(t[0] for t in ts) for g, ts in trig.items()}
    contacts = defaultdict(list)
    for g, at, kind, _ch in work_queue_signals.touch_rows(db, tid, first_at):
        if kind == "contact":
            contacts[g].append(at)
    rows = []
    for g, ts in trig.items():
        last = max(contacts[g]) if contacts.get(g) else None
        left = [t for t in ts if last is None or t[0] > last]
        if left:
            _, stage = newest_stage(g)
            if stage in {stages[i].label for i in lost_ids}:
                continue
            rows.append(
                {
                    "guest": name(g),
                    "why": ",".join(sorted({k for _, k in left})),
                    "stage_now": stage,
                    "on_my_day": ",".join(sorted(on_queue.get(g, ()))) or "no",
                }
            )
    out["bot_handover"] = rows

    # S10: open leads with a phone that nobody owns (arrived or came back in the window)
    done = set(work_queue_service._done_stage_ids(db, tid))
    q = (
        db.query(Inquiry, Guest.name)
        .join(Guest, Guest.id == Inquiry.guest_id)
        .filter(
            Inquiry.tenant_id == tid,
            Inquiry.assigned_to.is_(None),
            Guest.lead_identified_at.isnot(None),
            Guest.is_deleted.is_(False),
        )
    )
    returned = getattr(Inquiry, "returned_at", None)
    q = q.filter(
        or_(Inquiry.created_at >= start, returned >= start) if returned is not None else Inquiry.created_at >= start
    )
    out["unowned"] = [
        {
            "guest": _first(n),
            "stage_now": stages[i.stage_id].label if i.stage_id in stages else "?",
            "on_my_day": ",".join(sorted(on_queue.get(i.guest_id, ()))) or "no",
        }
        for i, n in q.all()
        if not (i.stage_id and i.stage_id in done)
    ]

    # S8: autopilot "date passed" Lost while the guest had written in the 3 days before
    rows = []
    for ev, gid in (
        db.query(LeadAutopilotEvent, Inquiry.guest_id)
        .join(Inquiry, Inquiry.id == LeadAutopilotEvent.inquiry_id)
        .filter(
            LeadAutopilotEvent.tenant_id == tid,
            LeadAutopilotEvent.rule == "dates_passed",
            LeadAutopilotEvent.created_at >= start,
        )
        .all()
    ):
        at = _aware(ev.created_at)
        wrote = (
            db.query(func.count(Message.id))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .filter(
                Conversation.tenant_id == tid,
                Conversation.guest_id == gid,
                Message.created_at >= at - timedelta(days=3),
                Message.created_at <= at,
                *_live_inbound(),
            )
            .scalar()
        )
        if wrote:
            rows.append(
                {
                    "guest": name(gid),
                    "status": ev.status,
                    "messages_3d_before": wrote,
                    "stage_now": newest_stage(gid)[1],
                }
            )
    out["date_passed_lost"] = rows

    # Staff alerts, last 7 days
    acts = (
        db.query(PlaybookAction)
        .filter(
            PlaybookAction.tenant_id == tid,
            PlaybookAction.playbook_key.in_(ALERT_KEYS),
            PlaybookAction.created_at >= now - timedelta(days=7),
        )
        .all()
    )
    users = {u.id: _first(u.name) for u in db.query(User.id, User.name).filter(User.tenant_id == tid)}
    out["staff_alerts"] = {
        "by_action": Counter(f"{a.action}:{a.status}" for a in acts),
        "meta_131049": sum(1 for a in acts if (a.reason or "").startswith("Meta 131049")),
        "whatsapp_per_person": Counter(
            users.get(a.recipient_user_id, "?")
            for a in acts
            if a.action == "staff_wa" and a.status in ("done", "queued")
        ),
        "queue_kinds_now": Counter(i["kind"] for i in queue["items"]),
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--list", type=int, default=10, help="Example rows printed per scenario (counts are always complete)"
    )
    args = parser.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No workspace with slug '{args.tenant_slug}'.")
            return 1
        set_tenant_context(db, tenant.id)
        found = find(db, tenant, args.days)
        print(f"Workspace: {tenant.name}   last {args.days} days   (read-only; nothing was changed)")
        titles = {
            "lost_came_back": "S1 Lost now, but the guest wrote or called after it was closed",
            "reopened": "S1 Reopened automatically (lead.auto_reopened)",
            "campaign_replies": "S3 Replied to a WhatsApp campaign",
            "bot_handover": "S4 Bot answered last, a person is still needed, nobody contacted them since",
            "unowned": "S10 Open leads nobody owns",
            "date_passed_lost": "S8 Autopilot 'date passed' Lost while the guest wrote in the 3 days before",
        }
        for key, title in titles.items():
            rows = found[key]
            on = sum(1 for r in rows if r.get("on_my_day", "no") != "no")
            print(
                f"\n== {title}: {len(rows)}" + (f"   (on My day now: {on})" if rows and "on_my_day" in rows[0] else "")
            )
            for col in ("closed_by", "trigger", "stage_now", "why", "status"):
                if rows and col in rows[0]:
                    print(
                        f"   by {col}: " + ", ".join(f"{k} {v}" for k, v in Counter(r[col] for r in rows).most_common())
                    )
            for r in rows[: args.list]:
                print("   " + "  ".join(f"{k}={v}" for k, v in r.items() if k != "inquiry_id"))
        alerts = found["staff_alerts"]
        print("\n== Staff alerts, last 7 days")
        print("   " + (", ".join(f"{k} {v}" for k, v in sorted(alerts["by_action"].items())) or "none"))
        print(f"   Meta 131049 failures: {alerts['meta_131049']}")
        print(
            "   WhatsApp per person: "
            + (", ".join(f"{k} {v}" for k, v in alerts["whatsapp_per_person"].most_common()) or "none")
        )
        print("   My day now, by kind: " + ", ".join(f"{k} {v}" for k, v in alerts["queue_kinds_now"].most_common()))
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
