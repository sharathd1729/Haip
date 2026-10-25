// Small pieces every v2 section uses. Server-rendered: no hooks here.
import type { ReactNode } from "react";
import { MessageCircle, Phone } from "lucide-react";
import { imageOf, type SiteEnv } from "../types";
import { txt, type Bound, type LiveDataV2, type PageV2, type SectionV2, type WaLink } from "./types";

export interface Ctx { env: SiteEnv; live: LiveDataV2; page: PageV2; first: boolean }

export function bound(ctx: Ctx, s: SectionV2): Bound {
  return ctx.live.bound[s.id] || { wa: null };
}

/** "Wake up where the *road* ends": the starred word is set in the accent italic. */
export function Em({ text }: { text: string }) {
  const parts = text.split(/\*(.+?)\*/g);
  return <>{parts.map((p, i) => (i % 2 ? <em key={i} className="sv-em">{p}</em> : <span key={i}>{p}</span>))}</>;
}

export function Img({ ref_, ctx, className, eager, sizes }: { ref_: unknown; ctx: Ctx; className?: string; eager?: boolean; sizes?: string }) {
  const img = imageOf(ctx.env, ref_);
  if (!img) return null;
  const dims = ctx.live.assets[txt(ref_).slice(6)];
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img className={className} src={img.src} alt={img.alt} width={dims?.w || undefined} height={dims?.h || undefined}
      loading={eager ? "eager" : "lazy"} decoding="async" sizes={sizes} {...(eager ? { fetchPriority: "high" as const } : {})} />
  );
}

export function Heading({ ctx, text, className = "sv-h2" }: { ctx: Ctx; text: string; className?: string }) {
  if (!text) return null;
  return ctx.first ? <h1 className={className}><Em text={text} /></h1> : <h2 className={className}><Em text={text} /></h2>;
}

export function Head({ ctx, s, center }: { ctx: Ctx; s: SectionV2; center?: boolean }) {
  const eyebrow = txt(s.slots.eyebrow), heading = txt(s.slots.heading), intro = txt(s.slots.intro) || txt(s.slots.text);
  if (!eyebrow && !heading && !intro) return null;
  return (
    <header className={`sv-head${center ? " sv-head--center" : ""}`}>
      {eyebrow && <p className="sv-eyebrow">{eyebrow}</p>}
      <Heading ctx={ctx} text={heading} />
      {intro && <p className="sv-lede">{intro}</p>}
    </header>
  );
}

/** A WhatsApp button that carries the section's reference code (data-wa-ref) so the enquiry can be traced to it. */
export function WaButton({ wa, label, quiet, className = "" }: { wa: WaLink | null | undefined; label: string; quiet?: boolean; className?: string }) {
  if (!wa) return null;
  return (
    <a className={`sv-btn${quiet ? " sv-btn--quiet" : ""} ${className}`.trim()} href={wa.href} target="_blank" rel="noopener noreferrer"
      data-wa-ref={wa.code}>
      <MessageCircle aria-hidden="true" size={18} strokeWidth={1.75} /><span className="sv-btn__label">{label}</span>
    </a>
  );
}

export function CallButton({ phone, quiet = true }: { phone: string; quiet?: boolean }) {
  if (!phone) return null;
  return (
    <a className={`sv-btn${quiet ? " sv-btn--quiet" : ""}`} href={`tel:${phone.replace(/[^\d+]/g, "")}`}>
      <Phone aria-hidden="true" size={18} strokeWidth={1.75} />Call us
    </a>
  );
}

export function Section({ s, children, band, className = "" }: { s: SectionV2; children: ReactNode; band?: boolean; className?: string }) {
  return (
    <section id={s.id} className={`sv-sec sv-${s.type} sv-${s.type}--${s.variant}${band ? " sv-band" : ""} ${className}`.trim()}
      data-section={s.type} data-variant={s.variant}>
      {children}
    </section>
  );
}

export function Stars({ n }: { n: number | null | undefined }) {
  if (!n) return null;
  const full = Math.round(n);
  return <span className="sv-stars" aria-label={`${n} out of 5`}>{"★".repeat(full)}<span aria-hidden="true" className="sv-stars__off">{"★".repeat(5 - full)}</span></span>;
}
