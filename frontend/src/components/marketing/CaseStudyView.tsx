// A published case study: the owner-approved snapshot of the impact view (aggregates only, no guest data). Every figure names
// its period and whether the "before" was entered by the owner or measured by HAIP.
import Link from "next/link";
import { ArrowRight } from "@/lib/icons";
import { CHANNEL_LABELS, formatChange, formatDay, formatPeriod, formatValue, type PublicSnapshot } from "@/components/impact/types";

const CHANGE_INK = { success: "text-[var(--haip-status-success-fg)]", danger: "text-[var(--haip-status-danger-fg)]", neutral: "text-[var(--mkt-muted)]" } as const;

export function CaseStudyView({ s }: { s: PublicSnapshot }) {
  return (
    <div className="min-h-screen bg-[var(--mkt-bg)] text-[var(--mkt-text)]">
      <section className="px-4 pb-10 pt-28 sm:px-8 sm:pt-32">
        <div className="mx-auto max-w-5xl">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--mkt-gold)]">Case study · HAIP live since {formatDay(s.go_live)}</p>
          <h1 className="mt-3 text-3xl font-black tracking-tight sm:text-5xl">{s.brand_name}</h1>
          {s.headline && <p className="mt-4 text-xl font-bold leading-snug sm:text-2xl">{s.headline}</p>}
          {s.summary && <p className="mt-4 max-w-3xl whitespace-pre-line text-base leading-relaxed text-[var(--mkt-muted)]">{s.summary}</p>}
          <p className="mt-5 text-sm text-[var(--mkt-muted)]">
            With HAIP = measured by HAIP, {formatPeriod(s.windows.with)} (IST). Before = the owner&apos;s own figure for the period stated,
            or what HAIP recorded {formatPeriod(s.windows.before)}.
          </p>
        </div>
      </section>

      <section className="px-4 pb-12 sm:px-8">
        <div className="mx-auto grid max-w-5xl grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {s.tiles.map(t => {
            const change = formatChange(t.change);
            return (
              <div key={t.key} className="rounded-2xl border border-[var(--mkt-border)] bg-[var(--mkt-panel)] p-5">
                <p className="text-sm font-semibold">{t.label}</p>
                <div className="mt-3 flex items-baseline gap-3">
                  <span className="text-3xl font-black tabular-nums">{formatValue(t.with.value, t.unit)}</span>
                  {change && <span className={`text-sm font-bold ${CHANGE_INK[change.tone]}`}>{change.text}</span>}
                </div>
                <p className="mt-1 text-xs text-[var(--mkt-muted)]">With HAIP · {t.with.period.replace(" to ", " – ")}</p>
                <p className="mt-3 text-sm text-[var(--mkt-muted)]">
                  {t.before
                    ? <>Before: <span className="font-semibold text-[var(--mkt-text)]">{formatValue(t.before.value, t.unit)}</span> ({t.before.source === "owner_entered" ? "reported by the owner" : "measured by HAIP"}, {t.before.period.replace(" to ", " – ")})</>
                    : "No before figure"}
                </p>
                <details className="mt-3 text-xs text-[var(--mkt-muted)]"><summary className="min-h-11 cursor-pointer py-3 font-semibold sm:min-h-0 sm:py-0">How this is counted</summary><p className="mt-1 leading-relaxed">{t.definition}</p></details>
              </div>
            );
          })}
        </div>
      </section>

      {s.channels.length > 0 && (
        <section className="px-4 pb-12 sm:px-8">
          <div className="mx-auto max-w-5xl rounded-2xl border border-[var(--mkt-border)] bg-[var(--mkt-panel)] p-5">
            <h2 className="text-lg font-bold">First reply, by channel</h2>
            <p className="mt-1 text-xs text-[var(--mkt-muted)]">{formatPeriod(s.windows.with)} (IST). One guest turn = a guest message after our reply or after 24 h of silence.</p>
            <table className="mt-3 w-full text-sm">
              <thead><tr className="text-left text-xs text-[var(--mkt-muted)]">
                <th className="py-2 font-semibold">Channel</th><th className="py-2 text-right font-semibold">Turns</th>
                <th className="py-2 text-right font-semibold">Answered</th><th className="py-2 text-right font-semibold">Median</th>
                <th className="hidden py-2 text-right font-semibold sm:table-cell">Within 15 min</th>
              </tr></thead>
              <tbody>{s.channels.map(c => (
                <tr key={c.channel} className="border-t border-[var(--mkt-border)]">
                  <td className="py-2 pr-2">{CHANNEL_LABELS[c.channel] ?? c.label}</td>
                  <td className="py-2 text-right tabular-nums">{formatValue(c.turns, "count")}</td>
                  <td className="py-2 text-right tabular-nums">{formatValue(c.answered_pct, "%")}</td>
                  <td className="py-2 text-right tabular-nums">{formatValue(c.median_minutes, "minutes")}</td>
                  <td className="hidden py-2 text-right tabular-nums sm:table-cell">{formatValue(c.within_15_pct, "%")}</td>
                </tr>))}
              </tbody>
            </table>
            {s.after_hours.turns > 0 && (
              <p className="mt-4 text-sm text-[var(--mkt-muted)]">
                After hours: {formatValue(s.after_hours.turns, "count")} guest turns, {formatValue(s.after_hours.within_15_pct, "%")} answered within 15 minutes,
                {" "}{formatValue(s.after_hours.ai_share_pct, "%")} of the answered ones by the AI on its own.
              </p>
            )}
          </div>
        </section>
      )}

      <section className="px-4 pb-20 sm:px-8">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-4">
          <p className="text-xs text-[var(--mkt-muted)]">Numbers as of {formatDay(s.measured_through)}, published by {s.brand_name}. No guest data is shown.</p>
          <Link href="/book-demo" className="inline-flex min-h-11 items-center gap-2 rounded-2xl bg-[var(--mkt-gold)] px-5 font-bold text-[var(--mkt-bg)]">
            Book a demo <ArrowRight size={16} />
          </Link>
        </div>
      </section>
    </div>
  );
}

export function CaseStudyComingSoon({ name }: { name?: string }) {
  return (
    <div className="min-h-screen bg-[var(--mkt-bg)] px-4 pb-20 pt-32 text-[var(--mkt-text)] sm:px-8">
      <div className="mx-auto max-w-2xl text-center">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--mkt-gold)]">Case study</p>
        <h1 className="mt-3 text-3xl font-black tracking-tight sm:text-4xl">{name ? `${name}: coming soon` : "Coming soon"}</h1>
        <p className="mt-4 text-base leading-relaxed text-[var(--mkt-muted)]">
          We publish a case study only with numbers the business itself has approved. This one is not ready yet.
        </p>
        <Link href="/case-studies" className="mt-8 inline-flex min-h-11 items-center gap-2 rounded-2xl border border-[var(--mkt-border)] px-5 font-semibold">
          All case studies <ArrowRight size={16} />
        </Link>
      </div>
    </div>
  );
}
