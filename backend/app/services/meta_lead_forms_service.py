"""Meta lead-form leads into HAIP.

A guest fills a lead form on a Facebook / Instagram ad; HAIP reads the page's forms every few minutes with the
workspace's Meta Business token and turns each new submission into a lead: the person through identity_service, the
enquiry through inquiry_service (entry stage + assignment like every other new lead), the ad it came from in
`meta_form_leads`. A submission is imported once (unique tenant + leadgen id).

shortcut: polling, so a lead arrives up to one beat interval late; add Meta's `leadgen` webhook when that matters.
The settings live in the `meta_business` integration's config under "lead_forms".
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, datetime

import structlog
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.marketing import meta_business
from app.adapters.marketing.meta_ads import MetaAdsError
from app.core.audit import append_audit
from app.core.database import set_tenant_context
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


def _when(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None


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
        guest_id, _ = identity_service.resolve_gid(
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
