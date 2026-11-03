"""E3 plans: marketing, social media, reviews and the website (same contract as plans.py; wired into plans.PLANNERS).

  MK1  comment spike, no auto-reply   -> every comment on that post gets a DM + a short public reply          R3 (public)
  MK4  posting slowed down            -> Marketing Studio drafts this week's posts (posting keeps its approval) R1
  MK7  Google reviews with no reply   -> AI drafts a reply to each; a person reads and posts                   R1
  WB1  more visits, fewer enquiries   -> a website DRAFT change: the enquiry button easier to find              R1
  WB3  long weekend still mostly free -> a website DRAFT change: a short section about that weekend, no price   R1
The texts that would go out are written by rule here (no model), so the owner approves exactly what guests will read.
Website changes only edit the draft; it goes live only when the owner approves the new version on the Website page.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.insight import Insight
from app.services.chief.steps import step


def _brand(tenant) -> str:
    return (tenant.brand_name or tenant.name or "us").strip()


def comment_texts(tenant) -> tuple[str, str]:
    """The DM and the public reply (no price, no promise, no link: the guest answers in the DM)."""
    dm = (
        f"Hi! Thanks for your comment. Tell us your travel dates and how many of you are coming, and we will share the "
        f"full plan with you right here. - {_brand(tenant)}"
    )
    return dm, "Thank you! We have sent you a message."


def _comment_rule(db: Session, tenant, row: Insight) -> dict | None:
    if not row.target_id:
        return None
    dm, public = comment_texts(tenant)
    return {
        "title": "Answer everyone who comments on that post",
        "steps": [
            step(
                "automation.comment_rule",
                "Turn on the automatic DM for that post",
                "R3",
                media_id=row.target_id,
                message=dm,
                public_reply=public,
            )
        ],
        "preview": [
            "Every new comment on that post gets this DM:",
            f'"{dm}"',
            f'And this short public reply under the comment: "{public}"',
            "Replies to the DM land in the Inbox as usual. You can switch the rule off in Automations.",
        ],
        "guest_facing": True,
    }


def _agency(db: Session, tenant, row: Insight) -> dict | None:
    from app.services import marketing_agency_service

    if marketing_agency_service.get_agency(tenant)["paused"]:
        return None
    return {
        "title": "Let Marketing Studio draft this week's posts",
        "steps": [step("marketing.agency_run", "Start Marketing Studio's weekly run", "R1")],
        "preview": [
            "Marketing Studio writes this week's plan and post drafts with photos from your library.",
            "Nothing is posted until you approve each post in Studio.",
        ],
        "guest_facing": False,
    }


def _reviews(db: Session, tenant, row: Insight) -> dict | None:
    ids = [e["id"] for e in (row.evidence or []) if e.get("type") == "google_review"]
    if not ids:
        return None
    return {
        "title": "Draft replies to your Google reviews",
        "steps": [step("reviews.draft_replies", "Draft a reply to each review", "R1", review_ids=ids)],
        "preview": [
            f"The AI drafts a reply to each of {len(ids)} review(s) in your brand voice.",
            "A person reads, edits and posts each reply from Marketing Studio; nothing is posted by itself.",
        ],
        "guest_facing": False,
    }


WB1_TEXT = (
    "Make it easier for visitors to ask us: put a clear button to plan the trip on WhatsApp in the first screen of the "
    "home page, and repeat it right after the packages. Keep everything else as it is."
)


def _website(text: str, title: str):
    def planner(db: Session, tenant, row: Insight) -> dict | None:
        from app.services.chief.detectors import Ctx
        from app.services.chief.detectors_growth import site_v2

        if site_v2(Ctx(db, tenant)) is None:
            return None
        body = text(row) if callable(text) else text
        return {
            "title": title,
            "steps": [
                step("website.change_draft", "Ask the website's AI to make this change in the draft", "R1", text=body)
            ],
            "preview": [
                f'Asks the website\'s AI to change the DRAFT: "{body}"',
                "Nothing goes live until you approve the new version on the Website page, and it can be undone.",
            ],
            "guest_facing": False,
        }

    return planner


def _weekend_text(row: Insight) -> str:
    ev = next((e for e in (row.evidence or []) if e.get("type") == "long_weekend"), {})
    label = (ev.get("label") or "the long weekend").strip()
    return (
        f"Add a short section near the top about {label} ({ev.get('id')} to {ev.get('end')}): we still have dates free "
        "that weekend, and visitors can ask us on WhatsApp. Do not mention any price or discount."
    )


PLANNERS = {
    "MK1": _comment_rule,
    "MK4": _agency,
    "MK7": _reviews,
    "WB1": _website(WB1_TEXT, "Make the website's enquiry button easier to find"),
    "WB3": _website(_weekend_text, "Tell website visitors about the free long weekend"),
}
