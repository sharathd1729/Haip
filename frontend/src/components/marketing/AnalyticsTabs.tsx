"use client";

import { useState } from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

const tabs = [
  {
    id: "calls",
    label: "Calls",
    question: "Which calls converted to bookings?",
    metrics: [
      { label: "Total Calls", value: "248", sub: "this month", trend: "up" },
      { label: "Converted", value: "67", sub: "27% conversion", trend: "up" },
      { label: "Avg Duration", value: "4m 18s", sub: "qualifying calls", trend: "neutral" },
      { label: "Missed Revenue", value: "₹1.8L", sub: "identified by AI", trend: "down" },
    ],
    rows: [
      { label: "Priya Sharma", detail: "Sunset Villa · 8m 12s", tag: "Booked", score: "94", color: "#00555a" },
      { label: "+91 98210 44392", detail: "Pool Villa · 3m 08s", tag: "Follow-up", score: "71", color: "#00888f" },
      { label: "Arjun Mehta", detail: "Garden Suite · 6m 44s", tag: "Booked", score: "88", color: "#00555a" },
      { label: "+91 77001 29384", detail: "Pricing inquiry · 1m 22s", tag: "Lost", score: "34", color: "#e11d48" },
    ],
    insight: "Top missed upsell: Private chef not offered in 43% of booking calls",
  },
  {
    id: "guests",
    label: "Guests",
    question: "Which guests are most likely to return?",
    metrics: [
      { label: "Active Guests", value: "124", sub: "with open inquiry", trend: "up" },
      { label: "Repeat Guests", value: "38%", sub: "of bookings", trend: "up" },
      { label: "Avg LTV", value: "₹94K", sub: "per returning guest", trend: "up" },
      { label: "DPDP Compliant", value: "100%", sub: "consent captured", trend: "neutral" },
    ],
    rows: [
      { label: "Priya & Rajesh Sharma", detail: "3 stays · ₹2.4L lifetime", tag: "VIP", score: "98", color: "#00555a" },
      { label: "Arjun Mehta", detail: "2 stays · ₹98K lifetime", tag: "Regular", score: "82", color: "#00888f" },
      { label: "Kavya & Dev Nair", detail: "First inquiry · WhatsApp", tag: "New Lead", score: "—", color: "#e6b000" },
      { label: "Sunita Krishnan", detail: "1 stay · Anniversary group", tag: "Return likely", score: "77", color: "#00888f" },
    ],
    insight: "Guests who receive a follow-up within 2 hours convert at 3.2× the rate",
  },
  {
    id: "bookings",
    label: "Bookings",
    question: "Where are bookings coming from?",
    metrics: [
      { label: "Confirmed", value: "34", sub: "this month", trend: "up" },
      { label: "Pipeline Value", value: "₹18.4L", sub: "open inquiries", trend: "up" },
      { label: "Avg Lead Time", value: "22 days", sub: "inquiry to booking", trend: "neutral" },
      { label: "Lost Inquiries", value: "12", sub: "reason captured", trend: "down" },
    ],
    rows: [
      { label: "WhatsApp Inbound", detail: "18 bookings · 52% share", tag: "Top channel", score: "52%", color: "#00555a" },
      { label: "Phone Inquiry", detail: "11 bookings · 32% share", tag: "Strong", score: "32%", color: "#00888f" },
      { label: "Instagram DM", detail: "5 bookings · 15% share", tag: "Growing", score: "15%", color: "#e6b000" },
      { label: "Lost: Price concern", detail: "8 inquiries lost", tag: "Review pricing", score: "—", color: "#e11d48" },
    ],
    insight: "62% of lost bookings cited no timely follow-up as the primary reason",
  },
  {
    id: "revenue",
    label: "Revenue",
    question: "Where is revenue coming from?",
    metrics: [
      { label: "This Month", value: "₹28.4L", sub: "confirmed bookings", trend: "up" },
      { label: "Pipeline", value: "₹18.4L", sub: "open inquiries", trend: "up" },
      { label: "Upsell Revenue", value: "₹3.2L", sub: "add-ons captured", trend: "up" },
      { label: "Avg Booking Value", value: "₹83K", sub: "per confirmed stay", trend: "up" },
    ],
    rows: [
      { label: "Sunset Villa", detail: "12 bookings · ₹9.8L", tag: "Top property", score: "₹9.8L", color: "#00555a" },
      { label: "Pool Villa", detail: "9 bookings · ₹7.2L", tag: "Strong", score: "₹7.2L", color: "#00888f" },
      { label: "Garden Suite (3)", detail: "13 bookings · ₹6.1L", tag: "Volume", score: "₹6.1L", color: "#e6b000" },
      { label: "Add-ons & Upsells", detail: "Chef, spa, transfers", tag: "Growing", score: "₹3.2L", color: "#00555a" },
    ],
    insight: "Properties with WhatsApp integration show 2.1× higher average booking values",
  },
  {
    id: "reviews",
    label: "Reviews",
    question: "Which guests are most likely to refer?",
    metrics: [
      { label: "Avg Rating", value: "4.8", sub: "across all properties", trend: "up" },
      { label: "Reviews Collected", value: "47", sub: "this month", trend: "up" },
      { label: "Response Rate", value: "94%", sub: "reviews responded to", trend: "up" },
      { label: "Promoters", value: "78%", sub: "NPS score", trend: "up" },
    ],
    rows: [
      { label: "Sunset Villa", detail: "4.9 avg · 18 reviews", tag: "Excellent", score: "4.9", color: "#00555a" },
      { label: "Pool Villa", detail: "4.8 avg · 14 reviews", tag: "Excellent", score: "4.8", color: "#00555a" },
      { label: "Garden Suite", detail: "4.6 avg · 15 reviews", tag: "Good", score: "4.6", color: "#00888f" },
      { label: "Priya Sharma", detail: "Repeat guest · Promoter", tag: "Referral sent", score: "★5", color: "#00888f" },
    ],
    insight: "Guests who receive a personalised post-stay message leave reviews at 4× the rate",
  },
];

