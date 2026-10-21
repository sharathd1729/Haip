"""Channels beyond Instagram (agency M3): how an approved payload becomes a Facebook Page post or a Google Business
Profile post, what blocks it, and the publish step for each.

The approval covers the payload; the per-channel text is derived from it by these deterministic rules (shown to the
approver in the preview), never rewritten by AI:
  * Facebook: the caption plus at most FB_HASHTAGS hashtags; carousels become one multi-photo post; stories are
    Instagram-only.
  * Google: the caption without hashtags or the first comment, cut at a sentence to <= 1,500 characters; one photo
    (the first); a button (Book / Learn more to the profile's website, else Call). Google rejects posts that contain a
    phone number, so one blocks the post. Stories are Instagram-only.
"""
import re
from typing import Callable

from app.adapters.google_business import SUMMARY_MAX
from app.adapters.instagram.publishing import PublishError
from app.models.media_asset import MediaAsset

CHANNELS = ("instagram", "facebook", "google")          # channels a post is PUBLISHED to
LABEL = {"instagram": "Instagram", "facebook": "Facebook Page", "google": "Google Business Profile", "whatsapp": "WhatsApp"}
FB_HASHTAGS = 3
_PHONE = re.compile(r"(?:\+?91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b|\b0\d{2,4}[\s-]?\d{6,8}\b")
_HASHTAG = re.compile(r"(?:^|\s)#[\wऀ-ॿ]+")


def channels_for(kind: str) -> tuple[str, ...]:
    """Where an item can go. A promo can also become a WhatsApp campaign DRAFT (marketing_whatsapp), never a post."""
    if kind in ("story", "reel"):          # reels go to Instagram only for now (Facebook Reels is a separate API)
        return ("instagram",)
    return (*CHANNELS, "whatsapp") if kind == "promo" else CHANNELS


def publish_targets(item) -> list[str]:
    return [c for c in targets_of(item) if c in CHANNELS]


def targets_of(item) -> list[str]:
    raw = item.targets if isinstance(getattr(item, "targets", None), list) else None
    allowed = channels_for(item.kind)
    return [c for c in (raw or ["instagram"]) if c in allowed] or ["instagram"]



def facebook_message(payload: dict) -> str:
    tags = " ".join((payload.get("hashtags") or [])[:FB_HASHTAGS])
    return (payload.get("caption") or "").strip() + (f"\n\n{tags}" if tags else "")


def google_summary(payload: dict) -> str:
    text = _HASHTAG.sub("", payload.get("caption") or "").strip()
    text = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", text))
    if len(text) <= SUMMARY_MAX:
        return text
    cut = text[:SUMMARY_MAX]
    end = max(cut.rfind(". "), cut.rfind("\n"))
    return (cut[:end + 1] if end > SUMMARY_MAX // 2 else cut).strip()


def google_action(kind: str, profile: dict) -> dict:
    site = ((profile.get("socials") or {}).get("website") or "").strip()
    if site.startswith("https://"):
        return {"actionType": "BOOK" if kind == "promo" else "LEARN_MORE", "url": site}
    return {"actionType": "CALL"}


def preview(kind: str, payload: dict, profile: dict, channel: str) -> dict:
    """What will be posted on a channel, as text (images come from marketing_render)."""
    if channel == "facebook":
        return {"text": facebook_message(payload), "images": "all" if kind == "carousel" else "first"}
    if channel == "google":
        return {"text": google_summary(payload), "images": "first", "button": google_action(kind, profile)}
    return {"text": payload.get("caption"), "images": "all"}


def problems(kind: str, payload: dict, channel: str) -> tuple[list[str], list[str]]:
    """(blocking problems, notes) for one channel, on top of the shared photo checks."""
    if channel == "instagram":
        return [], []
    if channel not in channels_for(kind):
        return [f"{LABEL[channel]} can't show a story; post it on Instagram only."], []
    out, notes = [], []
    if channel == "google":
        text = google_summary(payload)
        if _PHONE.search(text):
            out.append("Google rejects posts with a phone number in the text; take it out (the Call button adds it).")
        if not text:
            out.append("The caption is empty.")
        if kind == "carousel":
            notes.append("Google shows one photo: only the first slide is posted there.")
        if len(payload.get("caption") or "") > SUMMARY_MAX:
            notes.append("The caption is shortened to 1,500 characters for Google.")
    return out, notes


# ── Publishing (called by marketing_publish_service.publish_attempt with the rendered JPEGs) ─────────────────────────

def publish_facebook(pub, attempt, item, payload: dict, images: list[MediaAsset], url_for: Callable, save: Callable) -> list[str]:
    """Returns the published post ids. Unpublished photo ids are saved before the post so a retry reuses them."""
    message = facebook_message(payload)
    if item.kind == "carousel" and len(images) > 1:
        uploaded = list(attempt.container_ids or [])
        for asset in images[len(uploaded):]:
            uploaded.append(pub.upload_unpublished(url_for(asset)))
            attempt.container_ids = list(uploaded)
            save()
        return [pub.multi_photo_post(uploaded, message)]
    return [pub.photo_post(url_for(images[0]), message)]


def publish_google(pub, config: dict, item, payload: dict, profile: dict, images: list[MediaAsset], url_for: Callable) -> list[str]:
    account, location = config.get("account"), config.get("location")
    if not account or not location:
        raise PublishError("Choose which Google Business location to post to.", transient=False)
    post = pub.create_post(account, location, google_summary(payload), url_for(images[0]) if images else None,
                           google_action(item.kind, profile))
    return [post.get("name") or ""]
