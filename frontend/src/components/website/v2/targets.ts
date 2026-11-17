// What the on-page editor (website W2) edits: a page of the v2 spec, or (W4) a template that makes one page per stay or
// package. Pure functions over a draft copy (useDraft.update hands each one a clone), so they are easy to test.
import { CATALOGUE, type PageV2, type SectionType, type SectionV2, type SpecV2 } from "@/site-blocks/v2/types";

export type TemplateKey = "stay" | "package";
export type Target = { kind: "page"; slug: string } | { kind: "template"; key: TemplateKey };

export const sameTarget = (a: Target, b: Target) =>
  a.kind === b.kind && (a.kind === "page" ? a.slug === (b as { slug: string }).slug : a.key === (b as { key: TemplateKey }).key);

export function sectionsOf(doc: SpecV2, t: Target): SectionV2[] | null {
  if (t.kind === "page") return doc.pages.find(p => p.slug === t.slug)?.sections ?? null;
  return doc.templates?.[t.key]?.sections ?? null;
}

function allSections(doc: SpecV2): SectionV2[] {
  return [...doc.pages.flatMap(p => p.sections), ...Object.values(doc.templates || {}).flatMap(t => t?.sections || [])];
}

/** A section id unused anywhere on the site (ids name the WhatsApp reference code, so they are site-wide). */
export function newSectionId(doc: SpecV2, type: string): string {
  const ids = new Set(allSections(doc).map(s => s.id));
  const base = type === "booking-cta" ? "cta" : type;
  let id = base, n = 2;
  while (ids.has(id)) id = `${base}-${n++}`;
  return id;
}

export function blankSection(doc: SpecV2, type: SectionType): SectionV2 {
  const sec = CATALOGUE.sections[type];
  const slots: Record<string, unknown> = type === "hero" ? { headline: doc.site.name } : type === "offer" ? { heading: "Seasonal offer" } : {};
  return { id: newSectionId(doc, type), type, variant: sec.variants[0], source: sec.source, slots };
}

export function addSection(doc: SpecV2, t: Target, type: SectionType, at?: number): string | null {
  const list = sectionsOf(doc, t);
  if (!list || list.length >= 20) return null;
  const s = blankSection(doc, type);
  list.splice(at === undefined ? list.length : at, 0, s);
  return s.id;
}

export function moveSection(doc: SpecV2, t: Target, i: number, by: number): void {
  const list = sectionsOf(doc, t);
  if (!list || i + by < 0 || i + by >= list.length) return;
  [list[i], list[i + by]] = [list[i + by], list[i]];
}

export function duplicateSection(doc: SpecV2, t: Target, i: number): string | null {
  const list = sectionsOf(doc, t);
  if (!list || !list[i] || list.length >= 20) return null;
  const copy = { ...structuredClone(list[i]), id: newSectionId(doc, list[i].type) };
  list.splice(i + 1, 0, copy);
  return copy.id;
}

export function removeSection(doc: SpecV2, t: Target, i: number): void {
  const list = sectionsOf(doc, t);
  if (!list || list.length <= 1) return;
  list.splice(i, 1);
  pruneMenus(doc);
}

export function slugFor(title: string): string {
  const s = title.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  return `/${s || "page"}`;
}

/** A new page with a heading and a contact section; returns its address. Max 12 pages (backend SiteSpec). */
export function addPage(doc: SpecV2, title: string): string | null {
  if (doc.pages.length >= 12 || !title.trim()) return null;
  let slug = slugFor(title), n = 2;
  while (doc.pages.some(p => p.slug === slug)) slug = `${slugFor(title)}-${n++}`;
  const page: PageV2 = { slug, title: title.trim().slice(0, 60), nav: true, seo: { title: "", description: "" }, sections: [] };
  doc.pages.push(page);
  page.sections.push({ ...blankSection(doc, "text"), slots: { heading: page.title } });
  page.sections.push(blankSection(doc, "contact"));
  return slug;
}

export function removePage(doc: SpecV2, slug: string): void {
  if (slug === "/") return;
  doc.pages = doc.pages.filter(p => p.slug !== slug);
  pruneMenus(doc);
}

/** Same rule as backend site_spec.menu_problems: drop menu links to a page or section that is gone (else the save is refused). */
export function pruneMenus(doc: SpecV2): void {
  const menus = doc.site.menus;
  if (!menus) return;
  const pages = new Map(doc.pages.map(p => [p.slug, new Set(p.sections.map(s => s.id))]));
  const ok = (to: string) => {
    if (to.startsWith("https://")) return true;
    const [path0, anchor] = to.split("#");
    const path = path0.replace(/\/+$/, "") || "/";
    const page = pages.get(path);
    if (page) return !anchor || page.has(anchor);
    return ["/policies", "/compare", "/blog", "/my-booking", "/stays"].includes(path) || /^\/stays\/[a-z0-9]+(?:-[a-z0-9]+)*$/.test(path)
      || /^\/packages\/[a-z0-9]+(?:-[a-z0-9]+)*$/.test(path);
  };
  doc.site.menus = {
    main: menus.main.filter(m => ok(m.to)).map(m => ({ ...m, children: (m.children || []).filter(c => ok(c.to)) })),
    footer: menus.footer.filter(f => ok(f.to)),
  };
}
