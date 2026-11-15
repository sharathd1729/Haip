// Ready-made Instagram automations for stays (Automations v2, phase 5). Applied in the builder as a starting point:
// every field stays editable. No template mentions a price: the team or the workspace's price rule decides that.
import { DEFAULT_ACKS, DEFAULT_FORM, type IgForm, type IgSequenceStep, type IgTrigger } from "./automationTypes";

export interface IgTemplate {
  key: string;
  label: string;
  hint: string;
  trigger: IgTrigger;
  name: string;
  keywords: string[];
  replyAll?: boolean;
  acks?: string[];
  message: string;
  button?: { title: string; url: string };
  form?: IgForm;
  sequence?: IgSequenceStep[];
  suggest?: boolean;
}

export const TEMPLATES: IgTemplate[] = [
  {
    key: "price", label: "PRICE", hint: "Comment PRICE → three questions → a lead with dates and guests",
    trigger: "ig_comment_received", name: "PRICE on a post", keywords: ["price", "rates", "cost"], acks: DEFAULT_ACKS,
    message: "Thanks {first_name}! {agent_name} from our team will WhatsApp you the quote within 30 minutes.",
    form: { ...DEFAULT_FORM, enabled: true }, suggest: true,
  },
  {
    key: "dates", label: "DATES", hint: "Comment or DM about availability → dates, guests, number",
    trigger: "ig_comment_received", name: "Availability", keywords: ["dates", "available", "availability"], acks: DEFAULT_ACKS,
    message: "Thanks {first_name}! We're checking those dates and {agent_name} will WhatsApp you shortly.",
    form: { ...DEFAULT_FORM, enabled: true },
  },
  {
    key: "location", label: "LOCATION", hint: "Send directions with a map link",
    trigger: "ig_dm_received", name: "Location", keywords: ["location", "address", "directions"],
    message: "Hi {first_name}! Here's how to reach us. Tap below for directions 👇",
    button: { title: "Open the map", url: "" },
    sequence: [{ text: "Planning a visit? Tell us your dates and we'll check availability for you.", after_minutes: 180 }],
  },
  {
    key: "menu", label: "MENU", hint: "Share your food menu",
    trigger: "ig_comment_received", name: "Menu", keywords: ["menu", "food"], acks: DEFAULT_ACKS,
    message: "Hi {first_name}! Here's our menu 👇 Our chefs can also make something special on request.",
    button: { title: "See the menu", url: "" },
  },
  {
    key: "offer", label: "OFFER", hint: "Share this month's offer, then one gentle follow-up",
    trigger: "ig_comment_received", name: "Offer", keywords: ["offer", "deal", "discount"], acks: DEFAULT_ACKS,
    message: "Thanks {first_name}! Here are this month's offers 👇",
    button: { title: "See the offers", url: "" },
    sequence: [{ text: "Want us to check your dates for this offer? Just reply here.", after_minutes: 180 }],
    suggest: true,
  },
  {
    key: "story", label: "Story reply", hint: "Thank everyone who replies to your story",
    trigger: "ig_story_reply_received", name: "Story replies", keywords: [], replyAll: true,
    message: "Thanks for replying to our story, {first_name}! Want to see our stays or check your dates?",
    suggest: true,
  },
];
