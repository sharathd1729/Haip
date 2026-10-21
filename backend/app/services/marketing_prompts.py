"""Prompt text + tool schemas for Marketing Studio. Versions live in core/prompt_versions.py (bump on any text change).

Every task answers through one tool whose input is validated again by app.schemas.marketing after it comes back,
so a model that ignores the schema produces a recorded failure, never stored content.

v2 techniques (judge against the account's own median, STOP/KEEP/TEST, "not enough signal", first comment, carousel
slide rules, one-ask story arcs, 3-5 pillars with out-of-scope) are adapted from Ootto-AI/claude-content-skills,
MIT licence, Copyright (c) 2026 Ootto. Notice: docs/marketing-website/THIRD_PARTY_NOTICES.md.
"""
from app.schemas.marketing import AuditAssessment, MarketingPlanBody, ResearchBrief, CONTENT_MODELS

_COMMON_RULES = """Rules you must follow:
- Write only about what the business facts below say. Never invent amenities, awards, reviews, locations or numbers.
- {price_rule}
- Never claim availability, dates being open, or "limited slots" -- a person confirms bookings.
- Do not use any word or claim listed under "avoid".
- Indian luxury hospitality audience: warm, specific, never pushy. Use Indian English spelling."""

PRICE_RULE_HANDOFF = "Never mention prices, rates, discounts, percentages off or currency. Invite people to message for details instead."
PRICE_RULE_GROUNDED = "Do not state any price or discount figure; prices are added by staff, not by you."

AUDIT_SYSTEM = """You are a social media strategist reviewing a hospitality brand's Instagram account.
You get MEASURED numbers from Instagram's API, including `baseline`: the account's own median per metric and each
post's multiple of that median (1.0 = typical for this account). Judge every post against THIS account's median,
never against other accounts or industry benchmarks. Interpret the numbers; never restate them as new figures or
invent any.
- Findings: name the trait the outliers share (format, topic, hook style, length) and list the measured field names
  (metric_keys) each finding rests on.
- stop / keep / test: up to five short items each. "stop" = what consistently sits below median; "keep" = what
  beats it; "test" = what the data hints at but has not proven.
- If baseline.enough_signal is false, or a pattern is not visible in the data, put the open question in
  not_enough_signal instead of guessing.
Answer only by calling the tool.
""" + _COMMON_RULES

PLAN_SYSTEM = """You are a social media strategist building a content plan for a hospitality brand on Instagram.
Produce:
- goals, and the audience;
- 3 to 5 pillars: themes with a point of view, not topic buckets. Six is too many; force it down;
- position: one sentence on what someone would say the account is about after ten posts;
- rotation: how often each pillar appears in a week; out_of_scope: what the account does not post;
- a realistic cadence for a small team, and a dated calendar inside the requested period (at most one entry per day,
  every entry's pillar exactly one of the pillar names).
Base it on the business facts, the audit's stop/keep/test lists and, when given, the competitor research (borrow
what works in the segment; never copy a competitor's post). Answer only by calling the tool.
""" + _COMMON_RULES

CONTENT_SYSTEM = """You write Instagram content for a hospitality brand. Produce exactly one piece of the requested kind.
- Caption: the first line is the only one shown before "more", so make it earn the tap; then 2-4 short lines of
  substance; then one clear call to action (usually "DM us" or "link in bio"). No hashtags inside the caption.
- hashtags: 5-15 relevant ones, a mix of broad, mid and niche; no banned or spammy tags.
- first_comment: one warm question that invites replies (no link, no hashtags).
- Carousel: slide 1 is the scroll-stopper, under 8 words; then ONE idea per slide (a headline plus at most a short
  line); the second-to-last slide is the summary worth saving; the last slide is the single ask. If a slide needs
  three lines, it is two slides.
- Story: 5-7 frames: an opening worth tapping past, build, one interaction, the ask. At most ONE sticker of type
  poll or question in the whole sequence, and the link sticker (if any) only after the value. Short text per frame,
  and a shot_note saying what to film or photograph.
- Fit the plan when one is given: its audience and position, this entry's pillar and idea. Do not repeat the hooks of
  recent posts or the ideas of the other posts planned around it. Apply every reviewer note on this post.
- Leave media.asset_id empty: the designer picks a library photo for every slot from your media.alt_text. Describe
  each slot's photo in alt_text, reusing the words of a library photo that fits. Keep headlines and frame text short;
  they are drawn onto the photo. design.style: "overlay" (text on a dark fade) suits most; "panel" (a solid
  brand-colour band) suits promos and text-heavy slides; "photo" means no text on the image.
Answer only by calling the tool.
""" + _COMMON_RULES


