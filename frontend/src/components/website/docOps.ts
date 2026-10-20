// Pure edits on the site document (called inside useDraft().update, which clones first). The server re-validates
// everything; these just keep the editor's copy sensible.
import { SPEC, type Block, type FieldSpec, type Page, type SiteDoc } from "@/site-blocks/types";

export const newId = (p = "b") => `${p}${Math.random().toString(36).slice(2, 12)}`;

export function pageOf(d: SiteDoc, pageId: string): Page | undefined {
  return d.pages.find(p => p.id === pageId);
}

function emptyValue(f: FieldSpec): unknown {
  if (f.kind === "lines" || f.kind === "tags" || f.kind === "images" || f.kind === "list") return [];
  if (f.kind === "toggle") return false;
  if (f.kind === "select") return f.options?.[0] ?? "";
  return "";
}

export function newBlock(type: string): Block {
  const spec = SPEC.blocks[type];
  const props: Block["props"] = { id: newId(), layout: spec.layouts?.[0] || "", background: "page" };
  for (const f of spec.fields) props[f.key] = emptyValue(f);
  const starter: Record<string, Record<string, unknown>> = {
    Hero: { title: "A headline about *your* place", cta_label: "Check dates", cta_link: "/book" },
    Text: { heading: "A new heading", body: "Write a short paragraph here." },
    Offer: { title: "Stay longer, pay less", tone: "bright" },
    Band: { heading: "Talk to us on WhatsApp", cta_label: "Contact us", cta_link: "/contact" },
    Stays: { heading: "Our stays", limit: "all" }, FAQ: { heading: "Good to know" }, Reviews: { heading: "What guests say" },
    Amenities: { kicker: "Every stay has", icons: ["wifi", "parking"] }, Highlights: { heading: "Why guests choose us" },
    Gallery: { heading: "Gallery" }, Contact: { heading: "Get in touch", show_form: true }, Location: { heading: "Getting here" },
    BookingBar: { cta_label: "Check availability" },
  };
  return { type, props: { ...props, ...(starter[type] || {}) } };
}

export function addBlock(d: SiteDoc, pageId: string, type: string, afterId?: string | null): string {
  const page = pageOf(d, pageId);
  if (!page) return "";
  const b = newBlock(type);
  const i = afterId ? page.content.findIndex(x => x.props.id === afterId) : -1;
  page.content.splice(i >= 0 ? i + 1 : page.content.length, 0, b);
  return b.props.id;
}

export function setProps(d: SiteDoc, pageId: string, blockId: string, props: Block["props"]) {
  const b = pageOf(d, pageId)?.content.find(x => x.props.id === blockId);
  if (b) b.props = { ...props, id: blockId };
}

export function moveBlock(d: SiteDoc, pageId: string, blockId: string, dir: -1 | 1) {
  const page = pageOf(d, pageId);
  if (!page) return;
  const i = page.content.findIndex(x => x.props.id === blockId);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= page.content.length) return;
  [page.content[i], page.content[j]] = [page.content[j], page.content[i]];
}

export function removeBlock(d: SiteDoc, pageId: string, blockId: string) {
  const page = pageOf(d, pageId);
  if (!page) return;
  const b = page.content.find(x => x.props.id === blockId);
  if (b && !SPEC.blocks[b.type]?.system) page.content = page.content.filter(x => x.props.id !== blockId);
}

export function duplicateBlock(d: SiteDoc, pageId: string, blockId: string): string {
  const page = pageOf(d, pageId);
  if (!page) return "";
  const i = page.content.findIndex(x => x.props.id === blockId);
  if (i < 0 || SPEC.blocks[page.content[i].type]?.system) return "";
  const copy = structuredClone(page.content[i]);
  copy.props.id = newId();
  page.content.splice(i + 1, 0, copy);
  return copy.props.id;
}

export function addPage(d: SiteDoc, title: string): string {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "page";
  let path = `/${slug}`, n = 2;
  while (d.pages.some(p => p.path === path)) path = `/${slug}-${n++}`;
  const id = path.slice(1);
  d.pages.push({ id, key: "", title: title.slice(0, 60) || "New page", path, nav: true, seo: { title: "", description: "" },
    content: [newBlock("Text")] });
  return id;
}

export function removePage(d: SiteDoc, pageId: string) {
  const p = pageOf(d, pageId);
  if (p && !p.key) d.pages = d.pages.filter(x => x.id !== pageId);
}

export const ADDABLE = Object.entries(SPEC.blocks).filter(([, s]) => !s.system).map(([k, s]) => ({ type: k, label: s.label, desc: s.desc }));
