"use client";

import { useState, useRef, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Search, X, RefreshCw, AlertCircle, Inbox, Mail, Home, Globe, ChevronLeft, Clock, MessageSquare, Phone, AtSign, Hash, AlertTriangle, CheckCircle2, Loader2, Send } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useRWThreads, useRWThreadMessages, useSendRWMessage } from "@/hooks/useRentalWise";
import { type RWThread, type RWMessage, type RWProvider, localStr } from "@/lib/rentalwise";
import { Skeleton } from "@/components/ui/skeleton";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface ThreadFilter {
  value: string;
  label: string;
  provider?: RWProvider;
  attention?: boolean;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const THREAD_FILTERS: ThreadFilter[] = [
  { value: "all",          label: "All" },
  { value: "airbnb",       label: "Airbnb",       provider: "airbnb" },
  { value: "booking-com",  label: "Booking.com",  provider: "booking-com" },
  { value: "homeaway",     label: "HomeAway",     provider: "homeaway" },
  { value: "email",        label: "Email",        provider: "email" },
  { value: "attention",    label: "Needs Attention", attention: true },
];

const PROVIDER_COLORS: Record<string, string> = {
  airbnb:        "#FF5A5F",
  "booking-com": "#003580",
  homeaway:      "#1D5AA1",
  email:         "#6B7280",
};

const PROVIDER_LABELS: Record<string, string> = {
  airbnb:        "Airbnb",
  "booking-com": "Booking.com",
  homeaway:      "HomeAway",
  email:         "Email",
};

// ─── Provider badge ────────────────────────────────────────────────────────────

function ProviderBadge({ provider: providerRaw, size = "sm" }: { provider: RWProvider; size?: "sm" | "md" }) {
  // Guard: API may return an object instead of a string
  const provider: string = (
    typeof providerRaw === "string"
      ? providerRaw
      : typeof providerRaw === "object" && providerRaw !== null
        ? String((providerRaw as any).id ?? (providerRaw as any).slug ?? (providerRaw as any).name ?? "")
        : String(providerRaw ?? "")
  );
  const color = PROVIDER_COLORS[provider] ?? "#6B7280";
  const label = PROVIDER_LABELS[provider] ?? provider;
  const pad   = size === "sm" ? "px-1.5 py-0.5 text-[9px]" : "px-2 py-1 text-[11px]";

  const icon = provider === "booking-com" ? (
    <Globe size={size === "sm" ? 9 : 11} />
  ) : provider === "homeaway" ? (
    <Home size={size === "sm" ? 9 : 11} />
  ) : provider === "email" ? (
    <Mail size={size === "sm" ? 9 : 11} />
  ) : (
    // Airbnb — simple circle-A icon
    <span className="font-black leading-none" style={{ fontSize: size === "sm" ? 9 : 11 }}>A</span>
  );

  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-md font-semibold", pad)}
      style={{ background: `${color}15`, color }}
    >
      {icon}
      {label}
    </span>
  );
}

// ─── Time helper ──────────────────────────────────────────────────────────────

