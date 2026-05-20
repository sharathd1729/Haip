"""
Full demo-data seed for testing P1 features.

Creates for the existing sharath@ratha.in account:
  - 6 Guests with full profiles
  - 8 Inquiries across all stages (new/responding/quoted/site_visit/booked/lost)
    with assignees, ages, SLA states
  - 5 WhatsApp conversations with realistic message threads
    (delivery states: sent/delivered/read/failed; AI drafts; unread counts)
  - 4 Calls with full transcripts (t0/t1 per turn) + QA scores
  - 8 Saved replies (hospitality canned responses)

Run:  python scripts/seed_demo_data.py
"""

import sys, os, uuid, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.models.user import User
from app.models.property import Property
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource, LostReason
from app.models.conversation import Conversation, Message, MessageDeliveryState
from app.models.call import Call, CallDirection, CallDisposition, RecordingStatus
from app.models.transcript import Transcript
from app.models.score import CallScore, Rubric
from app.models.saved_reply import SavedReply

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)
def ago(**kw): return now() - timedelta(**kw)
def iso(dt): return dt.isoformat()


def run():
    db = SessionLocal()
    try:
        # ── Resolve tenant + users + property ─────────────────────────────────
        tenant = db.query(Tenant).filter_by(slug="ratha").first()
        if not tenant:
            print("Run seed_ratha.py first to create the tenant!")
            return

        owner = db.query(User).filter_by(email="sharath@ratha.in").first()
        concierge = db.query(User).filter_by(email="ravi@ratha.in").first()
        prop = db.query(Property).filter_by(tenant_id=tenant.id).first()
        rubric = db.query(Rubric).filter_by(tenant_id=tenant.id, is_default=True).first()

        tid = tenant.id
        oid = owner.id if owner else uid()
        cid = concierge.id if concierge else uid()

        # ── Guests ────────────────────────────────────────────────────────────
        print("Creating guests...")
        guests_data = [
            {"phone": "+919876543210", "name": "Priya Sharma",    "email": "priya@gmail.com",       "city": "Bangalore", "predicted_csat": 4.8, "lifetime_value": 48000},
            {"phone": "+917654321098", "name": "Kiran Reddy",     "email": "kiran.r@gmail.com",     "city": "Hyderabad", "predicted_csat": 4.2, "lifetime_value": 0},
            {"phone": "+919765432109", "name": "Rahul Mehta",     "email": None,                    "city": "Mumbai",    "predicted_csat": 3.9, "lifetime_value": 0},
            {"phone": "+918899001122", "name": "Anjali Nair",     "email": "anjali.n@outlook.com",  "city": "Kochi",     "predicted_csat": 4.6, "lifetime_value": 72000},
            {"phone": "+917788990011", "name": "Vikram Sinha",    "email": "vikram.s@gmail.com",    "city": "Delhi",     "predicted_csat": 4.1, "lifetime_value": 48000},
            {"phone": "+916677889900", "name": "Deepa Krishnan",  "email": "deepa.k@yahoo.com",    "city": "Chennai",   "predicted_csat": 4.9, "lifetime_value": 0},
        ]
        guests = {}
        for g in guests_data:
            existing = db.query(Guest).filter_by(tenant_id=tid, phone=g["phone"]).first()
            if existing:
                guests[g["phone"]] = existing
            else:
                guest = Guest(id=uid(), tenant_id=tid, **g)
                db.add(guest)
                guests[g["phone"]] = guest
        db.flush()
        print(f"  {len(guests)} guests ready")

        # ── Inquiries across all stages ────────────────────────────────────────
        print("Creating inquiries...")
        prop_id = prop.id if prop else None
        prop_name = prop.name if prop else "Ratha Caravan Fleet"

        inquiries_data = [
            # New — just came in, SLA will be breaching (old created_at)
            {
                "guest": "+919876543210", "stage": InquiryStage.NEW,
                "assigned_to": cid, "check_in": "2026-06-15", "check_out": "2026-06-18",
                "budget": 45000, "channel": "whatsapp",
                "stage_entered": ago(hours=2),  # 2h old → SLA breach
            },
            # Responding — assigned to Ravi
            {
                "guest": "+917654321098", "stage": InquiryStage.RESPONDING,
                "assigned_to": cid, "check_in": "2026-07-01", "check_out": "2026-07-04",
                "budget": 36000, "channel": "call",
                "stage_entered": ago(hours=5),
            },
            # Quoted — unassigned (K4 ⚠)
            {
                "guest": "+919765432109", "stage": InquiryStage.QUOTED,
                "assigned_to": None, "check_in": "2026-06-28", "check_out": "2026-07-01",
                "budget": 60000, "channel": "instagram",
                "stage_entered": ago(days=2),  # 2d old → yellow stripe
            },
            # Site visit arranged
            {
                "guest": "+918899001122", "stage": InquiryStage.SITE_VISIT,
                "assigned_to": oid, "check_in": "2026-08-10", "check_out": "2026-08-13",
                "budget": 72000, "channel": "whatsapp",
                "stage_entered": ago(days=4),  # 4d → orange stripe
            },
            # Booked — won
            {
                "guest": "+917788990011", "stage": InquiryStage.BOOKED,
                "assigned_to": cid, "check_in": "2026-06-20", "check_out": "2026-06-23",
                "budget": 48000, "channel": "whatsapp",
                "stage_entered": ago(days=1),
            },
            # Lost — price too high
            {
                "guest": "+916677889900", "stage": InquiryStage.LOST,
                "assigned_to": oid, "check_in": "2026-07-10", "check_out": "2026-07-13",
                "budget": 30000, "channel": "call",
                "stage_entered": ago(days=8),  # 8d → red stripe
                "lost_reason": LostReason.BUDGET_MISMATCH,
                "lost_note": "Guest said ₹30k was their max but our minimum is ₹36k for 3 nights.",
            },
            # Another new — unassigned + very fresh (K4+K6)
            {
                "guest": "+919876543210", "stage": InquiryStage.NEW,
                "assigned_to": None, "check_in": "2026-09-05", "check_out": "2026-09-08",
                "budget": 55000, "channel": "whatsapp",
                "stage_entered": ago(minutes=8),  # 8min → warning SLA
            },
            # Responding — another, assigned to owner
            {
                "guest": "+918899001122", "stage": InquiryStage.RESPONDING,
                "assigned_to": oid, "check_in": "2026-10-01", "check_out": "2026-10-05",
                "budget": 80000, "channel": "whatsapp",
                "stage_entered": ago(days=10),  # very old → red stripe
            },
        ]

        inq_list = []
        for d in inquiries_data:
            guest = guests[d["guest"]]
            inq = Inquiry(
                id=uid(), tenant_id=tid,
                guest_id=guest.id,
                property_id=prop_id,
                stage=d["stage"],
                assigned_to=d.get("assigned_to"),
                check_in=d.get("check_in"),
                check_out=d.get("check_out"),
                budget=d.get("budget"),
                lost_reason=d.get("lost_reason"),
                lost_note=d.get("lost_note"),
                current_stage_entered_at=d.get("stage_entered"),
                source=InquirySource.WA_DIRECT,
                tags=["luxury", "caravan"],
            )
            db.add(inq)
            inq_list.append((inq, guest))
        db.flush()
        print(f"  {len(inq_list)} inquiries created")

        # ── WhatsApp Conversations + Messages ─────────────────────────────────
        print("Creating conversations + messages...")

        def make_conv(guest_phone, channel="whatsapp", is_open=True, has_ai_draft=False, unread=0):
            g = guests[guest_phone]
            inq_tuple = next(((i, gu) for i, gu in inq_list if gu.id == g.id), None)
            conv = Conversation(
                id=uid(), tenant_id=tid,
                guest_id=g.id,
                inquiry_id=inq_tuple[0].id if inq_tuple else None,
                channel=channel,
                is_open=is_open,
                last_message_at=iso(ago(minutes=10)),
                ai_draft="We'd love to host you! Want me to check availability for those dates?" if has_ai_draft else None,
            )
            db.add(conv)
            return conv

        def msg(conv, direction, body, status=None, created_offset_mins=0,
                ai_drafted=False, ai_confidence=None, sender_name=None):
            state = None
            if direction == "outbound" and status:
                state_map = {
                    "sent":      MessageDeliveryState.SENT,
                    "delivered": MessageDeliveryState.DELIVERED,
                    "read":      MessageDeliveryState.READ,
                    "failed":    MessageDeliveryState.FAILED,
                    "pending":   MessageDeliveryState.PENDING,
                    "queued":    MessageDeliveryState.QUEUED,
                }
                state = state_map.get(status)
            m = Message(
                id=uid(), tenant_id=tid,
                conversation_id=conv.id,
                direction=direction,
                channel=conv.channel,
                body=body,
                sender_id=cid if direction == "outbound" else None,
                sender_name=sender_name or ("Ravi Kumar" if direction == "outbound" else None),
                was_approved=True,
                is_ai_generated=ai_drafted,
                ai_confidence=str(ai_confidence) if ai_confidence else None,
                delivery_state=state,
                delivery_error="Meta API error: rate limit exceeded" if status == "failed" else None,
                created_at=ago(minutes=60 - created_offset_mins),
            )
            db.add(m)
            return m

        # Conv 1 — Priya, WhatsApp, active conversation with read messages
        c1 = make_conv("+919876543210", unread=0)
        msg(c1, "inbound",  "Hi, I wanted to enquire about the Coorg caravan trip for 15th June?", created_offset_mins=0)
        msg(c1, "outbound", "Hello Priya! Yes, we have the Ratha Signature Caravan available for June 15-18. It's our most popular route — Bangalore → Coorg → Madikeri with a private chef and bonfire nights!", status="read", created_offset_mins=5)
        msg(c1, "inbound",  "That sounds amazing! How many people can it accommodate?", created_offset_mins=15)
        msg(c1, "outbound", "The Signature Caravan comfortably fits 4 adults. Are you travelling as a couple or a larger group?", status="read", created_offset_mins=20)
        msg(c1, "inbound",  "Just the two of us — it's our anniversary!", created_offset_mins=30)
        msg(c1, "outbound", "How wonderful! For couples, we actually include a complimentary couples spa session and a candlelit dinner under the stars on night 2. Would you like me to send you the full itinerary and pricing?", status="delivered", created_offset_mins=35)
        c1.last_message_at = iso(ago(minutes=25))

        # Conv 2 — Kiran, WhatsApp, has a failed message + unread
        c2 = make_conv("+917654321098", unread=2)
        msg(c2, "inbound",  "Hi, looking at your caravan packages for July. What's the price for 4 nights?", created_offset_mins=0)
        msg(c2, "outbound", "Hi Kiran! For 4 nights in July, our rate is ₹12,000/night + GST. So approximately ₹57,600 for 4 nights including all meals and butler service.", status="read", created_offset_mins=8)
        msg(c2, "inbound",  "That's a bit over our budget. Can you do ₹10k/night?", created_offset_mins=20)
        msg(c2, "outbound", "I completely understand — let me check if we have any July availability at our off-peak rate.", status="failed", created_offset_mins=25)
        msg(c2, "inbound",  "Hello? Did you check?", created_offset_mins=40)
        msg(c2, "inbound",  "Any update on the pricing?", created_offset_mins=55)
        c2.last_message_at = iso(ago(minutes=5))
        c2.unread_count = 2

        # Conv 3 — Rahul, WhatsApp, AI draft pending approval
        c3 = make_conv("+919765432109", has_ai_draft=True, unread=1)
        msg(c3, "inbound",  "Hey, saw your Instagram. Do you go to Wayanad?", created_offset_mins=0)
        msg(c3, "outbound", "Yes, Wayanad is one of our top routes! Bangalore → Wayanad → Banasura Sagar Dam — 3 nights, truly breathtaking.", status="read", created_offset_mins=5)
        msg(c3, "inbound",  "What dates are available in June?", created_offset_mins=20)
        msg(c3, "outbound",
            "Great news, Rahul! We have availability on June 28 – July 1 for the Wayanad route. The package includes:\n\n• Private chef (Kerala cuisine)\n• Bonfire by the lake\n• Morning nature walk with our guide\n• All transportation\n\nTotal: ₹60,000 for 2 pax. Shall I block this for you?",
            status="sent", created_offset_mins=22, ai_drafted=True, ai_confidence=0.87, sender_name="AI Concierge")
        c3.last_message_at = iso(ago(minutes=38))

        # Conv 4 — Anjali, Instagram, all delivered
        c4 = make_conv("+918899001122", channel="instagram", unread=0)
        msg(c4, "inbound",  "Hi! Is the caravan pet-friendly?", created_offset_mins=0)
        msg(c4, "outbound", "Hi Anjali! Unfortunately our caravans are not pet-friendly at the moment — we have guests with allergies and the confined space makes it difficult. We're working on a pet-friendly fleet for 2027 though!", status="read", created_offset_mins=6)
        msg(c4, "inbound",  "Oh that's a pity. My dog is my travel buddy! Okay what about Hampi — do you cover that?", created_offset_mins=15)
        msg(c4, "outbound", "Hampi is absolutely on our list! The Hampi Heritage Route is one of our most dramatic — ancient ruins, boulder landscapes, the Tungabhadra river. Available August onwards. Want me to share details?", status="delivered", created_offset_mins=20)
        c4.last_message_at = iso(ago(minutes=40))

        # Conv 5 — Vikram, WhatsApp, resolved (booked!)
        c5 = make_conv("+917788990011", is_open=False, unread=0)
        msg(c5, "inbound",  "Hi, I'd like to confirm the June 20-23 Coorg booking.", created_offset_mins=0)
        msg(c5, "outbound", "Wonderful news Vikram! I'm confirming your Ratha Signature Caravan booking for June 20-23, Coorg route. You'll receive a confirmation email shortly with full details and the payment link.", status="read", created_offset_mins=3)
        msg(c5, "inbound",  "Great! One question — can we request vegetarian meals?", created_offset_mins=10)
        msg(c5, "outbound", "Absolutely! I've noted vegetarian preference for your journey. Our chef specialises in South Indian cuisine and will curate a special menu just for you. See you June 20!", status="read", created_offset_mins=12)
        c5.last_message_at = iso(ago(hours=3))
        c5.status = "resolved"
        c5.is_open = False

        db.flush()
        print(f"  5 conversations with messages created")

        # ── Calls with Transcripts + QA Scores ───────────────────────────────
        print("Creating calls + transcripts + scores...")

        # Call 1 — Good call, 86/100 score
        call1_id = uid()
        call1 = Call(
            id=call1_id, tenant_id=tid,
            guest_id=guests["+919876543210"].id,
            inquiry_id=inq_list[0][0].id,
            property_id=prop_id,
            ivr_provider="callerdesk",
            ivr_call_id=f"CD-{uid()[:8]}",
            direction=CallDirection.INBOUND,
            from_number="+919876543210",
            to_number="+918040001234",
            duration_seconds=342,
            started_at=iso(ago(days=2, hours=3)),
            ended_at=iso(ago(days=2, hours=2, minutes=54)),
            transcription_status="done",
            ai_score_status="done",
            recording_status=RecordingStatus.AVAILABLE,
            ai_summary="Priya Sharma enquired about Coorg caravan for anniversary trip June 15-18. Agent presented the Signature Caravan package well, highlighted couples spa. Priya expressed strong interest. Quote sent. High-intent lead.",
            ai_next_action="Follow up in 48h with booking confirmation link.",
            ai_disposition=CallDisposition.HOT,
            ai_score=86.0,
        )
        db.add(call1)

        turns1 = [
            {"speaker": "agent", "t0": 0.0,   "t1": 5.2,  "text": "Good afternoon, thank you for calling Ratha Travels. This is Ravi, how can I make your journey memorable today?"},
            {"speaker": "guest", "t0": 5.5,   "t1": 12.1, "text": "Hi Ravi, I'm Priya. I wanted to enquire about your Coorg caravan package for mid-June."},
            {"speaker": "agent", "t0": 12.4,  "t1": 22.8, "text": "Wonderful choice, Priya! Coorg is absolutely spectacular in June. Could I ask — is this a leisure trip, a special occasion perhaps?"},
            {"speaker": "guest", "t0": 23.1,  "t1": 30.5, "text": "It's our fifth anniversary actually! My husband and I are looking for something really special."},
            {"speaker": "agent", "t0": 30.8,  "t1": 50.2, "text": "Congratulations on your fifth! This is exactly the kind of journey we specialise in. Our Signature Caravan for couples includes a complimentary couples spa, a candlelit dinner under the stars, and on night two our chef prepares a special anniversary menu. The route through Madikeri is breathtaking at this time of year."},
            {"speaker": "guest", "t0": 50.5,  "t1": 60.1, "text": "Oh that sounds absolutely perfect. What's the pricing for 3 nights?"},
            {"speaker": "agent", "t0": 60.4,  "t1": 82.6, "text": "For 3 nights — June 15 to 18 — our Signature Caravan rate is twelve thousand rupees per night, so thirty-six thousand total. That includes all meals, the private chef, bonfire nights, butler service, and local sightseeing. The couples spa and anniversary dinner are complimentary for you."},
            {"speaker": "guest", "t0": 82.9,  "t1": 93.3, "text": "That's actually really reasonable for everything included. I was budgeting around forty to forty-five thousand."},
            {"speaker": "agent", "t0": 93.6,  "t1": 120.0,"text": "Brilliant! And since you're within our peak-season window I'd recommend we tentatively hold the June 15th slot — it does get booked quickly. Can I send you a detailed itinerary on WhatsApp with photos of the caravan and all inclusions? And if you're happy, I can send the booking link directly."},
            {"speaker": "guest", "t0": 120.3, "t1": 132.7,"text": "Yes please, that would be great. My WhatsApp is the same number I called from."},
            {"speaker": "agent", "t0": 133.0, "t1": 155.4,"text": "Perfect. I'll send that across in the next five minutes. And Priya — happy early anniversary! I'm confident this is going to be a journey you'll both treasure. Is there anything else about dietary preferences or any special requests you'd like to add?"},
            {"speaker": "guest", "t0": 155.7, "t1": 168.1,"text": "We're both vegetarian. And maybe something for stargazing? We love astronomy."},
            {"speaker": "agent", "t0": 168.4, "t1": 195.2,"text": "Noted on the vegetarian menu — our chef is excellent with that. And stargazing — wonderful! Coorg at that elevation has minimal light pollution. I'll arrange our portable telescope on night one. Consider it done."},
            {"speaker": "guest", "t0": 195.5, "t1": 205.0,"text": "Wow, you've thought of everything! Looking forward to the WhatsApp message."},
            {"speaker": "agent", "t0": 205.3, "t1": 225.8,"text": "Thank you Priya! Sending it right now. And once you review, just reply to that message to confirm your slot. Have a wonderful afternoon!"},
        ]
        transcript1 = Transcript(
            id=uid(), tenant_id=tid, call_id=call1_id,
            provider="deepgram", language="en", redacted=False,
            turns=json.dumps(turns1),
            raw_text=" ".join(t["text"] for t in turns1),
        )
        db.add(transcript1)

        if rubric:
            score1 = CallScore(
                id=uid(), tenant_id=tid, call_id=call1_id, rubric_id=rubric.id,
                rubric_snapshot=rubric.criteria,
                total_score=86, max_score=100, percentage=86,
                model_used="claude-3-5-haiku-20241022",
                ai_confidence=0.91,
                criterion_scores=[
                    {"id": "greeting",  "score": 8,  "max_score": 8,  "evidence_span": "Good afternoon, thank you for calling Ratha Travels. This is Ravi — warm, brand-led opener."},
                    {"id": "discovery", "score": 10, "max_score": 12, "evidence_span": "Asked about occasion and group size well. Could have probed accommodation preferences."},
                    {"id": "expertise", "score": 11, "max_score": 12, "evidence_span": "Detailed Coorg route knowledge. Mentioned Madikeri, elevation, light pollution for stargazing — excellent."},
                    {"id": "pricing",   "score": 10, "max_score": 10, "evidence_span": "Clear breakdown: 12k/night, 36k total, inclusions listed explicitly."},
                    {"id": "empathy",   "score": 9,  "max_score": 10, "evidence_span": "Early anniversary acknowledgement was genuine. Personalised the spa and telescope add-ons proactively."},
                    {"id": "objection", "score": 8,  "max_score": 10, "evidence_span": "No strong objections raised. Agent preempted price concern with value framing."},
                    {"id": "next_step", "score": 12, "max_score": 12, "evidence_span": "Committed to WhatsApp itinerary in 5 minutes + booking link. Clear close."},
                    {"id": "close",     "score": 10, "max_score": 12, "evidence_span": "Offered to hold June 15 slot — urgency created. Did not get explicit commitment in call."},
                    {"id": "pii",       "score": 8,  "max_score": 8,  "evidence_span": "No PII leakage detected."},
                    {"id": "tone",      "score": 0,  "max_score": 6,  "evidence_span": "Professional throughout. Warm without being obsequious."},
                ],
            )
            db.add(score1)

        # Call 2 — Average call, 58/100
        call2_id = uid()
        call2 = Call(
            id=call2_id, tenant_id=tid,
            guest_id=guests["+917654321098"].id,
            inquiry_id=inq_list[1][0].id,
            property_id=prop_id,
            ivr_provider="callerdesk",
            ivr_call_id=f"CD-{uid()[:8]}",
            direction=CallDirection.INBOUND,
            from_number="+917654321098",
            to_number="+918040001234",
            duration_seconds=218,
            started_at=iso(ago(days=1, hours=5)),
            ended_at=iso(ago(days=1, hours=4, minutes=52)),
            transcription_status="done",
            ai_score_status="done",
            recording_status=RecordingStatus.AVAILABLE,
            ai_summary="Kiran Reddy called about July pricing. Agent struggled with budget objection — did not offer off-peak rate or alternative dates proactively. Lead went cold. Follow-up needed.",
            ai_next_action="Call back with off-peak July rates and tailored package.",
            ai_disposition=CallDisposition.CALLBACK,
            ai_score=58.0,
        )
        db.add(call2)

        turns2 = [
            {"speaker": "agent", "t0": 0.0,  "t1": 5.1,  "text": "Hello, Ratha Travels, how can I help?"},
            {"speaker": "guest", "t0": 5.4,  "t1": 15.8, "text": "Hi I'm Kiran, calling from Hyderabad. I saw your packages online — what's the price for 4 nights in July?"},
            {"speaker": "agent", "t0": 16.1, "t1": 28.3, "text": "Our rate is twelve thousand rupees per night. So for 4 nights that would be forty-eight thousand plus GST."},
            {"speaker": "guest", "t0": 28.6, "t1": 40.2, "text": "That's actually more than I was expecting. I was thinking more like forty thousand total. Is there any flexibility?"},
            {"speaker": "agent", "t0": 40.5, "t1": 52.7, "text": "Hmm, the rates are standard. I'm not sure if we can do anything different. Let me check... actually I'd have to check with my manager."},
            {"speaker": "guest", "t0": 53.0, "t1": 65.1, "text": "Okay. Also what's included in the forty-eight thousand?"},
            {"speaker": "agent", "t0": 65.4, "t1": 88.9, "text": "Meals are included. The caravan. And driver. Bonfire too I think. Let me check the exact inclusions — can I call you back?"},
            {"speaker": "guest", "t0": 89.2, "t1": 97.3, "text": "Sure, but I mean can you not just tell me now? I'm trying to decide today."},
            {"speaker": "agent", "t0": 97.6, "t1": 115.4,"text": "Yes yes — so all meals, private chef, bonfire, butler, local transport. It's a full package. The rate is fixed though, twelve thousand per night."},
            {"speaker": "guest", "t0": 115.7, "t1": 128.2,"text": "Hmm okay. I'll think about it and maybe call back. Thanks."},
            {"speaker": "agent", "t0": 128.5, "t1": 135.0,"text": "Sure, thanks for calling!"},
        ]
        transcript2 = Transcript(
            id=uid(), tenant_id=tid, call_id=call2_id,
            provider="deepgram", language="en",
            turns=json.dumps(turns2),
            raw_text=" ".join(t["text"] for t in turns2),
        )
        db.add(transcript2)

        if rubric:
            score2 = CallScore(
                id=uid(), tenant_id=tid, call_id=call2_id, rubric_id=rubric.id,
                rubric_snapshot=rubric.criteria,
                total_score=58, max_score=100, percentage=58,
                model_used="claude-3-5-haiku-20241022",
                ai_confidence=0.88,
                criterion_scores=[
                    {"id": "greeting",  "score": 4,  "max_score": 8,  "evidence_span": "Hello, Ratha Travels, how can I help? — functional but no warmth or brand identity."},
                    {"id": "discovery", "score": 4,  "max_score": 12, "evidence_span": "Did not ask about occasion, group size, or preferences. Jumped straight to price."},
                    {"id": "expertise", "score": 6,  "max_score": 12, "evidence_span": "Vague on inclusions — said 'I think' for bonfire. Had to look things up mid-call."},
                    {"id": "pricing",   "score": 7,  "max_score": 10, "evidence_span": "Gave correct total but did not mention GST implications or off-peak alternatives."},
                    {"id": "empathy",   "score": 5,  "max_score": 10, "evidence_span": "No empathy on budget concern. Did not acknowledge frustration."},
                    {"id": "objection", "score": 4,  "max_score": 10, "evidence_span": "Budget objection met with 'I'd have to check with my manager' — weak handling."},
                    {"id": "next_step", "score": 8,  "max_score": 12, "evidence_span": "Offered to call back, but no firm time commitment. Guest ended conversation."},
                    {"id": "close",     "score": 4,  "max_score": 12, "evidence_span": "No attempt to close. Guest left with 'I'll think about it'."},
                    {"id": "pii",       "score": 8,  "max_score": 8,  "evidence_span": "No PII issues detected."},
                    {"id": "tone",      "score": 8,  "max_score": 6,  "evidence_span": "Tone was okay but agent sounded uncertain and underprepared."},
                ],
            )
            db.add(score2)

        # Call 3 — Transcription in progress (no score yet)
        call3_id = uid()
        call3 = Call(
            id=call3_id, tenant_id=tid,
            guest_id=guests["+918899001122"].id,
            ivr_provider="callerdesk",
            ivr_call_id=f"CD-{uid()[:8]}",
            direction=CallDirection.INBOUND,
            from_number="+918899001122",
            to_number="+918040001234",
            duration_seconds=185,
            started_at=iso(ago(hours=1)),
            ended_at=iso(ago(minutes=50)),
            transcription_status="queued",
            ai_score_status="pending",
            recording_status=RecordingStatus.AVAILABLE,
        )
        db.add(call3)

        # Call 4 — Outbound, short, failed transcription
        call4_id = uid()
        call4 = Call(
            id=call4_id, tenant_id=tid,
            guest_id=guests["+916677889900"].id,
            ivr_provider="callerdesk",
            ivr_call_id=f"CD-{uid()[:8]}",
            direction=CallDirection.OUTBOUND,
            from_number="+918040001234",
            to_number="+916677889900",
            duration_seconds=42,
            started_at=iso(ago(days=3)),
            ended_at=iso(ago(days=3)),
            transcription_status="failed",
            ai_score_status="pending",
            recording_status=RecordingStatus.PERMANENTLY_MISSING,
        )
        db.add(call4)

        db.flush()
        print(f"  4 calls + 2 transcripts + 2 QA scores created")

        # ── Saved Replies ──────────────────────────────────────────────────────
        print("Creating saved replies...")
        replies = [
            {"title": "Welcome + enquiry ack",     "body": "Hi {{guest.name}}! Thanks for reaching out to Ratha Travels. We'd love to craft the perfect journey for you. Could you tell us your preferred dates and destination?"},
            {"title": "Rate quote",                 "body": "Hi {{guest.name}}, here's our rate for {{property.name}}: ₹12,000/night (all-inclusive). For {{check_in}} – {{check_out}} that works out to ₹{{rate}}. This includes private chef, bonfire, butler & all meals. Shall I hold these dates?"},
            {"title": "Check-in reminder",          "body": "Hi {{guest.name}}! Just a warm reminder — your Ratha journey begins tomorrow, {{check_in}}. Our team will be at the pickup point by 10 AM. So excited to welcome you!"},
            {"title": "Following up on enquiry",    "body": "Hi {{guest.name}}, following up on your enquiry from earlier. Did you get a chance to review the itinerary I sent? Happy to answer any questions or customise it further!"},
            {"title": "Dates available — confirm?", "body": "Great news {{guest.name}}! {{check_in}} – {{check_out}} is available for the {{property.name}} route. To confirm your booking I'll need a 30% advance. Shall I send the payment link?"},
            {"title": "Apology + checking",         "body": "I sincerely apologise for the delay {{guest.name}}. Let me check on this right away and get back to you within 30 minutes. Your experience is our priority."},
            {"title": "Suggest alternative dates",  "body": "Hi {{guest.name}}, unfortunately {{check_in}} is fully booked. However, we have availability on the weekend of [DATES]. Would that work for your group?"},
            {"title": "Post-trip thank you",        "body": "It was an absolute pleasure hosting you {{guest.name}}! We hope the journey was everything you dreamed of. We'd love a review if you have a moment — it means the world to us 🌟"},
        ]

        for r in replies:
            existing = db.query(SavedReply).filter_by(
                tenant_id=tid, title=r["title"]
            ).first()
            if not existing:
                db.add(SavedReply(
                    id=uid(), tenant_id=tid, created_by=oid,
                    user_id=None,   # tenant-shared
                    title=r["title"], body=r["body"], language="en",
                    usage_count=0,
                ))
        db.flush()
        print(f"  {len(replies)} saved replies created")

        db.commit()

        print("""
====================================================
  Demo data seeded successfully!

  Login: sharath@ratha.in / ratha2026

  What you can test:
  - Inbox      : 5 conversations with read/delivered/failed messages
  - Inquiries  : 8 cards across all stages (K1-K6)
  - Calls      : 4 calls, 2 with full transcripts + QA scores (C1, C3)
  - Saved replies: 8 templates, type / in composer (W3)
  - Status icons  : see read/delivered/failed on WhatsApp bubbles (W20)
  - Retry button  : Kiran's conversation has a failed message (W23)
  - Age stripes   : Kanban shows green/yellow/orange/red stripes (K5)
  - SLA badge     : Priya's new inquiry is >15min = breach (K6)
  - Unassigned    : Rahul's inquiry has no assignee → red chip (K4)
====================================================
""")

    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        print(f"Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
