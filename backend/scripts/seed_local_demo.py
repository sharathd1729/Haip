"""Seed a made-up demo business ("Wanderwheel Caravans", slug demo-caravans) into the LOCAL database.

Refuses to run unless DATABASE_URL points at localhost and ENVIRONMENT=development. Re-running wipes the demo tenant's rows
(only that tenant) and recreates them. No Celery task or LLM call is made. Photos/clips go through the normal storage
functions, so EXTERNAL_SERVICES=fake must be on (they then land in LOCAL_DATA_DIR, never in real S3/R2).

    cd backend && python scripts/seed_local_demo.py          # DEMO_PASSWORD=... to choose the password
"""
import io
import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def assert_local_target(database_url: str, environment: str) -> None:
    """Raise unless the target is a local development database. Never seed demo data anywhere else."""
    if environment != "development":
        raise SystemExit(f"Refusing to seed: ENVIRONMENT is {environment!r}, not 'development'.")
    host = (urlparse(database_url or "").hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"Refusing to seed: database host {host or '(none)'!r} is not localhost.")


def uid() -> str:
    return str(uuid.uuid4())


NOW = datetime.now(timezone.utc)


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


def wipe(db, tenant_id: str) -> None:
    """Delete every row of this one tenant. FK triggers are paused for this transaction only (local superuser)."""
    from sqlalchemy import text
    tables = db.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public' "
        "AND column_name IN ('tenant_id','workspace_id') AND table_name <> 'tenants'")).all()
    db.execute(text("SET LOCAL session_replication_role = replica"))
    for table, col in tables:
        db.execute(text(f'DELETE FROM "{table}" WHERE "{col}" = :t'), {"t": tenant_id})
    db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    db.commit()


def media_ready() -> str:
    """'' when photos can be stored safely (fake storage on), else the reason they are skipped."""
    from app.core import fake_services
    if not fake_services.enabled():
        return "EXTERNAL_SERVICES is not 'fake' (would write to real S3/R2)"
    fake_services.install()
    return ""


def make_photo(caption: str, top, bottom) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    w, h = 1080, 1350
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        px.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    try:
        font = ImageFont.truetype("arial.ttf", 72)
    except OSError:
        font = ImageFont.load_default()
    px.rectangle([0, h - 220, w, h], fill=(0, 0, 0))
    px.text((60, h - 170), caption, fill=(255, 255, 255), font=font)
    px.text((60, 60), "DEMO", fill=(255, 255, 255), font=font)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def make_clip(jpegs: list[bytes]) -> bytes:
    """~6 s silent mp4 slideshow from 3 images."""
    with tempfile.TemporaryDirectory() as tmp:
        for i, b in enumerate(jpegs):
            with open(os.path.join(tmp, f"f{i}.jpg"), "wb") as fh:
                fh.write(b)
        out = os.path.join(tmp, "clip.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", "0.5", "-i", os.path.join(tmp, "f%d.jpg"),
                        "-vf", "scale=720:900,format=yuv420p", "-r", "24", "-c:v", "libx264", "-t", "6", out],
                       check=True, timeout=120)
        with open(out, "rb") as fh:
            return fh.read()


