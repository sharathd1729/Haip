"""
O2 + O9 — Sample-data service.

seed_sample_data()         — seeds 30 guests, 20 conversations, 10 calls (full batch)
seed_welcome_conversation() — seeds exactly 1 welcome conversation (O9 single-seed)
wipe_sample_data()         — deletes all is_sample rows for the tenant
auto_wipe_on_real_inbound() — called when first real inbound arrives; wipes if sample present

All sample rows carry is_sample=True so they're easy to filter and wipe.
Data is deterministically seeded so the same tenant always gets the same names / numbers.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection, MessageDeliveryState
from app.models.call import Call, CallDirection, CallDisposition, RecordingStatus
from app.models.inquiry import Inquiry
from app.models.base import gen_uuid

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Realistic sample data (Indian hospitality context)
# ---------------------------------------------------------------------------

_GUEST_NAMES = [
    "Priya Sharma", "Rahul Gupta", "Anita Patel", "Vikram Singh", "Meera Nair",
    "Arjun Mehta", "Kavita Reddy", "Sanjay Joshi", "Neha Iyer", "Rohit Verma",
    "Deepika Rao", "Aditya Kumar", "Sunita Banerjee", "Kiran Desai", "Ramesh Pillai",
    "Pooja Agarwal", "Mohit Saxena", "Ritu Malhotra", "Suresh Nambiar", "Geeta Mishra",
    "Harish Tripathi", "Lakshmi Srinivasan", "Vivek Bose", "Swati Kulkarni", "Dinesh Rathi",
    "Archana Tiwari", "Manish Dubey", "Shilpa Ghosh", "Sushil Choudhary", "Rekha Pandey",
]

# Indian mobile numbers (91 prefix, realistic patterns)
_PHONE_BASE = [
    "+919876543210", "+919845001234", "+919812345678", "+919901234567", "+919934567890",
    "+919765432100", "+917891234560", "+919123456789", "+918976543210", "+919087654321",
    "+919234567891", "+919345678902", "+919456789013", "+919567890124", "+919678901235",
    "+919789012346", "+919890123457", "+919912345678", "+919011234567", "+919122345678",
    "+919233456789", "+919344567890", "+919455678901", "+919566789012", "+919677890123",
    "+919788901234", "+919899012345", "+919910123456", "+919021234567", "+919132345678",
]

_INQUIRY_SUBJECTS = [
    "Booking inquiry for weekend stay",
    "Availability check for Diwali weekend",
    "Corporate block booking — 5 rooms",
    "Honeymoon package enquiry",
    "Family trip 4 adults 2 children",
    "Anniversary stay — special arrangements?",
    "Group booking — wedding party 12 guests",
    "Long-stay discount query",
    "Pool villa availability",
    "Early check-in request",
    "Pet-friendly room availability",
    "Airport pickup arrangement",
    "Spa package add-on enquiry",
    "Last-minute booking for tonight",
    "Repeat guest — loyalty benefits",
    "Conference room booking",
    "Government rate for official visit",
    "International guest USD payment query",
    "WhatsApp inquiry — room tour video",
    "Instagram DM — price enquiry",
]

_WA_MESSAGES_INBOUND = [
    "Hi, I want to book a room for this weekend. What's available?",
    "Namaste! Do you have rooms available for Diwali?",
    "Hello, I need 3 rooms for a family reunion next month",
    "Can you send me photos of the pool villa?",
    "What's your best rate for a 3-night stay?",
    "Haan, is the pool heated? We're coming in December",
    "Do you have a family suite? 2 adults + 2 kids",
    "What time is check-in? We're arriving at 7am",
    "Can we do early check-in? Our flight lands at 6:30am",
    "Is breakfast included? What's the menu like?",
    "Do you accept UPI payment?",
    "Kya aapke paas parking hai? We have a car",
    "Can you arrange airport pickup from T2?",
    "Do you have vegan food options?",
    "I saw your property on MakeMyTrip. What's direct rate?",
    "Is there a swimming pool? What are the timings?",
    "We need a pet-friendly room. Do you allow dogs?",
    "Can I get a late checkout till 2pm?",
    "What's the cancellation policy?",
    "I stayed with you last year — Sharma family. Do you remember us?",
]

_AI_DRAFT_REPLIES = [
    "Namaste! 🙏 Thank you for reaching out. We have beautiful rooms available for your dates. Our Deluxe Room starts at ₹4,500/night. Shall I check specific availability?",
    "Hello! We'd love to host you for Diwali. Our property looks stunning with the festival decorations! Let me share available options.",
    "Thank you for your interest in a family reunion! We can accommodate up to 12 guests comfortably. Let me put together a special package for you.",
    "Of course! The pool villa has a private plunge pool, king-size bed, and garden views. Let me send you our full property video.",
    "Our best rate for 3 nights is ₹12,500 (₹4,167/night) including breakfast. This includes a complimentary sunset cruise on day 2! 🌅",
    "Yes! Our pool is heated to 28°C year-round. Perfect for a December stay. The pool timings are 7am–9pm.",
    "We have a gorgeous Family Suite with a connecting room — perfect for 2+2. It comes with a kids' corner and a private terrace.",
    "Check-in is 2pm, but we can arrange early check-in from 9am for a small charge of ₹500. Shall I block it for you?",
    "Absolutely! Early check-in can be arranged. We'll have your room ready by 7am. No extra charge for our valued guests! 🌟",
    "Breakfast is included — we serve a full Indian + Continental buffet from 7-10:30am. Our chef's special is Masala Dosa and Eggs Benedict!",
    "Yes, we accept UPI, credit cards, and all major payment methods. We also offer EMI on stays above ₹10,000.",
    "We have a dedicated parking area with CCTV — free for all guests! Space for up to 15 cars.",
    "Airport pickup available from all Mumbai terminals! ₹800 for a sedan, ₹1,200 for an SUV. I'll confirm the driver details after booking.",
    "Absolutely! Our kitchen offers a full vegan menu. Just mention it at booking and we'll arrange a special setup for your meals.",
    "Our direct rate is ₹500 less than MakeMyTrip, plus you get free airport pickup and room upgrade! Book directly to save more. 😊",
]

_CALL_SUMMARIES = [
    "Caller enquired about room availability for next weekend. Quoted ₹4,500/night for Deluxe Room. Interested but wanted to compare options. Suggested sending WhatsApp message with photos.",
    "Repeat guest calling to book anniversary package. Previous stay in March was very satisfactory. Booked Superior Room for 2 nights with complimentary spa voucher.",
    "Corporate inquiry for 10 rooms for off-site training. Discussed corporate rate (15% discount). Client to send RFP over email. Follow-up call scheduled for Thursday.",
    "Guest called to complain about noisy AC in room 204 during last stay. Apologized sincerely. Offered complimentary upgrade on next visit. Issue logged for maintenance.",
    "Family of 4 booking for summer holidays in June. Confirmed connecting rooms + kids' pool. Total booking value ₹52,000 for 4 nights. Sent WhatsApp confirmation.",
    "Caller asking about wedding venue capacity. Banquet hall can host 200 guests. F&B quotation sent via email. Site visit scheduled for Sunday 11am.",
    "International guest (US number) enquiring about USD rates. Explained payment options including international card. Quoted USD 58/night. Positive response.",
    "Last-minute booking request — wanted room tonight. Check if housekeeping ready by 4pm. Confirmed booking. Guest checking in at 6pm. High CSAT potential.",
    "Travel agent calling for bulk inventory allocation for festive season. Discussed allotment contract terms. Agreement on 5 rooms allotment. Paperwork to follow.",
    "Guest called to modify existing booking — change of dates from Nov 12 to Nov 15. Confirmed modification. No charge. Guest very appreciative of flexibility.",
]

_TRANSCRIPT_TURNS: list[list[dict[str, Any]]] = [
    [
        {"speaker": "agent", "text": "Good afternoon, thank you for calling The Grand Villa. This is Priya speaking. How may I help you?", "start": 0.0, "end": 4.5},
        {"speaker": "guest", "text": "Hi, yes I'm calling to check room availability for next weekend, the 10th and 11th.", "start": 5.2, "end": 9.8},
        {"speaker": "agent", "text": "Of course! Let me check for you. That would be Friday and Saturday nights. We do have availability. Are you looking for our Deluxe Room or would you prefer something larger?", "start": 10.5, "end": 18.2},
        {"speaker": "guest", "text": "What's the difference? And what's the price?", "start": 19.0, "end": 21.3},
        {"speaker": "agent", "text": "The Deluxe Room is on the garden-facing side, ₹4,500 per night. Our Pool Villa is the premium option at ₹9,800 per night with a private pool. Both include breakfast.", "start": 22.0, "end": 31.5},
        {"speaker": "guest", "text": "Hmm, the Deluxe sounds good. Is breakfast a proper buffet?", "start": 32.1, "end": 35.4},
        {"speaker": "agent", "text": "Yes sir, full Indian and Continental buffet from 7 to 10:30. Our chef is known for the masala dosa and eggs Benedict!", "start": 36.0, "end": 42.8},
        {"speaker": "guest", "text": "Sounds great. I'll discuss with my wife and call back. What's the best number?", "start": 43.5, "end": 47.2},
        {"speaker": "agent", "text": "You can reach us on this number anytime. Or just WhatsApp us — we reply faster there. May I have your name for reference?", "start": 48.0, "end": 54.5},
        {"speaker": "guest", "text": "Sure, it's Vikram. Vikram Singh.", "start": 55.2, "end": 57.1},
        {"speaker": "agent", "text": "Perfect, Vikram. I'll note this. We'll hold availability for you until tomorrow evening. Have a lovely day!", "start": 58.0, "end": 64.3},
    ],
    [
        {"speaker": "agent", "text": "The Grand Villa, good morning, Rahul speaking.", "start": 0.0, "end": 3.2},
        {"speaker": "guest", "text": "Hello, we're planning a small family trip — two adults and two kids. Do you have connecting rooms?", "start": 4.0, "end": 9.5},
        {"speaker": "agent", "text": "Absolutely! We have a beautiful Family Suite with a connecting room. Perfect for two adults and children up to 12. There's also a dedicated kids' corner in the suite.", "start": 10.2, "end": 20.8},
        {"speaker": "guest", "text": "Oh that sounds perfect. What dates do you have availability?", "start": 21.5, "end": 24.2},
        {"speaker": "agent", "text": "We have availability through most of December. When were you thinking of coming?", "start": 25.0, "end": 29.5},
        {"speaker": "guest", "text": "23rd to 27th December — Christmas week.", "start": 30.2, "end": 33.1},
        {"speaker": "agent", "text": "Let me check... Yes! The Family Suite is available for Christmas. I should mention we do a special Christmas program — carol evenings, bonfire, and a Christmas breakfast on the 25th. Kids love it.", "start": 34.0, "end": 46.5},
        {"speaker": "guest", "text": "Wow, the kids will love that! How much for 4 nights?", "start": 47.2, "end": 50.1},
        {"speaker": "agent", "text": "Family Suite for 4 nights during Christmas week is ₹36,000 total including all meals and the Christmas program. That's ₹9,000 per night. We can hold it with a 20% advance.", "start": 51.0, "end": 63.7},
        {"speaker": "guest", "text": "Okay, let me discuss with my husband and get back to you today.", "start": 64.5, "end": 68.2},
        {"speaker": "agent", "text": "Of course! Please call or WhatsApp — we'll hold it till 6pm today for you. Looking forward to hosting your family for Christmas!", "start": 69.0, "end": 77.5},
    ],
]


def _det_random(tenant_id: str, seed_salt: str = "") -> random.Random:
    """Create a deterministic random seeded from tenant_id."""
    seed = int(hashlib.md5(f"{tenant_id}{seed_salt}".encode()).hexdigest(), 16) % (2**31)
    return random.Random(seed)


def _now_minus(days: float = 0, hours: float = 0, minutes: float = 0) -> str:
    """Return an ISO datetime string offset from now."""
    dt = datetime.now(timezone.utc) - timedelta(days=days, hours=hours, minutes=minutes)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def seed_sample_data(db: Session, tenant_id: str) -> dict[str, int]:
    """
    Seed 30 fake guests, 20 conversations (WhatsApp + Instagram), 10 calls.
    Returns counts of rows created.
    """
    rng = _det_random(tenant_id, "seed_v1")

    # ── Guests ──────────────────────────────────────────────────────────────
    guests: list[Guest] = []
    for i, (name, phone) in enumerate(zip(_GUEST_NAMES, _PHONE_BASE)):
        g = Guest(
            id=gen_uuid(),
            tenant_id=tenant_id,
            name=name,
            phone=phone,
            email=f"{name.lower().replace(' ', '.')}@example.com",
            city=rng.choice(["Mumbai", "Delhi", "Bangalore", "Chennai", "Pune", "Hyderabad", "Kolkata"]),
            language_pref=rng.choice(["en", "hi", "en", "en", "hi"]),
            is_sample=True,
            marketing_consent=rng.choice([True, False]),
            recording_consent=True,
        )
        db.add(g)
        guests.append(g)

    db.flush()  # get IDs assigned

    # ── Conversations (WhatsApp + Instagram) ────────────────────────────────
    channel_choices = [ChannelType.WHATSAPP] * 15 + [ChannelType.INSTAGRAM] * 5
    convs: list[Conversation] = []
    for i in range(20):
        guest = guests[i % len(guests)]
        channel = channel_choices[i]
        days_ago = rng.uniform(0.5, 14)

        conv = Conversation(
            id=gen_uuid(),
            tenant_id=tenant_id,
            guest_id=guest.id,
            channel=channel,
            is_open=i < 12,  # first 12 open, rest closed
            last_message_at=_now_minus(days=days_ago, hours=rng.uniform(0, 8)),
            is_sample=True,
            ai_mode="shadow",
        )
        db.add(conv)
        convs.append(conv)

        # Add 2-6 messages per conversation
        num_msgs = rng.randint(2, 6)
        for j in range(num_msgs):
            direction = MessageDirection.INBOUND if j % 2 == 0 else MessageDirection.OUTBOUND
            body = (
                rng.choice(_WA_MESSAGES_INBOUND)
                if direction == MessageDirection.INBOUND
                else rng.choice(_AI_DRAFT_REPLIES)
            )
            msg_age = days_ago - j * 0.01  # slightly earlier messages come earlier

            msg = Message(
                id=gen_uuid(),
                tenant_id=tenant_id,
                conversation_id=conv.id,
                direction=direction,
                channel=channel,
                body=body,
                is_ai_generated=(direction == MessageDirection.OUTBOUND and j > 0),
                was_approved=(True if direction == MessageDirection.OUTBOUND else None),
                delivery_state=(MessageDeliveryState.READ if direction == MessageDirection.OUTBOUND else None),
                is_sample=True,
            )
            db.add(msg)

        # Add AI draft on open conversations
        if i < 12:
            draft_msg = Message(
                id=gen_uuid(),
                tenant_id=tenant_id,
                conversation_id=conv.id,
                direction=MessageDirection.OUTBOUND,
                channel=channel,
                body=rng.choice(_AI_DRAFT_REPLIES),
                is_ai_generated=True,
                was_approved=None,  # pending approval
                delivery_state=None,
                is_sample=True,
            )
            db.add(draft_msg)

    db.flush()

    # ── Calls ────────────────────────────────────────────────────────────────
    for i in range(10):
        guest = guests[i % len(guests)]
        days_ago = rng.uniform(1, 21)
        duration = rng.randint(90, 480)
        transcript_idx = i % len(_TRANSCRIPT_TURNS)
        summary_idx = i % len(_CALL_SUMMARIES)
        disposition = rng.choice([CallDisposition.HOT, CallDisposition.QUOTED, CallDisposition.BOOKED,
                                  CallDisposition.LOST, CallDisposition.CALLBACK])

        call = Call(
            id=gen_uuid(),
            tenant_id=tenant_id,
            guest_id=guest.id,
            ivr_provider="sample",
            ivr_call_id=f"SAMPLE-{tenant_id[:8]}-{i:03d}",
            direction=CallDirection.INBOUND,
            from_number=guest.phone,
            to_number="+918000000001",
            duration_seconds=duration,
            started_at=_now_minus(days=days_ago),
            ended_at=_now_minus(days=days_ago, minutes=-duration / 60),
            recording_status=RecordingStatus.AVAILABLE,
            transcription_status="done",
            ai_score_status="done",
            transcript_json=_TRANSCRIPT_TURNS[transcript_idx],
            ai_summary=_CALL_SUMMARIES[summary_idx],
            ai_disposition=disposition,
            ai_score=rng.uniform(60, 95),
            is_sample=True,
        )
        db.add(call)

    db.commit()

    return {"guests": len(guests), "conversations": len(convs), "calls": 10}


def seed_welcome_conversation(db: Session, tenant_id: str) -> str:
    """
    O9: Seed exactly 1 welcome conversation. Returns the conversation ID.
    Used when the tenant completes onboarding without sample data.
    """
    # Synthetic guest
    g = Guest(
        id=gen_uuid(),
        tenant_id=tenant_id,
        name="HAIP Team",
        phone="+919999900000",
        email="welcome@haip.app",
        is_sample=True,
    )
    db.add(g)
    db.flush()

    conv = Conversation(
        id=gen_uuid(),
        tenant_id=tenant_id,
        guest_id=g.id,
        channel=ChannelType.WHATSAPP,
        is_open=True,
        is_sample=True,
        ai_mode="off",
    )
    db.add(conv)
    db.flush()

    messages = [
        (MessageDirection.INBOUND, "👋 Welcome to HAIP! This is a sample conversation so you can see how the inbox works."),
        (MessageDirection.INBOUND, "When a guest messages you on WhatsApp, their conversation will appear here — just like this one."),
        (MessageDirection.INBOUND, "You can reply, see AI-drafted responses, view guest history, and manage inquiries — all from this inbox."),
        (MessageDirection.OUTBOUND, "This is what your reply will look like. The AI will draft responses for you; you approve before sending. ✅"),
    ]

    for direction, body in messages:
        msg = Message(
            id=gen_uuid(),
            tenant_id=tenant_id,
            conversation_id=conv.id,
            direction=direction,
            channel=ChannelType.WHATSAPP,
            body=body,
            is_ai_generated=(direction == MessageDirection.OUTBOUND),
            was_approved=(True if direction == MessageDirection.OUTBOUND else None),
            delivery_state=(MessageDeliveryState.READ if direction == MessageDirection.OUTBOUND else None),
            is_sample=True,
        )
        db.add(msg)

    db.commit()
    log.info("sample_welcome_conversation_seeded", tenant_id=tenant_id, conv_id=conv.id)
    return conv.id


def wipe_sample_data(db: Session, tenant_id: str) -> dict[str, int]:
    """
    Delete all is_sample rows for the tenant.
    Cascades: Messages → Conversations, Calls, Guests.
    Returns counts of deleted rows.
    """
    from sqlalchemy import delete

    # Messages (FK child of Conversation)
    msgs_del = db.execute(
        delete(Message).where(
            Message.tenant_id == tenant_id,
            Message.is_sample == True,  # noqa: E712
        )
    ).rowcount

    convs_del = db.execute(
        delete(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.is_sample == True,  # noqa: E712
        )
    ).rowcount

    calls_del = db.execute(
        delete(Call).where(
            Call.tenant_id == tenant_id,
            Call.is_sample == True,  # noqa: E712
        )
    ).rowcount

    guests_del = db.execute(
        delete(Guest).where(
            Guest.tenant_id == tenant_id,
            Guest.is_sample == True,  # noqa: E712
        )
    ).rowcount

    db.commit()

    log.info(
        "sample_data_wiped",
        tenant_id=tenant_id,
        guests=guests_del, conversations=convs_del, calls=calls_del, messages=msgs_del,
    )
    return {"guests": guests_del, "conversations": convs_del, "calls": calls_del, "messages": msgs_del}


def has_sample_data(db: Session, tenant_id: str) -> bool:
    """Return True if any sample rows exist for this tenant."""
    return db.query(Guest).filter_by(tenant_id=tenant_id, is_sample=True).first() is not None


def auto_wipe_on_real_inbound(db: Session, tenant_id: str) -> bool:
    """
    Called when a real inbound message arrives for the first time.
    Wipes sample data if present. Returns True if wiped.
    """
    if not has_sample_data(db, tenant_id):
        return False
    wipe_sample_data(db, tenant_id)
    log.info("sample_data_auto_wiped_on_real_inbound", tenant_id=tenant_id)
    return True
