"""Agent test bench (tau-bench style): run guest scenarios through the REAL reply pipeline and grade the outcome in code.

Used by two callers, never by production code:
  * tests/test_agent_bench.py   -- CI. The model is SCRIPTED (each scenario says what the classifier and the reply model return),
                                   so the checks pin the code-side guarantees: triggers fire, no unpublished / below-floor /
                                   invented price is sent, one holding reply, a consult opens, no payment link or booking
                                   without approval.
  * scripts/agent_bench.py      -- `--live`, never in CI: the real LLM router k times per scenario, pass^k per scenario.

A scenario (tests/fixtures/agent_bench/rathaa.json) = setup (price mode, hour, phone, channel, history), the guest's message,
the scripted classifier/reply (ignored live), and `expect` checks. Dates are relative: "{d+N}" = today + N days, "{peak}" = the
next 31 December (no published rate on purpose), "{quote_total:<package>}" = the price engine's total for that scenario's stay.
The world is Rathaa's published catalogue (scripts/data/ratha_catalogue_2026_10.json) re-dated to start today, two caravans that
travel 6 and Rathaa's sales playbook. Nothing leaves the process: every send and push is captured.
"""
from __future__ import annotations

import importlib.util
import json
import re
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import patch

from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[2]
FIXTURE = BACKEND / "tests" / "fixtures" / "agent_bench" / "rathaa.json"
CATALOGUE = BACKEND / "scripts" / "data" / "ratha_catalogue_2026_10.json"
IST = timezone(timedelta(hours=5, minutes=30))
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_KANNADA = re.compile(r"[ಀ-೿]")


def _load_script(name: str):
    path = BACKEND / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_scenarios(path: Path = FIXTURE) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["scenarios"]


# ── dates ────────────────────────────────────────────────────────────────────

def peak_day(today: date) -> date:
    """The next 31 December at least 3 days away (inside the catalogue's deliberate no-rate window)."""
    d = date(today.year, 12, 31)
    return d if (d - today).days >= 3 else date(today.year + 1, 12, 31)


def bench_valid(today: date) -> dict:
    peak = peak_day(today)
    return {"from": today.isoformat(), "peak_starts": (peak - timedelta(days=2)).isoformat(),
            "peak_ends": (peak + timedelta(days=1)).isoformat(), "to": (peak + timedelta(days=200)).isoformat()}


_DATE_TOKEN = re.compile(r"\{d\+(\d+)\}")
_PEAK_TOKEN = re.compile(r"\{peak(?:\+(\d+))?\}")


def resolve(value: Any, today: date, quotes: Optional[dict] = None) -> Any:
    """Fill {d+N}, {peak} and {quote_total:<pkg>} anywhere in a scenario value."""
    if isinstance(value, dict):
        return {k: resolve(v, today, quotes) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, today, quotes) for v in value]
    if not isinstance(value, str):
        return value
    out = _DATE_TOKEN.sub(lambda m: (today + timedelta(days=int(m.group(1)))).isoformat(), value)
    out = _PEAK_TOKEN.sub(lambda m: (peak_day(today) + timedelta(days=int(m.group(1) or 0))).isoformat(), out)
    for key, total in (quotes or {}).items():
        out = out.replace("{quote_total:" + key + "}", f"{int(float(total)):,}")
    return out


# ── the world ────────────────────────────────────────────────────────────────

@dataclass
class World:
    tenant: Any
    owner: Any
    manager: Any
    vehicles: list = field(default_factory=list)
    # brand_config keys every scenario starts from (the learning bench gate's treated learning_base); a scenario's own
    # setup is layered on top and never leaks into the next scenario.
    keep: dict = field(default_factory=dict)


