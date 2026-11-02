// Other languages on a v2 site (website phase 6; backend website_i18n + schemas.site_spec LANGUAGES). A language's words
// live in doc.i18n.<code>, published with the version (a person checked them). localise() returns the live data with those
// words put in place of the English ones; anything not translated stays English. URLs: /<code>/<page>.
import type { LiveDataV2 } from "./types";

export const LANGS: Record<string, { name: string; hreflang: string; switchTo: string }> = {
  hi: { name: "हिन्दी", hreflang: "hi-IN", switchTo: "हिन्दी में देखें" },
};

export function languagesOf(live: LiveDataV2): string[] {
  return Object.keys(live.doc.i18n || {}).filter(k => k in LANGS);
}

export function localise(live: LiveDataV2, lang: string): LiveDataV2 {
  const loc = live.doc.i18n?.[lang];
  if (!loc) return live;
  const pages = live.doc.pages.map(p => {
    const pt = loc.pages?.[p.slug] || {};
    return {
      ...p, title: pt.title || p.title,
      seo: { title: pt.seo_title || p.seo.title, description: pt.seo_description || p.seo.description },
      sections: p.sections.map(s => (loc.sections?.[s.id] ? { ...s, slots: { ...s.slots, ...loc.sections[s.id] } } : s)),
    };
  });
  return { ...live, doc: { ...live.doc, pages, site: { ...live.doc.site, tagline: loc.tagline || live.doc.site.tagline } } };
}
