"""The typed change catalogue: every change the learning loop may test, each mapped to an EXISTING control and an autonomy area.

  type                         area     control              diff
  playbook_wording             replies  sales_playbook       {field: opening_line|qualification_questions|objection_answers|
                                                              follow_up_style, value}
  early_package_share          replies  sales_playbook       {}  (share the best-matching published package + day plan first)
  kit_before_discount          prices   sales_playbook       {segments?: ["5-6", "7+"]}  (offer a kit before any discount)
  price_disclosure_per_package prices   price_disclosure     {packages: [published retail package keys]}  ("from Rs X + GST")
  consult_threshold            prices   consult_threshold    {above_inr: N}  (a quote above N goes to a person; only tightens)
  route_suggestion             routes   route_map            {ask: "goa", route_key: published destination/package key}
  followup_timing              replies  followup_timing      {playbook: "proposal_followup", first_hours: 2..48}

validate() normalises a diff or raises ChangeRefused. It is the guardrail at the door: published data only (never a draft, never
a b2b package), no figure, link or discount promise in any wording, numbers inside their limits. A change can therefore never
widen a guardrail; the code guards (price floor, discount policy, published data, escalation rules) apply to both arms anyway.
Changing a price, a policy or a discount RULE is not in this catalogue at all: it stays a suggestion for the owner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.sales_playbook import SalesPlaybook

METRICS = ("dm_to_lead", "lead_to_quote", "quote_to_won", "guest_reply")


@dataclass(frozen=True)
class ChangeType:
    key: str
    area: str
    control: str
    label: str
    metric: str


TYPES: dict[str, ChangeType] = {t.key: t for t in (
    ChangeType("playbook_wording", "replies", "sales_playbook", "Change the sales playbook wording", "dm_to_lead"),
    ChangeType("early_package_share", "replies", "sales_playbook", "Share a published package in the first reply", "lead_to_quote"),
    ChangeType("kit_before_discount", "prices", "sales_playbook", "Offer a kit before any discount", "quote_to_won"),
    ChangeType("price_disclosure_per_package", "prices", "price_disclosure", "Show published prices for some packages", "lead_to_quote"),
    ChangeType("consult_threshold", "prices", "consult_threshold", "Hand big quotes to a person", "quote_to_won"),
    ChangeType("route_suggestion", "routes", "route_map", "Suggest a published route for an unavailable ask", "dm_to_lead"),
    ChangeType("followup_timing", "replies", "followup_timing", "Change when the first quote follow-up goes", "quote_to_won"),
)}
WORDING_FIELDS = ("opening_line", "qualification_questions", "objection_answers", "follow_up_style")
SEGMENTS = ("1-2", "3-4", "5-6", "7+")
FOLLOWUP_PLAYBOOKS = ("proposal_followup",)
EARLY_RULE = "In your first reply, name the ONE published package that best fits what the guest said and offer its day plan."
_URL = re.compile(r"https?://|www\.", re.I)
_DISCOUNT = re.compile(r"\b(discount|% ?off|cheaper|lowest price|deal)\b", re.I)


class ChangeRefused(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _texts(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, dict):
        return [str(k) for k in value] + [str(v) for v in value.values()]
    return []


def _clean_wording(value) -> None:
    from app.services.price_policy import detect_price
    for t in _texts(value):
        if detect_price(t) or re.search(r"\d{3,}", t):
            raise ChangeRefused("figure_in_wording", "Wording may not contain a price or any figure.")
        if _URL.search(t):
            raise ChangeRefused("link_in_wording", "Wording may not contain a link.")
        if _DISCOUNT.search(t):
            raise ChangeRefused("discount_in_wording", "Wording may not promise a discount.")


def published(db: Session, tenant_id: str, kind: str) -> dict[str, str]:
    """{key: name} of PUBLISHED, effective records of a kind (packages: retail only, never b2b)."""
    from app.services import business_data_service as bds
    out = {}
    for rec in bds.list_effective(db, tenant_id, kind):
        try:
            data = bds.parse(rec)
        except Exception:  # noqa: BLE001 -- a record that no longer parses is not offered
            continue
        if kind == "package" and getattr(data, "audience", None) == "b2b":
            continue
        out[rec.key] = getattr(data, "name", rec.key)
    return out


def playbook_after(pb: dict, change_type: str, diff: dict, *, route_names: Optional[dict] = None) -> dict:
    """The sales playbook with one change applied (pure). Raises ChangeRefused when the result would not validate."""
    out = {**pb, "rules": list(pb.get("rules") or [])}
    if change_type == "playbook_wording":
        out[diff["field"]] = diff["value"]
    elif change_type == "early_package_share":
        if EARLY_RULE not in out["rules"]:
            out["rules"].append(EARLY_RULE)
    elif change_type == "kit_before_discount":
        out["add_value_before_discount"] = True
        segs = diff.get("segments") or []
        rule = ("Before any talk of a discount, offer a kit or an experience instead"
                + (f" (groups of {', '.join(segs)})." if segs else "."))
        if rule not in out["rules"]:
            out["rules"].append(rule)
    for ask, name in (route_names or {}).items():
        line = f'When a guest asks for "{ask}", say we do not run it and suggest our published route "{name}" instead.'
        if line not in out["rules"]:
            out["rules"].append(line)
    try:
        return SalesPlaybook.model_validate(out).model_dump()
    except Exception as exc:  # noqa: BLE001
        raise ChangeRefused("playbook_invalid", f"The playbook would not be valid: {exc}"[:300])


def validate(db: Session, tenant, change_type: str, diff: dict) -> dict:
    if change_type not in TYPES:
        raise ChangeRefused("unknown_change", f"Unknown change type {change_type!r}.")
    diff = dict(diff or {})
    if change_type == "playbook_wording":
        if diff.get("field") not in WORDING_FIELDS:
            raise ChangeRefused("bad_field", f"field must be one of {', '.join(WORDING_FIELDS)}")
        _clean_wording(diff.get("value"))
        from app.services import sales_playbook
        playbook_after(sales_playbook.get(tenant).model_dump(), change_type, diff)
        return {"field": diff["field"], "value": diff.get("value")}
    if change_type == "early_package_share":
        if not published(db, tenant.id, "package"):
            raise ChangeRefused("nothing_published", "No published package to share.")
        return {}
    if change_type == "kit_before_discount":
        segs = [s for s in (diff.get("segments") or []) if s in SEGMENTS]
        return {"segments": segs}
    if change_type == "price_disclosure_per_package":
        pkgs = published(db, tenant.id, "package")
        keys = [k for k in dict.fromkeys(diff.get("packages") or []) if isinstance(k, str)]
        bad = [k for k in keys if k not in pkgs]
        if not keys or bad or len(keys) > 10:
            raise ChangeRefused("not_published", f"Only published retail packages may show a price (refused: {bad or 'none given'}).")
        return {"packages": keys}
    if change_type == "consult_threshold":
        try:
            above = int(diff.get("above_inr"))
        except (TypeError, ValueError):
            raise ChangeRefused("bad_amount", "above_inr must be a whole number of rupees.")
        if not 1000 <= above <= 1_000_000:
            raise ChangeRefused("bad_amount", "above_inr must be between 1,000 and 10,00,000.")
        return {"above_inr": above}
    if change_type == "route_suggestion":
        ask = " ".join(str(diff.get("ask") or "").lower().split())[:40]
        key = diff.get("route_key")
        routes = {**published(db, tenant.id, "destination"), **published(db, tenant.id, "package")}
        if not ask or key not in routes:
            raise ChangeRefused("not_published", "Suggest only a published route or package for a named ask.")
        return {"ask": ask, "route_key": key}
    if change_type == "followup_timing":
        pb = diff.get("playbook") or "proposal_followup"
        try:
            hours = float(diff.get("first_hours"))
        except (TypeError, ValueError):
            raise ChangeRefused("bad_hours", "first_hours must be a number.")
        if pb not in FOLLOWUP_PLAYBOOKS or not 2 <= hours <= 48:
            raise ChangeRefused("bad_hours", "The first follow-up may move between 2 and 48 hours.")
        return {"playbook": pb, "first_hours": hours}
    raise ChangeRefused("unknown_change", change_type)


def describe(change_type: str, diff: dict) -> str:
    t = TYPES[change_type]
    if change_type == "playbook_wording":
        return f"{t.label}: {diff['field'].replace('_', ' ')}"
    if change_type == "price_disclosure_per_package":
        return f"{t.label}: {', '.join(diff['packages'])}"
    if change_type == "consult_threshold":
        return f"{t.label} (above Rs {diff['above_inr']:,})"
    if change_type == "route_suggestion":
        return f"{t.label}: {diff['ask']} -> {diff['route_key']}"
    if change_type == "followup_timing":
        return f"{t.label}: {diff['first_hours']:g} h"
    return t.label


# ── the base value of a control, and keeping / undoing a change on it ─────────────────────────────────────────────

def snapshot(tenant, change_type: str) -> object:
    from app.services import sales_playbook
    from app.services.learning import settings as ls
    control = TYPES[change_type].control
    if control == "sales_playbook":
        return sales_playbook.get(tenant).model_dump()
    b = ls.base(tenant)
    return {"price_disclosure": b["price_disclosure_packages"], "consult_threshold": b["consult_price_above"],
            "route_map": b["route_map"], "followup_timing": b["followup_first_hours"]}[control]


def after_value(db: Session, tenant, change_type: str, diff: dict):
    before = snapshot(tenant, change_type)
    if TYPES[change_type].control == "sales_playbook":
        return playbook_after(before, change_type, diff)
    if change_type == "price_disclosure_per_package":
        return sorted(set(before) | set(diff["packages"]))
    if change_type == "consult_threshold":
        return diff["above_inr"] if before is None else min(int(before), diff["above_inr"])
    if change_type == "route_suggestion":
        return {**before, diff["ask"]: diff["route_key"]}
    return {**before, diff["playbook"]: diff["first_hours"]}


def write(db: Session, tenant, change_type: str, value, actor_id: Optional[str], *, actor: str) -> None:
    """Store ``value`` as the control's base (the caller audits the experiment transition)."""
    from app.services import sales_playbook
    from app.services.learning import settings as ls
    control = TYPES[change_type].control
    if control == "sales_playbook":
        sales_playbook.update(db, tenant, actor_id, SalesPlaybook.model_validate(value), actor=actor)
        return
    key = {"price_disclosure": "price_disclosure_packages", "consult_threshold": "consult_price_above",
           "route_map": "route_map", "followup_timing": "followup_first_hours"}[control]
    ls.set_base(tenant, key, value)
