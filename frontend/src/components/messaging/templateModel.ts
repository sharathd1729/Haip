// Shared model for the WhatsApp template editor: form state, conversion to and
// from Meta's components array, and what the live preview shows.

export type HeaderKind = "none" | "text" | "image" | "video" | "document";
export type ButtonType = "QUICK_REPLY" | "URL" | "PHONE_NUMBER" | "COPY_CODE";
/** Standard message, limited-time offer (banner + optional countdown), or carousel (swipeable cards). */
export type TemplateFormat = "standard" | "offer" | "carousel";

export interface TemplateButton {
  type: ButtonType;
  text: string;
  url?: string;
  phone_number?: string;
  example?: string[] | string;   // URL ending in {{1}}: a full sample link; COPY_CODE: a sample code
}

/** HAIP's tracked-link path (backend wa_campaign_money.TRACK_MARKER): a URL button ending in it gets one code per guest. */
export const TRACK_MARKER = "/api/v1/c/{{1}}";

export interface TemplateComponent {
  type: string;
  format?: string;
  text?: string;
  buttons?: TemplateButton[];
  example?: { header_text?: string[]; body_text?: string[][]; header_handle?: string[] };
  limited_time_offer?: { text: string; has_expiration: boolean };
  cards?: { components: TemplateComponent[] }[];
  media_key?: string;      // HAIP-only: a carousel card's stored file (removed before Meta sees it)
  media_url?: string;      // HAIP-only: signed preview of it, when the server adds one
}

export interface Template {
  id: string;
  name: string;
  language: string;
  category: string;
  status: "draft" | "pending" | "approved" | "rejected" | "submission_failed";
  components: TemplateComponent[];
  meta_template_id: string | null;
  rejection_reason: string | null;
  header_media_key: string | null;
  header_media_url: string | null;
  created_at: string | null;
}

export interface HeaderMedia {
  key: string;
  handle: string;
  previewUrl: string | null;
  fileName: string;
}

export interface ButtonDraft {
  id: string;
  type: ButtonType;
  text: string;
  url: string;
  phone: string;
  urlExample: string;
  code: string;            // COPY_CODE: sample offer code
}

export interface CardDraft {
  id: string;
  kind: "image" | "video";
  media: HeaderMedia | null;
  body: string;
  buttons: ButtonDraft[];
}

export interface TemplateForm {
  name: string;
  language: string;
  category: string;
  headerKind: HeaderKind;
  headerText: string;
  headerExample: string;
  media: HeaderMedia | null;
  body: string;
  bodyExamples: Record<number, string>;
  footer: string;
  buttons: ButtonDraft[];
  format: TemplateFormat;
  offerText: string;
  offerCountdown: boolean;
  cards: CardDraft[];
}

// Meta's limits, mirrored from the backend (wa_template_service.py) so the
// editor can stop you before the server has to.
export const LIMITS = {
  header: 60, body: 1024, footer: 60, buttonText: 25, buttons: 10, urlButtons: 2, phoneButtons: 1,
  coupon: 15, offerText: 16, cards: 10, minCards: 2, cardBody: 160, cardButtons: 2,
} as const;

export const MEDIA_ACCEPT: Record<Exclude<HeaderKind, "none" | "text">, { accept: string; hint: string; maxMb: number }> = {
  image:    { accept: "image/jpeg,image/png",  hint: "JPG or PNG, up to 5 MB",  maxMb: 5 },
  video:    { accept: "video/mp4",             hint: "MP4, up to 16 MB",        maxMb: 16 },
  document: { accept: "application/pdf",       hint: "PDF, up to 16 MB",        maxMb: 16 },
};

export const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "en_US", label: "English (US)" },
  { value: "hi", label: "Hindi" },
  { value: "te", label: "Telugu" },
  { value: "ta", label: "Tamil" },
  { value: "kn", label: "Kannada" },
  { value: "ml", label: "Malayalam" },
];

let _btnSeq = 0;
export function newButton(type: ButtonType): ButtonDraft {
  _btnSeq += 1;
  return { id: `b${Date.now()}_${_btnSeq}`, type, text: "", url: "", phone: "", urlExample: "", code: "" };
}

export function newCard(kind: CardDraft["kind"] = "image", like?: CardDraft): CardDraft {
  _btnSeq += 1;
  // Meta wants every card to have the same buttons: copy the first card's button types.
  const buttons = like ? like.buttons.map(b => ({ ...newButton(b.type), text: b.text })) : [newButton("URL")];
  return { id: `c${Date.now()}_${_btnSeq}`, kind, media: null, body: "", buttons };
}

export function emptyForm(): TemplateForm {
  return {
    name: "", language: "en", category: "MARKETING",
    headerKind: "none", headerText: "", headerExample: "", media: null,
    body: "", bodyExamples: {}, footer: "", buttons: [],
    format: "standard", offerText: "", offerCountdown: false, cards: [],
  };
}

export function extractVarIndices(text: string): number[] {
  const found = new Set<number>();
  for (const m of text.matchAll(/\{\{(\d+)\}\}/g)) found.add(parseInt(m[1], 10));
  return [...found].sort((a, b) => a - b);
}

