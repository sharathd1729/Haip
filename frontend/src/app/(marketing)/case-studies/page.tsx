// /case-studies: only case studies a business has published from its own impact view (owner-approved snapshots, aggregates
// only). The placeholder stories and made-up figures that used to be here are gone; with nothing published the page says so.
import Link from "next/link";
import { ArrowRight, ChevronRight, Sparkles } from "@/lib/icons";
import { formatChange, formatDay, formatValue } from "@/components/impact/types";
import { fetchCaseStudies } from "@/lib/caseStudies";

export const metadata = {
  title: "HAIP Case Studies — How hospitality teams use HAIP",
  description: "Case studies from hospitality and experiential travel businesses using HAIP, with numbers each business approved.",
};

export default async function CaseStudiesPage() {
  const items = await fetchCaseStudies();
  return (
    <div className="min-h-screen bg-[var(--mkt-bg)] text-[var(--mkt-text)]">
      <section className="px-4 pb-12 pt-28 text-center sm:px-8 sm:pt-32">
        <div className="mx-auto max-w-3xl">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[var(--mkt-border-gold)] px-4 py-1.5">
            <Sparkles size={12} className="text-[var(--mkt-gold)]" />
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--mkt-gold)]">Case studies</span>
          </div>
          <h1 className="mb-5 text-4xl font-black tracking-tight sm:text-5xl">Real teams. Their own numbers.</h1>
          <p className="text-lg leading-relaxed text-[var(--mkt-muted)]">
            Every figure here was measured by HAIP or reported by the business, and published only once the owner approved it.
          </p>
        </div>
      </section>

      <section className="px-4 pb-20 sm:px-8">
        <div className="mx-auto grid max-w-5xl gap-5">
          {items.length === 0 ? (
            <div className="rounded-3xl border border-[var(--mkt-border)] bg-[var(--mkt-panel)] p-8 text-center sm:p-12">
              <h2 className="text-2xl font-black tracking-tight">Coming soon</h2>
              <p className="mx-auto mt-3 max-w-xl text-[var(--mkt-muted)]">
                Our design partners are measuring their first months on HAIP. Their case studies appear here as soon as they approve the numbers.
              </p>
            </div>
          ) : items.map(({ slug, snapshot: s }) => (
            <Link key={slug} href={`/case-studies/${slug}`} className="group block rounded-3xl border border-[var(--mkt-border)] bg-[var(--mkt-panel)] p-6 sm:p-10">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-wider text-[var(--mkt-gold)]">HAIP live since {formatDay(s.go_live)}</p>
                  <h2 className="mt-2 text-2xl font-black tracking-tight sm:text-3xl">{s.brand_name}</h2>
                  {s.headline && <p className="mt-2 text-lg font-bold leading-snug">{s.headline}</p>}
                </div>
                <ChevronRight size={18} className="mt-2 shrink-0 text-[var(--mkt-muted)] transition-transform group-hover:translate-x-0.5" />
              </div>
              <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {s.tiles.slice(0, 4).map(t => {
                  const change = formatChange(t.change);
                  return (
                    <div key={t.key} className="min-w-0">
                      <p className="text-xs text-[var(--mkt-muted)]">{t.label}</p>
                      <p className="mt-1 text-2xl font-black tabular-nums">{formatValue(t.with.value, t.unit)}</p>
                      <p className="text-xs text-[var(--mkt-muted)]">
                        {t.before ? `from ${formatValue(t.before.value, t.unit)}` : "no before figure"}{change ? ` · ${change.text}` : ""}
                      </p>
                    </div>
                  );
                })}
              </div>
              <span className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-[var(--mkt-gold)]">
                Read the case study <ArrowRight size={14} />
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="border-t border-[var(--mkt-border)] bg-[var(--mkt-surface)] px-4 py-20 sm:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="mb-4 text-3xl font-black tracking-tight sm:text-4xl">Want to be the next case study?</h2>
          <p className="mx-auto mb-8 max-w-xl text-[var(--mkt-muted)]">Design partners get 6 months free in exchange for case-study rights.</p>
          <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/book-demo?topic=design-partner" className="inline-flex min-h-11 items-center gap-2 rounded-2xl bg-[var(--mkt-gold)] px-6 py-3 font-bold text-[var(--mkt-bg)]">
              Apply as a design partner <ArrowRight size={16} />
            </Link>
            <Link href="/pricing" className="inline-flex min-h-11 items-center gap-2 rounded-2xl border border-[var(--mkt-border)] bg-[var(--mkt-bg)] px-6 py-3 font-semibold">
              See pricing
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
