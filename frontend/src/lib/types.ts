export type UserRole =
  | "owner"
  | "manager"
  | "reservations"
  | "concierge"
  | "foh"
  | "marketing"
  | "compliance"
  | "read_only";

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  tenant_id: string;
}

export interface Call {
  id: string;
  direction: "inbound" | "outbound";
  from_number: string;
  to_number: string;
  duration_seconds: number;
  started_at: string;
  ended_at: string;
  guest_id: string | null;
  inquiry_id: string | null;
  transcription_status: "pending" | "processing" | "done" | "failed";
  ai_score_status: "pending" | "processing" | "done" | "failed";
  ai_score: number | null;
  ai_summary: string | null;
  ai_disposition: string | null;
  ai_next_action: string | null;
  human_disposition: string | null;
  ivr_provider: string;
  created_at: string;
}

export interface Guest {
  id: string;
  phone: string;
  email?: string;
  name: string;
  city?: string;
  vip_tier?: string;
  total_stays: number;
  total_inquiries: number;
  lifetime_value: number;
  tags: string[];
  created_at: string;
}

export interface Inquiry {
  id: string;
  guest_id: string;
  property_id?: string;
  stage: InquiryStage;
  source?: string;
  check_in?: string;
  check_out?: string;
  adults?: number;
  occasion?: string;
  quoted_amount?: number;
  ai_summary?: string;
  ai_next_action?: string;
  created_at: string;
}

export type InquiryStage =
  | "new"
  | "responding"
  | "quoted"
  | "site_visit"
  | "booked"
  | "lost"
  | "ghosted";

export interface Conversation {
  id: string;
  guest_id: string;
  channel: "whatsapp" | "instagram" | "voice" | "webchat" | "email";
  is_open: boolean;
  ai_mode: "shadow" | "autonomous" | "off";
  last_message_at: string;
  created_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  direction: "inbound" | "outbound";
  channel: string;
  body: string;
  media_url?: string;
  is_ai_generated: boolean;
  was_approved?: boolean;
  created_at: string;
}

export interface Property {
  id: string;
  name: string;
  slug: string;
  type: string;
  city?: string;
  ivr_virtual_number?: string;
  max_adults: number;
  bedrooms: number;
}

export type CallDisposition =
  | "hot"
  | "quoted"
  | "booked"
  | "lost"
  | "callback"
  | "no_answer"
  | "voicemail";
