"""Meta lead-form leads into HAIP.

A guest fills a lead form on a Facebook / Instagram ad; HAIP reads the page's forms every few minutes with the
workspace's Meta Business token and turns each new submission into a lead: the person through identity_service, the
enquiry through inquiry_service (entry stage + assignment like every other new lead), the ad it came from in
`meta_form_leads`. A submission is imported once (unique tenant + leadgen id).

shortcut: polling, so a lead arrives up to one beat interval late; add Meta's `leadgen` webhook when that matters.
The settings live in the `meta_business` integration's config under "lead_forms".
"""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.marketing import meta_business
from app.adapters.marketing.meta_ads import MetaAdsError
from app.core.audit import append_audit
from app.core.database import set_tenant_context
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.meta_form_lead import MetaFormLead
from app.services import meta_business_service as biz

log = structlog.get_logger()

OVERLAP_S = 600  # re-read the last 10 minutes each run; the unique key drops what was already imported
MAX_IMPORT_DAYS = 90  # Meta keeps a form's leads for 90 days
_NAME = ("full_name",)
_PHONE = ("phone_number", "phone", "work_phone_number")
_EMAIL = ("email", "work_email")
_KNOWN = {*_NAME, *_PHONE, *_EMAIL, "first_name", "last_name"}


class NotEnabled(Exception):
    """Lead forms are switched off, or the connection cannot read them."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _block(row) -> dict:
    return dict(((row.config if row else None) or {}).get("lead_forms") or {})


def _save(db: Session, tenant_id: str, **changes) -> None:
    row = biz.get_row(db, tenant_id)
    row.config = {**(row.config or {}), "lead_forms": {**_block(row), **changes}}
    db.flush()


def set_enabled(db: Session, tenant_id: str, enabled: bool) -> None:
    row = biz.get_row(db, tenant_id)
    if not row or not biz.get_token(db, tenant_id):
        raise NotEnabled("Connect Meta Business first.")
    cfg = row.config or {}
    if enabled:
        cap = (cfg.get("capabilities") or {}).get("lead_forms") or {}
        if not cap.get("ok"):
            raise NotEnabled(
                "This token cannot read lead forms: " + "; ".join(cap.get("missing") or ["unknown reason"]) + "."
            )
        if not cfg.get("page_id"):
            raise NotEnabled("Choose the Facebook page first.")
    was = _block(row).get("enabled")
    changes = {"enabled": bool(enabled), "last_error": None}
    if enabled and not was:
        changes["since"] = int(time.time())  # from now on; older leads come in with "Import"
    _save(db, tenant_id, **changes)


def parse_fields(field_data) -> tuple[str, str, str, dict]:
    """(name, phone, email, other answers) from Meta's [{name, values}]."""
    got: dict[str, str] = {}
    for f in field_data or []:
        key = str(f.get("name") or "").strip().lower()
        value = ", ".join(str(v).strip() for v in (f.get("values") or []) if str(v).strip())
        if key and value:
            got[key] = value
    name = next((got[k] for k in _NAME if k in got), "") or " ".join(
        x for x in (got.get("first_name"), got.get("last_name")) if x
    )
    phone = next((got[k] for k in _PHONE if k in got), "")
    email = next((got[k] for k in _EMAIL if k in got), "")
    answers = {k.replace("_", " ").strip().capitalize(): v[:500] for k, v in got.items() if k not in _KNOWN}
    return name[:200], phone, email, answers


_NUM = re.compile(r"\d[\d,]*")
_MONTH_WORD = re.compile(r"[a-z]{3,9}", re.I)


def _numbers(text: str) -> list[int]:
    return [int(n.replace(",", "")) for n in _NUM.findall(text or "") if n.replace(",", "")]