// Meta wants quick replies together and call-to-action buttons together; quick
// replies first is the order WhatsApp itself shows them in.
export function orderedButtons(buttons: ButtonDraft[]): ButtonDraft[] {
  return [
    ...buttons.filter(b => b.type === "QUICK_REPLY"),
    ...buttons.filter(b => b.type !== "QUICK_REPLY"),
  ];
}

/** A link ending in {{1}} keeps the sample it came with (Meta reviews it); a new one gets "…/example". */
export function urlExample(b: Pick<ButtonDraft, "url" | "urlExample">): { example?: string[] } {
  if (!b.url.endsWith("{{1}}")) return {};
  const base = b.url.slice(0, -5);
  return { example: [b.urlExample.startsWith(base) && b.urlExample.length > base.length ? b.urlExample : `${base}example`] };
}

function draftToButton(b: ButtonDraft): TemplateButton {
  if (b.type === "URL") return { type: "URL", text: b.text, url: b.url, ...urlExample(b) };
  if (b.type === "PHONE_NUMBER") return { type: "PHONE_NUMBER", text: b.text, phone_number: b.phone };
  if (b.type === "COPY_CODE") return { type: "COPY_CODE", text: "Copy offer code", example: b.code.trim() };
  return { type: "QUICK_REPLY", text: b.text };
}

function buttonToDraft(b: TemplateButton): ButtonDraft {
  const ex = Array.isArray(b.example) ? b.example[0] ?? "" : b.example ?? "";
  return { ...newButton(b.type), text: b.text, url: b.url ?? "", phone: b.phone_number ?? "",
           urlExample: b.type === "URL" ? ex : "", code: b.type === "COPY_CODE" ? ex : "" };
}

export function buildComponents(form: TemplateForm): TemplateComponent[] {
  const comps: TemplateComponent[] = [];
  const headerVars = extractVarIndices(form.headerText);
  const bodyVars = extractVarIndices(form.body);

  if (form.format === "carousel") {
    if (form.body.trim()) {
      comps.push({ type: "BODY", text: form.body,
        ...(bodyVars.length ? { example: { body_text: [bodyVars.map(i => form.bodyExamples[i] ?? "")] } } : {}) });
    }
    comps.push({ type: "CAROUSEL", cards: form.cards.map(c => ({ components: [
      { type: "HEADER", format: c.kind.toUpperCase(),
        ...(c.media ? { example: { header_handle: [c.media.handle] }, media_key: c.media.key } : {}) },
      { type: "BODY", text: c.body },
      { type: "BUTTONS", buttons: c.buttons.map(draftToButton) },
    ] })) });
    return comps;
  }

  if (form.headerKind === "text" && form.headerText.trim()) {
    comps.push({
      type: "HEADER", format: "TEXT", text: form.headerText,
      ...(headerVars.length ? { example: { header_text: [form.headerExample] } } : {}),
    });
  } else if (form.headerKind !== "none" && form.headerKind !== "text") {
    comps.push({
      type: "HEADER", format: form.headerKind.toUpperCase(),
      ...(form.media ? { example: { header_handle: [form.media.handle] } } : {}),
    });
  }
  if (form.body.trim()) {
    comps.push({
      type: "BODY", text: form.body,
      ...(bodyVars.length ? { example: { body_text: [bodyVars.map(i => form.bodyExamples[i] ?? "")] } } : {}),
    });
  }
  if (form.format === "offer") {
    comps.push({ type: "LIMITED_TIME_OFFER", limited_time_offer: { text: form.offerText, has_expiration: form.offerCountdown } });
  } else if (form.footer.trim()) comps.push({ type: "FOOTER", text: form.footer });

  const buttons = orderedButtons(form.buttons).map(draftToButton);
  if (buttons.length) comps.push({ type: "BUTTONS", buttons });
  return comps;
}