function formatTime(iso: string | null): string {
  if (!iso) return "";
  const d    = new Date(iso);
  const now  = new Date();
  const hrs  = (now.getTime() - d.getTime()) / 3600000;
  if (hrs < 24)    return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  if (hrs < 48*24) return `${Math.floor(hrs / 24)}d ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

// ─── Thread list item ──────────────────────────────────────────────────────────

function ThreadRow({ thread, active, onClick }: { thread: RWThread; active: boolean; onClick: () => void }) {
  const { first_name, last_name, email } = thread.account ?? {};
  const name     = [localStr(first_name), localStr(last_name)].filter(Boolean).join(" ") || localStr(email) || "Unknown";
  const initials = name.split(" ").map((n: string) => n[0]).join("").slice(0, 2).toUpperCase();

  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-4 py-3 border-b transition-colors",
        active
          ? "bg-[var(--haip-primary-tint)] border-l-2 border-l-[#0F766E]"
          : "hover:bg-[var(--haip-surface)] border-l-2 border-l-transparent",
        "border-b-gray-100"
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0 mt-0.5"
          style={{
            background: thread.requires_attention
              ? "linear-gradient(135deg, #F59E0B, #D97706)"
              : "linear-gradient(135deg, #14B8A6, #0F766E)",
          }}
        >
          {initials}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-0.5">
            <p className="text-[13px] font-semibold truncate" style={{ color: "#111827" }}>
              {name}
            </p>
            <span className="text-[10px] flex-shrink-0" style={{ color: "#9CA3AF" }}>
              {formatTime(thread.last_message_at)}
            </span>
          </div>

          {thread.last_message_excerpt && (
            <p className="text-[11px] truncate mb-1.5" style={{ color: "#9CA3AF" }}>
              {localStr(thread.last_message_excerpt)}
            </p>
          )}

          <div className="flex items-center gap-1.5 flex-wrap">
            <ProviderBadge provider={thread.default_message_provider} size="sm" />
            {thread.requires_attention && (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[9px] font-semibold bg-amber-50 text-amber-700">
                <AlertTriangle size={8} /> Attention
              </span>
            )}
            {thread.messages_count > 0 && (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[9px] font-medium bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-subtle)]">
                <MessageSquare size={8} /> {thread.messages_count}
              </span>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

// ─── Message bubble ────────────────────────────────────────────────────────────

function RWMessageBubble({ msg }: { msg: RWMessage }) {
  const isOutbound = msg.direction === "outbound";
  // Guard: content must be a string for safe rendering
  if (!msg || typeof msg !== "object") return null;
  const time = new Date(msg.sent_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

  // Strip basic HTML tags for display when content_type is text/html
  const rawContent = localStr(msg.content);
  const displayContent = msg.content_type === "text/html"
    ? rawContent.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&nbsp;/g, " ").trim()
    : rawContent;

  return (
    <div className={cn("flex gap-2 mb-3", isOutbound ? "justify-end" : "justify-start")}>
      {!isOutbound && (
        <div
          className="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold text-white flex-shrink-0 mt-1"
          style={{ background: PROVIDER_COLORS[msg.provider] ?? "#6B7280" }}
        >
          G
        </div>
      )}

      <div className={cn("max-w-[72%] space-y-1", isOutbound && "items-end flex flex-col")}>
        {/* Sender */}
        {(msg.sent_by_name || msg.sent_by_workflow?.name) && (
          <p className="text-[10px] font-medium px-1" style={{ color: "#9CA3AF" }}>
            {msg.sent_by_workflow?.name
              ? `🤖 ${localStr(msg.sent_by_workflow.name)}`
              : localStr(msg.sent_by_name)}
          </p>
        )}

        {/* Bubble */}
        <div
          className={cn(
            "rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed",
            isOutbound
              ? "bg-[#0F766E] text-white rounded-br-sm"
              : "bg-white border border-[var(--haip-border)] shadow-sm text-[var(--haip-fg)] rounded-bl-sm"
          )}
        >
          <p className="whitespace-pre-wrap break-words">{displayContent}</p>

          {/* Translation */}
          {msg.translated_content && localStr(msg.translated_content) !== displayContent && (
            <div
              className={cn(
                "mt-2 pt-2 text-[11px] italic border-t",
                isOutbound ? "border-white/20 text-white/70" : "border-[var(--haip-border)] text-[var(--haip-fg-subtle)]"
              )}
            >
              <span className="font-medium not-italic">Translated: </span>
              {localStr(msg.translated_content)}
            </div>
          )}

          {/* Error */}
          {msg.error_message && typeof msg.error_message === "string" && (
            <p className="mt-1 text-[10px] text-red-300 flex items-center gap-1">
              <AlertTriangle size={9} /> {msg.error_message}
            </p>
          )}
        </div>

        {/* Footer row */}
        <div className={cn("flex items-center gap-1.5 px-1", isOutbound ? "justify-end" : "justify-start")}>
          <ProviderBadge provider={msg.provider} size="sm" />
          <span className="text-[10px]" style={{ color: "#9CA3AF" }}>{time}</span>
          {isOutbound && msg.is_sent && <CheckCircle2 size={10} className="text-primary" />}
          {isOutbound && !msg.is_sent && !msg.error_message && <Loader2 size={10} className="text-[var(--haip-fg-subtle)]/70 animate-spin" />}
        </div>
      </div>

      {isOutbound && (
        <div
          className="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold text-white flex-shrink-0 mt-1"
          style={{ background: "#0F766E" }}
        >
          T
        </div>
      )}
    </div>
  );
}

// ─── Thread panel (messages + reply) ──────────────────────────────────────────

function ThreadPanel({ thread, onBack }: { thread: RWThread; onBack: () => void }) {
  const { data, isLoading, isError, refetch } = useRWThreadMessages(thread.id);
  const messages: RWMessage[] = data?.data ?? [];
  const bottomRef = useRef<HTMLDivElement>(null);

  // Reply state
  const [replyText, setReplyText]         = useState("");
  const [selectedProvider, setSelectedProvider] = useState<RWProvider>(thread.default_message_provider);
  const sendMutation = useSendRWMessage(thread.id);

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  // Sync provider when thread changes
  useEffect(() => {
    setSelectedProvider(thread.default_message_provider);
  }, [thread.id, thread.default_message_provider]);

  const { first_name, last_name, email } = thread.account ?? {};
  const guestName = [localStr(first_name), localStr(last_name)].filter(Boolean).join(" ") || localStr(email) || "Unknown";

  const providers = thread.available_message_providers?.length
    ? thread.available_message_providers
    : [{ id: thread.default_message_provider, name: PROVIDER_LABELS[thread.default_message_provider] ?? thread.default_message_provider, icon_url: "" }];

  async function handleSend() {
    const text = replyText.trim();
    if (!text || sendMutation.isPending) return;
    try {
      await sendMutation.mutateAsync({
        thread:   thread.thread_identifier,
        provider: selectedProvider,
        content:  text,
      });
      setReplyText("");
    } catch {
      // error shown via sendMutation.error
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 py-3.5 flex-shrink-0"
        style={{ background: "#FFFFFF", borderBottom: "1px solid #E5E7EB" }}
      >
        <button
          onClick={onBack}
          className="md:hidden flex items-center justify-center w-8 h-8 rounded-lg hover:bg-[var(--haip-status-neutral-bg)] transition-colors"
          style={{ color: "#6B7280" }}
        >
          <ChevronLeft size={18} />
        </button>

        <div
          className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
          style={{ background: "linear-gradient(135deg, #14B8A6, #0F766E)" }}
        >
          {guestName.slice(0, 2).toUpperCase()}
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-[14px] font-semibold truncate" style={{ color: "#111827" }}>
            {guestName}
          </p>
          <div className="flex items-center gap-2 mt-0.5">
            {thread.subject && (
              <p className="text-[11px] truncate" style={{ color: "#6B7280" }}>{localStr(thread.subject)}</p>
            )}
            <ProviderBadge provider={thread.default_message_provider} size="sm" />
          </div>
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          {thread.requires_attention && (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
              <AlertTriangle size={10} /> Needs attention
            </span>
          )}
          <button
            onClick={() => refetch()}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-[var(--haip-status-neutral-bg)] transition-colors"
            style={{ color: "#9CA3AF" }}
            title="Refresh"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 haip-scrollbar" style={{ background: "#F8FAFC" }}>
        {isLoading ? (
          <div className="space-y-4">
            {[1, 2, 3].map(i => (
              <div key={i} className={cn("flex gap-2", i % 2 === 0 && "justify-end")}>
                <Skeleton className="w-6 h-6 rounded-full flex-shrink-0" />
                <Skeleton className="h-16 w-64 rounded-2xl" />
              </div>
            ))}
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <AlertCircle size={28} className="text-red-400" />
            <p className="text-sm text-[var(--haip-fg-subtle)]">Failed to load messages</p>
            <button
              onClick={() => refetch()}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-[#0F766E] text-white hover:bg-[#0d6660] transition-colors"
            >
              Retry
            </button>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-2">
            <MessageSquare size={28} className="text-[var(--haip-fg-subtle)]/70" />
            <p className="text-sm text-[var(--haip-fg-subtle)]">No messages in this thread</p>
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <RWMessageBubble key={msg.id} msg={msg} />
            ))}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Reply composer */}
      <div
        className="flex-shrink-0 px-4 pt-3 pb-3"
        style={{ borderTop: "1px solid #E5E7EB", background: "#FFFFFF" }}
      >
        {/* Provider selector (only show if multiple providers available) */}
        {providers.length > 1 && (
          <div className="flex gap-1 mb-2">
            {providers.map(p => (
              <button
                key={p.id}
                onClick={() => setSelectedProvider(p.id)}
                className={cn(
                  "px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-colors border",
                  selectedProvider === p.id
                    ? "border-[#0F766E] bg-[#0F766E]/5 text-[#0F766E]"
                    : "border-[var(--haip-border)] text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)]"
                )}
              >
                {PROVIDER_LABELS[p.id] ?? p.id}
              </button>
            ))}
          </div>
        )}

        {/* Text area + send button */}
        <div className="flex gap-2 items-end">
          <div className="flex-1 relative">
            <textarea
              value={replyText}
              onChange={e => setReplyText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Reply via ${PROVIDER_LABELS[selectedProvider] ?? selectedProvider}…`}
              rows={2}
              className="w-full px-3 py-2.5 rounded-xl text-[13px] resize-none focus:outline-none focus:ring-2 focus:ring-[#0F766E]/20"
              style={{
                background: "#F8FAFC",
                border: "1px solid #E5E7EB",
                color: "#111827",
                maxHeight: 120,
              }}
              onFocus={e => { (e.currentTarget as HTMLElement).style.borderColor = "#0F766E"; }}
              onBlur={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E5E7EB"; }}
            />
            <span className="absolute right-2 bottom-2 text-[10px]" style={{ color: "#D1D5DB" }}>
              ⌘↵
            </span>
          </div>
          <button
            onClick={handleSend}
            disabled={!replyText.trim() || sendMutation.isPending}
            className={cn(
              "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-all",
              "disabled:opacity-40"
            )}
            style={{ background: "#0F766E", color: "#fff" }}
            onMouseEnter={e => { if (!replyText.trim()) return; (e.currentTarget as HTMLElement).style.background = "#0d6660"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "#0F766E"; }}
            title="Send (⌘+Enter)"
          >
            {sendMutation.isPending
              ? <Loader2 size={16} className="animate-spin" />
              : <Send size={16} />
            }
          </button>
        </div>

        {/* Send error */}
        {sendMutation.isError && (
          <p className="mt-1.5 text-[11px] text-red-500 flex items-center gap-1">
            <AlertTriangle size={10} />
            {String((sendMutation.error as any)?.message ?? "Failed to send — check your RentalWise connection")}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Guest context panel ──────────────────────────────────────────────────────

function GuestContextPanel({ thread }: { thread: RWThread }) {
  const { first_name, last_name, email, phone, company } = thread.account ?? {};
  const guestName = [localStr(first_name), localStr(last_name)].filter(Boolean).join(" ") || "Unknown";
  const initials  = guestName.split(" ").map((n: string) => n[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div
      className="hidden lg:flex flex-col w-60 flex-shrink-0 overflow-y-auto haip-scrollbar"
      style={{ borderLeft: "1px solid #E5E7EB", background: "#FFFFFF" }}
    >
      {/* Header */}
      <div className="px-4 py-4 flex-shrink-0" style={{ borderBottom: "1px solid #E5E7EB" }}>
        <p className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: "#9CA3AF" }}>
          Guest Info
        </p>
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold text-white flex-shrink-0"
            style={{ background: "linear-gradient(135deg, #14B8A6, #0F766E)" }}
          >
            {initials}
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-bold truncate" style={{ color: "#111827", fontFamily: "var(--font-display), sans-serif" }}>
              {guestName}
            </p>
            <ProviderBadge provider={thread.default_message_provider} size="sm" />
          </div>
        </div>
      </div>

      {/* Details */}
      <div className="flex-1 px-4 py-4 space-y-3.5">
        {email && (
          <div className="flex items-start gap-2.5">
            <AtSign size={13} className="flex-shrink-0 mt-0.5" style={{ color: "#9CA3AF" }} />
            <div className="min-w-0">
              <p className="text-[9.5px] font-semibold uppercase tracking-wide mb-0.5" style={{ color: "#9CA3AF" }}>Email</p>
              <p className="text-[11.5px] font-medium truncate" style={{ color: "#374151" }}>{localStr(email)}</p>
            </div>
          </div>
        )}
        {phone && (
          <div className="flex items-start gap-2.5">
            <Phone size={13} className="flex-shrink-0 mt-0.5" style={{ color: "#9CA3AF" }} />
            <div className="min-w-0">
              <p className="text-[9.5px] font-semibold uppercase tracking-wide mb-0.5" style={{ color: "#9CA3AF" }}>Phone</p>
              <p className="text-[11.5px] font-medium" style={{ color: "#374151" }}>{localStr(phone)}</p>
            </div>
          </div>
        )}
        {company && (
          <div className="flex items-start gap-2.5">
            <Globe size={13} className="flex-shrink-0 mt-0.5" style={{ color: "#9CA3AF" }} />
            <div className="min-w-0">
              <p className="text-[9.5px] font-semibold uppercase tracking-wide mb-0.5" style={{ color: "#9CA3AF" }}>Company</p>
              <p className="text-[11.5px] font-medium truncate" style={{ color: "#374151" }}>{localStr(company)}</p>
            </div>
          </div>
        )}
        <div className="flex items-start gap-2.5">
          <Hash size={13} className="flex-shrink-0 mt-0.5" style={{ color: "#9CA3AF" }} />
          <div className="min-w-0">
            <p className="text-[9.5px] font-semibold uppercase tracking-wide mb-0.5" style={{ color: "#9CA3AF" }}>Thread ID</p>
            <p className="text-[11px] font-mono truncate" style={{ color: "#374151" }}>{thread.thread_identifier}</p>
          </div>
        </div>
        {thread.thread_external_id && (
          <div className="flex items-start gap-2.5">
            <Hash size={13} className="flex-shrink-0 mt-0.5" style={{ color: "#9CA3AF" }} />
            <div className="min-w-0">
              <p className="text-[9.5px] font-semibold uppercase tracking-wide mb-0.5" style={{ color: "#9CA3AF" }}>External ID</p>
              <p className="text-[11px] font-mono truncate" style={{ color: "#374151" }}>{thread.thread_external_id}</p>
            </div>
          </div>
        )}
        <div className="flex items-start gap-2.5">
          <MessageSquare size={13} className="flex-shrink-0 mt-0.5" style={{ color: "#9CA3AF" }} />
          <div className="min-w-0">
            <p className="text-[9.5px] font-semibold uppercase tracking-wide mb-0.5" style={{ color: "#9CA3AF" }}>Messages</p>
            <p className="text-[11.5px] font-semibold" style={{ color: "#374151" }}>{thread.messages_count}</p>
          </div>
        </div>
        {thread.last_message_at && (
          <div className="flex items-start gap-2.5">
            <Clock size={13} className="flex-shrink-0 mt-0.5" style={{ color: "#9CA3AF" }} />
            <div className="min-w-0">
              <p className="text-[9.5px] font-semibold uppercase tracking-wide mb-0.5" style={{ color: "#9CA3AF" }}>Last message</p>
              <p className="text-[11px]" style={{ color: "#374151" }}>
                {new Date(thread.last_message_at).toLocaleDateString("en-IN", {
                  day: "numeric", month: "short", year: "numeric",
                })}
              </p>
            </div>
          </div>
        )}

        {/* Available providers */}
        {(thread.available_message_providers?.length ?? 0) > 1 && (
          <div>
            <p className="text-[9.5px] font-semibold uppercase tracking-wide mb-1.5" style={{ color: "#9CA3AF" }}>Channels</p>
            <div className="flex flex-wrap gap-1">
              {thread.available_message_providers.map(p => (
                <ProviderBadge key={p.id} provider={p.id} size="sm" />
              ))}
            </div>
          </div>
        )}

        {thread.requires_attention && (
          <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl border border-amber-200 bg-amber-50">
            <AlertTriangle size={13} className="text-amber-600 flex-shrink-0" />
            <p className="text-[11px] font-semibold text-amber-700">Needs attention</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Channel filter row ────────────────────────────────────────────────────────

function FilterRow({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto scrollbar-hide px-4 py-2.5 border-b" style={{ borderColor: "#E5E7EB" }}>
      {THREAD_FILTERS.map(f => (
        <button
          key={f.value}
          onClick={() => onChange(f.value)}
          className={cn(
            "flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors",
            value === f.value ? "bg-[#0F766E] text-white" : "text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-status-neutral-bg)]"
          )}
        >
          {f.value === "airbnb"      && <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: "#FF5A5F" }} />}
          {f.value === "booking-com" && <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: "#003580" }} />}
          {f.value === "homeaway"    && <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: "#1D5AA1" }} />}
          {f.value === "email"       && <Mail size={11} />}
          {f.value === "attention"   && <AlertTriangle size={11} />}
          {f.label}
        </button>
      ))}
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function ChannelManagerPage() {
  const queryClient                        = useQueryClient();
  const [activeFilter, setActiveFilter]   = useState("all");
  const [search, setSearch]               = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [activeThreadId, setActiveThreadId]   = useState<number | null>(null);
  const [mobileView, setMobileView]       = useState<"list" | "thread">("list");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(t);
  }, [search]);

  const filterConfig = THREAD_FILTERS.find(f => f.value === activeFilter);
  const queryFilters: Parameters<typeof useRWThreads>[0] = {
    search:             debouncedSearch || undefined,
    provider:           filterConfig?.provider,
    requires_attention: filterConfig?.attention,
    per_page:           40,
  };

  const { data, isLoading, isError, refetch, isFetching } = useRWThreads(queryFilters);
  const threads: RWThread[] = data?.data ?? [];
  const activeThread = threads.find(t => t.id === activeThreadId) ?? null;

  function handleSelectThread(thread: RWThread) {
    setActiveThreadId(thread.id);
    setMobileView("thread");
  }

  function handleBack() {
    setMobileView("list");
    setActiveThreadId(null);
  }

  return (
    <div className="h-full flex flex-col" style={{ background: "#F8FAFC" }}>

      {/* Page header */}
      <div
        className="flex-shrink-0 px-6 py-4"
        style={{ background: "#FFFFFF", borderBottom: "1px solid #E5E7EB" }}
      >
        <div className="flex items-center justify-between">
          <div>
            <h1
              className="haip-page-title haip-page-title--keep leading-tight"
            >
              Channel Manager
            </h1>
            <p className="text-[12px] mt-0.5" style={{ color: "#6B7280" }}>
              Guest conversations from Airbnb, Booking.com, HomeAway &amp; Email
            </p>
          </div>
          <button
            onClick={() => { queryClient.invalidateQueries({ queryKey: ["rw-threads"] }); }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-[12px] font-semibold transition-colors border border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]"
          >
            <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Three-panel layout */}
      <div className="flex flex-1 overflow-hidden">

        {/* LEFT: Thread list */}
        <div
          className={cn(
            "flex flex-col border-r flex-shrink-0",
            "w-full md:w-72 lg:w-80",
            mobileView === "thread" && "hidden md:flex"
          )}
          style={{ borderColor: "#E5E7EB", background: "#FFFFFF" }}
        >
          {/* Search */}
          <div className="px-4 py-3 border-b" style={{ borderColor: "#E5E7EB" }}>
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "#9CA3AF" }} />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search guests, email…"
                className="w-full pl-8 pr-8 py-2 rounded-xl text-[12.5px] focus:outline-none"
                style={{ background: "#F8FAFC", border: "1px solid #E5E7EB", color: "#374151" }}
                onFocus={e => { (e.currentTarget as HTMLElement).style.borderColor = "#0F766E"; }}
                onBlur={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E5E7EB"; }}
              />
              {search && (
                <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2" style={{ color: "#9CA3AF" }}>
                  <X size={12} />
                </button>
              )}
            </div>
          </div>

          {/* Filter tabs */}
          <FilterRow value={activeFilter} onChange={setActiveFilter} />

          {/* Thread list */}
          <div className="flex-1 overflow-y-auto haip-scrollbar">
            {isLoading ? (
              <div>
                {[1, 2, 3, 4, 5].map(i => (
                  <div key={i} className="px-4 py-3 border-b border-[var(--haip-border)]">
                    <div className="flex items-start gap-3">
                      <Skeleton className="w-9 h-9 rounded-full flex-shrink-0" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-3 w-3/4 rounded" />
                        <Skeleton className="h-2.5 w-full rounded" />
                        <Skeleton className="h-2.5 w-1/2 rounded" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : isError ? (
              <div className="flex flex-col items-center justify-center py-16 px-4 gap-3">
                <AlertCircle size={28} className="text-red-400" />
                <p className="text-sm text-[var(--haip-fg-subtle)] text-center">Failed to load conversations</p>
                <button
                  onClick={() => refetch()}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-[#0F766E] text-white hover:bg-[#0d6660] transition-colors"
                >
                  Retry
                </button>
              </div>
            ) : threads.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 px-4 gap-2">
                <Inbox size={28} className="text-[var(--haip-fg-subtle)]/70" />
                <p className="text-sm font-medium text-[var(--haip-fg-subtle)]">No conversations found</p>
                {debouncedSearch && <p className="text-xs text-[var(--haip-fg-subtle)]">Try a different search term</p>}
              </div>
            ) : (
              threads.map(t => (
                <ThreadRow
                  key={t.id}
                  thread={t}
                  active={t.id === activeThreadId}
                  onClick={() => handleSelectThread(t)}
                />
              ))
            )}
          </div>

          {/* Total count */}
          {!isLoading && !isError && threads.length > 0 && (
            <div className="px-4 py-2 text-center flex-shrink-0" style={{ borderTop: "1px solid #E5E7EB" }}>
              <p className="text-[10px]" style={{ color: "#9CA3AF" }}>
                {data?.meta?.total
                  ? `${data.meta.total} total · showing ${threads.length}`
                  : `${threads.length} conversations`}
              </p>
            </div>
          )}
        </div>

        {/* CENTER + RIGHT: Thread detail */}
        <div
          className={cn(
            "flex flex-1 min-w-0 overflow-hidden",
            mobileView === "list" && "hidden md:flex"
          )}
        >
          {activeThread ? (
            <>
              <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
                <ThreadPanel thread={activeThread} onBack={handleBack} />
              </div>
              <GuestContextPanel thread={activeThread} />
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center gap-3" style={{ background: "#F8FAFC" }}>
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center"
                style={{ background: "rgba(15,118,110,0.08)" }}
              >
                <MessageSquare size={24} style={{ color: "#0F766E" }} />
              </div>
              <p className="text-[15px] font-semibold" style={{ color: "#374151" }}>Select a conversation</p>
              <p className="text-[13px]" style={{ color: "#9CA3AF" }}>Choose a thread from the left to view messages</p>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
