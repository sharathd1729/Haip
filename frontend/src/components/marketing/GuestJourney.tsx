"use client";

import { useState } from "react";
import {
  MessageCircle, Phone, UserCheck, CalendarCheck, Star, RefreshCw,
} from "lucide-react";

const stages = [
  {
    id: "inquiry",
    label: "Inquiry",
    icon: MessageCircle,
    color: "#0F766E",
    source: "via WhatsApp",
    screen: {
      title: "Lead captured",
      detail: "Sunset Villa · Dec 20–26 · Family of 6",
      channel: "WhatsApp",
      tags: ["New Lead", "High Value"],
      body: [
        { from: "guest", text: "Is the Sunset Villa available for Dec 20–26? We are a family of 6." },
        { from: "agent", text: "Hi Priya! Yes, it's available and fits 8 guests comfortably. Let me send you pricing." },
      ],
      meta: "Lead source identified · Guest profile auto-created",
    },
  },
  {
    id: "conversation",
    label: "Conversation",
    icon: Phone,
    color: "#14B8A6",
    source: "Call + WhatsApp",
    screen: {
      title: "Communication history",
      detail: "3 WhatsApp messages · 1 call (4m 32s)",
      channel: "Multi-channel",
      tags: ["In Progress", "Interested"],
      body: [
        { from: "meta", text: "📞 Inbound call · 4m 32s · AI Score: 91 · Outcome: Pricing discussed" },
        { from: "guest", text: "What about early check-in on the 20th?" },
        { from: "agent", text: "Absolutely — we can arrange 11 AM check-in at no extra charge." },
      ],
      meta: "AI transcript ready · Sentiment: Positive · Intent: Booking",
    },
  },
  {
    id: "booking",
    label: "Booking",
    icon: CalendarCheck,
    color: "#0F766E",
    source: "Reservation confirmed",
    screen: {
      title: "Booking confirmed",
      detail: "Sunset Villa · Dec 20–26 · ₹84,000",
      channel: "Direct",
      tags: ["Confirmed", "Paid"],
      body: [
        { from: "meta", text: "✅ Reservation created · Advance: ₹21,000 received" },
        { from: "agent", text: "Priya, your booking is confirmed! Sending itinerary on WhatsApp." },
        { from: "meta", text: "📋 Itinerary sent · Pre-arrival checklist triggered" },
      ],
      meta: "Revenue: ₹84,000 · Nights: 6 · Guests: 6 · Source: WhatsApp Inquiry",
    },
  },
  {
    id: "stay",
    label: "Stay",
    icon: UserCheck,
    color: "#14B8A6",
    source: "Checked in",
    screen: {
      title: "Guest in-stay",
      detail: "Day 2 of 6 · All requests handled",
      channel: "Active",
      tags: ["Checked In", "VIP"],
      body: [
        { from: "guest", text: "Can we arrange a private chef for dinner tomorrow?" },
        { from: "agent", text: "Of course! Chef Rohan is available. Menu options sent to your WhatsApp." },
        { from: "meta", text: "🍽️ Upsell logged: Private chef · ₹6,000 · Revenue updated" },
      ],
      meta: "In-stay requests: 3 handled · Upsell revenue: ₹6,000 · NPS: Excellent",
    },
  },
  {
    id: "review",
    label: "Review",
    icon: Star,
    color: "#14B8A6",
    source: "5-star review",
    screen: {
      title: "Post-stay feedback",
      detail: "5 stars · Google + WhatsApp",
      channel: "Review collected",
      tags: ["5 Stars", "Promoter"],
      body: [
        { from: "meta", text: "⭐⭐⭐⭐⭐ Google review submitted by Priya Sharma" },
        { from: "guest", text: "Absolutely magical stay. The team went above and beyond. Will be back!" },
        { from: "meta", text: "🎉 Review response sent · Guest tagged as Promoter" },
      ],
      meta: "Review score: 5/5 · Shared to Google · Loyalty tag: Promoter",
    },
  },
  {
    id: "repeat",
    label: "Repeat Guest",
    icon: RefreshCw,
    color: "#0F766E",
    source: "Returns in 4 months",
    screen: {
      title: "Returning guest",
      detail: "3rd visit · Lifetime value: ₹2.4L",
      channel: "Recognised",
      tags: ["VIP", "Returning"],
      body: [
        { from: "meta", text: "🔄 Priya Sharma is back · Previous stays: 2 · Preferences loaded" },
        { from: "agent", text: "Welcome back, Priya! We've pre-arranged early check-in and your preferred chef." },
        { from: "guest", text: "You remembered! This is why we keep coming back 😊" },
      ],
      meta: "Lifetime stays: 3 · Total revenue: ₹2,40,000 · Acquisition cost: ₹0",
    },
  },
];