export function formFromTemplate(t: Template): TemplateForm {
  const form = emptyForm();
  form.name = t.name;
  form.language = t.language;
  form.category = t.category;
  for (const c of t.components ?? []) {
    if (c.type === "HEADER") {
      const fmt = (c.format ?? "TEXT").toUpperCase();
      if (fmt === "TEXT") {
        form.headerKind = "text";
        form.headerText = c.text ?? "";
        form.headerExample = c.example?.header_text?.[0] ?? "";
      } else {
        form.headerKind = fmt.toLowerCase() as HeaderKind;
        const handle = c.example?.header_handle?.[0];
        if (t.header_media_key && handle) {
          form.media = { key: t.header_media_key, handle, previewUrl: t.header_media_url, fileName: "Uploaded file" };
        }
      }
    } else if (c.type === "BODY") {
      form.body = c.text ?? "";
      (c.example?.body_text?.[0] ?? []).forEach((v, i) => { form.bodyExamples[i + 1] = v; });
    } else if (c.type === "FOOTER") {
      form.footer = c.text ?? "";
    } else if (c.type === "BUTTONS") {
      form.buttons = (c.buttons ?? []).map(buttonToDraft);
    } else if (c.type === "LIMITED_TIME_OFFER") {
      form.format = "offer";
      form.offerText = c.limited_time_offer?.text ?? "";
      form.offerCountdown = !!c.limited_time_offer?.has_expiration;
    } else if (c.type === "CAROUSEL") {
      form.format = "carousel";
      form.cards = (c.cards ?? []).map(card => {
        const header = card.components.find(x => x.type === "HEADER");
        const body = card.components.find(x => x.type === "BODY");
        const btns = card.components.find(x => x.type === "BUTTONS");
        const handle = header?.example?.header_handle?.[0];
        return {
          ...newCard((header?.format ?? "IMAGE").toLowerCase() === "video" ? "video" : "image"),
          media: header?.media_key && handle ? { key: header.media_key, handle, previewUrl: header.media_url ?? null, fileName: "Uploaded file" } : null,
          body: body?.text ?? "",
          buttons: (btns?.buttons ?? []).map(buttonToDraft),
        };
      });
    }
  }
  return form;
}

// What the preview shows in place of {{n}}: the example you typed, or the
// placeholder itself so you can see where it will land.
export function fillExamples(text: string, examples: Record<number, string>): string {
  return text.replace(/\{\{(\d+)\}\}/g, (whole, n) => (examples[Number(n)] ?? "").trim() || whole);
}

// Problems the editor can spot without asking the server.
export function localProblems(form: TemplateForm): string[] {
  const problems: string[] = [];
  const headerVars = extractVarIndices(form.headerText);
  const bodyVars = extractVarIndices(form.body);
  if (!form.name.trim()) problems.push("Give the template a name.");
  if (!form.body.trim()) problems.push("Write the message body.");
  if (form.format === "offer") {
    if (!form.offerText.trim() || form.offerText.length > LIMITS.offerText) problems.push(`Write the offer banner (up to ${LIMITS.offerText} characters).`);
    if (form.footer.trim()) problems.push("A limited-time offer can't have a footer.");
    if (form.headerKind === "text" || form.headerKind === "document") problems.push("An offer's header must be an image or a video (or none).");
    if (!form.buttons.some(b => b.type === "URL")) problems.push("A limited-time offer needs a link button.");
    if (form.offerCountdown && !form.buttons.some(b => b.type === "COPY_CODE")) problems.push("An offer with a countdown needs an offer code button.");
  }
  if (form.format === "carousel") {
    if (form.cards.length < LIMITS.minCards || form.cards.length > LIMITS.cards) problems.push(`A carousel needs ${LIMITS.minCards} to ${LIMITS.cards} cards.`);
    form.cards.forEach((c, i) => {
      if (!c.media) problems.push(`Upload the ${c.kind} for card ${i + 1}.`);
      if (!c.body.trim() || c.body.length > LIMITS.cardBody) problems.push(`Card ${i + 1} needs text (up to ${LIMITS.cardBody} characters).`);
      if (extractVarIndices(c.body).length) problems.push(`Card ${i + 1}'s text can't have variables.`);
      if (c.buttons.some(b => !b.text.trim())) problems.push(`Every button on card ${i + 1} needs a label.`);
      if (c.buttons.some(b => b.type === "URL" && (!b.url.startsWith("https://") || extractVarIndices(b.url).length))) problems.push(`Card ${i + 1}'s link must be a fixed https:// address.`);
    });
    return problems;
  }
  for (const b of form.buttons) {
    if (b.type === "COPY_CODE" && !/^[A-Za-z0-9]{1,15}$/.test(b.code.trim())) { problems.push("The offer code button needs a sample code (letters and numbers, up to 15)."); break; }
  }
  if (form.headerKind === "text" && !form.headerText.trim()) problems.push("Header text is empty — choose \"None\" or write it.");
  if (form.headerKind !== "none" && form.headerKind !== "text" && !form.media) problems.push(`Upload the header ${form.headerKind}.`);
  if (headerVars.length > 1) problems.push("A text header can have only one variable.");
  if (headerVars.length && !form.headerExample.trim()) problems.push("Add an example for the header variable.");
  for (const i of bodyVars) {
    if (!(form.bodyExamples[i] ?? "").trim()) problems.push(`Add an example for {{${i}}} — Meta needs it to review the template.`);
  }
  if (extractVarIndices(form.footer).length) problems.push("A footer can't contain variables.");
  for (const b of form.buttons) {
    if (b.type !== "COPY_CODE" && !b.text.trim()) { problems.push("Every button needs a label."); break; }
  }
  for (const b of form.buttons) {
    if (b.type === "URL" && !b.url.trim().toLowerCase().startsWith("https://")) { problems.push("Link buttons need an address starting with https://."); break; }
  }
  for (const b of form.buttons) {
    if (b.type === "PHONE_NUMBER" && !/^\+\d{8,15}$/.test(b.phone.trim())) { problems.push("Call buttons need a number like +919876543210."); break; }
  }
  return problems;
}
