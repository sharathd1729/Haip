"use client";
// Free summary and the full report (unlocked by name + phone). Every figure is the server's; this file only lays it out.
import type { ReactNode } from "react";
import { Download } from "@/lib/icons";
import type { AssessmentReport, AssessmentSummary, Cta } from "@/lib/assessment";
import { SCENARIOS, SCENARIO_LABEL, money, months, pct, reportPdfUrl } from "@/lib/assessment";
import { OccupancyCurve, ZoningSketch } from "./Charts";

export function Panel({ title, children, hint }: { title: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-[var(--mkt-border)] bg-[var(--mkt-bg)] p-5 sm:p-6">
      <h2 className="text-lg font-bold text-[var(--mkt-text)]">{title}</h2>
      {hint && <p className="mt-1 text-[13px] text-[var(--mkt-muted)]">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Benchmarks({ label, version, sample }: { label: string; version: string; sample: boolean }) {
  return (
    <p className="text-[12px] text-[var(--mkt-muted)]">
      Benchmarks: {label} (version {version}){sample && <strong className="font-semibold"> · sample values, to be confirmed</strong>}
    </p>
  );
}

function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5 rounded-xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-4 py-3 text-[13px] text-[var(--haip-status-warning-fg)]">
      {items.map(w => <li key={w}>{w}</li>)}
    </ul>
  );
}

export function SummaryCard({ summary }: { summary: AssessmentSummary }) {
  return (
    <Panel title="Your estimate" hint={`${summary.property_type_label} · ${summary.segment_label} · ${summary.keys} rooms · ${summary.location_label}`}>
      <p className="text-[13px] font-semibold uppercase tracking-wide text-[var(--mkt-muted)]">Revenue a year</p>
      <div className="mt-2 grid grid-cols-3 gap-2">
        {SCENARIOS.map(s => (
          <div key={s} className={`rounded-xl px-3 py-3 ${s === "likely" ? "bg-[var(--mkt-surface)] border border-[var(--mkt-border-gold)]" : "bg-[var(--mkt-panel)]"}`}>
            <p className="text-[12px] text-[var(--mkt-muted)]">{SCENARIO_LABEL[s]}</p>
            <p className={`mt-0.5 font-bold tabular-nums break-words ${s === "likely" ? "text-[17px] text-[var(--mkt-gold)]" : "text-[15px] text-[var(--mkt-text)]"}`}>
              {money(summary.yearly_revenue[s])}
            </p>
          </div>
        ))}
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-[14px]">
        <div><dt className="text-[12px] text-[var(--mkt-muted)]">Investment estimate</dt><dd className="font-semibold tabular-nums">{money(summary.investment_total)}</dd></div>
        <div><dt className="text-[12px] text-[var(--mkt-muted)]">Payback (likely)</dt><dd className="font-semibold">{months(summary.payback_months_likely)}</dd></div>
      </dl>
      <div className="mt-4 space-y-3">
        <Warnings items={summary.warnings} />
        <Benchmarks label={summary.benchmark_label} version={summary.benchmark_version} sample={summary.benchmark_sample} />
      </div>
    </Panel>
  );
}

function Row({ label, values, strong }: { label: string; values: ReactNode[]; strong?: boolean }) {
  return (
    <tr className="border-t border-[var(--mkt-border)]">
      <th scope="row" className={`py-2 pr-3 text-left font-normal ${strong ? "font-semibold" : ""}`}>{label}</th>
      {values.map((v, i) => <td key={i} className={`py-2 pl-2 text-right tabular-nums whitespace-nowrap ${strong ? "font-semibold" : ""}`}>{v}</td>)}
    </tr>
  );
}

export function CtaPanel({ cta }: { cta: Cta }) {
  return (
    <Panel title="Run it with HAIP" hint="Two ways to work with us once your property is open.">
      <div className="grid gap-3 sm:grid-cols-2">
        {[cta.saas, cta.service].map(o => (
          <div key={o.title} className="rounded-xl border border-[var(--mkt-border)] bg-[var(--mkt-panel)] p-4">
            <p className="font-bold text-[var(--mkt-text)]">{o.title}</p>
            <p className="mt-1 text-[13.5px] leading-relaxed text-[var(--mkt-muted)]">{o.text}</p>
            <p className="mt-2 text-[13px] font-semibold text-[var(--mkt-gold)]">{o.price_text}</p>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function FullReport({ report, id, token }: { report: AssessmentReport; id: string; token: string }) {
  const y = report.yearly;
  const inv = report.investment;
  return (
    <div className="space-y-5">
      <Panel title="Your full report" hint={`${report.property_type_label} · ${report.segment_label} · ${report.keys} rooms · ${report.plot_sqft.toLocaleString("en-IN")} sq ft · ${report.location_label}`}>
        <a href={reportPdfUrl(id, token)} className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[var(--mkt-gold)] px-5 text-[15px] font-bold text-white">
          <Download size={16} /> Download PDF
        </a>
        <div className="mt-4 space-y-3">
          <Warnings items={report.warnings} />
          <Benchmarks label={report.benchmark_label} version={report.benchmark_version} sample={report.benchmark_sample} />
        </div>
      </Panel>

      <Panel title="A year in numbers" hint={`Room rate about ${money(report.adr)} a night (likely).`}>
        <div className="overflow-x-auto -mx-1 px-1">
          <table className="w-full min-w-[320px] text-[13.5px] text-[var(--mkt-text)]">
            <thead>
              <tr className="text-[12px] text-[var(--mkt-muted)]">
                <th className="py-1 text-left font-semibold"><span className="sr-only">Figure</span></th>
                {SCENARIOS.map(s => <th key={s} className="py-1 pl-2 text-right font-semibold">{SCENARIO_LABEL[s]}</th>)}
              </tr>
            </thead>
            <tbody>
              <Row label="Revenue" strong values={SCENARIOS.map(s => money(y[s].revenue))} />
              <Row label="Per month (average)" values={SCENARIOS.map(s => money(y[s].monthly_average_revenue))} />
              <Row label="OTA commission" values={SCENARIOS.map(s => money(y[s].ota_commission))} />
              <Row label="Running costs" values={SCENARIOS.map(s => money(y[s].running_costs))} />
              <Row label="Net operating income" strong values={SCENARIOS.map(s => money(y[s].net_operating_income))} />
              <Row label="Average occupancy" values={SCENARIOS.map(s => pct(y[s].average_occupancy))} />
              <Row label="Payback" strong values={SCENARIOS.map(s => months(report.payback_months[s]))} />
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[12px] text-[var(--mkt-muted)]">
          Running costs {pct(report.running_cost_pct)} of revenue · OTAs bring {pct(report.ota_share)} of room revenue at {pct(report.ota_commission_pct)} commission.
        </p>
      </Panel>

      <Panel title="Occupancy by month" hint="Likely occupancy (dark) against the high case (light), in %.">
        <OccupancyCurve monthly={report.monthly} />
      </Panel>

      <Panel title="Revenue by month">
        <div className="overflow-x-auto -mx-1 px-1">
          <table className="w-full min-w-[300px] text-[13px] text-[var(--mkt-text)]">
            <thead>
              <tr className="text-[12px] text-[var(--mkt-muted)]">
                <th className="py-1 text-left font-semibold">Month</th>
                {SCENARIOS.map(s => <th key={s} className="py-1 pl-2 text-right font-semibold">{SCENARIO_LABEL[s]}</th>)}
              </tr>
            </thead>
            <tbody>
              {report.monthly.map(m => <Row key={m.month} label={m.month} values={SCENARIOS.map(s => money(m.revenue[s]))} />)}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Investment estimate" hint={`${inv.built_up_sqft.toLocaleString("en-IN")} sq ft built up · ${inv.build_status === "conversion" ? "converting an existing building" : "new build"}`}>
        <table className="w-full text-[14px] text-[var(--mkt-text)]">
          <tbody>
            <Row label="Building" values={[money(inv.build_cost)]} />
            <Row label="Fit-out (rooms)" values={[money(inv.fitout)]} />
            <Row label="Amenities" values={[money(inv.amenities)]} />
            <Row label="Contingency" values={[money(inv.contingency)]} />
            <Row label="Total" strong values={[money(inv.total)]} />
          </tbody>
        </table>
      </Panel>

      <Panel title="Zoning sketch">
        <ZoningSketch zoning={report.zoning} />
      </Panel>

      <Panel title="How we worked it out">
        <ul className="list-disc space-y-1.5 pl-5 text-[13px] leading-relaxed text-[var(--mkt-muted)]">
          {report.assumptions.map(a => <li key={a}>{a}</li>)}
        </ul>
        <p className="mt-3 text-[12px] text-[var(--mkt-muted)]">{report.disclaimer}</p>
      </Panel>

      <CtaPanel cta={report.cta} />
    </div>
  );
}
