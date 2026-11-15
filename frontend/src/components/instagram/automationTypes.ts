// Instagram automations: shapes mirror backend/app/schemas/ig_automation.py (change both together).

export type IgTrigger =
  | "ig_comment_received"
  | "ig_live_comment_received"
  | "ig_story_reply_received"
  | "ig_story_mention_received"
  | "ig_dm_received"
  | "ig_ad_chat_started";

export const IG_ACTION = "send_instagram_quick_reply";

export const TRIGGERS: { value: IgTrigger; label: string; short: string; hint: string }[] = [
  { value: "ig_comment_received", label: "Comment on a post or reel", short: "Post comment", hint: "Someone comments a keyword on your post, reel or ad." },
  { value: "ig_live_comment_received", label: "Comment during a Live", short: "Live comment", hint: "Works only while the Live is running." },
  { value: "ig_story_reply_received", label: "Reply to your story", short: "Story reply", hint: "Someone replies to one of your stories." },
  { value: "ig_story_mention_received", label: "Mention in their story", short: "Story mention", hint: "Someone tags you in their story: thank them." },
  { value: "ig_dm_received", label: "DM with a keyword", short: "DM keyword", hint: "Someone sends you a keyword in a DM." },
  { value: "ig_ad_chat_started", label: "Chat started from an ad", short: "Ad chat", hint: "A welcome for people who open a chat from your ad." },
];

export const triggerMeta = (t: string) => TRIGGERS.find(x => x.value === t);

export interface IgTriggerConfig {
  keywords?: string[];
  exclude_keywords?: string[];
  reply_all?: boolean;
  scope?: "post" | "any" | "next_post";
  media_id?: string;
  media_thumb?: string;
  media_caption?: string;
  media_bound_at?: string;
  ad_id?: string;
}

export type IgFormKey = "dates" | "guests" | "phone" | "email" | "budget" | "occasion" | "custom";

export interface IgFormQuestion {
  key: IgFormKey;
  text: string;
  options?: string[];
}

export interface IgForm {
  enabled: boolean;
  questions: IgFormQuestion[];
}

export const FORM_KEYS: { value: IgFormKey; label: string }[] = [
  { value: "dates", label: "Dates" },
  { value: "guests", label: "Number of guests" },
  { value: "phone", label: "WhatsApp number" },
  { value: "email", label: "Email" },
  { value: "budget", label: "Budget" },
  { value: "occasion", label: "Occasion" },
  { value: "custom", label: "Your own question" },
];

// The recommended default (Automations v2 plan): short enough that most people finish.
export const DEFAULT_FORM: IgForm = {
  enabled: false,
  questions: [
    { key: "dates", text: "When are you planning to come?", options: ["This weekend", "Next month", "Dates not fixed"] },
    { key: "guests", text: "How many guests?", options: ["2", "4", "6", "8+"] },
    { key: "phone", text: "Last one: your WhatsApp number, so our team can send the quote." },
  ],
};

export interface IgActionConfig {
  message: string;
  button?: { title: string; url: string } | null;
  opener?: string;
  opener_button?: string;
  public_ack_pool?: string[];
  follow_gate?: { enabled: boolean; ask_text?: string; button_title?: string; max_asks?: number; send_anyway?: boolean };
  once_per_person?: boolean;
  form?: IgForm;
}

export interface IgRule {
  id: string;
  name: string;
  trigger: string;
  trigger_config: IgTriggerConfig;
  action: string;
  action_config: IgActionConfig;
  is_active: boolean;
  run_count: number;
  last_run_at?: string;
  created_at?: string;
}

export interface IgMedia {
  id: string;
  caption: string;
  type: string;
  thumbnail?: string | null;
  permalink?: string;
  timestamp?: string;
  comments?: number;
}

export interface IgRuleStats {
  rule_id: string;
  name: string;
  triggered: number;
  dm_sent: number;
  link_sent: number;
  clicked: number;
  followed: number;
  gate_asked: number;
  people: number;
  leads: number;
  skipped: number;
  dm_failed: number;
  form_started?: number;
  form_completed?: number;
  form_dropped?: number;
}

export const isIgRule = (r: { trigger: string; action: string }) => r.action === IG_ACTION && r.trigger.startsWith("ig_");

export const DEFAULT_ACKS = ["Sent you a DM 📩", "Check your DMs! 📥", "Just messaged you 😊"];