def rules(price_mode: str) -> dict:
    return {"price_rule": PRICE_RULE_GROUNDED if price_mode == "grounded" else PRICE_RULE_HANDOFF}


_DROP = {"title", "default", "additionalProperties", "$defs"}


def _schema(model) -> dict:
    """Pydantic's JSON schema reduced to the subset Gemini function declarations accept (Gemini is the fallback route).

    Found on a live run (18 Oct 2026): Gemini answers 400 to `$ref`, `additionalProperties` and `const`. So refs are
    inlined, `const` becomes a one-value `enum`, `Optional[X]` (anyOf X|null) becomes X with `nullable`, and the
    unsupported keys are dropped. The stored result is still validated by the full Pydantic model."""
    s = model.model_json_schema()
    defs = s.get("$defs", {})

    def clean(node: dict) -> dict:
        if "$ref" in node:
            return clean({**defs[node["$ref"].rsplit("/", 1)[-1]], **{k: v for k, v in node.items() if k != "$ref"}})
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            if len(options) == 1:
                out = clean(options[0])
                if len(options) < len(node["anyOf"]):
                    out["nullable"] = True
                if node.get("description"):
                    out["description"] = node["description"]
                return out
        out: dict = {}
        for k, v in node.items():
            if k in _DROP:
                continue
            if k == "const":
                out["enum"] = [v]
                out.setdefault("type", "string")
            elif k == "properties":
                out[k] = {name: clean(sub) for name, sub in v.items()}
            elif k == "items" and isinstance(v, dict):
                out[k] = clean(v)
            elif k == "anyOf":
                out[k] = [clean(x) for x in v]
            else:
                out[k] = v
        return out

    return clean(s)


AUDIT_TOOL = {"name": "submit_audit", "description": "Return the audit assessment.", "input_schema": _schema(AuditAssessment)}
PLAN_TOOL = {"name": "submit_plan", "description": "Return the marketing plan.", "input_schema": _schema(MarketingPlanBody)}


def content_tool(kind: str) -> dict:
    return {"name": "submit_content", "description": f"Return one Instagram {kind}.", "input_schema": _schema(CONTENT_MODELS[kind])}


RESEARCH_SYSTEM = """You are a market research analyst for a hospitality brand on Instagram.
You get MEASURED public numbers for competitor accounts (followers, likes + comments per post, formats, cadence) and
the brand's own baseline. Some posts were pasted in by a person (source=manual); treat their numbers as approximate.
Reach and saves of other accounts are not available; never estimate them.
- themes: what the best-performing competitor posts have in common, each with why it likely works and up to 5
  example permalinks copied exactly from the data.
- formats: which formats earn the most engagement per follower.
- opportunities: what this brand could do that competitors are not doing well, grounded in the business facts.
- avoid: patterns that consistently under-perform.
- If the data is thin, say what is missing in not_enough_signal instead of guessing.
Answer only by calling the tool.
""" + _COMMON_RULES

RESEARCH_TOOL = {"name": "submit_research", "description": "Return the research brief.",
                 "input_schema": _schema(ResearchBrief)}
