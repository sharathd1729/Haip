"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  MessageCircle, Phone, UserCheck, CalendarCheck, Star, RefreshCw,
} from "lucide-react";

// ─── Stage data (copy unchanged) ─────────────────────────────────────────────

const stages = [
  {
    id: "inquiry", label: "Inquiry", icon: MessageCircle, source: "via WhatsApp",
    screen: {
      title: "Lead captured", detail: "Sunset Villa · Dec 20–26 · Family of 6",
      channel: "WhatsApp", tags: ["New Lead", "High Value"],
      body: [
        { from: "guest", text: "Is the Sunset Villa available for Dec 20–26? We are a family of 6." },
        { from: "agent", text: "Hi Priya! Yes, it's available and fits 8 guests comfortably. Let me send you pricing." },
      ],
      meta: "Lead source identified · Guest profile auto-created",
    },
  },
  {
    id: "conversation", label: "Conversation", icon: Phone, source: "Call + WhatsApp",
    screen: {
      title: "Communication history", detail: "3 WhatsApp messages · 1 call (4m 32s)",
      channel: "Multi-channel", tags: ["In Progress", "Interested"],
      body: [
        { from: "meta", text: "📞 Inbound call · 4m 32s · AI Score: 91 · Outcome: Pricing discussed" },
        { from: "guest", text: "What about early check-in on the 20th?" },
        { from: "agent", text: "Absolutely — we can arrange 11 AM check-in at no extra charge." },
      ],
      meta: "AI transcript ready · Sentiment: Positive · Intent: Booking",
    },
  },
  {
    id: "booking", label: "Booking", icon: CalendarCheck, source: "Reservation confirmed",
    screen: {
      title: "Booking confirmed", detail: "Sunset Villa · Dec 20–26 · ₹84,000",
      channel: "Direct", tags: ["Confirmed", "Paid"],
      body: [
        { from: "meta", text: "✅ Reservation created · Advance: ₹21,000 received" },
        { from: "agent", text: "Priya, your booking is confirmed! Sending itinerary on WhatsApp." },
        { from: "meta", text: "📋 Itinerary sent · Pre-arrival checklist triggered" },
      ],
      meta: "Revenue: ₹84,000 · Nights: 6 · Guests: 6 · Source: WhatsApp Inquiry",
    },
  },
  {
    id: "stay", label: "Stay", icon: UserCheck, source: "Checked in",
    screen: {
      title: "Guest in-stay", detail: "Day 2 of 6 · All requests handled",
      channel: "Active", tags: ["Checked In", "VIP"],
      body: [
        { from: "guest", text: "Can we arrange a private chef for dinner tomorrow?" },
        { from: "agent", text: "Of course! Chef Rohan is available. Menu options sent to your WhatsApp." },
        { from: "meta", text: "🍽️ Upsell logged: Private chef · ₹6,000 · Revenue updated" },
      ],
      meta: "In-stay requests: 3 handled · Upsell revenue: ₹6,000 · NPS: Excellent",
    },
  },
  {
    id: "review", label: "Review", icon: Star, source: "5-star review",
    screen: {
      title: "Post-stay feedback", detail: "5 stars · Google + WhatsApp",
      channel: "Review collected", tags: ["5 Stars", "Promoter"],
      body: [
        { from: "meta", text: "⭐⭐⭐⭐⭐ Google review submitted by Priya Sharma" },
        { from: "guest", text: "Absolutely magical stay. The team went above and beyond. Will be back!" },
        { from: "meta", text: "🎉 Review response sent · Guest tagged as Promoter" },
      ],
      meta: "Review score: 5/5 · Shared to Google · Loyalty tag: Promoter",
    },
  },
  {
    id: "repeat", label: "Repeat Guest", icon: RefreshCw, source: "Returns in 4 months",
    screen: {
      title: "Returning guest", detail: "3rd visit · Lifetime value: ₹2.4L",
      channel: "Recognised", tags: ["VIP", "Returning"],
      body: [
        { from: "meta", text: "🔄 Priya Sharma is back · Previous stays: 2 · Preferences loaded" },
        { from: "agent", text: "Welcome back, Priya! We've pre-arranged early check-in and your preferred chef." },
        { from: "guest", text: "You remembered! This is why we keep coming back 😊" },
      ],
      meta: "Lifetime stays: 3 · Total revenue: ₹2,40,000 · Acquisition cost: ₹0",
    },
  },
];

// ─── Component ────────────────────────────────────────────────────────────────

