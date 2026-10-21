"""Prompts and tool schemas for the AI web developer (website_ai_service). Bump the version in core/prompt_versions.py
("website_generate", "website_edit") whenever the text below changes.

The model never writes HTML or a whole document. It returns a list of small operations on block ids it was shown;
website_ai_service.apply_ops validates every one against website_blocks.json and refuses the rest with a reason."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.services.marketing_prompts import _schema


class Op(BaseModel):
    op: Literal["set", "add_block", "remove_block", "move_block", "add_page", "set_theme", "set_seo", "set_site"]
    page_id: Optional[str] = Field(None, description="Page id from the outline (not needed for set_theme/set_site)")
    block_id: Optional[str] = Field(None, description="Block id from the outline (set, remove_block, move_block). For "
                                    "add_block, choose a new id like 'new1' and use it in later set operations")
    field: Optional[str] = Field(None, description="Field key for set / set_seo (title|description) / set_site (tagline)")
    value: Optional[str] = Field(None, description="New text. For list fields: one item per line; FAQ items as 'question | answer'")
    block_type: Optional[str] = Field(None, description="Section type for add_block")
    after_block_id: Optional[str] = Field(None, description="add_block: insert after this block; empty = at the end")
    to_index: Optional[int] = Field(None, ge=0, le=40, description="move_block: new position, 0 = top")
    title: Optional[str] = Field(None, description="add_page: page name")
    path: Optional[str] = Field(None, description="add_page: address like /long-stays")
    pack: Optional[str] = None
    personality: Optional[str] = None


class Changes(BaseModel):
    reply: str = Field(description="One or two plain sentences to the owner saying what you changed, or why not")
    ops: list[Op] = Field(default_factory=list, max_length=40)
    refused: list[str] = Field(default_factory=list, max_length=10,
                               description="Things you were asked for but must not do, each with the reason")


EDIT_TOOL = {"name": "submit_site_changes",
             "description": "Return the changes to make to the website draft as operations, plus a short reply.",
             "input_schema": _schema(Changes)}

_RULES = """Hard rules:
- Use ONLY facts given in BUSINESS FACTS and the current page text. Never invent amenities, awards, distances, guest
  numbers, ratings, reviews, testimonials or guest names. If a fact you need is missing, leave it out and say so.
- Never write a price, discount amount, percentage off, or any ₹/Rs/INR figure. Prices and offers come from HAIP
  Bookings and are shown by the site itself. {price_rule}
- Never add or edit Reviews items: real reviews are pasted by the owner. You may change a Reviews heading.
- System sections (StayDetail, BookingEngine, ManageBooking, Policies) can't be added or removed; policies text comes
  from HAIP business data.
- Write in clear Indian English for travellers: specific, warm, no clichés ("nestled", "haven", "oasis", "unparalleled",
  "breathtaking", "luxurious experience"), no exclamation marks, no emoji. Short sentences.
- Respect the length limit of every field in the SECTION SPEC. Headlines may wrap one word in *stars* for colour.
- Only operate on page_id and block_id values from the OUTLINE. Answer only through the tool."""

EDIT_SYSTEM = """You are the web developer and copywriter for a hospitality business's website, inside HAIP. The owner
asks for changes in plain words; you return precise operations on the site's draft. Keep everything you weren't asked
to change exactly as it is. Prefer the smallest set of operations that does what was asked.

""" + _RULES

GENERATE_SYSTEM = """You are writing the first real version of a hospitality business's website, inside HAIP. You get
the page outline (every block with its current placeholder text) and the business facts. Rewrite the copy of every
text field so the site reads like this specific business: hero headlines, intros, highlights, about text, FAQ (only
questions the facts can answer), call-to-action bands and every page's search title (max 60 chars) and description
(120-160 chars). You may pick a better theme pack and personality for the region and tone. Use "set", "set_seo",
"set_site" and "set_theme" operations; add a Highlights or FAQ block only when the facts support it.

""" + _RULES


def rules_for(price_mode: str) -> str:
    return ("Never mention prices at all, not even 'affordable' claims tied to money; guests ask on WhatsApp."
            if price_mode == "handoff" else "You may say prices are shown on the booking page.")