def build_world(db: Session, today: Optional[date] = None, *, playbook: bool = True) -> World:
    """A fresh Rathaa-like workspace with the catalogue PUBLISHED (re-dated to start today) and two caravans."""
    from app.models.property import Property
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.services import authz_service
    from app.services import business_data_service as bds
    from app.services import sales_playbook
    today = today or date.today()
    t = Tenant(id=str(uuid.uuid4()), name="Rathaa (bench)", slug=f"bench-{uuid.uuid4().hex[:8]}", plan="growth",
               wa_ai_mode_default="autonomous", ig_ai_mode_default="autonomous", wa_ai_confidence_threshold=0.6,
               ig_ai_confidence_threshold=0.6, brand_config={})
    db.add(t)
    db.flush()
    authz_service.seed_default_capabilities(db, t.id)
    users = []
    for role in (UserRole.OWNER, UserRole.MANAGER):
        u = User(id=str(uuid.uuid4()), tenant_id=t.id, name=f"Bench {role.value}", email=f"{role.value}-{uuid.uuid4().hex[:6]}@bench.test",
                 hashed_password="!", role=role, is_active=True)
        db.add(u)
        users.append(u)
    vehicles = []
    from app.models.property import RatePlan
    for name in ("Ratha 1", "Ratha 2"):
        p = Property(id=str(uuid.uuid4()), tenant_id=t.id, name=name, slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan",
                     max_adults=6, max_children=0, home_base="Bengaluru")
        db.add(p)
        db.add(RatePlan(id=str(uuid.uuid4()), tenant_id=t.id, property_id=p.id, name="Day rate", base_price_per_night=45000))
        vehicles.append(p)
    db.commit()
    imp = _load_script("import_ratha_catalogue")
    with open(CATALOGUE, encoding="utf-8") as fh:
        catalogue = json.load(fh)
    catalogue["valid"] = bench_valid(today)
    for kind, key, data in imp.build(catalogue):
        draft = bds.create_draft(db, t.id, kind, key, data, None)
        bds.publish(db, t.id, draft.id, None)
    if playbook:
        sales_playbook.update(db, t, None, _load_script("seed_ratha_playbook").RATHA_PLAYBOOK, actor="agent_bench")
    db.commit()
    return World(tenant=t, owner=users[0], manager=users[1], vehicles=vehicles)


def configure(db: Session, world: World, setup: dict) -> None:
    """Per-scenario tenant settings (price mode, policy overrides). Commits."""
    cfg = {k: v for k, v in (world.tenant.brand_config or {}).items() if k == "sales_playbook"}
    cfg.update({k: dict(v) if isinstance(v, dict) else v for k, v in world.keep.items()})
    cfg["price_disclosure"] = setup.get("price_disclosure", "handoff")
    if setup.get("policy"):
        cfg["agent_policy"] = {"modes": dict(setup["policy"])}
    if setup.get("sales_agent"):
        cfg["sales_agent"] = {"mode": setup["sales_agent"]}
    if setup.get("learning_base"):                 # a learning-loop control as a kept change / treatment would set it
        cfg["learning_base"] = {**(cfg.get("learning_base") or {}), **setup["learning_base"]}
    if setup.get("learning"):                      # the owner's autonomy levels (brand_config.learning)
        cfg["learning"] = dict(setup["learning"])
    world.tenant.brand_config = cfg
    db.commit()


def precompute_quotes(db: Session, world: World, scenario: dict, today: date) -> dict:
    """{package: total} for "{quote_total:<package>}" placeholders, from the same engine the reply path uses."""
    from app.services import sales_gateway
    want = set(re.findall(r"\{quote_total:([a-z0-9-]+)\}", json.dumps(scenario)))
    if not want:
        return {}
    c = resolve(scenario.get("classify") or {}, today)
    out = {}
    for key in want:
        res = sales_gateway.quote_package(db, world.tenant.id, key, date.fromisoformat(c["check_in"]),
                                          date.fromisoformat(c["check_out"]), int(c.get("adults") or 2), int(c.get("children") or 0))
        if res.ok:
            out[key] = res.data["total"]
    return out


# ── running one scenario ─────────────────────────────────────────────────────

class ScriptedLLM:
    """get_llm stand-in: the classifier returns ``classify``, the reply model returns ``reply``; prompts are recorded."""

    def __init__(self, classify: dict, reply: dict):
        self.classify, self.reply, self.prompts = classify, reply, []

    def __call__(self, task):
        outer = self

        class _LLM:
            provider = "scripted"

            async def complete(self, **kwargs):
                if task == "quick_classify":
                    return {"tool_use": outer.classify}
                outer.prompts.append(kwargs.get("system_prompt") or "")
                return {"tool_use": outer.reply}
        return _LLM()


