// WhatsApp flow canvas: the stored node/edge shape (docs/whatsapp/FLOW_CANVAS_SPEC.md), the block catalogue, and what
// each node shows and connects to. Pure: no React, so flowGraph.test.ts covers it.
import { describeDelay } from "../flowOrder";

export type NodeType =
  | "trigger" | "message" | "media" | "location" | "buttons" | "list" | "cta_url" | "template"
  | "question" | "condition" | "delay" | "action" | "http" | "end";
export type MediaKind = "image" | "video" | "audio" | "document";
export type TriggerKind = "keyword" | "opt_in" | "new_inquiry" | "check_in" | "check_out";
export type ActionKey = "tag_vip" | "create_inquiry" | "notify_agent" | "opt_out" | "add_label";

export interface Option { id: string; title: string; description?: string }

/** Everything a node holds besides id + position. Old flows also carry `x`/`y` (dropped on save) and keep the trigger /
 *  action key in `content`; the canvas writes both the new field and `content` so the engine reads either. */
export interface NodeData {
  type: NodeType;
  label?: string;
  content?: string;
  trigger?: TriggerKind;
  keywords?: string[];
  match?: "exact" | "contains";
  media_kind?: MediaKind;
  file_key?: string;
  filename?: string;
  caption?: string;
  latitude?: number;
  longitude?: number;
  name?: string;
  address?: string;
  buttons?: Option[];
  rows?: Option[];
  button_label?: string;
  url?: string;
  save_as?: string;
  condition?: string;
  delay_minutes?: number;
  action?: ActionKey;
  tag?: string;
  method?: "POST" | "GET";
  body?: string;
  template_id?: string;
  variable_map?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface StoredNode extends NodeData { id: string; position?: { x: number; y: number } }
export interface StoredEdge { id: string; from: string; to: string; label: string | null }

export const LIMITS = { buttonTitle: 20, rowTitle: 24, rowDescription: 72, buttons: 3, rows: 10, buttonLabel: 20 } as const;

export const TRIGGER_OPTIONS: { value: TriggerKind; label: string }[] = [
  { value: "keyword", label: "Guest sends a keyword" },
  { value: "opt_in", label: "Contact opts in" },
  { value: "new_inquiry", label: "New inquiry created" },
  { value: "check_in", label: "Guest check-in (D-1)" },
  { value: "check_out", label: "Guest check-out (D+1)" },
];

export const CONDITION_OPTIONS = [
  { value: "message_read", label: "Message was read" },
  { value: "replied", label: "Contact replied" },
  { value: "not_replied", label: "Contact has not replied" },
  { value: "is_vip", label: "Contact has the VIP tag" },
  { value: "has_booking", label: "Has an active booking" },
];

export const SAVE_AS_OPTIONS = [
  { value: "name", label: "Guest name" },
  { value: "email", label: "Email" },
  { value: "notes", label: "Enquiry notes" },
];

export const ACTION_LABELS: Record<ActionKey, string> = {
  tag_vip: "Add tag: VIP", create_inquiry: "Create enquiry", notify_agent: "Notify team", opt_out: "Opt out", add_label: "Add label",
};

// ─── Block catalogue (palette) ────────────────────────────────────────────────

export interface Block { key: string; label: string; group: string; make: () => NodeData }

let seq = 0;
/** Short unique id: time + counter, so two adds in the same millisecond still differ. */
export const uid = (prefix = "n") => `${prefix}${Date.now().toString(36)}${(++seq).toString(36)}`;

const media = (media_kind: MediaKind, label: string): NodeData => ({ type: "media", media_kind, label });
const act = (action: ActionKey): NodeData => ({ type: "action", action, content: action, label: ACTION_LABELS[action] });

export const BLOCKS: Block[] = [
  { key: "text", group: "Messages", label: "Text", make: () => ({ type: "message", label: "Text", content: "" }) },
  { key: "photo", group: "Messages", label: "Photo", make: () => media("image", "Photo") },
  { key: "video", group: "Messages", label: "Video", make: () => media("video", "Video") },
  { key: "audio", group: "Messages", label: "Audio", make: () => media("audio", "Audio") },
  { key: "file", group: "Messages", label: "File", make: () => media("document", "File") },
  { key: "location", group: "Messages", label: "Location", make: () => ({ type: "location", label: "Location" }) },
  { key: "buttons", group: "Interactive", label: "Buttons", make: () => ({ type: "buttons", label: "Buttons", content: "", buttons: [{ id: uid("b"), title: "Option 1" }] }) },
  { key: "list", group: "Interactive", label: "List", make: () => ({ type: "list", label: "List", content: "", button_label: "See options", rows: [{ id: uid("r"), title: "Option 1" }] }) },
  { key: "cta_url", group: "Interactive", label: "Link button", make: () => ({ type: "cta_url", label: "Link button", content: "", button_label: "Open", url: "https://" }) },
  { key: "template", group: "Interactive", label: "Template", make: () => ({ type: "template", label: "Template" }) },
  { key: "question", group: "Data", label: "Question", make: () => ({ type: "question", label: "Question", content: "", save_as: "name" }) },
  { key: "condition", group: "Flow control", label: "Condition", make: () => ({ type: "condition", label: "Condition", condition: "replied" }) },
  { key: "delay", group: "Flow control", label: "Delay", make: () => ({ type: "delay", label: "Delay", delay_minutes: 60 }) },
  { key: "add_label", group: "Flow control", label: "Add label", make: () => ({ ...act("add_label"), tag: "" }) },
  { key: "notify", group: "Flow control", label: "Notify team", make: () => act("notify_agent") },
  { key: "create_inquiry", group: "Flow control", label: "Create enquiry", make: () => act("create_inquiry") },
  { key: "opt_out", group: "Flow control", label: "Opt out", make: () => act("opt_out") },
  { key: "http", group: "Integrations", label: "HTTP API", make: () => ({ type: "http", label: "HTTP API", method: "POST", url: "https://", body: "" }) },
  { key: "end", group: "End", label: "End", make: () => ({ type: "end", label: "End" }) },
];

export const BLOCK_GROUPS = [...new Set(BLOCKS.map(b => b.group))];

// ─── Outputs (handles) ────────────────────────────────────────────────────────

export interface Output { id: string; label: string }
/** Single-output nodes use this handle id; it is stored as label null. */
export const OUT = "out";

export function outputsOf(d: NodeData): Output[] {
  switch (d.type) {
    case "end": return [];
    case "buttons": return [...(d.buttons ?? []).map(b => ({ id: `btn:${b.id}`, label: b.title || "Button" })), { id: "other", label: "Any other reply" }];
    case "list": return [...(d.rows ?? []).map(r => ({ id: `row:${r.id}`, label: r.title || "Row" })), { id: "other", label: "Any other reply" }];
    case "condition": return [{ id: "yes", label: "Yes" }, { id: "no", label: "No" }];
    default: return [{ id: OUT, label: "" }];
  }
}

// ─── Card summary ─────────────────────────────────────────────────────────────

const firstLine = (s?: string) => (s ?? "").split("\n").find(l => l.trim())?.trim() ?? "";

export function triggerOf(d: NodeData): string { return (d.trigger ?? d.content ?? "") as string }
export function actionOf(d: NodeData): string { return (d.action ?? d.content ?? "") as string }

export function blockTitle(d: NodeData): string {
  if (d.type === "action") return ACTION_LABELS[actionOf(d) as ActionKey] ?? "Action";
  if (d.type === "media") return BLOCKS.find(b => b.make().media_kind === d.media_kind)?.label ?? "Media";
  if (d.type === "trigger") return "Start";
  return BLOCKS.find(b => b.make().type === d.type)?.label ?? d.type;
}

/** One short line under the card title: first line of text, the file name, option titles, the wait. */
export function summarize(d: NodeData): string {
  switch (d.type) {
    case "trigger": {
      const t = triggerOf(d);
      if (t === "keyword") return d.keywords?.length ? `Keyword: ${d.keywords.join(", ")}` : "Keyword: none yet";
      return TRIGGER_OPTIONS.find(o => o.value === t)?.label ?? "Choose a trigger";
    }
    case "message": case "question": return firstLine(d.content) || "Empty message";
    case "media": return d.filename || "No file yet";
    case "location": return d.name || (d.latitude != null && d.longitude != null ? `${d.latitude}, ${d.longitude}` : "No place yet");
    case "buttons": return (d.buttons ?? []).map(b => b.title).join(" / ") || "No buttons";
    case "list": return (d.rows ?? []).map(r => r.title).join(" / ") || "No rows";
    case "cta_url": return d.button_label ? `${d.button_label}: ${d.url ?? ""}` : d.url ?? "";
    case "template": return d.template_id ? "Approved template" : "Choose a template";
    case "condition": return CONDITION_OPTIONS.find(o => o.value === d.condition)?.label ?? "Choose a condition";
    case "delay": return describeDelay(d.delay_minutes ?? 60);
    case "action": return actionOf(d) === "add_label" ? (d.tag ? `Label: ${d.tag}` : "No label yet") : "";
    case "http": return `${d.method ?? "POST"} ${d.url ?? ""}`;
    default: return "";
  }
}
