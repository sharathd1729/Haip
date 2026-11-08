"use client";
// Website report › "On Google": visibility, actions, money searches and real-visitor speed (backend google_metrics.summary,
// returned as `google` by GET /websites/report). Each block names its period; null = "No data", never 0.
import Link from "next/link";
import { Gauge, MousePointerClick, Search, TrendingUp } from "lucide-react";
import { Stat } from "@/components/ui/kit";
import { type GoogleSummary, num, pctChange, positionChange, VERDICT } from "@/lib/websiteGoogle";

const fmt = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

export function GoogleNumbers({ g }: { g: GoogleSummary }) {
  const period = `${fmt(g.period.from)} – ${fmt(g.period.to)}`;
  const through = g.data_through.search_console || g.data_through.business_profile;
  const home = g.speed.pages[0];
  const phone = home?.mobile;
  const v = g.visibility, a = g.actions;
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <p className="mr-auto font-semibold">On Google</p>
        <Link className="text-sm underline underline-offset-4" href="/dashboard/marketing/website/google">Connect and choose searches</Link>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Stat className="haip-card" icon={Search} label="Seen on Google" value={num(v.total)} change={pctChange(v.change_pct)}
          hint={`${period}. Profile ${num(v.business_profile)}, search results ${num(v.search_results)}`} />
        <Stat className="haip-card" icon={MousePointerClick} label="Google actions" value={num(a.total)} change={pctChange(a.change_pct)}
          hint={`${period}. Website ${num(a.website_clicks)}, calls ${num(a.calls)}, directions ${num(a.directions)}, messages ${num(a.messages)}, search clicks ${num(a.search_clicks)}`} />
        <Stat className="haip-card" icon={TrendingUp} label="Searches you follow"
          value={g.money_queries.length ? `${g.money_queries.filter(q => q.position != null).length} of ${g.money_queries.length} found` : "None picked"}
          hint={`${period}. Average position, 1 = top`} />
        <Stat className="haip-card" icon={Gauge} label="Speed on phones (real visitors)"
          value={!g.speed.configured && !home ? "Not set up" : !phone ? "No data" : phone.verdict ? VERDICT[phone.verdict] ?? phone.verdict : "Too few visitors"}
          hint={g.speed.week_of ? `Google PageSpeed, week of ${fmt(g.speed.week_of)}${phone?.lab_score != null ? `. Lab test ${phone.lab_score}/100` : ""}` : "Checked weekly by Google PageSpeed"} />
      </div>
      {g.money_queries.length > 0 && (
        <ul className="grid gap-1 text-sm">{g.money_queries.map(q => {
          const ch = positionChange(q.position, q.previous);
          return (
            <li key={q.query} className="flex flex-wrap items-baseline gap-x-2 border-t border-[var(--haip-border)] py-2">
              <span className="mr-auto min-w-0 break-words font-medium">{q.query}</span>
              <span>{q.position == null ? "No data" : `position ${q.position}`}</span>
              {ch && <span className={ch.tone === "success" ? "text-[var(--haip-status-success-fg)]" : ch.tone === "danger" ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-muted)]"}>{ch.text}</span>}
            </li>);
        })}</ul>
      )}
      <p className="text-xs text-[var(--haip-fg-muted)]">
        Google reports two to three days late{through ? `; data up to ${fmt(through)}` : ""}. One search can show both your profile and your website, so &quot;Seen on Google&quot; counts appearances, not people.
      </p>
    </div>
  );
}
