"""WhatsApp buttons on a v2 site prefill "(Ref WW-HOME-HERO)" (website_bindings.ref_code: PREFIX-PAGE-SECTION). When a
guest's FIRST WhatsApp message carries one, the chat's lead records which page and section sent it.

Called from the WhatsApp webhook task right after the chat's lead exists (identity was already resolved there through
identity_service; this only reads the message text). A code counts only when its prefix is the tenant's live v2 site's
own prefix, so a pasted code from another business is ignored. Writes inquiry.custom_fields["website_ref"]
{code, page, section} once; a lead the website created just now (source WA_DIRECT, under 10 minutes old) becomes
source WEBSITE. Older leads keep their stored source (a returning guest's lead is not re-labelled). Audited.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.inquiry import Inquiry, InquirySource

REF_IN_TEXT = re.compile(r"\(Ref ([A-Z0-9]{2,8})-([A-Z0-9]{1,12})-([A-Z0-9]{1,12})\)")
FRESH = timedelta(minutes=10)


def find(text: Optional[str]) -> Optional[tuple[str, str, str]]:
    m = REF_IN_TEXT.search(text or "")
    return (m.group(1), m.group(2), m.group(3)) if m else None


def site_prefix(db: Session, tenant_id: str) -> Optional[str]:
    from app.models.website import SiteVersion
    from app.services.website_bindings import ref_prefix
    from app.services.website_service import get_site
    from app.services.website_spec_service import is_v2
    site = get_site(db, tenant_id)
    v = db.get(SiteVersion, site.live_version_id) if site and site.live_version_id else None
    return ref_prefix(v.doc) if v is not None and is_v2(v.doc) else None


def stamp(db: Session, tenant_id: str, inquiry: Inquiry, text: Optional[str]) -> Optional[dict]:
    found = find(text)
    if not found or (inquiry.custom_fields or {}).get("website_ref"):
        return None
    prefix, page, section = found
    if prefix != site_prefix(db, tenant_id):
        return None
    ref = {"code": f"{prefix}-{page}-{section}", "page": page, "section": section}
    inquiry.custom_fields = {**(inquiry.custom_fields or {}), "website_ref": ref}
    made = inquiry.created_at
    made = made if made is None or made.tzinfo else made.replace(tzinfo=timezone.utc)
    relabel = inquiry.source == InquirySource.WA_DIRECT and (made is None or datetime.now(timezone.utc) - made < FRESH)
    if relabel:
        inquiry.source = InquirySource.WEBSITE
    append_audit(db, tenant_id=tenant_id, action="website.whatsapp_ref", target_type="inquiry", target_id=inquiry.id,
                 payload={"actor": "system", "code": ref["code"], "source_changed": relabel})
    db.flush()
    return ref
