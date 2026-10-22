// Lead page (layout "C · Chat"): the two payloads it reads. GET /leads/{id} (LeadDetailSchema, backend/app/schemas/leads.py)
// and GET /leads/{id}/feed (LeadFeedSchema, backend/app/schemas/lead_feed.py). Hand-written; keep in step with those files.
import type { Actionable, AutopilotBlock } from "@/lib/actionable";
import type { RecommendedAction } from "@/components/ai/AIRecommendationCard";

export interface FieldValue { field_key: string; label: string; data_type: string; value: unknown }

export interface QuoteHistory {
  id: string; amount: number; currency: string; created_at?: string | null; is_active?: boolean; status?: string | null;
  option_rank?: number; payment_link_status?: "created" | "paid" | "expired" | "cancelled" | null; booking_id?: string | null;
  shared_via?: "sent" | "copied" | null; valid_until?: string | null; label?: string | null;
}

export interface AiAnalysis extends Actionable {
  intent?: string | null; sentiment?: string | null; objection?: string | null; reply_urgency?: string | null;
  next_action?: string | null; unanswered_questions?: string[]; requirements?: string[]; inferences?: string[];
  follow_up?: string | null; booking_status?: { state: string; payment?: string | null; stays?: number } | null;
  /** Stamped by generate_ai_summary: the stage this summary was written at. */
  written_stage_key?: string | null; written_at?: string | null;
}

export interface LeadDetail {
  inquiry_id: string; guest_id: string; display_name: string; source?: string | null; stage_key?: string | null;
  inquiry_stage: string; check_in?: string | null; check_out?: string | null; adults?: number | null; children?: number | null;
  occasion?: string | null; budget_estimate?: number | null; budget_range_label?: string | null; quoted_amount?: number | null;
  ai_summary?: string | null; ai_next_action?: string | null; ai_analysis?: AiAnalysis | null;
  assigned_agent_name?: string | null; assigned_agent_id?: string | null; created_at?: string | null;
  identity_signals?: string[]; property_interest?: string[]; quote_history?: QuoteHistory[];
  custom_field_values?: FieldValue[]; recommended_actions?: RecommendedAction[]; autopilot?: AutopilotBlock | null;
  pending_draft?: { message_id: string; conversation_id: string; preview: string } | null;
  response_time_seconds?: number | null; response_time_status?: string | null;
  /** CRM reporting (migration 169): guest | b2b | partner; paid | organic | unknown (derived); a person's review. */
  lead_type?: string | null; came_from?: "paid" | "organic" | "unknown" | null; validation?: LeadValidation | null;
}

export interface LeadValidation {
  status: "valid" | "invalid" | null; dates_confirmed?: boolean | null; budget_fits?: boolean | null; clear_intent?: boolean | null;
  note?: string | null; by_id?: string | null; by_name?: string | null; at?: string | null;
}

export type FeedKind = "message" | "call" | "quote" | "booking" | "stage" | "task" | "merge";

export interface FeedItem {
  id: string; kind: FeedKind; at: string;
  channel?: string | null; direction?: string | null; conversation_id?: string | null; text?: string | null;
  media_type?: string | null; sender_name?: string | null; is_ai?: boolean; is_draft?: boolean; is_internal?: boolean;
  is_template?: boolean; delivery?: string | null;
  call_id?: string | null; duration_seconds?: number | null; answered?: boolean | null; summary?: string | null;
  summary_pending?: boolean; has_recording?: boolean; has_transcript?: boolean;
  /** A call logged by hand from a personal phone (POST /leads/{id}/log-call); its note is in `text`. */
  manual?: boolean;
  quote_id?: string | null; amount?: number | null; label?: string | null; shared_via?: string | null; status?: string | null;
  valid_until?: string | null; valid_until_text?: string | null;
  booking_id?: string | null; check_in?: string | null; check_out?: string | null; guests?: number | null; amount_restricted?: boolean;
  from_label?: string | null; to_label?: string | null; reason?: string | null;
  task_id?: string | null; due_date?: string | null; by_name?: string | null;
}

export interface FeedChannel {
  conversation_id: string; channel: string; last_inbound_at?: string | null; last_outbound_at?: string | null;
  can_send: boolean; ai_enabled: boolean;
}

export interface FeedBooking {
  booking_id: string; inquiry_id?: string | null; property_name?: string | null; check_in: string; check_out: string;
  status: string; guests: number; total?: number | null; paid?: number | null; outstanding?: number | null;
  payment_status?: string | null; amount_restricted?: boolean;
}

export interface FeedTask {
  task_id: string; title: string; due_date?: string | null; is_done: boolean; priority: string;
  assignee_name?: string | null; created_at?: string | null;
}

export interface FeedMerge { merge_id: string; at: string; reason: string; by_name?: string | null; undone: boolean; joined: string[] }

export interface LeadFeed {
  inquiry_id: string; guest_id: string; items: FeedItem[]; capped: boolean; total_available: number;
  messages_restricted: boolean; channels: FeedChannel[]; bookings: FeedBooking[]; tasks: FeedTask[]; merges: FeedMerge[];
  availability: { property_id: string; name: string; free: boolean }[];
  contact: {
    phone_masked?: string | null; has_phone: boolean; has_whatsapp: boolean; has_instagram: boolean; email_masked?: string | null;
    first_touch_channel?: string | null; first_touch_at?: string | null;
  };
  trip: { route?: string | null; pickup?: string | null; special_requests?: string | null; lost_reason?: string | null; lost_note?: string | null };
  facts: {
    last_inbound_at?: string | null; last_outbound_at?: string | null; unanswered_outbound_calls: number;
    missed_inbound_unreturned: boolean; last_call_at?: string | null; pending_drafts: number;
  };
}

export interface PipelineStage {
  id: string; key: string; label: string; order: number; category?: string | null;
  is_closed_won: boolean; is_closed_lost: boolean; is_default_entry: boolean;
}

/** Everything a button on the page can ask for; the page owns the sheets and the call panel. */
export type LeadActionKey = "call" | "message" | "quote" | "book" | "stage" | "lost" | "owner" | "task" | "more" | "open_booking" | "review_draft" | "mark_sold";
export type RunAction = (key: LeadActionKey, arg?: string) => void;
