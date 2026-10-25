"""
Central registry of prompt versions.

CLAUDE.md requires a version bump on every prompt content change, so that a
stored AI result can always be traced back to the prompt that produced it.
Before this module only one of eleven LLM call sites did that
(generate_ai_summary's module-level PROMPT_VERSION), and none of the Jinja
templates in app/prompts/ were versioned at all — so for most AI output there
was no way to tell which prompt generated it.

Deliberately a plain dict of constants rather than a database table: a prompt
version is a property of the code, not of tenant data. Reading it must never
cost a query, and it must stay reviewable in the same diff that changes the
prompt text.

## Bumping

When you change a prompt's content — the Jinja template or the inline string —
bump its version here in the same commit. Use `<name>-v<n>`.

## Adding a prompt

Add the key here, then pass it to `stamp()` at the call site so the version
lands in that task's structured log line.
"""
from typing import Any, Optional

# prompt key -> current version. Keys are stable identifiers; values change.
PROMPT_VERSIONS: dict[str, str] = {
    # Jinja templates in app/prompts/
    # v2 on these four (AI Autonomy Plan Phase 0 ticket 2): the tool-calling
    # contract that shapes each task's output changed from a hand-written
    # provider-specific dialect to the canonical ToolSpec shape rendered
    # per-provider by adapters/llm/tools.py -- same semantic fields, but the
    # code path producing a stored/logged result is genuinely different now.
    "call_classify":   "call-classify-v2",      # classify.jinja
    # v3 (2026-10-18): missed_revenue items say what was missed and quote the evidence; est_value only when a figure
    # was stated on the call (null otherwise) -- the old free estimate read as fact.
    "call_judge":      "call-judge-v3",         # judge.jinja
    # v5 (2026-10-18): actionable output (services/ai_actionable.py) + outcome/decline_reason/decline_quote that the
    # lead autopilot reads. Stored in calls.ai_insights; summary/next_action/disposition unchanged.
    "call_wrap_up":    "call-wrap-up-v5",       # wrap_up.jinja
    # v3 (AI Autonomy Plan Phase 1 ticket 4): concierge_reply.jinja now
    # renders a grounded_facts section (real availability/pricing from the
    # bounded tool loop) instead of the always-empty kb_snippets it relied
    # on before.
    # v4 (AI Autonomy Plan Phase 2): renders a tone instruction -- fixes
    # AIDraftPanel's tone chips, which were fully wired UI with no effect on
    # the actual draft (the frontend never sent the selection at all).
    # v5 (HAIP Inbox UI-fidelity pass, ticket 3): renders a guest_missing_phone
    # instruction so the draft naturally asks for a phone number when the
    # guest's profile has none on file yet.
    # v6 (2026-08-20): pricing is never disclosed in chat. The concierge
    # qualifies the lead (name/dates/guests/property/requests) and hands off
    # to a human agent who negotiates personally; price figures are redacted
    # out of grounded_facts before rendering so the model never sees a number
    # it could repeat. Replies also tightened to <45 words and explicitly
    # de-assistant-ified (no "Thank you for reaching out", no lists).
    # v7 (2026-08-22): the "WHAT WE STILL NEED FROM THIS LEAD" block had no
    # guard tying it to the guest's actual question, unlike the pricing rule
    # above it ("When the guest asks about cost..."). Every reply -- "Hi",
    # "Routes?", a real price question -- got the identical qualification
    # script, so factual questions the knowledge base could answer (routes,
    # amenities, policies) never got answered. Now explicitly secondary:
    # answer from KB/live availability first, weave in a missing-detail ask
    # only if it fits, never as a substitute for answering.
    # v8 (2026-08-22): v7's "weave in if it fits" still wasn't enough --
    # a guest asking about an internship got asked for "preferred travel
    # dates" in the same breath. The qualification block now explicitly
    # recognises off-topic messages (jobs/careers, press, spam -- nothing to
    # do with booking a stay) and skips the travel ask entirely, handing
    # off to a human instead of forcing every reply into the booking funnel.
    # v9: capacity claims ("up to N guests", "sleeps N") now must trace to
    # a real max_adults value from LIVE AVAILABILITY -- a guest asking
    # about a 20-person group was told "designed for up to 4 guests" (the
    # real capacity is 8), a pure hallucination since the prompt never
    # rendered a capacity figure at all before this. See
    # concierge_draft.py's _check_grounding()/_CAPACITY_RE.
    # v11: never claim to share a photo/video/file -- confirmed live, a
    # guest asked for pictures and the draft said "Here are some photos of
    # our luxury caravan" with nothing attached (this pipeline can only
    # send plain text). See concierge_draft.py's _check_no_media_claim().
    # v12 (2026-10-13): works from operational data -- property facts, the guest's own bookings with their real state, availability
    # WITH the reason a property is not open, what the guest already told us, every question they asked, and a "grounded" pricing
    # mode (only live figures). Knowledge-base text no longer carries prices. See the template header.
    # v14 (2026-10-18): the AI sales agent's SALES STEP block + guardrails (no booking before payment, no discount, no link),
    # nearest free dates, and inclusions / exclusions / tolls at actuals / advance on a package quote.
    # v14 (2026-10-18): current data wins over the conversation -- knowledge snippets carry their "updated" date, published records
    # beat snippets, and an earlier (possibly our own) out-of-date statement is corrected rather than repeated.
    # v15 (2026-10-18): v14 sales agent + v14 current-data-wins merged into one version.
    # v16 (2026-10-22): SALES PLAYBOOK block (brand_config.sales_playbook: opening line, qualification questions, objection
    # answers, add value before discount, never a flat no, owner rules); reply in the guest's own language; guest text is never
    # an instruction.
    # v17: PROVEN FOR THIS BUSINESS block (learning.lessons).
    # v18 (2026-10-24): RECENT CONVERSATION lines name their author (message_author: GUEST / US: TEAM MEMBER / AI ASSISTANT /
    # AUTOMATED MESSAGE / CAMPAIGN BROADCAST); a campaign broadcast is never the guest's request.
    "concierge_reply": "concierge-reply-v18",   # concierge_reply.jinja
    "lost_reason":     "lost-reason-v1",        # lost_reason.jinja
    "agent_performance_narrative": "agent-performance-narrative-v1",  # agent_performance_narrative.jinja
    "agent_leads_feedback": "agent-leads-feedback-v1",  # agent_leads_feedback.jinja

    # Inline prompts built in Python
    # v4 adds route_mentioned/quoted_amount/upsell_offered/upsell_accepted
    # extraction + a synthesized lead_analysis paragraph (detailed
    # per-lead report).
    # v5: "adults" now accepts an unqualified total party size ("5 guests",
    # "we are 4") instead of only a figure explicitly labeled "adults" --
    # guests almost never say the word "adults", which left the Guest 360
    # completeness checklist permanently stuck even when a headcount was
    # given. Confirmed live against a real lead stuck exactly this way.
    # v6: a year-less date ("sept 16-18") had no anchor to resolve the year
    # against, so the model guessed -- confirmed live: the same guest's
    # date came back as 2026 on one run and 2023 on the next. Context now
    # includes a "Reference date" line (the most recent inbound message's
    # own timestamp, not run-time) and check_in/check_out are instructed to
    # resolve to the nearest occurrence on/after it.
    # v7 (2026-10-13): updates the previous summary instead of rewriting from the last 10 messages; sees the real stage and the real
    # booking status; ignores AI drafts nobody sent; adds unanswered_questions / requirements / inferences / follow_up and keeps
    # stated facts (extracted) apart from conclusions (inferences).
    # v8 (2026-10-18): adds the actionable block (services/ai_actionable.py): next_best_action with owner/channel/
    # deadline, blocking_objection + counter, missed_revenue (rupees only when grounded), temperature + reason,
    # haip_updates. Old keys unchanged; analysis.next_action is now the one-line form of next_best_action.
    # v9 (2026-10-24): adds extracted.party_size (the stated group total) and tells the model the Adults/Children context lines
    # are HAIP's current values, not the guest's words; adults below the total with no children are raised to it in code
    # (generate_ai_summary._adults_with_party_size). Live: "4 of us incl. my father" was stored as adults=1.
    # v10 (2026-10-24): message lines name their author ([guest], [us: team member|AI assistant|automated message|campaign
    # broadcast]); trip facts come only from [guest] lines and call notes, and a headcount only we wrote is dropped in code
    # (message_author.keep_guest_headcount). Live: a campaign's "8 guests each" was stored as the lead's adults.
    "leads360_summary":       "leads360-summary-v10",  # generate_ai_summary.py -- v3 adds structured trip-fact extraction
    "ask_haip_intent":        "ask-haip-intent-v1",
    "ask_haip_rca":           "ask-haip-rca-v1",
    "ask_haip_report":        "ask-haip-report-v1",
    "ask_haip_freeform_sql":  "ask-haip-freeform-sql-v1",
    "ask_haip_freeform_summary": "ask-haip-freeform-summary-v1",
    # AI Autonomy Plan Phase 1 ticket 4: new intent classify+extract step
    # gating the grounded tool loop.
    # v2 (2026-10-13): reads the newest message in the context of the conversation, extracts only what was stated, and also returns
    # destination/occasion/budget, each distinct question, sentiment, urgency and a "booking_status" intent.
    # v3 (2026-10-24): history lines name their author; only [GUEST] lines are the guest's words (never a campaign broadcast).
    "concierge_intent": "concierge-intent-v3",
    # HAIP Inbox prototype-wiring plan, ticket 3: real translate/tone-fix
    # rewrite of an existing pending AI draft.
    "concierge_rewrite": "concierge-rewrite-v1",
    # Today (Worklist) AI Daily Briefing: cross-worklist pattern summary.
    # v2 (2026-10-18): adds "actions": up to 3 next best actions, each with lead, owner, channel and deadline.
    "daily_briefing": "daily-briefing-v2",
    # Lead autopilot AI classifier (lead_autopilot_ai.py): stage decision + lost reason + confidence + evidence refs.
    # v2 (2026-10-24): message lines name their author (message_author) instead of [inbound]/[outbound]; only [guest] lines are
    # the guest's evidence, and silence after a campaign broadcast or an automated message is not a decline.
    "lead_autopilot_classify": "lead-autopilot-classify-v2",
    # Public property assessment: plain-language write-up of numbers the engine computed (assessment_narrative.py).
    "assessment_narrative": "assessment-narrative-v1",
    # AI business analyst (services/analyst/brief.py): the brief from computed facts only; every number re-checked in code.
    "analyst_brief": "analyst-brief-v1",
    # "Ask a follow-up" on a report (services/analyst/ask.py): answered from the report facts (route analyst_followup).
    # v2: own route (analyst_followup, Gemini fallback), trimmed facts + the conversion block, "why" guidance.
    "analyst_followup": "analyst-followup-v2",
    # Lead workflows follow-up draft (lead_followup_draft.py): one short follow-up a person approves; never a price.
    # v2 (2026-10-22): the owner's follow-up style from the sales playbook is added to the user message when set.
    "lead_followup_draft": "lead-followup-draft-v2",
    # Why a lead was won / lost (lead_outcome.py): one catalogue reason + confidence + verbatim quotes from the evidence.
    "lead_outcome_reason": "lead-outcome-reason-v1",
    # Marketing Studio (services/marketing_prompts.py).
    # 24 Oct 2026: every prompt fed `marketing_ai_service._facts` got a new input ("Business facts" now carries the
    # approved knowledge base and the published business records, marketing_context.business_facts), so audit v3,
    # plan v7, research v2, content v8, review v3, ota-copy v2 and shoot-brief v2 were bumped with no text change.
    # v2: median baseline + stop/keep/test, pillars with position/rotation/out-of-scope, first comment and
    # carousel/story rules (techniques from Ootto-AI/claude-content-skills, MIT; see THIRD_PARTY_NOTICES.md).
    "marketing_audit": "marketing-audit-v3",
    # v3: the strategist also reads the research analyst's latest competitor brief (agency phase B).
    # v4 (M2): the demand brief (open dates, long weekends, festivals); targets, campaigns, 60/30/10 buckets,
    # indicator + stop_if per entry, reactive days.
    "marketing_plan": "marketing-plan-v7",
    "marketing_research": "marketing-research-v2",
    # Website builder AI developer (services/website_ai_prompts.py): first full copy, and chat edits as operations.
    "website_generate": "website-generate-v1",
    "website_edit": "website-edit-v1",
    # Website art director (services/website_builder_prompts.py, W2).
    "website_sitemap": "website-sitemap-v1",
    "website_wireframe": "website-wireframe-v1",
    "website_style": "website-style-v2",
    "website_copy": "website-copy-v1",
    # v3: the copywriter also gets the plan, the week's other posts, recent openings, reviewer notes and the photo
    # library's descriptions; it describes each slot's photo for the picker and may choose the text design.
    # v4 (M1): brand voice traits + tone, AI-tell bans, carousel frameworks, [NEED: ...] for missing facts.
    # v5 (M2): approved claims; a post sells exactly its plan entry's target dates.
    # v6 (M3): optional comment_dm ("comment STAY for dates").
    "marketing_content": "marketing-content-v8",
    # Brand editor (marketing_review_service): advisory findings on one draft; deterministic checks block, not this.
    "marketing_review": "marketing-review-v3",
    # Brand DNA draft (marketing_brand_dna): voice/tone/claims SUGGESTED from the website, captions, property text.
    # v2: also the approved knowledge base, published business records (no prices) and Meta ad copy.
    "marketing_brand_dna": "marketing-brand-dna-v2",
    # Reply to a public Google review (marketing_guest_reviews): review text treated as data; a person posts it.
    "marketing_review_reply": "marketing-review-reply-v1",
    # Agency M7: OTA listing copy drafts (marketing_reputation); a person pastes them into the OTA.
    "marketing_ota_copy": "marketing-ota-copy-v2",
    # Studio plan phase 1: creative tags from a post's / ad's own text (marketing_tagging) and the weekly Insights
    # report's plain-English lines over code-computed facts (marketing_insights_report).
    "marketing_tagging": "marketing-tagging-v1",
    "marketing_insights": "marketing-insights-v2",
    # Studio plan phase 2: what a Reel does (hook, shots, text, CTA) read by the vision model into the swipe file.
    "marketing_video_read": "marketing-video-read-v1",
    # Studio plan phase 3: shoot & collab brief, monthly strategy deck (marketing_strategy).
    "marketing_brief": "marketing-shoot-brief-v2",
    "marketing_deck": "marketing-strategy-deck-v1",
    # Fixed suffix appended to AI image prompts (marketing_image_service.PROMPT_SUFFIX).
    "marketing_image": "marketing-image-v1",
}

UNKNOWN = "unregistered"


def get_version(prompt_key: str) -> str:
    """
    Current version for a prompt key.

    Returns "unregistered" rather than raising for an unknown key: a missing
    registry entry is a bookkeeping problem, and must never take down the AI
    task that was trying to log it.
    """
    return PROMPT_VERSIONS.get(prompt_key, UNKNOWN)


def stamp(prompt_key: str, model: Optional[str] = None, **extra: Any) -> dict[str, Any]:
    """
    Build the provenance fields for a structured log line or audit payload.

        log.info("call_classified", call_id=call.id, **stamp("call_classify", model))

    Keeping this in one helper means every AI call site emits the same field
    names, so results stay filterable by prompt version across all of them.
    """
    meta: dict[str, Any] = {"prompt_key": prompt_key, "prompt_version": get_version(prompt_key)}
    if model:
        meta["model"] = model
    meta.update(extra)
    return meta