const trendIcon = (t: string) => {
  if (t === "up") return <TrendingUp size={11} className="text-emerald-500" />;
  if (t === "down") return <TrendingDown size={11} className="text-rose-500" />;
  return <Minus size={11} className="opacity-30" style={{ color: "var(--mkt-text)" }} />;
};

export function AnalyticsTabs() {
  const [active, setActive] = useState(0);
  const tab = tabs[active];

  return (
    <div>
      {/* Tabs */}
      <div className="flex gap-1 mb-8 overflow-x-auto pb-1">
        {tabs.map((t, i) => (
          <button
            key={t.id}
            onClick={() => setActive(i)}
            className="flex-shrink-0 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200"
            style={{
              backgroundColor:
                i === active ? "var(--mkt-gold)" : "var(--mkt-surface)",
              color: i === active ? "#fff" : "var(--mkt-text)",
              opacity: i === active ? 1 : 0.6,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Question */}
      <p
        className="text-base font-medium mb-6 italic"
        style={{ color: "var(--mkt-text)", opacity: 0.5 }}
      >
        &ldquo;{tab.question}&rdquo;
      </p>

      {/* Metric cards */}
      <div
        key={active}
        className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6"
        style={{ animation: "haipFadeUp 0.3s cubic-bezier(0.16,1,0.3,1) both" }}
      >
        {tab.metrics.map((m) => (
          <div
            key={m.label}
            className="rounded-xl p-4 border"
            style={{
              backgroundColor: "var(--mkt-panel)",
              borderColor: "var(--mkt-border)",
            }}
          >
            <div className="flex items-start justify-between mb-1">
              <p className="text-sm font-medium" style={{ color: "#475569" }}>
                {m.label}
              </p>
              {trendIcon(m.trend)}
            </div>
            <p
              className="font-display text-2xl font-light leading-none mb-1"
              style={{ color: "var(--mkt-gold)" }}
            >
              {m.value}
            </p>
            <p className="text-xs" style={{ color: "#1E293B" }}>
              {m.sub}
            </p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div
        className="rounded-2xl border overflow-hidden mb-4"
        style={{ borderColor: "rgba(0,0,0,0.07)" }}
      >
        {tab.rows.map((row, i) => (
          <div
            key={i}
            className="flex items-center gap-4 px-4 py-3.5 border-b last:border-0"
            style={{
              borderColor: "rgba(0,0,0,0.05)",
              backgroundColor: i % 2 === 0 ? "var(--mkt-surface)" : "var(--mkt-panel)",
            }}
          >
            <div
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: row.color }}
            />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold truncate" style={{ color: "#0F172A" }}>
                {row.label}
              </p>
              <p className="text-sm truncate" style={{ color: "#1E293B" }}>
                {row.detail}
              </p>
            </div>
            <span
              className="text-[11px] font-semibold px-2 py-0.5 rounded-full flex-shrink-0"
              style={{
                backgroundColor: `${row.color}12`,
                color: row.color,
                border: `1px solid ${row.color}25`,
              }}
            >
              {row.tag}
            </span>
            <span
              className="text-sm font-bold flex-shrink-0 min-w-[48px] text-right font-display"
              style={{ color: "var(--mkt-gold)" }}
            >
              {row.score}
            </span>
          </div>
        ))}
      </div>

      {/* Insight callout */}
      <div
        className="rounded-xl px-4 py-3 border"
        style={{
          backgroundColor: "rgba(0,85,90,0.06)",
          borderColor: "rgba(0,85,90,0.18)",
        }}
      >
        <p className="text-sm" style={{ color: "var(--mkt-gold)" }}>
          <span className="font-bold">AI Insight: </span>{tab.insight}
        </p>
      </div>
    </div>
  );
}