export function GuestJourney() {
  const [active, setActive] = useState(0);
  const stage = stages[active];
  const Icon = stage.icon;

  // Progress fraction for the line under the tabs
  const progressPct = stages.length > 1 ? (active / (stages.length - 1)) * 100 : 0;

  return (
    <div>
      {/* ── Tab row ───────────────────────────────────────────────────────── */}
      <div className="flex gap-2 flex-wrap justify-center mb-6">
        {stages.map((s, i) => {
          const isActive = i === active;
          const SIcon = s.icon;
          return (
            <button
              key={s.id}
              onClick={() => setActive(i)}
              className="flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold transition-all duration-150"
              style={isActive
                ? { backgroundColor: "#00555a", color: "#ffffff", boxShadow: "0 4px 12px rgba(0,85,90,0.25)" }
                : { color: "#64748B" }
              }
              onMouseEnter={e => {
                if (!isActive) {
                  (e.currentTarget as HTMLElement).style.color = "#00555a";
                  (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(0,85,90,0.06)";
                }
              }}
              onMouseLeave={e => {
                if (!isActive) {
                  (e.currentTarget as HTMLElement).style.color = "#64748B";
                  (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                }
              }}
            >
              <SIcon size={13} />
              {s.label}
            </button>
          );
        })}
      </div>

      {/* ── Progress line ─────────────────────────────────────────────────── */}
      <div className="relative h-0.5 rounded-full mb-10 mx-auto max-w-2xl" style={{ backgroundColor: "#E2E8F0" }}>
        <motion.div
          className="absolute left-0 top-0 h-full rounded-full"
          style={{ backgroundColor: "#00555a" }}
          animate={{ width: `${progressPct}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
      </div>

      {/* ── Content card ─────────────────────────────────────────────────── */}
      <AnimatePresence mode="wait">
        <motion.div
          key={active}
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0, transition: { duration: 0.25, ease: "easeOut" } }}
          exit={{ opacity: 0, x: 10, transition: { duration: 0.15 } }}
          className="rounded-2xl border overflow-hidden"
          style={{
            backgroundColor: "#ffffff",
            borderColor: "#E2E8F0",
            boxShadow: "0 20px 48px rgba(0,0,0,0.08)",
          }}
        >
          {/* Card header */}
          <div
            className="flex items-center justify-between px-6 py-5 border-b"
            style={{ backgroundColor: "rgba(0,85,90,0.04)", borderColor: "#E2E8F0" }}
          >
            <div className="flex items-center gap-3">
              <div
                className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: "#00555a" }}
              >
                <Icon size={15} color="#ffffff" />
              </div>
              <div>
                <p className="text-sm font-semibold" style={{ color: "#0F172A" }}>
                  {stage.screen.title}
                </p>
                <p className="text-xs mt-0.5" style={{ color: "#64748B" }}>
                  {stage.screen.detail}
                </p>
              </div>
            </div>

            {/* Tags — "High Value" gets mimosa, others get teal */}
            <div className="flex gap-2 flex-wrap justify-end">
              {stage.screen.tags.map(tag => (
                <span
                  key={tag}
                  className="text-[10px] font-bold px-2.5 py-0.5 rounded-full"
                  style={tag === "High Value" || tag === "VIP"
                    ? { backgroundColor: "#ffc94b", color: "#00555a" }
                    : { backgroundColor: "rgba(0,85,90,0.10)", color: "#00555a" }
                  }
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>

          {/* Messages */}
          <div className="px-6 py-5 space-y-3">
            {stage.screen.body.map((msg, i) => (
              <div key={i} className={`flex ${msg.from === "agent" ? "justify-end" : "justify-start"}`}>
                {msg.from === "meta" ? (
                  <div
                    className="w-full text-center text-xs py-1.5 px-3 rounded-lg"
                    style={{ backgroundColor: "rgba(0,85,90,0.06)", color: "#00555a" }}
                  >
                    {msg.text}
                  </div>
                ) : (
                  <div
                    className="max-w-[75%] rounded-2xl px-4 py-2.5"
                    style={msg.from === "agent"
                      ? { backgroundColor: "rgba(0,85,90,0.10)", border: "1px solid rgba(0,85,90,0.18)" }
                      : { backgroundColor: "#F1F5F9", border: "1px solid #E2E8F0" }
                    }
                  >
                    <p className="text-sm leading-relaxed" style={{ color: "#0F172A" }}>
                      {msg.text}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Card footer */}
          <div
            className="px-6 py-3.5 border-t"
            style={{ borderColor: "#E2E8F0", backgroundColor: "#FAFAFA" }}
          >
            <p className="text-xs" style={{ color: "#64748B" }}>
              {stage.screen.meta}
            </p>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