export function GuestJourney() {
  const [active, setActive] = useState(0);
  const stage = stages[active];
  const Icon = stage.icon;

  return (
    <div className="grid lg:grid-cols-[320px_1fr] gap-8 items-start">
      {/* Stage nav */}
      <div className="flex flex-col gap-1">
        {stages.map((s, i) => {
          const SIcon = s.icon;
          const isActive = i === active;
          const isPast = i < active;
          return (
            <button
              key={s.id}
              onClick={() => setActive(i)}
              className="flex items-center gap-3 px-4 py-3.5 rounded-xl text-left transition-all duration-200 group"
              style={{
                backgroundColor: isActive
                  ? `${s.color}15`
                  : "transparent",
                border: `1px solid ${isActive ? s.color + "40" : "transparent"}`,
              }}
            >
              {/* Connector */}
              <div className="flex flex-col items-center gap-1 flex-shrink-0">
                <div
                  className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-all duration-200"
                  style={{
                    backgroundColor: isActive
                      ? s.color
                      : isPast
                      ? `${s.color}30`
                      : "rgba(0,0,0,0.05)",
                    border: `2px solid ${isActive || isPast ? s.color : "rgba(0,0,0,0.1)"}`,
                  }}
                >
                  <SIcon
                    size={14}
                    style={{
                      color: isActive ? "#fff" : isPast ? s.color : "rgba(0,0,0,0.3)",
                    }}
                  />
                </div>
                {i < stages.length - 1 && (
                  <div
                    className="w-px h-4"
                    style={{
                      backgroundColor: isPast ? s.color + "50" : "rgba(0,0,0,0.08)",
                    }}
                  />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p
                  className="text-sm font-semibold leading-none mb-0.5"
                  style={{
                    color: isActive
                      ? s.color
                      : "var(--mkt-text)",
                    opacity: isActive ? 1 : 0.6,
                  }}
                >
                  {s.label}
                </p>
                <p
                  className="text-xs truncate"
                  style={{ color: "var(--mkt-text)", opacity: 0.35 }}
                >
                  {s.source}
                </p>
              </div>
              {isActive && (
                <div
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: s.color }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Screen preview */}
      <div
        key={active}
        className="rounded-2xl border overflow-hidden shadow-xl"
        style={{
          backgroundColor: "var(--mkt-panel)",
          borderColor: `${stage.color}25`,
          boxShadow: `0 20px 60px -10px ${stage.color}20`,
          animation: "haipFadeUp 0.3s cubic-bezier(0.16,1,0.3,1) both",
        }}
      >
        {/* Screen header */}
        <div
          className="flex items-center justify-between px-5 py-4 border-b"
          style={{
            backgroundColor: `${stage.color}08`,
            borderColor: `${stage.color}20`,
          }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: stage.color }}
            >
              <Icon size={15} color="#fff" />
            </div>
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--mkt-text)" }}>
                {stage.screen.title}
              </p>
              <p className="text-xs" style={{ color: "var(--mkt-text)", opacity: 0.45 }}>
                {stage.screen.detail}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            {stage.screen.tags.map((tag) => (
              <span
                key={tag}
                className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                style={{
                  backgroundColor: `${stage.color}15`,
                  color: stage.color,
                  border: `1px solid ${stage.color}30`,
                }}
              >
                {tag}
              </span>
            ))}
          </div>
        </div>

        {/* Messages */}
        <div className="px-5 py-4 space-y-3">
          {stage.screen.body.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.from === "agent" ? "justify-end" : "justify-start"}`}
            >
              {msg.from === "meta" ? (
                <div
                  className="w-full text-center text-[11px] py-1.5 px-3 rounded-lg"
                  style={{
                    backgroundColor: `${stage.color}08`,
                    color: stage.color,
                    opacity: 0.8,
                  }}
                >
                  {msg.text}
                </div>
              ) : (
                <div
                  className="max-w-[75%] rounded-2xl px-3.5 py-2.5"
                  style={{
                    backgroundColor:
                      msg.from === "agent"
                        ? `${stage.color}15`
                        : "rgba(0,0,0,0.05)",
                    border: msg.from === "agent"
                      ? `1px solid ${stage.color}25`
                      : "1px solid rgba(0,0,0,0.06)",
                  }}
                >
                  <p
                    className="text-xs leading-relaxed"
                    style={{ color: "var(--mkt-text)", opacity: msg.from === "agent" ? 0.85 : 0.65 }}
                  >
                    {msg.text}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Screen footer */}
        <div
          className="px-5 py-3 border-t"
          style={{
            borderColor: `${stage.color}15`,
            backgroundColor: "rgba(0,0,0,0.02)",
          }}
        >
          <p className="text-[11px]" style={{ color: "var(--mkt-text)", opacity: 0.4 }}>
            {stage.screen.meta}
          </p>
        </div>
      </div>
    </div>
  );
}
