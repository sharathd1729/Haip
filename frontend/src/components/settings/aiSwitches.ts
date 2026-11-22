// Settings > AI (docs/ai/AI_SWITCHES_SPEC.md step 3): plain-language labels and cost text for GET /settings/ai.
// Keys mirror backend/app/services/ai_features.py (DEFAULTS, REPLY_MODES, UNSWITCHED); change both together.

export type Mode = "off" | "shadow" | "autonomous";

export interface Usage {
  cost_usd: number | null;
  uses: number | null;
  cost_unknown_uses: number | null;
  cost_note?: "not_metered" | "in_lead_summaries";
}
export interface ReplyRow extends Usage {
  key: string;
  mode: Mode;
  choices: Mode[];
  threshold: number;
  threshold_editable: boolean;
  unused_drafts: number;
}
export interface FeatureRow extends Usage {
  key: string;
  enabled: boolean;
  default: boolean;
}
export interface AiSettingsView {
  period_days: number;
  usd_inr: number;
  reply_modes: ReplyRow[];
  replies_other: Usage;
  features: FeatureRow[];
  module_switched: (Usage & { key: string })[];
  total_cost_usd: number;
}

export const MODE_LABELS: Record<Mode, string> = {
  off: "Off",
  shadow: "Draft for staff",
  autonomous: "Reply automatically",
};

export const ROW_TEXT: Record<string, { title: string; does: string }> = {
  whatsapp_replies: { title: "WhatsApp replies", does: "Writes replies to guests who message your WhatsApp Business number." },
  instagram_dm_replies: { title: "Instagram DM replies", does: "Writes replies to Instagram direct messages." },
  instagram_comment_replies: { title: "Instagram comment replies", does: "Writes replies to comments that no keyword automation answers." },
  call_analysis: { title: "Call analysis", does: "Scores each recorded call and writes its summary and next step." },
  call_transcription: { title: "Call transcription", does: "Turns call recordings into text. Call analysis needs it." },
  lead_summaries: { title: "Lead summaries", does: "Keeps a short summary on each lead from its chats and calls." },
  personal_whatsapp_summaries: {
    title: "Personal WhatsApp: update lead summaries",
    does: "Also refreshes a lead's summary when the guest writes to a staff member's personal WhatsApp.",
  },
  lead_autopilot: { title: "Lead autopilot AI", does: "Reads unclear leads to suggest or move their stage. The rules still run when this is off." },
  briefings: { title: "Briefings and AI Executive", does: "Writes the report summaries, explanations and team feedback. The numbers stay when this is off." },
  ask_haip: { title: "Ask HAIP", does: "Answers questions about your business. Follows the Ask HAIP module." },
  marketing: { title: "Marketing Studio", does: "Plans, posts and images. Follows the Marketing Studio module." },
  website: { title: "Website builder", does: "Website text and SEO. Follows the Website module." },
  operations: { title: "Operations helpers", does: "Answers staff questions on WhatsApp and drafts SOPs." },
  personal_assistant: { title: "Personal assistant", does: "Yaad's answers, daily digest and folders." },
  core: { title: "Background helpers", does: "Small checks, such as alternate wordings for the knowledge base." },
};

export const THRESHOLDS = [0.7, 0.75, 0.78, 0.8, 0.85, 0.9, 0.95];

/** Rupees in the Indian style (₹1,25,000); small amounts keep paise so ₹0.42 does not read as ₹0. */
export function rupees(usd: number, usdInr: number): string {
  const inr = usd * usdInr;
  const digits = inr > 0 && inr < 100 ? 2 : 0;
  return `₹${inr.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** The cost line of one row: "₹123 · 45 uses", or why there is no cost of its own. */
export function costLine(u: Usage, usdInr: number): string {
  if (u.cost_note === "not_metered") return "Cost not tracked here (billed by the transcription provider)";
  if (u.cost_note === "in_lead_summaries") return "Cost counted in Lead summaries";
  const uses = u.uses ?? 0;
  if (!uses) return "Not used";
  const unknown = u.cost_unknown_uses ? ` (${u.cost_unknown_uses} with unknown cost)` : "";
  return `${rupees(u.cost_usd ?? 0, usdInr)} · ${uses.toLocaleString("en-IN")} ${uses === 1 ? "use" : "uses"}${unknown}`;
}
