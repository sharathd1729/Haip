"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { openOAuth } from "@/components/marketing/studio/types";
import { MessageSquare, Phone, AtSign, CheckCircle2, AlertCircle, Loader2, RefreshCw, ExternalLink, Key, X, Check, Clock, Wifi, WifiOff, Zap, Shield, Copy, Info, ChevronDown, ChevronUp, Pencil } from "@/lib/icons";
import { Plug, Unplug } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CatalogItem {
  provider: string;
  name: string;
  description: string;
  category: string;
  auth_type: string;
  logo: string;
  popular: boolean;
  notes?: string;
}

interface Integration {
  id: string;
  tenant_id: string;
  kind: string;   // matches IntegrationKind on backend (e.g. "whatsapp", "callerdesk")
  status: "active" | "disconnected" | "error" | "pending";
  config: Record<string, string>;   // merged metadata + provider info from backend
  installed_at: string | null;
  last_health_at: string | null;
}

interface WebhookInfo {
  webhook_url: string;
  // The verify token is never part of this response: it stays hidden until an owner asks to see it.
  verify_token_set: boolean;
  verify_token_hint: string | null;
  legacy_token_active: boolean;
  can_reveal: boolean;
  instructions: string[];
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function ProviderIcon({
  logo,
  size = 22,
  className = "",
}: {
  logo: string;
  size?: number;
  className?: string;
}) {
  if (logo === "whatsapp") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={cn("text-green-500", className)}>
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z" />
      </svg>
    );
  }
  if (logo === "instagram") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={cn("text-pink-500", className)}>
        <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
      </svg>
    );
  }
  if (logo === "phone") return <Phone size={size} className={cn("text-blue-500", className)} />;
  if (logo === "ivr") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className={cn("text-primary", className)}>
        <path d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18" />
      </svg>
    );
  }
  if (logo === "hotel") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className={cn("text-indigo-500", className)}>
        <path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-4h6v4M9 9h1m5 0h1M9 13h1m5 0h1" />
      </svg>
    );
  }
  return <Plug size={size} className={cn("text-[var(--haip-fg-subtle)]", className)} />;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: Integration["status"] }) {
  const cfg = {
    active:       { label: "Connected",     icon: <Wifi size={10} />,        cls: "bg-green-50 text-green-700 border-green-200" },
    error:        { label: "Error",          icon: <AlertCircle size={10} />, cls: "bg-red-50 text-red-700 border-red-200" },
    pending:      { label: "Pending",        icon: <Clock size={10} />,       cls: "bg-amber-50 text-amber-700 border-amber-200" },
    disconnected: { label: "Not connected",  icon: <WifiOff size={10} />,     cls: "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)] border-[var(--haip-border)]" },
  }[status] ?? { label: status, icon: null, cls: "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)] border-[var(--haip-border)]" };

  return (
    <span className={cn("inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border", cfg.cls)}>
      {cfg.icon} {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Token expiry badge
// ---------------------------------------------------------------------------

function TokenExpiryBadge({ expiry }: { expiry?: string | null }) {
  // `token_expires_at` is saved by the daily Meta token check; absent means the token never expires or has not
  // been checked yet.
  if (!expiry) return null;
  const exp = new Date(expiry);
  if (Number.isNaN(exp.getTime())) return null;
  const daysLeft = Math.ceil((exp.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  if (daysLeft > 14) return null;
  const expired = daysLeft <= 0;
  return (
    <span
      title={`Access token ends ${exp.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}`}
      className={cn(
        "inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border",
        expired || daysLeft <= 3
          ? "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]"
          : "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)]",
      )}
    >
      <Clock size={10} />
      {expired ? "Token expired" : `Token expires in ${daysLeft}d`}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Copy field helper
// ---------------------------------------------------------------------------

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <p className="text-[10px] text-[var(--haip-fg-subtle)] mb-1 font-semibold uppercase tracking-wide">{label}</p>
      <div className="flex items-center gap-2 bg-[var(--haip-surface)] border border-[var(--haip-border)] rounded-lg px-2.5 py-1.5">
        <code className="text-[11px] text-[var(--haip-fg-2)] flex-1 break-all font-mono">{value}</code>
        <button
          onClick={() => { navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
          className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)] flex-shrink-0 transition-colors"
          title="Copy"
        >
          {copied ? <CheckCircle2 size={13} className="text-green-500" /> : <Copy size={13} />}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Webhook Info Panel (shown after WhatsApp / Instagram is connected)
// ---------------------------------------------------------------------------

/** The webhook verify token: hidden by default. Only an owner can show it or replace it, and both are logged. */
function VerifyTokenRow({ provider, info }: { provider: string; info: WebhookInfo }) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const show = useMutation({
    mutationFn: (action: "reveal" | "rotate") => api.post(`/integrations/${provider}/verify-token/${action}`).then(r => r.data as { verify_token: string }),
    onSuccess: res => {
      setToken(res.verify_token);
      queryClient.invalidateQueries({ queryKey: ["webhook-info", provider] });
      setTimeout(() => setToken(null), 60_000);     // hide again after a minute
    },
  });
  const failed = show.isError ? ((show.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not load the token.") : null;

  return (
    <div>
      <p className="text-[10px] text-[var(--haip-fg-subtle)] mb-1 font-semibold uppercase tracking-wide">Verify Token</p>
      <div className="flex items-center gap-2 bg-[var(--haip-surface)] border border-[var(--haip-border)] rounded-lg px-2.5 py-1.5">
        <code className="text-[11px] text-[var(--haip-fg-2)] flex-1 break-all font-mono">
          {token ?? (info.verify_token_set ? `••••••••••••${info.verify_token_hint ?? ""}` : "Not created yet")}
        </code>
        {token && (
          <button
            onClick={() => { navigator.clipboard.writeText(token); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
            className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)] flex-shrink-0 transition-colors" title="Copy"
          >
            {copied ? <CheckCircle2 size={13} className="text-green-500" /> : <Copy size={13} />}
          </button>
        )}
      </div>
      {info.can_reveal ? (
        <div className="flex flex-wrap items-center gap-3 mt-1.5">
          <button onClick={() => (token ? setToken(null) : show.mutate("reveal"))} disabled={show.isPending}
            className="text-[11px] font-semibold text-primary hover:underline disabled:opacity-50">
            {token ? "Hide" : info.verify_token_set ? "Show token" : "Create token"}
          </button>
          {info.verify_token_set && (
            <button
              onClick={() => { if (confirm("Create a new verify token? The current one stops working. Paste the new one into Meta the next time you save the webhook there.")) show.mutate("rotate"); }}
              disabled={show.isPending} className="text-[11px] font-semibold text-[var(--haip-fg-subtle)] hover:underline disabled:opacity-50">
              Generate new token
            </button>
          )}
        </div>
      ) : (
        <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Only the account owner can view or replace the verify token.</p>
      )}
      {failed && <p className="text-[10px] text-red-600 mt-1">{failed}</p>}
      {info.can_reveal && info.legacy_token_active && (
        <p className="text-[10px] text-amber-700 mt-1">An older shared token is still accepted. Once the new token is saved in Meta, ask your administrator to switch the old one off.</p>
      )}
    </div>
  );
}

function WebhookInfoPanel({ provider }: { provider: string }) {
  const [open, setOpen] = useState(true);
  const { data, isLoading } = useQuery<WebhookInfo>({
    queryKey: ["webhook-info", provider],
    queryFn: () => api.get(`/integrations/${provider}/webhook-info`).then(r => r.data),
    staleTime: Infinity,
  });

  const providerLabel = provider === "whatsapp_meta" ? "WhatsApp" : "Instagram";

  return (
    <div className="border-t border-[var(--haip-border)] pt-3 mt-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center justify-between w-full text-left"
      >
        <p className="text-[10px] text-primary font-semibold uppercase tracking-wide flex items-center gap-1">
          <Info size={10} />
          Configure {providerLabel} Webhook
        </p>
        {open ? <ChevronUp size={12} className="text-[var(--haip-fg-subtle)]" /> : <ChevronDown size={12} className="text-[var(--haip-fg-subtle)]" />}
      </button>

      {open && (
        <div className="mt-2 space-y-3">
          {isLoading ? (
            <div className="h-12 bg-[var(--haip-surface)] rounded-lg animate-pulse" />
          ) : data ? (
            <>
              <CopyField label="Webhook URL" value={data.webhook_url} />
              <VerifyTokenRow provider={provider} info={data} />
              {data.instructions?.length > 0 && (
                <div className="bg-blue-50 border border-blue-100 rounded-xl p-3">
                  <p className="text-[10px] font-semibold text-blue-700 mb-1.5">Setup steps</p>
                  <ol className="space-y-1">
                    {data.instructions.map((step, i) => (
                      <li key={i} className="text-[10px] text-blue-700 flex gap-1.5">
                        <span className="font-bold flex-shrink-0">{i + 1}.</span>
                        <span>{step}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </>
          ) : (
            <p className="text-[10px] text-[var(--haip-fg-subtle)]">Could not load webhook info.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connect Modal — api_key / basic_auth / hostaway / whatsapp_meta / instagram
// ---------------------------------------------------------------------------

function ConnectModal({
  provider,
  providerName,
  authType,
  notes,
  onConnect,
  onClose,
}: {
  provider: string;
  providerName: string;
  authType?: string;
  notes?: string;
  onConnect: (fields: Record<string, string>) => void;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const set = (k: string, v: string) => setFields(prev => ({ ...prev, [k]: v }));

  const isWhatsApp    = provider === "whatsapp_meta";
  const isInstagram   = provider === "instagram";
  const isRentalWise  = provider === "retalwise";
  const isBasicAuth   = authType === "basic_auth" && !isWhatsApp && !isInstagram && !isRentalWise;
  const isHostaway    = provider === "hostaway";
  const isVobiz       = provider === "vobiz";
  const isIvr         = provider === "callerdesk" || provider === "acefone" || provider === "mcube";

  // RentalWise: user can choose between API token (Bearer) or username/password (Basic)
  const [rwAuthMode, setRwAuthMode] = useState<"token" | "basic">("token");

  const canSubmit = (() => {
    if (isWhatsApp)    return !!(fields.phone_number_id?.trim() && fields.waba_id?.trim() && fields.access_token?.trim());
    if (isInstagram)   return !!fields.app_secret?.trim();
    if (isRentalWise)  return rwAuthMode === "token" ? !!fields.api_token?.trim() : !!(fields.username?.trim() && fields.password?.trim());
    if (isBasicAuth)   return !!(fields.username?.trim() && fields.password?.trim());
    if (isVobiz)       return !!(fields.api_key?.trim() && fields.api_secret?.trim() && fields.forward_number?.trim() && fields.webhook_secret?.trim());
    if (isIvr)         return !!(fields.api_key?.trim() && fields.webhook_secret?.trim());
    if (isHostaway)    return !!(fields.account_id?.trim() && fields.api_secret?.trim());
    return !!fields.api_key?.trim();
  })();

  const handleSubmit = async () => {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try { await onConnect(fields); } finally { setSubmitting(false); }
  };

  const inputCls = "w-full pl-9 pr-4 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/30 bg-white";

  const subtitle = (() => {
    if (isWhatsApp)   return "Paste your WhatsApp Cloud API credentials from Meta Business Suite";
    if (isInstagram)  return "Save your App Secret, then use \"Connect via Instagram Login\" to finish connecting";
    if (isRentalWise) return "Paste your RentalWise API token (provided by your Engagement Manager)";
    if (isBasicAuth)  return `Enter your ${providerName} username and password`;
    if (isVobiz)      return "Enter your Vobiz account credentials — this is your client's own Vobiz account, not a shared HAIP one";
    if (isHostaway)   return "Enter your Hostaway Account ID and API Secret";
    return `Enter your API key from the ${providerName} dashboard`;
  })();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden max-h-[90vh] flex flex-col" style={{ maxHeight: "calc(100dvh - 2rem)" }}>
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-[var(--haip-border)] flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-base font-bold text-[var(--haip-fg)]">Connect {providerName}</h2>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">{subtitle}</p>
          </div>
          <button onClick={onClose} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)] transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4 overflow-y-auto flex-1">
          {isWhatsApp ? (
            <>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  Phone Number ID <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input autoFocus type="text" value={fields.phone_number_id ?? ""} onChange={e => set("phone_number_id", e.target.value)} placeholder="e.g. 123456789012345" className={inputCls} />
                </div>
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Found in Meta Business Suite → WhatsApp → Getting Started.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  WhatsApp Business Account ID (WABA ID) <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="text" value={fields.waba_id ?? ""} onChange={e => set("waba_id", e.target.value)} placeholder="e.g. 987654321098765" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  Access Token <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="password" value={fields.access_token ?? ""} onChange={e => set("access_token", e.target.value)} placeholder="Permanent or temporary user token" className={inputCls} />
                </div>
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Use a permanent System User token for production (never expires).</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  App Secret <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="password" value={fields.app_secret ?? ""} onChange={e => set("app_secret", e.target.value)} placeholder="Meta App Secret (Settings → Basic)" className={inputCls} />
                </div>
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Needed to receive replies and delivery updates. Without it messages send, but they stay at “sent” and guests' replies never appear. Leave blank to keep the one already saved.</p>
              </div>
            </>
          ) : isInstagram ? (
            <>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  App Secret <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input autoFocus type="password" value={fields.app_secret ?? ""} onChange={e => set("app_secret", e.target.value)} placeholder="Meta App Secret" className={inputCls} />
                </div>
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Required for webhook signature verification and to bootstrap the Instagram Login connection.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  Instagram Business Account ID <span className="text-[var(--haip-fg-subtle)] font-normal">(optional)</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="text" value={fields.instagram_business_account_id ?? ""} onChange={e => set("instagram_business_account_id", e.target.value)} placeholder="e.g. 17841234567890123" className={inputCls} />
                </div>
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Found in Meta Business Suite → Instagram → Account settings.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  Access Token <span className="text-[var(--haip-fg-subtle)] font-normal">(not needed — use Instagram Login instead)</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="password" value={fields.access_token ?? ""} onChange={e => set("access_token", e.target.value)} placeholder="Leave blank — use Connect via Instagram Login after saving" className={inputCls} />
                </div>
              </div>
            </>
          ) : isRentalWise ? (
            <>
              {/* Auth mode toggle */}
              <div className="flex gap-1 p-1 bg-[var(--haip-status-neutral-bg)] rounded-xl">
                <button
                  type="button"
                  onClick={() => setRwAuthMode("token")}
                  className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors ${rwAuthMode === "token" ? "bg-white text-[var(--haip-fg)] shadow-sm" : "text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-2)]"}`}
                >
                  API Token
                </button>
                <button
                  type="button"
                  onClick={() => setRwAuthMode("basic")}
                  className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors ${rwAuthMode === "basic" ? "bg-white text-[var(--haip-fg)] shadow-sm" : "text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-2)]"}`}
                >
                  Username / Password
                </button>
              </div>

              {rwAuthMode === "token" ? (
                <div>
                  <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                    API Token <span className="text-red-500">*</span>
                  </label>
                  <div className="relative">
                    <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                    <input
                      autoFocus
                      type="password"
                      value={fields.api_token ?? ""}
                      onChange={e => set("api_token", e.target.value)}
                      placeholder="e.g. 14079|rw_production_..."
                      className={inputCls}
                    />
                  </div>
                  <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Provided by your RentalWise Engagement Manager during onboarding.</p>
                </div>
              ) : (
                <>
                  <div>
                    <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Username <span className="text-red-500">*</span></label>
                    <div className="relative">
                      <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                      <input autoFocus type="text" value={fields.username ?? ""} onChange={e => set("username", e.target.value)} placeholder="Your RentalWise username" className={inputCls} />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Password <span className="text-red-500">*</span></label>
                    <div className="relative">
                      <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                      <input type="password" value={fields.password ?? ""} onChange={e => set("password", e.target.value)} placeholder="Your RentalWise password" className={inputCls} />
                    </div>
                  </div>
                </>
              )}

              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">API Base URL <span className="text-[var(--haip-fg-subtle)] font-normal">(optional)</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="text" value={fields.base_url ?? ""} onChange={e => set("base_url", e.target.value)} placeholder="https://app.rentalwise.io" className={inputCls} />
                </div>
                <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-1">Leave blank to use the default production URL.</p>
              </div>
            </>
          ) : isBasicAuth ? (
            <>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Username <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input autoFocus type="text" value={fields.username ?? ""} onChange={e => set("username", e.target.value)} placeholder="Username" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Password <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="password" value={fields.password ?? ""} onChange={e => set("password", e.target.value)} placeholder="Password" className={inputCls} />
                </div>
              </div>
            </>
          ) : isVobiz ? (
            <>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Auth ID <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input autoFocus type="text" value={fields.api_key ?? ""} onChange={e => set("api_key", e.target.value)} placeholder="e.g. MA_K8PLCAKA" className={inputCls} />
                </div>
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">From the Vobiz Console → Basic Information → Auth ID.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Auth Secret <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="password" value={fields.api_secret ?? ""} onChange={e => set("api_secret", e.target.value)} placeholder="From Vobiz Console → Basic Information → Auth Secret" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Agent Forwarding Number <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="text" value={fields.forward_number ?? ""} onChange={e => set("forward_number", e.target.value)} placeholder="+9198XXXXXXXX" className={inputCls} />
                </div>
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Every inbound call rings this mobile number while the whole session records. E.164 format.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Vobiz Phone Number (DID)</label>
                <div className="relative">
                  <Phone size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="text" value={fields.did_number ?? ""} onChange={e => set("did_number", e.target.value)} placeholder="+9122XXXXXXXX" className={inputCls} />
                </div>
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">
                  Optional for inbound — required for agents to click-to-call guests. From the Vobiz Console → Numbers.
                </p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  Webhook Secret <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Shield size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input
                    type="password"
                    value={fields.webhook_secret ?? ""}
                    onChange={e => set("webhook_secret", e.target.value)}
                    placeholder="Any random string you generate"
                    className={inputCls}
                    onKeyDown={e => { if (e.key === "Enter") handleSubmit(); }}
                  />
                </div>
                <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-1">
                  Generate any random string — it becomes part of the Answer URL you'll copy after connecting.
                </p>
              </div>
            </>
          ) : isHostaway ? (
            <>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Account ID <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input autoFocus type="text" value={fields.account_id ?? ""} onChange={e => set("account_id", e.target.value)} placeholder="Your Hostaway Account ID" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">API Secret <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input type="password" value={fields.api_secret ?? ""} onChange={e => set("api_secret", e.target.value)} placeholder="Your Hostaway API Secret" className={inputCls} />
                </div>
              </div>
            </>
          ) : (
            <>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                  API Key <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                  <input
                    autoFocus
                    type="password"
                    value={fields.api_key ?? ""}
                    onChange={e => set("api_key", e.target.value)}
                    placeholder="Paste your API key here…"
                    className={inputCls}
                    onKeyDown={e => { if (e.key === "Enter") handleSubmit(); }}
                  />
                </div>
              </div>
              {isIvr && (
                <div>
                  <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                    Webhook Secret <span className="text-red-500">*</span>
                  </label>
                  <div className="relative">
                    <Shield size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
                    <input
                      type="password"
                      value={fields.webhook_secret ?? ""}
                      onChange={e => set("webhook_secret", e.target.value)}
                      placeholder="Any random string you generate"
                      className={inputCls}
                      onKeyDown={e => { if (e.key === "Enter") handleSubmit(); }}
                    />
                  </div>
                  <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-1">
                    {provider === "mcube"
                      ? "Generate any random string — it becomes part of the webhook URL you'll copy after connecting."
                      : `Generate any random string, then paste the same value into your ${providerName} dashboard → Webhooks → Secret.`}
                  </p>
                </div>
              )}
            </>
          )}

          <p className="text-[11px] text-[var(--haip-fg-subtle)] flex items-center gap-1">
            <Shield size={10} />
            Encrypted with AES-256 before storage — never visible after saving.
          </p>

          {notes && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-700">
              <p className="font-semibold mb-0.5">Important</p>
              <p>{notes}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 pb-5 pt-3 flex items-center gap-3 justify-end border-t border-[var(--haip-border)] flex-shrink-0">
          <button onClick={onClose} className="px-4 py-2 text-sm text-[var(--haip-fg-muted)] hover:text-[var(--haip-fg)] transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
            className="px-4 py-2 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Connect
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

function Toast({ message, type, onClose }: { message: string; type: "success" | "error" | "warning"; onClose: () => void }) {
  return (
    <div className={cn(
      "fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-green-50 text-green-800 border-green-200"
        : type === "warning" ? "bg-amber-50 text-amber-800 border-amber-200"
        : "bg-red-50 text-red-800 border-red-200"
    )}>
      {type === "success"
        ? <CheckCircle2 size={16} className="text-green-600 flex-shrink-0" />
        : type === "warning"
        ? <AlertCircle size={16} className="text-amber-500 flex-shrink-0" />
        : <AlertCircle size={16} className="text-red-600 flex-shrink-0" />
      }
      <span className="flex-1">{message}</span>
      <button onClick={onClose} className="ml-2 opacity-60 hover:opacity-100">
        <X size={14} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Webhook URL copy widget (for telephony providers)
// ---------------------------------------------------------------------------

function WebhookUrlCopy({ provider }: { provider: string }) {
  const [copied, setCopied] = useState(false);

  const { data, isLoading } = useQuery<{ webhook_url: string | null; instructions?: string[] }>({
    queryKey: ["ivr-webhook-info", provider],
    queryFn: () => api.get(`/integrations/${provider}/webhook-info`).then(r => r.data),
  });

  const url = data?.webhook_url ?? null;

  const copy = () => {
    if (!url) return;
    navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="border-t border-[var(--haip-border)] pt-3">
      <p className="text-[10px] text-[var(--haip-fg-subtle)] mb-1.5 font-semibold uppercase tracking-wide">Webhook URL</p>
      {isLoading ? (
        <p className="text-[10px] text-[var(--haip-fg-subtle)]">Loading…</p>
      ) : url ? (
        <>
          <div className="flex items-center gap-2 bg-[var(--haip-surface)] rounded-lg px-2.5 py-1.5">
            <code className="text-[10px] text-[var(--haip-fg-muted)] flex-1 truncate font-mono">{url}</code>
            <button onClick={copy} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)] transition-colors flex-shrink-0" title="Copy">
              {copied ? <CheckCircle2 size={11} className="text-green-500" /> : <Copy size={11} />}
            </button>
          </div>
          {data?.instructions?.map((line, i) => (
            <p key={i} className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">{line}</p>
          ))}
        </>
      ) : (
        <p className="text-[10px] text-amber-600">
          {data?.instructions?.[0] ?? `Reconnect ${provider} with a webhook secret to generate this URL.`}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Integration Card
// ---------------------------------------------------------------------------

// Mcube-disconnect + outbound-calling pass: the main connect form only
// renders pre-connection (see IntegrationCard's isConnected branching
// below), so tenants that connected Vobiz before the DID field existed
// have no way to add it without this -- a full disconnect/reconnect would
// rotate webhook_secret and break the live inbound Answer URL already
// pasted into their Vobiz Console.
function VobizDidNumberEditor() {
  const [value, setValue] = useState("");
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (did_number: string) => api.patch("/integrations/vobiz/did-number", { did_number }),
    onSuccess: () => { setSavedMsg("Saved — outbound calling is ready."); setValue(""); },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSavedMsg(typeof msg === "string" ? msg : "Could not save — please try again.");
    },
  });

  return (
    <div className="bg-[var(--haip-primary-tint)] border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] rounded-xl p-3 space-y-2">
      <p className="text-[11px] font-semibold text-[var(--haip-fg-2)]">Vobiz Phone Number (DID)</p>
      <p className="text-[10px] text-[var(--haip-fg-subtle)] leading-relaxed">
        Required for agents to click-to-call guests. Not needed for inbound. From the Vobiz Console → Numbers.
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={e => { setValue(e.target.value); setSavedMsg(null); }}
          placeholder="+9122XXXXXXXX"
          className="flex-1 px-2.5 py-1.5 rounded-lg text-xs border border-[var(--haip-border)] outline-none focus:border-primary"
        />
        <button
          type="button"
          onClick={() => value.trim() && save.mutate(value.trim())}
          disabled={save.isPending || !value.trim()}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-primary hover:bg-primary disabled:opacity-50"
        >
          {save.isPending ? <Loader2 size={12} className="animate-spin" /> : "Save"}
        </button>
      </div>
      {savedMsg && (
        <p className={cn("text-[10px]", save.isError ? "text-red-600" : "text-primary")}>{savedMsg}</p>
      )}
    </div>
  );
}

function IntegrationCard({
  item,
  integration,
  onConnect,
  onDisconnect,
  onVerify,
  isConnecting,
  isDisconnecting,
  isVerifying,
}: {
  item: CatalogItem;
  integration?: Integration;
  onConnect: (provider: string) => void;
  onDisconnect: (provider: string) => void;
  onVerify: (provider: string) => void;
  isConnecting: boolean;
  isDisconnecting: boolean;
  isVerifying: boolean;
}) {
  const { data: session } = useSession();
  const accessToken = (session as unknown as { accessToken?: string })?.accessToken ?? null;
  // A fresh token at click time (openOAuth): the session token in memory may have expired while the page sat open.
  const igOAuthUrl = accessToken ? "/integrations/instagram/oauth-start" : null;

  const status = integration?.status ?? "disconnected";
  const isConnected = status === "active";
  const isMessaging = item.provider === "whatsapp_meta" || item.provider === "instagram";

  return (
    <div className={cn(
      "bg-white rounded-2xl border transition-all duration-200 p-5 flex flex-col gap-4",
      isConnected ? "border-[color-mix(in_srgb,var(--primary)_25%,transparent)] shadow-sm shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]" : "border-[var(--haip-border)] hover:border-[var(--haip-border)] hover:shadow-sm"
    )}>
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0",
          isConnected ? "bg-[var(--haip-primary-tint)]" : "bg-[var(--haip-surface)]"
        )}>
          <ProviderIcon logo={item.logo} size={24} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <span className="text-sm font-bold text-[var(--haip-fg)]">{item.name}</span>
            {item.popular && (
              <span className="text-[9px] bg-[var(--haip-primary-tint)] text-primary px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wide">Popular</span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={status} />
            <span className="text-[10px] text-[var(--haip-fg-subtle)] capitalize">{item.category}</span>
            <TokenExpiryBadge expiry={integration?.config?.token_expires_at ?? integration?.config?.token_expiry} />
          </div>
        </div>
      </div>

      {/* Description */}
      <p className="text-xs text-[var(--haip-fg-subtle)] leading-relaxed">{item.description}</p>

      {/* Metadata (when connected) */}
      {isConnected && integration?.config && Object.keys(integration.config).length > 0 && (
        <div className="bg-[var(--haip-surface)] rounded-xl p-3 text-[11px] text-[var(--haip-fg-muted)] space-y-1.5">
          {integration.config.display_phone && (
            <div className="flex items-center gap-2">
              <Phone size={11} className="text-[var(--haip-fg-subtle)]" />
              <span className="font-mono font-medium">{integration.config.display_phone}</span>
            </div>
          )}
          {integration.config.verified_name && (
            <div className="flex items-center gap-2">
              <CheckCircle2 size={11} className="text-green-500" />
              <span>{integration.config.verified_name}</span>
            </div>
          )}
          {integration.config.username && (
            <div className="flex items-center gap-2">
              <AtSign size={11} className="text-[var(--haip-fg-subtle)]" />
              <span>@{integration.config.username}</span>
            </div>
          )}
          {integration.config.account_name && (
            <div className="flex items-center gap-2">
              <Zap size={11} className="text-[var(--haip-fg-subtle)]" />
              <span>{integration.config.account_name}</span>
            </div>
          )}
          {integration.config.token_expires_at && (
            <div className="flex items-center gap-2">
              <Clock size={11} className="text-[var(--haip-fg-subtle)]" />
              <span>Access token ends {new Date(integration.config.token_expires_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</span>
            </div>
          )}
          {integration.config.waba_id && (
            <div className="flex items-center gap-2 text-[var(--haip-fg-subtle)]">
              <span className="font-mono text-[10px]">WABA: {integration.config.waba_id}</span>
            </div>
          )}
          {integration.last_health_at && (
            <div className="flex items-center gap-2 text-[var(--haip-fg-subtle)] pt-0.5 border-t border-[var(--haip-border)]">
              <Clock size={10} />
              <span>Last verified {new Date(integration.last_health_at).toLocaleString()}</span>
            </div>
          )}
        </div>
      )}

      {/* S7: Meta quality shortcut — only for connected WhatsApp */}
      {isConnected && item.provider === "whatsapp_meta" && (
        <a
          href="/dashboard/settings/integrations/meta-quality"
          className="flex items-center justify-between px-3 py-2 bg-blue-50 border border-blue-100 rounded-xl text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
        >
          <span className="flex items-center gap-1.5">
            <Wifi size={11} />
            View WABA quality rating &amp; trend
          </span>
          <ExternalLink size={10} />
        </a>
      )}

      {/* Error message */}
      {status === "error" && integration?.config?.last_error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700 flex gap-2">
          <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
          <span>{integration.config.last_error}</span>
        </div>
      )}

      {/* Notes (before connected) */}
      {item.notes && !isConnected && (
        <p className="text-[10px] text-amber-600 bg-amber-50 rounded-lg px-2.5 py-1.5 leading-relaxed">
          {item.notes}
        </p>
      )}

      {/* Actions */}
      <div className="flex flex-col gap-2 pt-1">
        {isConnected ? (
          <>
          {/* Instagram DMs are sent via graph.instagram.com, which only
              accepts a token minted by Instagram Login -- a hand-pasted
              Facebook Page token is rejected with "Cannot parse access
              token". Saving one manually still flips status to active,
              which used to hide this button (it rendered only in the
              disconnected branch below), leaving no way back to OAuth
              except Disconnect -- and that wipes credentials_kms_blob and
              config, App Secret included. Confirmed live on Ratha: four
              reconnect attempts, every one a pasted token, inbound and
              outbound both dead for days. Offer the real flow here. */}
          {item.provider === "instagram" && igOAuthUrl && (
            <button type="button"
              onClick={() => openOAuth(igOAuthUrl, true)}
              className="w-full flex items-center justify-center gap-1.5 px-4 py-2.5 bg-primary text-white rounded-xl text-xs font-semibold hover:bg-primary transition-colors shadow-sm shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]"
            >
              <Plug size={13} />
              Reconnect via Instagram Login
            </button>
          )}
          <div className="flex items-center gap-2">
            <button
              onClick={() => onConnect(item.provider)}
              disabled={isConnecting}
              title="Update credentials without disconnecting — e.g. a rotated token or the wrong number pasted the first time"
              className="flex items-center justify-center gap-1.5 px-3 py-2 border border-[var(--haip-border)] rounded-xl text-xs font-medium text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)] transition-colors disabled:opacity-50"
            >
              {isConnecting ? <Loader2 size={12} className="animate-spin" /> : <Pencil size={12} />}
              Edit
            </button>
            <button
              onClick={() => onVerify(item.provider)}
              disabled={isVerifying}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 border border-[var(--haip-border)] rounded-xl text-xs font-medium text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)] transition-colors disabled:opacity-50"
            >
              {isVerifying ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Test connection
            </button>
            <button
              onClick={() => onDisconnect(item.provider)}
              disabled={isDisconnecting}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 border border-red-200 rounded-xl text-xs font-medium text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
            >
              {isDisconnecting ? <Loader2 size={12} className="animate-spin" /> : <Unplug size={12} />}
              Disconnect
            </button>
          </div>
          </>
        ) : item.provider === "instagram" && igOAuthUrl ? (
          <>
            <button type="button"
              onClick={() => openOAuth(igOAuthUrl, true)}
              className="w-full flex items-center justify-center gap-1.5 px-4 py-2.5 bg-primary text-white rounded-xl text-xs font-semibold hover:bg-primary transition-colors shadow-sm shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]"
            >
              <Plug size={13} />
              Connect via Instagram Login
            </button>
            <p className="text-[10px] text-[var(--haip-fg-subtle)] text-center">
              First time connecting? An App Secret must be saved first —{" "}
              <button onClick={() => onConnect(item.provider)} className="underline hover:text-[var(--haip-fg-muted)]">
                save credentials manually
              </button>.
            </p>
          </>
        ) : (
          <button
            onClick={() => onConnect(item.provider)}
            disabled={isConnecting}
            className="w-full flex items-center justify-center gap-1.5 px-4 py-2.5 bg-primary text-white rounded-xl text-xs font-semibold hover:bg-primary transition-colors disabled:opacity-50 shadow-sm shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]"
          >
            {isConnecting ? <Loader2 size={13} className="animate-spin" /> : <Plug size={13} />}
            {item.provider === "haip_ivr" ? "Configure IVR" : `Connect ${item.name}`}
          </button>
        )}
      </div>

      {/* Webhook URL for telephony */}
      {isConnected && item.category === "telephony" && (
        <WebhookUrlCopy provider={item.provider} />
      )}

      {/* Mcube-disconnect + outbound-calling pass: DID number editor for
          already-connected Vobiz integrations (see VobizDidNumberEditor
          docstring for why this can't just be part of the connect form). */}
      {isConnected && item.provider === "vobiz" && <VobizDidNumberEditor />}

      {/* Webhook info panel for WhatsApp / Instagram after connect */}
      {isConnected && isMessaging && (
        <WebhookInfoPanel provider={item.provider} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function IntegrationsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "warning" } | null>(null);
  const [connectModal, setConnectModal] = useState<{ provider: string; name: string; authType?: string; notes?: string } | null>(null);
  const [loadingProvider, setLoadingProvider] = useState<string | null>(null);
  const [disconnectingProvider, setDisconnectingProvider] = useState<string | null>(null);
  const [verifyingProvider, setVerifyingProvider] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>("all");

  const showToast = useCallback((message: string, type: "success" | "error" | "warning") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 5000);
  }, []);

  // Static fallback catalog — shown when API is down or returns empty
  const STATIC_CATALOG: CatalogItem[] = [
    { provider: "whatsapp_meta", name: "WhatsApp",      description: "Connect WhatsApp Business via Meta Cloud API to send & receive messages.", category: "messaging",  auth_type: "whatsapp_meta", logo: "whatsapp", popular: true },
    { provider: "instagram",     name: "Instagram DM",  description: "Receive and reply to Instagram Direct Messages from your hospitality page.", category: "messaging",  auth_type: "instagram",     logo: "instagram", popular: true },
    { provider: "haip_ivr",       name: "HAIP IVR",      description: "Route inbound calls across your team — round robin, parallel ring, or fixed order — with a greeting before the call connects.", category: "telephony", auth_type: "ivr_settings", logo: "ivr", popular: true },
    { provider: "callerdesk",    name: "CallerDesk",    description: "Inbound & outbound IVR calls with auto-transcription and QA scoring.", category: "telephony",   auth_type: "api_key",       logo: "phone",  popular: true },
    { provider: "acefone",       name: "Acefone",       description: "Cloud telephony for inbound call handling, call routing, and recordings.", category: "telephony",   auth_type: "api_key",       logo: "phone",  popular: false },
    { provider: "exotel",        name: "Exotel",        description: "Indian cloud telephony platform for voice calls and SMS automation.", category: "telephony",   auth_type: "api_key",       logo: "phone",  popular: false },
    { provider: "hostaway",      name: "Hostaway PMS",  description: "Sync property listings, guest reservations, and stay data from Hostaway.", category: "pms",         auth_type: "hostaway",      logo: "hotel",  popular: true },
    { provider: "deepgram",      name: "Deepgram",      description: "Fast, accurate call transcription with speaker diarisation.", category: "ai",          auth_type: "api_key",       logo: "phone",  popular: false },
  ];

  // Fetch catalog — public endpoint, no auth needed, drives whether cards render
  const { data: catalogRaw = [], isLoading: catalogLoading } = useQuery<CatalogItem[]>({
    queryKey: ["integrations-catalog"],
    queryFn: () => api.get("/integrations/catalog").then(r => r.data),
    staleTime: Infinity,
    retry: 2,
  });

  // Use API catalog when available, fall back to static catalog
  const catalog: CatalogItem[] = catalogRaw.length > 0 ? catalogRaw : STATIC_CATALOG;

  // Fetch connected integrations — auth-required; only affects connection badges,
  // never blocks the catalog from rendering
  const { data: integrations = [] } = useQuery<Integration[]>({
    queryKey: ["integrations"],
    queryFn: () => api.get("/integrations").then(r => r.data),
    staleTime: 30_000,
    retry: false,   // don't retry on 401 — just show cards as disconnected
  });

  // Backend returns `kind` (e.g. "whatsapp"), catalog uses `provider` (e.g. "whatsapp_meta").
  // Build a map keyed by both kind and provider so catalog lookups always hit.
  const integrationMap: Record<string, Integration> = {};
  for (const i of integrations) {
    integrationMap[i.kind] = i;
    // Alias: "whatsapp" → "whatsapp_meta" so catalog cards look up correctly
    if (i.kind === "whatsapp") integrationMap["whatsapp_meta"] = i;
  }

  // Mutations
  const connectMutation = useMutation({
    mutationFn: ({ provider, fields }: { provider: string; fields: Record<string, string> }) =>
      api.post(`/integrations/${provider}/connect-key`, fields),
    onSuccess: (res, { provider }) => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      // Also pre-fetch webhook info for messaging providers
      if (provider === "whatsapp_meta" || provider === "instagram") {
        queryClient.prefetchQuery({
          queryKey: ["webhook-info", provider],
          queryFn: () => api.get(`/integrations/${provider}/webhook-info`).then(r => r.data),
        });
      }
      const providerName = catalog.find(c => c.provider === provider)?.name ?? integrationMap[provider]?.config?.provider_name ?? provider;
      const warning = (res as any)?.data?.warning;
      if (warning) {
        showToast(`${providerName} saved — ${warning}`, "warning");
      } else {
        showToast(`${providerName} connected successfully!`, "success");
      }
      setConnectModal(null);
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || "Failed to connect integration.", "error");
    },
    onSettled: () => setLoadingProvider(null),
  });

  const disconnectMutation = useMutation({
    mutationFn: (provider: string) => api.delete(`/integrations/${provider}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      showToast("Integration disconnected.", "success");
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || "Failed to disconnect.", "error");
    },
    onSettled: () => setDisconnectingProvider(null),
  });

  const verifyMutation = useMutation({
    mutationFn: (provider: string) => api.post(`/integrations/${provider}/test`).then(r => r.data as { status: string; message: string }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      if (data.status === "active" || data.status === "connected") {
        showToast(data.message || "Connection verified!", "success");
      } else {
        showToast(data.message || "Verification failed — check your credentials.", "error");
      }
    },
    onError: (err: any) => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      const msg = err?.response?.data?.detail || "Verification failed — check your credentials.";
      showToast(msg, "error");
    },
    onSettled: () => setVerifyingProvider(null),
  });

  // Handlers
  const handleConnect = useCallback((provider: string) => {
    if (provider === "haip_ivr") {
      router.push("/dashboard/settings/ivr");
      return;
    }
    const item = catalog.find(c => c.provider === provider);
    if (!item) return;
    setConnectModal({ provider, name: item.name, authType: item.auth_type, notes: item.notes });
  }, [catalog, router]);

  const handleModalConnect = useCallback(async (fields: Record<string, string>) => {
    if (!connectModal) return;
    setLoadingProvider(connectModal.provider);
    connectMutation.mutate({ provider: connectModal.provider, fields });
  }, [connectModal, connectMutation]);

  const handleDisconnect = useCallback((provider: string) => {
    if (!confirm("Are you sure you want to disconnect this integration? Conversation history is preserved.")) return;
    setDisconnectingProvider(provider);
    disconnectMutation.mutate(provider);
  }, [disconnectMutation]);

  const handleVerify = useCallback((provider: string) => {
    setVerifyingProvider(provider);
    verifyMutation.mutate(provider);
  }, [verifyMutation]);

  // Grouping — only block on catalogLoading; integrations just fills in connection state
  const categories = ["all", ...Array.from(new Set(catalog.map(c => c.category)))];
  const filtered = activeCategory === "all" ? catalog : catalog.filter(c => c.category === activeCategory);
  const connectedCount = integrations.filter(i => i.status === "active").length;
  const isLoading = catalogLoading;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-[var(--haip-border)] flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="haip-page-title">Integrations</h1>
            <p className="text-sm text-[var(--haip-fg-subtle)] mt-0.5">
              Connect your tools directly — each client uses their own API credentials.
            </p>
          </div>
          {connectedCount > 0 && (
            <div className="flex items-center gap-2 bg-green-50 border border-green-200 rounded-xl px-3 py-1.5">
              <CheckCircle2 size={14} className="text-green-600" />
              <span className="text-xs font-semibold text-green-700">{connectedCount} active</span>
            </div>
          )}
        </div>

        {/* Category tabs */}
        <div className="flex items-center gap-1 mt-4 flex-wrap">
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium capitalize transition-colors",
                activeCategory === cat ? "bg-[var(--haip-tab-active-bg)] text-[var(--haip-tab-active-fg)]" : "text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-status-neutral-bg)] hover:text-[var(--haip-fg-2)]"
              )}
            >
              {cat === "all" ? "All integrations" : cat}
              {cat !== "all" && (
                <span className="ml-1.5 text-[10px] opacity-70">({catalog.filter(c => c.category === cat).length})</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Cards grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="bg-white rounded-2xl border border-[var(--haip-border)] p-5 animate-pulse">
                <div className="flex items-center gap-4 mb-4">
                  <div className="w-12 h-12 rounded-xl bg-[var(--haip-status-neutral-bg)]" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3 bg-[var(--haip-status-neutral-bg)] rounded w-1/2" />
                    <div className="h-2 bg-[var(--haip-status-neutral-bg)] rounded w-1/4" />
                  </div>
                </div>
                <div className="space-y-2 mb-4">
                  <div className="h-2 bg-[var(--haip-status-neutral-bg)] rounded" />
                  <div className="h-2 bg-[var(--haip-status-neutral-bg)] rounded w-4/5" />
                </div>
                <div className="h-9 bg-[var(--haip-status-neutral-bg)] rounded-xl" />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-[var(--haip-fg-subtle)]">
            <Plug size={40} className="mb-3 opacity-30" />
            <p className="text-sm">No integrations in this category</p>
          </div>
        ) : (
          <>
            {/* Popular */}
            {activeCategory === "all" && filtered.some(c => c.popular) && (
              <div className="mb-6">
                <h2 className="text-xs font-bold text-[var(--haip-fg-subtle)] uppercase tracking-widest mb-3">Popular</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {filtered.filter(c => c.popular).map(item => (
                    <IntegrationCard
                      key={item.provider}
                      item={item}
                      integration={integrationMap[item.provider]}
                      onConnect={handleConnect}
                      onDisconnect={handleDisconnect}
                      onVerify={handleVerify}
                      isConnecting={loadingProvider === item.provider}
                      isDisconnecting={disconnectingProvider === item.provider}
                      isVerifying={verifyingProvider === item.provider}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Remaining */}
            {(activeCategory !== "all" || filtered.some(c => !c.popular)) && (
              <div>
                {activeCategory === "all" && (
                  <h2 className="text-xs font-bold text-[var(--haip-fg-subtle)] uppercase tracking-widest mb-3">All</h2>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {(activeCategory === "all" ? filtered.filter(c => !c.popular) : filtered).map(item => (
                    <IntegrationCard
                      key={item.provider}
                      item={item}
                      integration={integrationMap[item.provider]}
                      onConnect={handleConnect}
                      onDisconnect={handleDisconnect}
                      onVerify={handleVerify}
                      isConnecting={loadingProvider === item.provider}
                      isDisconnecting={disconnectingProvider === item.provider}
                      isVerifying={verifyingProvider === item.provider}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* Security footer */}
        <div className="mt-8 haip-card p-4 flex items-start gap-3">
          <div className="w-8 h-8 rounded-lg bg-[var(--haip-primary-tint)] flex items-center justify-center flex-shrink-0 mt-0.5">
            <Shield size={16} className="text-primary" />
          </div>
          <div>
            <p className="text-xs font-semibold text-[var(--haip-fg-2)] mb-1">Enterprise-grade security</p>
            <p className="text-xs text-[var(--haip-fg-subtle)] leading-relaxed">
              All credentials are encrypted at rest using AES-256 (Fernet) before being stored in the database.
              Tokens are never exposed to the frontend or API responses.
              Each organisation has fully isolated credentials — no cross-tenant data access.
              Each client brings their own Meta Cloud API / Graph API credentials — HAIP never holds shared tokens.
            </p>
          </div>
        </div>
      </div>

      {/* Connect Modal */}
      {connectModal && (
        <ConnectModal
          provider={connectModal.provider}
          providerName={connectModal.name}
          authType={connectModal.authType}
          notes={connectModal.notes}
          onConnect={handleModalConnect}
          onClose={() => setConnectModal(null)}
        />
      )}

      {/* Toast */}
      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}
    </div>
  );
}