def _at_hour(hour: Optional[int]) -> Optional[datetime]:
    if hour is None:
        return None
    local = datetime.now(IST).replace(hour=int(hour), minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


def run_scenario(db: Session, world: World, scenario: dict, *, today: Optional[date] = None,
                 llm_factory: Optional[Callable] = None) -> dict:
    """Seed the conversation, run concierge_draft once, and return everything the checks read."""
    from app.models.agent_consult import AgentConsult
    from app.models.conversation import ChannelType, Conversation, Message
    from app.models.guest import Guest
    from app.models.sales_action import SalesAction
    from app.models.property import Stay
    from app.workers.tasks.concierge_draft import concierge_draft
    today = today or date.today()
    setup = scenario.get("setup") or {}
    configure(db, world, setup)
    quotes = precompute_quotes(db, world, scenario, today)
    s = resolve(scenario, today, quotes)
    t = world.tenant
    channel = ChannelType.INSTAGRAM if setup.get("channel") == "instagram" else ChannelType.WHATSAPP
    has_phone = setup.get("phone", True)
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name=setup.get("guest_name", "Priya Sharma"),
              phone=f"+9198{uuid.uuid4().int % 10**8:08d}" if has_phone else "",
              lead_identified_at=datetime.now(timezone.utc) if has_phone else None)
    db.add(g)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=channel, is_open=True, ai_mode="shadow")
    db.add(conv)
    db.flush()
    now = datetime.now(timezone.utc)
    history = s.get("history") or []
    for i, turn in enumerate(history):
        at = now - timedelta(minutes=5 * (len(history) - i) + 1)
        if turn.get("guest"):
            db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id, direction="inbound",
                           channel=channel.value, body=turn["guest"], created_at=at))
        if turn.get("ai"):
            db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id, direction="outbound", channel=channel.value,
                           body=turn["ai"], is_ai_generated=True, was_approved=True, sent_autonomously=True,
                           ai_intent=turn.get("intent"), created_at=at + timedelta(seconds=30)))
    inbound = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id, direction="inbound", channel=channel.value,
                      body=s["guest"], created_at=now - timedelta(seconds=20))
    db.add(inbound)
    db.commit()
    reply = s.get("reply") or {}
    llm = llm_factory() if llm_factory else ScriptedLLM(
        s.get("classify") or {"intent": "general"},
        {"reply": reply.get("text", ""), "confidence": reply.get("confidence", 0.9), "citations": [], "needs_human": False})
    sent: list[str] = []
    ids = (t.id, conv.id, g.id)
    at = _at_hour(setup.get("hour_ist"))
    with ExitStack() as stack:
        if not llm_factory or isinstance(llm, ScriptedLLM):
            stack.enter_context(patch("app.workers.tasks.concierge_draft.get_llm", llm))
        stack.enter_context(patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db))
        stack.enter_context(patch.object(db, "close"))
        stack.enter_context(patch("app.services.push_service.send_to_tenant"))
        stack.enter_context(patch("app.services.lead_alert_sender.deliver", return_value=False))
        stack.enter_context(patch("app.workers.tasks.concierge_draft._emit_sse"))
        stack.enter_context(patch("app.workers.tasks.concierge_draft._send_whatsapp_typing_indicator"))
        stack.enter_context(patch("app.services.agent_consult_notify.emit_sse"))
        for target in ("app.workers.tasks.send_whatsapp.send_whatsapp.delay", "app.workers.tasks.send_instagram_dm.send_instagram_dm.delay"):
            stack.enter_context(patch(target, side_effect=lambda **kw: sent.append(kw["message_id"])))
        stack.enter_context(patch("app.workers.tasks.sales_agent_tasks.send_quote.delay", side_effect=lambda *a, **k: sent.append("sales_quote")))
        if at is not None:
            dt = stack.enter_context(patch("app.services.agent_consult_settings.datetime"))
            dt.now.return_value = at
            dt.side_effect = lambda *a, **k: datetime(*a, **k)
            stack.enter_context(patch("app.services.agent_consult_service._now", return_value=at))
        concierge_draft.run(message_id=inbound.id, conversation_id=conv.id, tenant_id=t.id)
    tid, cid, gid = ids
    out_msgs = db.query(Message).filter_by(conversation_id=cid, direction="outbound").order_by(Message.created_at).all()
    draft = next((m for m in reversed(out_msgs) if m.is_ai_generated), None)
    consult = db.query(AgentConsult).filter_by(tenant_id=tid, conversation_id=cid).first()
    by_id = {m.id: m for m in out_msgs}
    return {
        "id": scenario["id"], "draft": draft.body if draft else None, "auto_sent": bool(draft and draft.sent_autonomously),
        "draft_facts": (draft.grounded_facts if draft else None) or [], "needs_human": draft.ai_needs_human_reason if draft else None,
        "consult": bool(consult), "reasons": list(consult.reason_codes) if consult else [],
        "holding": [m.body for m in out_msgs if m.sender_kind == "ai_holding"],
        "sent_bodies": [by_id[i].body for i in sent if i in by_id], "sales_quote_sent": "sales_quote" in sent,
        "sales_actions": db.query(SalesAction).filter_by(tenant_id=tid).filter(SalesAction.conversation_id == cid).count(),
        "bookings": db.query(Stay).filter_by(tenant_id=tid, guest_id=gid).count(),
        "prompt": (llm.prompts[-1] if isinstance(llm, ScriptedLLM) and llm.prompts else None),
    }


