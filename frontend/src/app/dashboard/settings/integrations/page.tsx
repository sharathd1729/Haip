"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  MessageSquare, Phone, AtSign, CheckCircle2, AlertCircle,
  Loader2, Plug, Unplug, RefreshCw, ExternalLink, Key,
  X, Check, Clock, Wifi, WifiOff, Zap, Shield, Copy,
  Info, ChevronDown, ChevronUp,
} from "lucide-react";

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
  organization_id: string;
  provider: string;
  status: "connected" | "disconnected" | "error" | "pending";
  metadata_json: Record<string, string>;
  last_synced_at: string | null;
  error_message: string | null;
  token_expiry: string | null;
  created_at: string;
  updated_at: string;
}

interface WebhookInfo {
  webhook_url: string;
  verify_token: string;
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
  if (logo === "hotel") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className={cn("text-indigo-500", className)}>
        <path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-4h6v4M9 9h1m5 0h1M9 13h1m5 0h1" />
      </svg>
    );
  }
  return <Plug size={size} className={cn("text-gray-400", className)} />;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: Integration["status"] }) {
  const cfg = {
    connected:    { label: "Connected",     icon: <Wifi size={10} />,        cls: "bg-green-50 text-green-700 border-green-200" },
    error:        { label: "Error",          icon: <AlertCircle size={10} />, cls: "bg-red-50 text-red-700 border-red-200" },
    pending:      { label: "Pending",        icon: <Clock size={10} />,       cls: "bg-amber-50 text-amber-700 border-amber-200" },
    disconnected: { label: "Not connected",  icon: <WifiOff size={10} />,     cls: "bg-gray-50 text-gray-500 border-gray-200" },
  }[status] ?? { label: status, icon: null, cls: "bg-gray-50 text-gray-500 border-gray-200" };

  return (
    <span className={cn("inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border", cfg.cls)}>
      {cfg.icon} {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Token expiry badge
// ---------------------------------------------------------------------------

function TokenExpiryBadge({ expiry }: { expiry: string | null }) {
  if (!expiry) return null;
  const exp = new Date(expiry);
  const now = new Date();
  const daysLeft = Math.ceil((exp.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  if (daysLeft > 14) return null;
  return (
    <span className={cn(
      "inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border",
      daysLeft <= 3
        ? "bg-red-50 text-red-700 border-red-200"
        : "bg-amber-50 text-amber-700 border-amber-200"
    )}>
      <Clock size={10} />
      Token expires in {daysLeft}d
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
      <p className="text-[10px] text-gray-400 mb-1 font-semibold uppercase tracking-wide">{label}</p>
      <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5">
        <code className="text-[11px] text-gray-700 flex-1 break-all font-mono">{value}</code>
        <button
          onClick={() => { navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
          className="text-gray-400 hover:text-gray-600 flex-shrink-0 transition-colors"
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

function WebhookInfoPanel({ provider }: { provider: string }) {
  const [open, setOpen] = useState(true);
  const { data, isLoading } = useQuery<WebhookInfo>({
    queryKey: ["webhook-info", provider],
    queryFn: () => api.get(`/integrations/${provider}/webhook-info`).then(r => r.data),
    staleTime: Infinity,
  });

  const providerLabel = provider === "whatsapp_meta" ? "WhatsApp" : "Instagram";

  return (
    <div className="border-t border-gray-100 pt-3 mt-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center justify-between w-full text-left"
      >
        <p className="text-[10px] text-teal-700 font-semibold uppercase tracking-wide flex items-center gap-1">
          <Info size={10} />
          Configure {providerLabel} Webhook
        </p>
        {open ? <ChevronUp size={12} className="text-gray-400" /> : <ChevronDown size={12} className="text-gray-400" />}
      </button>

      {open && (
        <div className="mt-2 space-y-3">
          {isLoading ? (
            <div className="h-12 bg-gray-50 rounded-lg animate-pulse" />
          ) : data ? (
            <>
              <CopyField label="Webhook URL" value={data.webhook_url} />
              <CopyField label="Verify Token" value={data.verify_token} />
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
            <p className="text-[10px] text-gray-400">Could not load webhook info.</p>
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

  const isWhatsApp  = provider === "whatsapp_meta";
  const isInstagram = provider === "instagram";
  const isBasicAuth = authType === "basic_auth" && !isWhatsApp && !isInstagram;
  const isHostaway  = provider === "hostaway";

  const canSubmit = (() => {
    if (isWhatsApp)  return !!(fields.phone_number_id?.trim() && fields.waba_id?.trim() && fields.access_token?.trim());
    if (isInstagram) return !!(fields.instagram_business_account_id?.trim() && fields.access_token?.trim());
    if (isBasicAuth) return !!(fields.username?.trim() && fields.password?.trim());
    if (isHostaway)  return !!(fields.account_id?.trim() && fields.api_secret?.trim());
    return !!fields.api_key?.trim();
  })();

  const handleSubmit = async () => {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try { await onConnect(fields); } finally { setSubmitting(false); }
  };

  const inputCls = "w-full pl-9 pr-4 py-2.5 border border-gray-200 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-teal-500/30 bg-white";

  const subtitle = (() => {
    if (isWhatsApp)  return "Paste your WhatsApp Cloud API credentials from Meta Business Suite";
    if (isInstagram) return "Paste your Instagram Graph API credentials from Meta Business Suite";
    if (isBasicAuth) return `Enter your ${providerName} username and password`;
    if (isHostaway)  return "Enter your Hostaway Account ID and API Secret";
    return `Enter your API key from the ${providerName} dashboard`;
  })();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-base font-bold text-gray-900">Connect {providerName}</h2>
            <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4 overflow-y-auto flex-1">
          {isWhatsApp ? (
            <>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">
                  Phone Number ID <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input autoFocus type="text" value={fields.phone_number_id ?? ""} onChange={e => set("phone_number_id", e.target.value)} placeholder="e.g. 123456789012345" className={inputCls} />
                </div>
                <p className="text-[10px] text-gray-400 mt-1">Found in Meta Business Suite → WhatsApp → Getting Started.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">
                  WhatsApp Business Account ID (WABA ID) <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="text" value={fields.waba_id ?? ""} onChange={e => set("waba_id", e.target.value)} placeholder="e.g. 987654321098765" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">
                  Access Token <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="password" value={fields.access_token ?? ""} onChange={e => set("access_token", e.target.value)} placeholder="Permanent or temporary user token" className={inputCls} />
                </div>
                <p className="text-[10px] text-gray-400 mt-1">Use a permanent System User token for production (never expires).</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">
                  App Secret <span className="text-gray-400 font-normal">(recommended)</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="password" value={fields.app_secret ?? ""} onChange={e => set("app_secret", e.target.value)} placeholder="Meta App Secret (for webhook signature validation)" className={inputCls} />
                </div>
              </div>
            </>
          ) : isInstagram ? (
            <>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">
                  Instagram Business Account ID <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input autoFocus type="text" value={fields.instagram_business_account_id ?? ""} onChange={e => set("instagram_business_account_id", e.target.value)} placeholder="e.g. 17841234567890123" className={inputCls} />
                </div>
                <p className="text-[10px] text-gray-400 mt-1">Found in Meta Business Suite → Instagram → Account settings.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">
                  Access Token <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="password" value={fields.access_token ?? ""} onChange={e => set("access_token", e.target.value)} placeholder="Page or System User token with instagram_manage_messages" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">
                  App Secret <span className="text-gray-400 font-normal">(recommended)</span>
                </label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="password" value={fields.app_secret ?? ""} onChange={e => set("app_secret", e.target.value)} placeholder="Meta App Secret" className={inputCls} />
                </div>
              </div>
            </>
          ) : isBasicAuth ? (
            <>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Username <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input autoFocus type="text" value={fields.username ?? ""} onChange={e => set("username", e.target.value)} placeholder="Your RentalWise username" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Password <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="password" value={fields.password ?? ""} onChange={e => set("password", e.target.value)} placeholder="Your RentalWise password" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">API Base URL <span className="text-gray-400 font-normal">(optional)</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="text" value={fields.base_url ?? ""} onChange={e => set("base_url", e.target.value)} placeholder="https://partners-api.rentalwise.com" className={inputCls} />
                </div>
                <p className="text-[11px] text-gray-400 mt-1">Leave blank to use the default production URL.</p>
              </div>
            </>
          ) : isHostaway ? (
            <>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Account ID <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input autoFocus type="text" value={fields.account_id ?? ""} onChange={e => set("account_id", e.target.value)} placeholder="Your Hostaway Account ID" className={inputCls} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">API Secret <span className="text-red-500">*</span></label>
                <div className="relative">
                  <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="password" value={fields.api_secret ?? ""} onChange={e => set("api_secret", e.target.value)} placeholder="Your Hostaway API Secret" className={inputCls} />
                </div>
              </div>
            </>
          ) : (
            <div>
              <label className="text-xs font-semibold text-gray-700 block mb-1.5">
                API Key <span className="text-red-500">*</span>
              </label>
              <div className="relative">
                <Key size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
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
          )}

          <p className="text-[11px] text-gray-400 flex items-center gap-1">
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
        <div className="px-6 pb-5 pt-3 flex items-center gap-3 justify-end border-t border-gray-100 flex-shrink-0">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
            className="px-4 py-2 bg-teal-500 text-white rounded-xl text-sm font-medium hover:bg-teal-600 transition-colors disabled:opacity-50 flex items-center gap-1.5"
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

function Toast({ message, type, onClose }: { message: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn(
      "fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-green-50 text-green-800 border-green-200" : "bg-red-50 text-red-800 border-red-200"
    )}>
      {type === "success"
        ? <CheckCircle2 size={16} className="text-green-600 flex-shrink-0" />
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
  const url = typeof window !== "undefined"
    ? `${window.location.origin.replace(":3000", ":8000")}/webhooks/${provider}`
    : `https://your-haip-domain.com/webhooks/${provider}`;

  const copy = () => {
    navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="border-t border-gray-100 pt-3">
      <p className="text-[10px] text-gray-400 mb-1.5 font-semibold uppercase tracking-wide">Webhook URL</p>
      <div className="flex items-center gap-2 bg-gray-50 rounded-lg px-2.5 py-1.5">
        <code className="text-[10px] text-gray-600 flex-1 truncate font-mono">{url}</code>
        <button onClick={copy} className="text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0" title="Copy">
          {copied ? <CheckCircle2 size={11} className="text-green-500" /> : <Copy size={11} />}
        </button>
      </div>
      <p className="text-[10px] text-gray-400 mt-1">Configure this URL in your {provider} portal.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Integration Card
// ---------------------------------------------------------------------------

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
  const status = integration?.status ?? "disconnected";
  const isConnected = status === "connected";
  const isMessaging = item.provider === "whatsapp_meta" || item.provider === "instagram";

  return (
    <div className={cn(
      "bg-white rounded-2xl border transition-all duration-200 p-5 flex flex-col gap-4",
      isConnected ? "border-teal-200 shadow-sm shadow-teal-50" : "border-gray-100 hover:border-gray-200 hover:shadow-sm"
    )}>
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0",
          isConnected ? "bg-teal-50" : "bg-gray-50"
        )}>
          <ProviderIcon logo={item.logo} size={24} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <span className="text-sm font-bold text-gray-900">{item.name}</span>
            {item.popular && (
              <span className="text-[9px] bg-teal-100 text-teal-700 px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wide">Popular</span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={status} />
            <span className="text-[10px] text-gray-400 capitalize">{item.category}</span>
            {integration?.token_expiry && (
              <TokenExpiryBadge expiry={integration.token_expiry} />
            )}
          </div>
        </div>
      </div>

      {/* Description */}
      <p className="text-xs text-gray-500 leading-relaxed">{item.description}</p>

      {/* Metadata (when connected) */}
      {isConnected && integration?.metadata_json && Object.keys(integration.metadata_json).length > 0 && (
        <div className="bg-gray-50 rounded-xl p-3 text-[11px] text-gray-600 space-y-1.5">
          {integration.metadata_json.display_phone && (
            <div className="flex items-center gap-2">
              <Phone size={11} className="text-gray-400" />
              <span className="font-mono font-medium">{integration.metadata_json.display_phone}</span>
            </div>
          )}
          {integration.metadata_json.verified_name && (
            <div className="flex items-center gap-2">
              <CheckCircle2 size={11} className="text-green-500" />
              <span>{integration.metadata_json.verified_name}</span>
            </div>
          )}
          {integration.metadata_json.username && (
            <div className="flex items-center gap-2">
              <AtSign size={11} className="text-gray-400" />
              <span>@{integration.metadata_json.username}</span>
            </div>
          )}
          {integration.metadata_json.account_name && (
            <div className="flex items-center gap-2">
              <Zap size={11} className="text-gray-400" />
              <span>{integration.metadata_json.account_name}</span>
            </div>
          )}
          {integration.metadata_json.waba_id && (
            <div className="flex items-center gap-2 text-gray-400">
              <span className="font-mono text-[10px]">WABA: {integration.metadata_json.waba_id}</span>
            </div>
          )}
          {integration.last_synced_at && (
            <div className="flex items-center gap-2 text-gray-400 pt-0.5 border-t border-gray-100">
              <Clock size={10} />
              <span>Last verified {new Date(integration.last_synced_at).toLocaleString()}</span>
            </div>
          )}
        </div>
      )}

      {/* Error message */}
      {status === "error" && integration?.error_message && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700 flex gap-2">
          <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
          <span>{integration.error_message}</span>
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
          <div className="flex items-center gap-2">
            <button
              onClick={() => onVerify(item.provider)}
              disabled={isVerifying}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 border border-gray-200 rounded-xl text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              {isVerifying ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Verify
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
        ) : (
          <button
            onClick={() => onConnect(item.provider)}
            disabled={isConnecting}
            className="w-full flex items-center justify-center gap-1.5 px-4 py-2.5 bg-teal-500 text-white rounded-xl text-xs font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50 shadow-sm shadow-teal-200"
          >
            {isConnecting ? <Loader2 size={13} className="animate-spin" /> : <Plug size={13} />}
            Connect {item.name}
          </button>
        )}
      </div>

      {/* Webhook URL for telephony */}
      {isConnected && item.category === "telephony" && (
        <WebhookUrlCopy provider={item.provider} />
      )}

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
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const [connectModal, setConnectModal] = useState<{ provider: string; name: string; authType?: string; notes?: string } | null>(null);
  const [loadingProvider, setLoadingProvider] = useState<string | null>(null);
  const [disconnectingProvider, setDisconnectingProvider] = useState<string | null>(null);
  const [verifyingProvider, setVerifyingProvider] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>("all");

  const showToast = useCallback((message: string, type: "success" | "error") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 5000);
  }, []);

  // Fetch catalog
  const { data: catalog = [], isLoading: catalogLoading } = useQuery<CatalogItem[]>({
    queryKey: ["integrations-catalog"],
    queryFn: () => api.get("/integrations/catalog").then(r => r.data),
    staleTime: Infinity,
  });

  // Fetch connected integrations
  const { data: integrations = [], isLoading: integrationsLoading } = useQuery<Integration[]>({
    queryKey: ["integrations"],
    queryFn: () => api.get("/integrations").then(r => r.data),
    staleTime: 30_000,
  });

  const integrationMap = Object.fromEntries(integrations.map(i => [i.provider, i]));

  // Mutations
  const connectMutation = useMutation({
    mutationFn: ({ provider, fields }: { provider: string; fields: Record<string, string> }) =>
      api.post(`/integrations/${provider}/connect-key`, fields),
    onSuccess: (_, { provider }) => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      // Also pre-fetch webhook info for messaging providers
      if (provider === "whatsapp_meta" || provider === "instagram") {
        queryClient.prefetchQuery({
          queryKey: ["webhook-info", provider],
          queryFn: () => api.get(`/integrations/${provider}/webhook-info`).then(r => r.data),
        });
      }
      showToast(`${catalog.find(c => c.provider === provider)?.name ?? provider} connected successfully!`, "success");
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
    mutationFn: (provider: string) => api.post(`/integrations/${provider}/verify`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      showToast("Connection verified!", "success");
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      showToast("Verification failed — check your credentials.", "error");
    },
    onSettled: () => setVerifyingProvider(null),
  });

  // Handlers
  const handleConnect = useCallback((provider: string) => {
    const item = catalog.find(c => c.provider === provider);
    if (!item) return;
    setConnectModal({ provider, name: item.name, authType: item.auth_type, notes: item.notes });
  }, [catalog]);

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

  // Grouping
  const categories = ["all", ...Array.from(new Set(catalog.map(c => c.category)))];
  const filtered = activeCategory === "all" ? catalog : catalog.filter(c => c.category === activeCategory);
  const connectedCount = integrations.filter(i => i.status === "connected").length;
  const isLoading = catalogLoading || integrationsLoading;

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Integrations</h1>
            <p className="text-sm text-gray-400 mt-0.5">
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
                activeCategory === cat ? "bg-teal-500 text-white" : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
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
              <div key={i} className="bg-white rounded-2xl border border-gray-100 p-5 animate-pulse">
                <div className="flex items-center gap-4 mb-4">
                  <div className="w-12 h-12 rounded-xl bg-gray-100" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3 bg-gray-100 rounded w-1/2" />
                    <div className="h-2 bg-gray-100 rounded w-1/4" />
                  </div>
                </div>
                <div className="space-y-2 mb-4">
                  <div className="h-2 bg-gray-100 rounded" />
                  <div className="h-2 bg-gray-100 rounded w-4/5" />
                </div>
                <div className="h-9 bg-gray-100 rounded-xl" />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <Plug size={40} className="mb-3 opacity-30" />
            <p className="text-sm">No integrations in this category</p>
          </div>
        ) : (
          <>
            {/* Popular */}
            {activeCategory === "all" && filtered.some(c => c.popular) && (
              <div className="mb-6">
                <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">Popular</h2>
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
                  <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">All</h2>
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
        <div className="mt-8 bg-white border border-gray-100 rounded-2xl p-4 flex items-start gap-3">
          <div className="w-8 h-8 rounded-lg bg-teal-50 flex items-center justify-center flex-shrink-0 mt-0.5">
            <Shield size={16} className="text-teal-600" />
          </div>
          <div>
            <p className="text-xs font-semibold text-gray-700 mb-1">Enterprise-grade security</p>
            <p className="text-xs text-gray-400 leading-relaxed">
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