def run() -> None:
    from app.core.config import settings
    assert_local_target(settings.DATABASE_URL, settings.ENVIRONMENT)

    import app.models  # noqa: F401  registers every model
    import app.workers.tasks.instagram_insights_poll as igp  # inline models, created by the API's create_all
    from app.core.database import Base, SessionLocal, engine
    from app.core.encryption import encrypt_credentials
    from app.core.security import get_password_hash
    from app.models.ad_entity import AdEntity
    from app.models.ad_metrics import AdMetric
    from app.models.call import Call, CallDirection, CallDisposition
    from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
    from app.models.guest import Guest
    from app.models.guest_identity import GuestIdentity
    from app.models.inquiry import Inquiry, InquirySource, InquiryStage, LostReason
    from app.models.integration import Integration
    from app.models.lead_attribution import LeadAttribution
    from app.models.marketing import InstagramPostMetricDaily
    from app.models.module import Module, WorkspaceModule
    from app.models.pipeline_stage import PipelineStage
    from app.models.property import Property, RatePlan
    from app.models.score import CallScore, Rubric
    from app.models.stay_finance import StayDeposit, StayInstalment, StayPayment
    from app.models.property import Stay
    from app.models.tenant import Tenant
    from app.models.transcript import Transcript
    from app.models.user import User, UserRole
    from app.services import business_data_service as bds
    from app.services.authz_service import seed_default_capabilities
    from app.services.pipeline_stage_service import seed_default_pipeline_stages
    from app.services.workspace_context import provision_default_modules
    import _demo_data as D

    random.seed(42)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    old = db.query(Tenant).filter_by(slug=D.SLUG).first()
    if old:
        print(f"Wiping existing demo tenant {old.id} ...")
        wipe(db, old.id)

    # ── tenant + users ────────────────────────────────────────────────────────────────────────────────────────
    tid = uid()
    tenant = Tenant(id=tid, name=D.BRAND, slug=D.SLUG, plan="growth", business_type="caravan", brand_name=D.BRAND,
                    timezone="Asia/Kolkata", ivr_provider="vobiz", whatsapp_phone_number_id="100000000000001",
                    brand_config={"price_disclosure": "handoff",
                                  "business_profile": {"tagline": "Luxury caravan road trips (demo)", "city": "Bengaluru",
                                                       "description": "A made-up caravan brand for local testing.",
                                                       "usps": ["Driver-host included", "Pets welcome"],
                                                       "avoid": ["cheapest"], "languages": ["en"]},
                                  "marketing_studio": {"ai_images_enabled": False}})
    db.add(tenant)
    db.flush()
    provision_default_modules(db, tid)
    seed_default_pipeline_stages(db, tid)
    seed_default_capabilities(db, tid)
    have = {m for (m,) in db.query(WorkspaceModule.module_id).filter_by(workspace_id=tid)}
    for m in db.query(Module).all():   # demo = every module on, incl. marketing_studio and analytics
        if m.id not in have:
            db.add(WorkspaceModule(id=uid(), workspace_id=tid, module_id=m.id, enabled=True))

    password = os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(9)
    hashed = get_password_hash(password)
    users = {}
    for key, name, role in [("owner", "Olivia Owner", UserRole.OWNER), ("manager", "Manu Manager", UserRole.MANAGER),
                            ("agent", "Asha Agent", UserRole.RESERVATIONS)]:
        users[key] = User(id=uid(), tenant_id=tid, email=f"{key}@wanderwheel.example", name=name, hashed_password=hashed,
                          role=role, is_active=True, consent_recorded_at=NOW)
        db.add(users[key])
    owner, agents = users["owner"], [users["manager"], users["agent"]]

    # ── vehicles, rates, published business data ──────────────────────────────────────────────────────────────
    props = []
    for n in (1, 2):
        p = Property(id=uid(), tenant_id=tid, name=f"Wanderwheel {n}", slug=f"wanderwheel-{n}", type="caravan",
                     vehicle_name=f"Wanderwheel {n}", vehicle_type="luxury_caravan", home_base="Bengaluru", seats=4 + n,
                     max_adults=4, city="Bengaluru", price_per_day=18000 + 2000 * n, driver_included=True,
                     routes=[{"from": "Bengaluru", "to": d["name"], "km": d["km"]} for d in D.DESTINATIONS],
                     amenities=["AC", "Kitchenette", "Washroom", "Wi-Fi"], description="Demo caravan (made up).")
        db.add(p)
        props.append(p)
        db.add(RatePlan(id=uid(), tenant_id=tid, property_id=p.id, name="Standard", base_price_per_night=18000 + 2000 * n))
    db.flush()
    today = date.today()
    for d in D.DESTINATIONS:
        rec = bds.create_draft(db, tid, "destination", d["key"], {
            "name": d["name"], "description": "Demo route.", "distance_km_from_base": d["km"],
            "travel_hours_from_base": d["hours"], "best_months": [10, 11, 12, 1, 2],
            "stops": [{"name": s, "order": i + 1} for i, s in enumerate(d["stops"])]}, owner.id)
        bds.publish(db, tid, rec.id, owner.id)
    for pk in D.PACKAGES:
        rec = bds.create_draft(db, tid, "package", pk["key"], {
            "name": pk["name"], "summary": "Demo package.", "product": pk["product"], "min_nights": pk["nights"],
            "max_nights": pk["nights"], "max_guests": 4, "included_km": 400, "inclusions": ["Driver-host", "Breakfast"],
            "destination_keys": [pk["dest"]], "rates": [{"label": "Season", "valid_from": today.isoformat(),
                                                         "valid_to": (today + timedelta(days=365)).isoformat(),
                                                         "amount": pk["amount"]}]}, owner.id)
        bds.publish(db, tid, rec.id, owner.id)

    # ── integrations (obviously fake credentials; EXTERNAL_SERVICES=fake intercepts every call) ───────────────
    for kind, creds, cfg in [
        ("whatsapp", {"access_token": "FAKE-local-demo-wa-token"},
         {"phone_number_id": "100000000000001", "waba_id": "200000000000001", "display_phone": "+91 90000 00000",
          "verified_name": D.BRAND}),
        ("instagram", {"access_token": "FAKE-local-demo-ig-token"},
         {"instagram_business_account_id": "17800000000000001", "username": "wanderwheel.demo"}),
        ("razorpay", {"key_id": "rzp_test_FAKEDEMO0001", "key_secret": "FAKE-demo-secret",
                      "webhook_secret": secrets.token_urlsafe(24)}, {"mode": "test", "key_id_hint": "0001"}),
        ("meta_ads", {}, {"ad_account_id": "act_000000000000001", "ad_account_name": "Demo ads", "currency": "INR"}),
    ]:
        db.add(Integration(id=uid(), tenant_id=tid, kind=kind, status="active", config=cfg, installed_at=NOW.isoformat(),
                           credentials_kms_blob=encrypt_credentials(creds) if creds else None))

    # ── leads: guest + identity + inquiry + conversation ─────────────────────────────────────────────────────
    stages = {s.key: s for s in db.query(PipelineStage).filter_by(tenant_id=tid)}
    legacy = {"sold": InquiryStage.BOOKED, "lost": InquiryStage.LOST, "active": InquiryStage.RESPONDING,
              "unsuitable": InquiryStage.LOST}
    plan = (["general_enquiry"] * 10 + ["unqualified"] * 2 + ["active"] * 14 + ["rnr"] * 5 + ["sold"] * 9 + ["lost"] * 7 + ["unsuitable"] * 2
            + ["collaboration_engagement"])
    sources = [InquirySource.META_IG, InquirySource.CLICK_TO_WA, InquirySource.WA_DIRECT, InquirySource.ORGANIC_CALL,
               InquirySource.REFERRAL, InquirySource.WEBSITE, InquirySource.PHONE]
    lost_map = [("price", LostReason.BUDGET_MISMATCH), ("dates_unavailable", LostReason.WRONG_DATES),
                ("no_response", LostReason.NO_RESPONSE), ("chose_alternative", LostReason.CHOSE_COMPETITOR)]
    won, counts = [], {"messages": 0}
    for i, stage_key in enumerate(plan):
        n = i + 1
        phone = f"+9190000{n:05d}"
        awaiting_reply = stage_key == "active" and i % 4 == 0   # guest has the last word, recently -> "reply" on My day
        if stage_key in ("general_enquiry", "unqualified"):
            first_at = ago(hours=2 + i * 13 % 40)
        else:
            first_at = ago(days=1, hours=i % 9) if awaiting_reply else ago(days=2 + (i * 37) % 75, hours=i % 9)
        src = sources[i % len(sources)]
        g = Guest(id=uid(), tenant_id=tid, phone=phone, name=f"{D.FIRST[i % len(D.FIRST)]} {D.LAST[i % len(D.LAST)]}",
                  email=f"guest{n}@guests.example" if n % 3 == 0 else None, city=D.CITIES[i % len(D.CITIES)],
                  lead_identified_at=first_at, lead_identified_via="whatsapp", first_touch_channel="whatsapp",
                  first_touch_at=first_at, total_inquiries=1, last_contact_at=first_at.isoformat(), created_at=first_at)
        db.add(g)
        db.add(GuestIdentity(id=uid(), tenant_id=tid, guest_id=g.id, identity_type="phone", identity_value=phone,
                             source="whatsapp", confidence=0.90, first_seen_at=first_at, last_seen_at=first_at))
        db.add(GuestIdentity(id=uid(), tenant_id=tid, guest_id=g.id, identity_type="whatsapp_number",
                             identity_value=phone.lstrip("+"), source="whatsapp", confidence=0.85, first_seen_at=first_at))
        channel = ChannelType.INSTAGRAM if src == InquirySource.META_IG else ChannelType.WHATSAPP
        if channel == ChannelType.INSTAGRAM:
            db.add(GuestIdentity(id=uid(), tenant_id=tid, guest_id=g.id, identity_type="instagram_user_id",
                                 identity_value=f"99000000000{n:04d}", source="instagram", confidence=0.70,
                                 first_seen_at=first_at))
        stage = stages[stage_key]
        check_in = today + timedelta(days=(i * 11) % 60 - 20)
        inq = Inquiry(id=uid(), tenant_id=tid, guest_id=g.id, property_id=props[i % 2].id,
                      assigned_to=agents[i % 2].id if stage_key != "general_enquiry" else None,
                      stage=legacy.get(stage_key, InquiryStage.NEW), stage_id=stage.id, source=src,
                      check_in=check_in.isoformat(), check_out=(check_in + timedelta(days=2)).isoformat(),
                      adults=2 + i % 4, children=i % 2, occasion=D.OCCASIONS[i % len(D.OCCASIONS)],
                      budget=20000 + (i % 5) * 8000, current_stage_entered_at=first_at + timedelta(hours=3),
                      created_at=first_at, route_mentioned=D.DESTINATIONS[i % 2]["name"],
                      ai_summary=f"Demo lead from {src.value}: {2 + i % 4} adults, interested in {D.DESTINATIONS[i % 2]['name']}.")
        if stage.is_closed_lost or stage_key == "unsuitable":
            reason, legacy_reason = lost_map[i % len(lost_map)]
            inq.lost_reason, inq.outcome_reason, inq.outcome_reason_source = legacy_reason, reason, "person"
            inq.outcome_decided_by, inq.outcome_decided_at = owner.id, first_at + timedelta(days=1)
        if stage.is_closed_won:
            inq.outcome_reason, inq.outcome_reason_source = ["package_fit", "occasion", "quick_response"][i % 3], "person"
            inq.outcome_decided_by, inq.outcome_decided_at = owner.id, first_at + timedelta(days=1)
            inq.quoted_amount = D.PACKAGES[i % 2]["amount"]
            won.append((g, inq, check_in))
        db.add(inq)
        conv = Conversation(id=uid(), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, property_id=inq.property_id,
                            assigned_to=inq.assigned_to, channel=channel, channel_conversation_id=f"demo-thread-{n}",
                            is_open=stage_key not in ("sold", "lost", "unsuitable"), ai_mode="shadow",
                            source=src.value, created_at=first_at)
        db.add(conv)
        db.flush()   # no ORM relationships between these tables, so parents must hit the DB before the children
        # unanswered leads (general_enquiry) get guest-only turns -> "new_lead"/"reply" on My day
        turns = D.CHATS[4] if stage_key == "general_enquiry" else D.CHATS[i % len(D.CHATS)]
        if awaiting_reply:
            turns = D.CHATS[3][:3]
        at = first_at
        for direction, body in turns:
            at += timedelta(minutes=7 + len(body) % 20)
            out = direction == "out"
            db.add(Message(id=uid(), tenant_id=tid, conversation_id=conv.id, channel=channel, body=body, created_at=at,
                           direction=MessageDirection.OUTBOUND if out else MessageDirection.INBOUND,
                           delivery_state=MessageDeliveryState.READ if out else None, channel_status="read" if out else None,
                           channel_message_id=f"demo.{uid()}", sender_kind="human" if out else None,
                           sender_id=inq.assigned_to if out else None))
            counts["messages"] += 1
        conv.last_message_at = at.isoformat()
        if not any(d == "out" for d, _ in turns) and n % 2 == 0:
            conv.ai_draft = "Thanks for reaching out to Wanderwheel! Which dates and how many guests?"
        if src in (InquirySource.META_IG, InquirySource.CLICK_TO_WA):
            db.add(LeadAttribution(id=uid(), tenant_id=tid, inquiry_id=inq.id, conversation_id=conv.id, guest_id=g.id,
                                   destination_channel=channel.value, ad_id=f"2385000000000{1 + i % 2}",
                                   adset_id="23840000000001", campaign_id=f"2383000000000{1 + i % 2}", source_type="ad",
                                   headline="Weekend caravan escapes", first_message_at=first_at))
    db.flush()

    # ── calls (answered with transcripts + scores; two missed -> callback) ───────────────────────────────────
    rubric = Rubric(id=uid(), tenant_id=tid, name="Demo sales call", is_default=True, criteria=[
        {"id": "greet", "name": "Greeting", "weight": 1, "method": "llm", "description": "Warm greeting"},
        {"id": "needs", "name": "Needs discovery", "weight": 2, "method": "llm", "description": "Asks dates and party"},
        {"id": "next", "name": "Next step", "weight": 2, "method": "llm", "description": "Agrees a next step"}])
    db.add(rubric)
    leads = db.query(Inquiry).filter_by(tenant_id=tid).order_by(Inquiry.created_at.desc()).all()
    disp = [CallDisposition.HOT, CallDisposition.QUOTED, CallDisposition.LOST, CallDisposition.BOOKED]
    for k, turns in enumerate(D.TRANSCRIPTS):
        inq = leads[5 + k * 3]
        g = db.get(Guest, inq.guest_id)
        start = ago(days=1 + k, hours=3)
        tj = [{"speaker": s, "text": t, "start": j * 9.0, "end": j * 9.0 + 8} for j, (s, t) in enumerate(turns)]
        call = Call(id=uid(), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, agent_id=agents[k % 2].id,
                    property_id=inq.property_id, ivr_provider="vobiz", ivr_call_id=f"demo-call-{k}",
                    direction=CallDirection.OUTBOUND if k == 3 else CallDirection.INBOUND, ivr_dial_status="completed",
                    from_number=g.phone, to_number="+919000099999", duration_seconds=60 + 45 * k,
                    started_at=start.isoformat(), ended_at=(start + timedelta(minutes=2 + k)).isoformat(),
                    transcription_status="done", ai_score_status="done", transcript_json=tj, ai_disposition=disp[k],
                    ai_summary=" ".join(t for _, t in turns)[:300], ai_score=62 + 9 * k, created_at=start,
                    ai_next_action="Send package details on WhatsApp")
        db.add(call)
        db.flush()
        db.add(Transcript(id=uid(), tenant_id=tid, call_id=call.id, provider="demo", language="en-IN",
                          turns=json.dumps(tj), raw_text="\n".join(f"{s}: {t}" for s, t in turns)))
        pct = 62 + 9 * k
        db.add(CallScore(id=uid(), tenant_id=tid, call_id=call.id, rubric_id=rubric.id, rubric_snapshot=rubric.criteria,
                         total_score=pct / 20, max_score=5, percentage=pct, model_used="demo-seed",
                         criterion_scores=[{"criterion_id": c["id"], "score": 1 + (k + j) % 2, "confidence": 0.8}
                                           for j, c in enumerate(rubric.criteria)]))
    for k in range(2):
        g = db.get(Guest, leads[k].guest_id)
        t = ago(hours=1 + 2 * k)
        db.add(Call(id=uid(), tenant_id=tid, guest_id=g.id, inquiry_id=leads[k].id, ivr_provider="vobiz",
                    ivr_call_id=f"demo-missed-{k}", direction=CallDirection.INBOUND, from_number=g.phone,
                    to_number="+919000099999", duration_seconds=0, ivr_dial_status="no-answer",
                    human_disposition=CallDisposition.NO_ANSWER, started_at=t.isoformat(), created_at=t,
                    transcription_status="skipped", ai_score_status="skipped"))

    # ── bookings + payments (won leads) ──────────────────────────────────────────────────────────────────────
    n_stays = n_pay = 0
    for j, (g, inq, check_in) in enumerate(won):
        total = D.PACKAGES[j % 2]["amount"]
        ci = today + timedelta(days=[-40, -25, -12, -1, 0, 6, 15, 30, 45][j % 9])
        status = "checked_out" if ci < today - timedelta(days=2) else ("checked_in" if ci <= today else "confirmed")
        stay = Stay(id=uid(), tenant_id=tid, guest_id=g.id, property_id=props[j % 2].id, inquiry_id=inq.id,
                    check_in=ci, check_out=ci + timedelta(days=2), adults=inq.adults, children=inq.children,
                    status=status, total_amount=total, channel_source="direct", occasion=inq.occasion,
                    internal_notes="Demo booking", gst_percent=12)
        db.add(stay)
        n_stays += 1
        db.flush()
        paid = total if status != "confirmed" else total // 2
        db.add(StayPayment(id=uid(), tenant_id=tid, stay_id=stay.id, amount=paid, method=["upi", "razorpay", "bank_transfer"][j % 3],
                           reference=f"DEMO-UTR-{j:04d}", paid_on=min(ci, today) - timedelta(days=3), created_by=owner.id))
        n_pay += 1
        if paid < total:
            db.add(StayInstalment(id=uid(), tenant_id=tid, stay_id=stay.id, label="Balance", amount=total - paid,
                                  due_date=ci - timedelta(days=2)))
        if j == 0:
            db.add(StayDeposit(id=uid(), tenant_id=tid, stay_id=stay.id, amount=10000, status="released", method="upi",
                               collected_on=ci, resolved_on=ci + timedelta(days=2)))
        if j == 5:
            db.add(StayDeposit(id=uid(), tenant_id=tid, stay_id=stay.id, amount=10000, status="pending"))

    # ── Meta ads: 2 campaigns, 30 days ───────────────────────────────────────────────────────────────────────
    acct = "act_000000000000001"
    for c in (1, 2):
        cid, aid = f"2383000000000{c}", f"2385000000000{c}"
        name = ["Weekend escapes - CTWA", "Monsoon reels - IG"][c - 1]
        db.add(AdEntity(id=uid(), tenant_id=tid, ad_account_id=acct, level="campaign", entity_id=cid, campaign_id=cid,
                        name=name, status="ACTIVE", effective_status="ACTIVE", objective="OUTCOME_ENGAGEMENT",
                        daily_budget=800 * c, starts_at=ago(days=45)))
        db.add(AdEntity(id=uid(), tenant_id=tid, ad_account_id=acct, level="ad", entity_id=aid, campaign_id=cid,
                        adset_id="23840000000001", name=f"{name} / ad 1", status="ACTIVE", effective_status="ACTIVE",
                        creative={"title": "Weekend caravan escapes", "body": "Sunrise from your bed. Book now."}))
        for day in range(30):
            spend = 500 + random.randint(0, 400) * c
            imp = spend * 9 + random.randint(0, 900)
            clicks = imp // 60
            db.add(AdMetric(id=uid(), tenant_id=tid, ad_account_id=acct, date=today - timedelta(days=day + 1),
                            campaign_id=cid, campaign_name=name, adset_id="23840000000001", adset_name="Bengaluru 25-45",
                            ad_id=aid, ad_name=f"{name} / ad 1", spend=spend, impressions=imp, reach=int(imp * 0.7),
                            clicks=clicks, link_clicks=int(clicks * 0.8), unique_clicks=int(clicks * 0.9),
                            ctr=round(clicks * 100 / imp, 4), cpm=round(spend * 1000 / imp, 4), cpc=round(spend / max(clicks, 1), 4),
                            frequency=1.4, conversations_started=random.randint(1, 6), first_replies=random.randint(0, 4),
                            post_engagement=random.randint(20, 120), video_views=random.randint(100, 900) if c == 2 else 0))

    # ── Instagram account + post snapshots ───────────────────────────────────────────────────────────────────
    for day in range(30):
        db.add(igp.InstagramInsightsSnapshot(id=uid(), tenant_id=tid, ig_account_id="17800000000000001",
                                             reach=900 + random.randint(0, 600), profile_views=60 + random.randint(0, 50),
                                             follower_count=random.randint(0, 12), followers_count=5000 + day * 4,
                                             following_count=310, media_count=120, accounts_engaged=150 + random.randint(0, 90),
                                             total_interactions=300 + random.randint(0, 200), likes=250, comments=18,
                                             shares=12, saves=20, created_at=ago(days=29 - day)))
    for p_i, caption in enumerate(D.IG_CAPTIONS):
        mid = f"1790000000000{p_i:04d}"
        posted = ago(days=3 + p_i * 4)
        mtype = "VIDEO" if p_i % 3 == 0 else "IMAGE"
        likes, reach = 80 + (p_i * 53) % 400, 900 + (p_i * 311) % 4000
        db.add(igp.InstagramPostSnapshot(id=uid(), tenant_id=tid, media_id=mid, caption=caption, media_type=mtype,
                                         permalink=f"https://www.instagram.com/p/DEMO{p_i}/", posted_at=posted.isoformat(),
                                         like_count=likes, comments_count=likes // 12, reach=reach, saved=likes // 8,
                                         shares=likes // 15, total_interactions=likes + likes // 4))
        for d_i in range(3):
            db.add(InstagramPostMetricDaily(id=uid(), tenant_id=tid, media_id=mid, media_type=mtype,
                                            day=(posted + timedelta(days=d_i)).date().isoformat(), posted_at=posted.isoformat(),
                                            like_count=likes * (d_i + 1) // 3, comments_count=likes // 30, reach=reach * (d_i + 1) // 3,
                                            saved=likes // 20, shares=likes // 30, total_interactions=likes * (d_i + 1) // 2,
                                            media_product_type="REELS" if mtype == "VIDEO" else "FEED", views=reach * 2))
    db.commit()

    # ── photos + clips through the normal storage path (fake storage only) ───────────────────────────────────
    photos = clips = 0
    reason = media_ready()
    if reason:
        print(f"Skipping demo photos and clips: {reason}.")
    else:
        from app.services.media_library_service import add_upload
        jpegs = []
        for cap, top, bottom in D.PHOTO_CAPTIONS:
            raw = make_photo(cap, top, bottom)
            jpegs.append(raw)
            add_upload(db, tid, raw, actor_id=owner.id, alt_text=f"Demo photo: {cap}", property_id=props[photos % 2].id)
            photos += 1
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            from app.services.marketing_reel import add_clip
            for c in range(2):
                add_clip(db, tid, make_clip(jpegs[c * 3:c * 3 + 3]), actor_id=owner.id, alt_text=f"Demo clip {c + 1}")
                clips += 1
        else:
            print("Skipping demo clips: ffmpeg/ffprobe not on PATH.")
        db.commit()

    import _demo_site   # the website, built with the v2 builder (SiteSpec); binds to the photos above
    site_host = _demo_site.seed(db, tenant, owner)

    print(f"\nDemo tenant '{D.BRAND}' ({D.SLUG}) ready: {len(plan)} leads, {counts['messages']} messages, "
          f"{len(D.TRANSCRIPTS) + 2} calls, {n_stays} bookings, {n_pay} payments, {photos} photos, {clips} clips.")
    print(f"Website (v2 builder, published): {site_host}  (sites app: DEV_SITE_HOST={site_host})")
    print("Sign in at http://localhost:3000 with owner@wanderwheel.example / manager@wanderwheel.example / agent@wanderwheel.example")
    print(f"Password (shown once): {password}")
    db.close()


if __name__ == "__main__":
    run()