def _day_dates(text: str, filled: date) -> list[date]:
    """"14 and 15" / "20-22 Dec" / "5th January" -> dates. Days with no month = the next such day on or after the day the
    form was filled ("14 and 15" filled on 10 Nov = 14 and 15 Nov). Never a date in the past of the form."""
    from app.services.ical_event_details import _month

    month = next((m for w in _MONTH_WORD.findall(text or "") if (m := _month(w))), None)
    out = []
    for day in [n for n in _numbers(text) if 1 <= n <= 31][:2]:
        tries = [(filled.year, month), (filled.year + 1, month)] if month else [
            (filled.year + (filled.month + i - 1) // 12, (filled.month + i - 1) % 12 + 1) for i in range(13)]
        for year, mon in tries:
            try:
                d = date(year, mon, day)
            except ValueError:
                continue
            if d >= filled:
                out.append(d)
                break
    return sorted(set(out))


def trip_facts(answers: dict, filled: date) -> dict:
    """Guests / dates / budget read from the form's own questions, for the lead's fields (the Inbox strip, the lead page).
    A range keeps its TOP figure ("10-20 people" = 20, "30,000-40,000" = 40,000): enough room and the most they will
    spend. The exact answer stays in the note. A question it cannot read is left alone."""
    out: dict = {}
    for question, raw in (answers or {}).items():
        q, text = question.lower(), str(raw).replace("_", " ")
        nums = _numbers(text)
        if not nums:
            continue
        if "budget" in q or "price" in q or "spend" in q:
            out.setdefault("budget", float(max(nums)))
        elif any(w in q for w in ("guest", "people", "pax", "party", "persons", "members", "how many")):
            top = max(n for n in nums if n <= 200) if any(n <= 200 for n in nums) else None
            if top:
                out.setdefault("adults", top)
        elif "date" in q or "when" in q:
            days = _day_dates(text, filled)
            if days:
                out.setdefault("check_in", days[0].isoformat())
                out.setdefault("check_out", (days[-1] if len(days) > 1 else days[0] + timedelta(days=1)).isoformat())
    return out


def apply_trip_facts(inquiry: Inquiry, answers: dict, filled: date) -> list[str]:
    """Fill the lead's empty Guests / Dates / Budget from the form. Never overwrites what a person or the chat already set."""
    done = []
    for field, value in trip_facts(answers, filled).items():
        if getattr(inquiry, field) in (None, ""):
            setattr(inquiry, field, value)
            done.append(field)
    return done


def _when(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None


def _use_form_time(db: Session, tenant_id: str, guest_id: str, inquiry: Inquiry, rec: MetaFormLead, new_person: bool) -> None:
    """The lead's clock starts when the form was filled, not when HAIP read it. An import reads months back: stamped
    "now", every old lead would show as brand new in My day, count as today's lead and alert the team."""
    when = rec.lead_created_at
    if not when or when > datetime.now(UTC):
        return
    if rec.status == "created":
        inquiry.created_at = when
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first() if new_person else None
    if guest is not None:  # only a person this submission created; a known person keeps their first dates
        if guest.lead_identified_at is not None:
            guest.lead_identified_at = when
        if guest.first_touch_at is not None:
            guest.first_touch_at = when


def open_thread(db: Session, tenant_id: str, rec: MetaFormLead, inquiry: Inquiry) -> bool:
    """Put the lead in the Inbox (owner, 10 Nov 2026): one "Facebook" thread holding the form's answers. A form is not a
    chat, so the answers are a STAFF NOTE: the AI never replies to it and it is never "waiting for a reply". A person who
    already has a thread on any channel keeps that one. True when a thread was made."""
    if db.query(Conversation.id).filter_by(tenant_id=tenant_id, guest_id=rec.guest_id).first():
        return False
    when = rec.lead_created_at or datetime.now(UTC)
    conv = Conversation(
        tenant_id=tenant_id,
        guest_id=rec.guest_id,
        inquiry_id=inquiry.id,
        channel=ChannelType.FACEBOOK,
        is_open=True,
        ai_mode="off",
        source="lead_form",
        last_message_at=when.isoformat(),
    )
    db.add(conv)
    db.flush()
    answers = ((inquiry.custom_fields or {}).get("lead_form") or {}).get("answers") or {}
    where = "Instagram" if rec.platform == "ig" else "Facebook"
    note = Message(
        tenant_id=tenant_id,
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        channel=ChannelType.FACEBOOK,
        body=(f'Filled the lead form "{rec.form_name}" on {where}.' + "".join(f"\n{k}: {v}" for k, v in answers.items()))[:4000],
        is_internal=True,
        sender_name="Meta lead form",
        sender_kind="system",
    )
    db.add(note)
    db.flush()
    note.created_at = when
    return True


def ingest(db: Session, tenant_id: str, raw: dict, form: dict, page_id: str) -> str:
    """Turn one submission into a lead. Returns created | attached | no_contact | duplicate. Commits."""
    from app.services import identity_service, inquiry_service, phone_identity

    leadgen_id = str(raw.get("id") or "")
    if not leadgen_id or db.query(MetaFormLead.id).filter_by(tenant_id=tenant_id, leadgen_id=leadgen_id).first():
        return "duplicate"
    name, phone_raw, email, answers = parse_fields(raw.get("field_data"))
    phone = phone_identity.normalize(phone_raw, phone_identity.region_for_tenant(db, tenant_id)) if phone_raw else None
    rec = MetaFormLead(
        tenant_id=tenant_id,
        leadgen_id=leadgen_id,
        form_id=form.get("id"),
        form_name=(form.get("name") or "")[:255],
        page_id=page_id,
        ad_id=raw.get("ad_id"),
        adset_id=raw.get("adset_id"),
        campaign_id=raw.get("campaign_id"),
        platform=str(raw.get("platform") or "")[:20],
        lead_created_at=_when(raw.get("created_time")),
        status="no_contact",
    )
    inquiry = None
    if phone or email:
        source = InquirySource.META_IG if rec.platform == "ig" else InquirySource.META_FB
        signal, value = ("phone", phone) if phone else ("email", email)
        guest_id, new_person = identity_service.resolve_gid(
            db,
            tenant_id,
            signal_type=signal,
            value=value,
            source=source.value,
            guest_fields={"name": name} if name else None,
        )
        if phone and email:
            identity_service.add_signal(
                db, tenant_id=tenant_id, guest_id=guest_id, signal_type="email", value=email, source=source.value
            )
        closed = [InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED]
        inquiry = (
            db.query(Inquiry)
            .filter_by(tenant_id=tenant_id, guest_id=guest_id)
            .filter(~Inquiry.stage.in_(closed))
            .order_by(Inquiry.created_at.desc())
            .first()
        )
        rec.status = "attached" if inquiry else "created"
        if inquiry is None:  # no open lead: a new one, in the entry stage, assigned like any other
            inquiry = inquiry_service.create_lead_for_guest(
                db, tenant_id, guest_id, source=source, has_phone=bool(phone), commit=False
            )
        inquiry.custom_fields = {
            **(inquiry.custom_fields or {}),
            "lead_form": {
                "form_id": rec.form_id,
                "form_name": rec.form_name,
                "leadgen_id": leadgen_id,
                "campaign_id": rec.campaign_id,
                "ad_id": rec.ad_id,
                "submitted_at": raw.get("created_time"),
                "answers": answers,
            },
        }
        if answers and not inquiry.special_requests:
            inquiry.special_requests = (
                f'Meta lead form "{rec.form_name}": ' + "; ".join(f"{k}: {v}" for k, v in answers.items())
            )[:2000]
        rec.guest_id, rec.inquiry_id = guest_id, inquiry.id
        apply_trip_facts(inquiry, answers, (rec.lead_created_at or datetime.now(UTC)).date())
        _use_form_time(db, tenant_id, guest_id, inquiry, rec, new_person)
        open_thread(db, tenant_id, rec, inquiry)
    db.add(rec)
    try:
        db.flush()
    except IntegrityError:  # another run imported it between the check and here
        db.rollback()
        return "duplicate"
    append_audit(
        db,
        tenant_id=tenant_id,
        action="meta_lead_form.lead_imported",
        target_type="inquiry",
        target_id=inquiry.id if inquiry else leadgen_id,
        payload={"actor": "system", "leadgen_id": leadgen_id, "form_id": rec.form_id, "result": rec.status},
    )
    db.commit()
    return rec.status


def sync(db: Session, tenant_id: str, *, since_days: int | None = None) -> dict:
    """Read new submissions (or the last `since_days` for an import) and ingest them. Returns counts by result."""
    row = biz.get_row(db, tenant_id)
    token = biz.get_token(db, tenant_id)
    block = _block(row)
    if not token or not block.get("enabled"):
        raise NotEnabled("Lead forms are switched off.")
    page_id = (row.config or {}).get("page_id")
    started = int(time.time())
    importing = since_days is not None
    since = (
        started - min(int(since_days), MAX_IMPORT_DAYS) * 86400
        if importing
        else int(block.get("since") or started) - OVERLAP_S
    )
    counts: Counter = Counter()
    try:
        page_access = meta_business.page_token(token, page_id) if page_id else None
        if not page_access:
            raise MetaAdsError("The token can no longer see the chosen Facebook page.")
        forms = meta_business.list_lead_forms(page_access, page_id)
        for form in forms:
            if not importing and form["status"] not in ("ACTIVE", ""):
                continue  # only a live form gets new leads; an import reads every form
            for raw in meta_business.fetch_leads(page_access, form["id"], since):
                try:
                    counts[ingest(db, tenant_id, raw, form, page_id)] += 1
                except Exception as exc:  # noqa: BLE001  one bad submission must not stop the rest
                    db.rollback()
                    counts["failed"] += 1
                    log.error(
                        "meta_lead_form_ingest_failed",
                        tenant_id=tenant_id,
                        leadgen_id=str(raw.get("id")),
                        error=type(exc).__name__,
                    )
                set_tenant_context(db, tenant_id)
    except MetaAdsError as exc:  # every submission before this point is already committed or rolled back
        _save(db, tenant_id, last_error=str(exc)[:200], last_run_at=_now_iso())
        db.commit()
        raise
    changes = {
        "forms": [{"id": f["id"], "name": f["name"], "status": f["status"]} for f in forms],
        "last_run_at": _now_iso(),
        "last_error": None,
    }
    if not importing and not counts["failed"]:
        changes["since"] = started  # the cursor moves only when every submission was handled
    _save(db, tenant_id, **changes)
    db.commit()
    result = {k: counts[k] for k in ("created", "attached", "no_contact", "duplicate", "failed")}
    log.info("meta_lead_forms_synced", tenant_id=tenant_id, importing=importing, **result)
    return result


def status_block(db: Session, tenant_id: str, cfg: dict) -> dict:
    block = dict(cfg.get("lead_forms") or {})
    imported, last = (
        db.query(func.count(MetaFormLead.id), func.max(MetaFormLead.lead_created_at))
        .filter(MetaFormLead.tenant_id == tenant_id, MetaFormLead.inquiry_id.isnot(None))
        .one()
    )
    return {
        "enabled": bool(block.get("enabled")),
        "forms": block.get("forms") or [],
        "last_run_at": block.get("last_run_at"),
        "last_error": block.get("last_error"),
        "imported": int(imported or 0),
        "last_lead_at": last.isoformat() if last else None,
    }