# ── grading ──────────────────────────────────────────────────────────────────

def grade(scenario: dict, out: dict, today: Optional[date] = None) -> list[dict]:
    """Every check in ``expect``, each {check, ok, detail}. Code-graded only."""
    from app.services.price_policy import money_figures, unsupported_figures
    exp = resolve(scenario.get("expect") or {}, today or date.today())
    res: list[dict] = []

    def add(name, ok, detail=""):
        res.append({"check": name, "ok": bool(ok), "detail": detail})

    if "consult" in exp:
        add("consult", out["consult"] == exp["consult"], f"consult={out['consult']} reasons={out['reasons']}")
    if exp.get("reasons_any"):
        add("reasons_any", set(exp["reasons_any"]) & set(out["reasons"]), f"got {out['reasons']}")
    if "auto_sent" in exp:
        add("auto_sent", out["auto_sent"] == exp["auto_sent"], f"auto_sent={out['auto_sent']}")
    if "holding_reply" in exp:
        n = len(out["holding"])
        add("holding_reply", (n == 1) if exp["holding_reply"] else n == 0, f"{n} holding replies")
    if exp.get("holding_regex"):
        add("holding_regex", any(re.search(exp["holding_regex"], h, re.I) for h in out["holding"]), str(out["holding"]))
    # Always: anything that actually went to the guest quotes only figures a live fact gave (no unpublished, invented or
    # below-floor price), and nothing was booked or sent as a quote/payment link without approval unless the scenario allows it.
    leaked = [b for b in out["sent_bodies"] if unsupported_figures(b, out["draft_facts"])]
    add("no_unsupported_figure_sent", not leaked, str(leaked)[:200])
    if exp.get("no_figure_sent"):
        add("no_figure_sent", not any(money_figures(b) for b in out["sent_bodies"]), str(out["sent_bodies"])[:200])
    if not exp.get("allow_payment_link"):
        add("no_payment_link_or_quote_sent_by_ai", not out["sales_quote_sent"])
    add("no_booking_created", out["bookings"] == 0, f"{out['bookings']} bookings")
    for key in ("draft_regex", "draft_not_regex"):
        if exp.get(key):
            hit = bool(out["draft"] and re.search(exp[key], out["draft"], re.I))
            add(key, hit if key == "draft_regex" else not hit, (out["draft"] or "")[:160])
    if exp.get("prompt_contains") and out.get("prompt") is not None:
        missing = [p for p in exp["prompt_contains"] if p not in out["prompt"]]
        add("prompt_contains", not missing, f"missing {missing}")
    if exp.get("language") and out["draft"] and out["auto_sent"]:
        pat = _DEVANAGARI if exp["language"] == "hi" else _KANNADA
        add("language", pat.search(out["draft"]), out["draft"][:80])
    return res


def passed(checks: list[dict]) -> bool:
    return all(c["ok"] for c in checks)
