"""Prompt text + tool schemas for Marketing Studio. Versions live in core/prompt_versions.py (bump on any text change).

Every task answers through one tool whose input is validated again by app.schemas.marketing after it comes back,
so a model that ignores the schema produces a recorded failure, never stored content.
"""
from app.schemas.marketing import AuditAssessment, MarketingPlanBody, CONTENT_MODELS

_COMMON_RULES = """Rules you must follow:
- Write only about what the business facts below say. Never invent amenities, awards, reviews, locations or numbers.
- {price_rule}
- Never claim availability, dates being open, or "limited slots" -- a person confirms bookings.
- Do not use any word or claim listed under "avoid".
- Indian luxury hospitality audience: warm, specific, never pushy. Use Indian English spelling."""

PRICE_RULE_HANDOFF = "Never mention prices, rates, discounts, percentages off or currency. Invite people to message for details instead."
PRICE_RULE_GROUNDED = "Do not state any price or discount figure; prices are added by staff, not by you."

AUDIT_SYSTEM = """You are a social media strategist reviewing a hospitality brand's Instagram account.
You get MEASURED numbers from Instagram's API. Interpret them; never restate them as new numbers or invent any.
For every finding list the measured field names (metric_keys) it is based on. If data is missing, say what is missing
instead of guessing. Answer only by calling the tool.
""" + _COMMON_RULES

PLAN_SYSTEM = """You are a social media strategist building a content plan for a hospitality brand on Instagram.
Produce goals, audience, 3-5 content pillars, a realistic cadence for a small team, and a dated calendar inside the
requested period (at most one entry per day). Base it on the business facts and, when given, the audit findings.
Answer only by calling the tool.
""" + _COMMON_RULES

CONTENT_SYSTEM = """You write Instagram content for a hospitality brand. Produce exactly one piece of the requested kind.
Captions: a strong first line, short paragraphs, one clear call to action (usually "DM us" or "link in bio").
Hashtags: 5-15 relevant ones, no banned or spammy tags. Leave media.asset_id empty; staff pick photos.
Write alt_text describing the kind of photo that should go with each slide or frame.
Answer only by calling the tool.
""" + _COMMON_RULES


def rules(price_mode: str) -> dict:
    return {"price_rule": PRICE_RULE_GROUNDED if price_mode == "grounded" else PRICE_RULE_HANDOFF}


def _schema(model) -> dict:
    """Pydantic's JSON schema with every $ref inlined (Gemini function declarations, the fallback route, reject $ref)."""
    s = model.model_json_schema()
    defs = s.pop("$defs", {})

    def inline(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(dict(defs[node["$ref"].rsplit("/", 1)[-1]]))
            return {k: inline(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [inline(x) for x in node]
        return node

    return inline(s)


AUDIT_TOOL = {"name": "submit_audit", "description": "Return the audit assessment.", "input_schema": _schema(AuditAssessment)}
PLAN_TOOL = {"name": "submit_plan", "description": "Return the marketing plan.", "input_schema": _schema(MarketingPlanBody)}


def content_tool(kind: str) -> dict:
    return {"name": "submit_content", "description": f"Return one Instagram {kind}.", "input_schema": _schema(CONTENT_MODELS[kind])}
