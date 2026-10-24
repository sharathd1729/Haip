"use client";
// How each art-director step reads to an owner: the sitemap as a tree with reasons, the wireframe as grey section blocks,
// the style directions as swatch + type cards. Client palettes and faces are DATA here (the client's site), so they are
// applied inline; HAIP's own chrome uses HAIP tokens.
import type { CSSProperties } from "react";
import catalogue from "@/site-blocks/v2/spec.json";
import { SECTION_LABEL, type Direction, type SitemapArt, type StyleArt, type WireframeArt } from "@/lib/websiteBuilder";

const fonts = catalogue.fonts as { display: Record<string, { family: string; stack: string; google: string }>; body: Record<string, { family: string; stack: string; google: string }> };
export const FONTS_HREF = "https://fonts.googleapis.com/css2?family=" +
  [...new Set([...Object.values(fonts.display), ...Object.values(fonts.body)].map(f => f.google))].join("&family=") + "&display=swap";

const plain = (t: string) => t.replace(/\*(.+?)\*/g, "$1");

export function SitemapView({ a }: { a: SitemapArt }) {
  return (
    <div className="space-y-4">
      {a.note && <p className="text-[14px] text-[var(--haip-fg-2)]">{a.note}</p>}
      <ol className="space-y-3">
        {a.pages.map(p => (
          <li key={p.slug} className="rounded-xl border border-[var(--haip-border)] bg-[var(--haip-surface)] p-3 sm:p-4">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-[15px] font-semibold text-[var(--haip-fg)]">{p.title}</span>
              <code className="text-[12px] text-[var(--haip-fg-subtle)]">{p.slug}</code>
              {p.nav && <span className="text-[12px] text-[var(--haip-fg-subtle)]">· in the menu</span>}
            </div>
            <p className="mt-1 text-[13px] text-[var(--haip-fg-muted)]">{p.reason}</p>
            <ol className="mt-3 space-y-1.5 border-l border-[var(--haip-border)] pl-3">
              {p.sections.map((s, i) => (
                <li key={i} className="text-[13px]">
                  <span className="font-semibold text-[var(--haip-fg-2)]">{SECTION_LABEL[s.type] || s.type}</span>
                  <span className="text-[var(--haip-fg-muted)]"> · {s.reason}</span>
                </li>
              ))}
            </ol>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function WireframeView({ a }: { a: WireframeArt }) {
  return (
    <div className="space-y-5">
      {a.note && <p className="text-[14px] text-[var(--haip-fg-2)]">{a.note}</p>}
      {a.pages.map(p => (
        <section key={p.slug} aria-label={p.title} className="space-y-2">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <h3 className="text-[15px] font-semibold text-[var(--haip-fg)]">{p.title}</h3>
            <code className="text-[12px] text-[var(--haip-fg-subtle)]">{p.slug}</code>
          </div>
          {p.seo_description && <p className="text-[12px] text-[var(--haip-fg-subtle)]">Search preview: {p.seo_description}</p>}
          <div className="space-y-2 rounded-xl border border-dashed border-[var(--haip-border-strong)] p-2">
            {p.sections.map(s => {
              const big = s.type === "hero";
              const text = s.headline || s.heading || s.eyebrow;
              return (
                <div key={s.id} className={`rounded-lg bg-[var(--haip-surface)] px-3 ${big ? "py-6" : "py-3"}`}>
                  <div className="flex flex-wrap items-center gap-2 text-[12px] text-[var(--haip-fg-subtle)]">
                    <span className="font-semibold uppercase tracking-wide">{SECTION_LABEL[s.type] || s.type}</span>
                    <span className="rounded-full border border-[var(--haip-border)] px-2 py-0.5">{s.variant}</span>
                  </div>
                  {text && <p className={`mt-1 text-[var(--haip-fg-2)] ${big ? "text-[18px] font-semibold" : "text-[14px]"}`}>{plain(text)}</p>}
                  {big && s.subhead && <p className="mt-1 text-[13px] text-[var(--haip-fg-muted)]">{s.subhead}</p>}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function Swatches({ d }: { d: Direction }) {
  const p = d.tokens.palette;
  return (
    <div className="flex gap-1.5" aria-label={`Colours: ${p.ink}, ${p.surface}, ${p.primary}, ${p.accent}`}>
      {[p.surface, p.ink, p.primary, p.accent].map((c, i) => (
        <span key={i} className="h-7 w-7 rounded-full border border-[var(--haip-border)]" style={{ background: c }} />
      ))}
    </div>
  );
}

export function StyleView({ a, pickedIndex, onPick, busy }: { a: StyleArt; pickedIndex: number | null; onPick?: (i: number) => void; busy?: boolean }) {
  return (
    <div className="space-y-3">
      <link rel="stylesheet" href={FONTS_HREF} />
      {a.note && <p className="text-[14px] text-[var(--haip-fg-2)]">{a.note}</p>}
      <div className="grid gap-3 md:grid-cols-3">
        {a.directions.map((d, i) => {
          const p = d.tokens.palette;
          const radius = d.tokens.radius === "sharp" ? "2px" : d.tokens.radius === "pill" ? "999px" : "12px";
          const sample: CSSProperties = { background: p.surface, color: p.ink };
          return (
            <article key={i} className="flex flex-col overflow-hidden rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)]">
              <div className="space-y-3 p-4" style={sample}>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: p.primary, fontFamily: fonts.body[d.tokens.body]?.stack }}>{d.name}</p>
                <p className="text-[26px] leading-[1.05]" style={{ fontFamily: fonts.display[d.tokens.display]?.stack }}>{plain(d.sample_headline)}</p>
                <p className="text-[14px]" style={{ fontFamily: fonts.body[d.tokens.body]?.stack, opacity: 0.8 }}>{d.mood}</p>
                <span className="inline-flex min-h-10 items-center px-4 text-[13px] font-semibold"
                  style={{ background: p.primary, color: contrastText(p), borderRadius: radius, fontFamily: fonts.body[d.tokens.body]?.stack }}>
                  Plan my trip on WhatsApp
                </span>
              </div>
              <div className="flex flex-1 flex-col gap-3 border-t border-[var(--haip-border)] p-4">
                <Swatches d={d} />
                <p className="text-[12px] text-[var(--haip-fg-muted)]">
                  {`${fonts.display[d.tokens.display]?.family} + ${fonts.body[d.tokens.body]?.family} · ${d.tokens.radius} corners · calm motion`}
                </p>
                {onPick && (
                  <button type="button" disabled={busy} onClick={() => onPick(i)}
                    className="mt-auto inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-3.5 text-[13px] font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 sm:min-h-9">
                    Use this look
                  </button>
                )}
                {pickedIndex === i && <p className="text-[13px] font-semibold text-primary">Picked: your draft uses this look</p>}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

/** The same choice the server makes (schemas/site_spec.derived): ink or surface, whichever reads better on primary. */
function contrastText(p: Direction["tokens"]["palette"]): string {
  const lum = (h: string) => {
    const c = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
  return ratio(p.ink, p.primary) >= ratio(p.surface, p.primary) ? p.ink : p.surface;
}
