"""Demo data for the Instagram toolkit screens (phases 1-4), used by seed_local_demo.py. Made-up business only.

No LLM call: the "AI" drafts are fixed text run through the same code the real flow uses (humanizer, hook scorer,
competitor ranking, profile checklist), so every new screen has something to show.
"""
from app.models.marketing import MarketingCompetitor, MarketingCompetitorPost
from app.schemas.sops import StartIn
from app.services import marketing_content_service as content_svc
from app.services import marketing_hooks as hooks
from app.services import marketing_humanize as human
from app.services.sops import generate
from app.services.sops import service as sop_svc

AI_POST = {"caption": "Wake up by the Kabini backwaters—chai on the caravan step at 6, mist still on the water. "
                      "Unlock a seamless weekend away from the city.​\n\nComment KABINI for the December dates.",
           "hashtags": ["#kabini", "#caravanstay", "#karnatakatourism"], "media": {"alt_text": "caravan by the river at dawn"},
           "comment_dm": {"keyword": "KABINI", "message": "Here it is: the December weekends we still have, 6-8 and 13-15. "
                          "Reply with the one you like and we'll hold it for a day. Which weekend suits you?",
                          "public_reply": "Sent you a DM."}}
REEL = {"caption": "A night parked under the stars near Coorg. DM us COORG for dates.",
        "clips": [{"seconds": 3, "caption": "Coorg at night", "media": {"alt_text": "caravan under stars"}},
                  {"seconds": 4, "caption": "Coffee at sunrise", "media": {"alt_text": "coffee on the step"}},
                  {"seconds": 4, "caption": "DM us COORG", "media": {"alt_text": "the road through the estate"}}]}
HOOKS = {"options": [
    {"formula_id": 3, "spoken": "Nobody tells you Coorg is quietest after midnight.", "on_screen": "COORG AFTER MIDNIGHT"},
    {"formula_id": 17, "spoken": "Hotel versus caravan in Coorg: one of them wins on stars.", "on_screen": "HOTEL vs CARAVAN"},
    {"formula_id": 24, "spoken": "Hey everyone, so this is our new trip.", "on_screen": "NEW TRIP"}],
    "script": [{"line": "Most people see Coorg from a hotel window and miss the sky.", "shot": "caravan under stars"},
               {"line": "We park on the estate, kettle on, no city light for 20 km.", "shot": "coffee on the step"},
               {"line": "DM us COORG and we'll send the free weekends for Coorg after midnight.", "shot": "the road"}]}
COMPETITORS = {"hillroamers": [(48000, "Nobody tells you the Western Ghats are best in the rain."), (11000, "Our new van"),
                               (9500, "Packing list"), (12000, "Sunset at Chikmagalur"), (10500, "Guest review")],
               "vanlife.blr": [(6000, "Stop booking hill stations in May."), (5500, "Breakfast"), (6400, "Road trip"),
                               (3100, "Weekend offer")]}


def seed(db, tenant, owner) -> None:
    tid = tenant.id
    # Phase 1: an AI draft cleaned by the humanizer (Undo available) + its caption checks.
    post = content_svc.create_item(db, tid, kind="post", title="Kabini: mornings on the water", actor_id=owner.id)
    cleaned, record = human.clean_payload(AI_POST, human.keep_words(tenant))
    content_svc.add_version(db, tid, post.id, cleaned, origin="ai", actor_id=owner.id, note="Demo draft",
                            prompt_version="marketing-content-v10", model="demo", humanize=record)
    # Phase 2: a reel draft with three scored opening lines and a timed shot list.
    reel = content_svc.create_item(db, tid, kind="reel", title="Coorg after midnight", actor_id=owner.id)
    content_svc.add_version(db, tid, reel.id, REEL, origin="ai", actor_id=owner.id, prompt_version="marketing-content-v10",
                            model="demo")
    reel.hook_plan = {**hooks.build_plan(HOOKS, "handoff"), "prompt_version": "marketing-reel-hooks-v1", "model": "demo"}
    # Phase 3: the Instagram profile checklist, two manual steps ticked (pinned posts, highlights).
    inst = sop_svc.start(db, tenant, StartIn(template_key="instagram_profile"), owner.id)
    generate.make_version(db, tenant, inst, reason="first", actor_id=owner.id, use_ai=False)
    for key in ("pinned", "highlights"):
        sop_svc.mark(db, inst, key, "done", owner.id)
    # Phase 4: competitor posts pasted by a person, with views, ranked against each account's own median.
    for handle, posts in COMPETITORS.items():
        comp = MarketingCompetitor(tenant_id=tid, handle=handle, created_by=owner.id)
        db.add(comp)
        db.flush()
        for i, (views, caption) in enumerate(posts):
            db.add(MarketingCompetitorPost(tenant_id=tid, competitor_id=comp.id, source="manual", views=views,
                                           media_type="REELS", caption=caption, created_by=owner.id,
                                           permalink=f"https://www.instagram.com/reel/DEMO{handle[:4]}{i}/",
                                           posted_at=f"2026-11-{14 - i:02d}"))
    db.commit()
