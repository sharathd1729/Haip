"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Phone, Plus, Trash2, Save, Eye, EyeOff, Loader2,
  CheckCircle2, AlertCircle, BarChart3, PhoneCall, Clock,
  RefreshCw, Copy, Info, Upload, Users, Shuffle, GitBranch,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────────

interface IVROption {
  id?: string;
  digit: number;
  label: string;
  spoken_text: string;
  route_number: string;
  department?: string;
}

interface IVRConfig {
  id: string;
  greeting_text: string;
  language: string;
  vobiz_username: string;
  vobiz_server: string;
  sip_number: string;
  dograh_workflow_id?: string;
  webhook_url?: string;
  is_active: boolean;
  options: IVROption[];
  updated_at: string;
}

interface IVRAnalytics {
  total_calls: number;
  calls_by_option: Record<string, number>;
  avg_duration_seconds: number;
  calls_today: number;
  top_option?: string;
  days: number;
}

const LANGUAGES = [
  { value: "en-IN", label: "English (India)" },
  { value: "hi-IN", label: "Hindi" },
  { value: "kn-IN", label: "Kannada" },
  { value: "ta-IN", label: "Tamil" },
  { value: "te-IN", label: "Telugu" },
];

const EMPTY_OPTION: IVROption = {
  digit: 1,
  label: "",
  spoken_text: "",
  route_number: "",
  department: "",
};

// ── Main page ─────────────────────────────────────────────────────────────────

export default function IVRPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"config" | "analytics">("config");
  const [showPassword, setShowPassword] = useState(false);
  const [saved, setSaved] = useState(false);
  const [previewText, setPreviewText] = useState<string | null>(null);

  const [form, setForm] = useState({
    greeting_text: "",
    language: "en-IN",
    business_hours_enabled: false,
    vobiz_username: "",
    vobiz_password: "",
    vobiz_server: "",
    sip_number: "",
    options: [{ ...EMPTY_OPTION }] as IVROption[],
  });

  const { data: config, isLoading: configLoading } = useQuery<IVRConfig>({
    queryKey: ["ivr-config"],
    queryFn: () => api.get("/api/v1/ivr/config").then(r => r.data),
    retry: false,
    onSuccess: (cfg: IVRConfig) => {
      setForm(f => ({
        ...f,
        greeting_text: cfg.greeting_text,
        language: cfg.language,
        vobiz_username: cfg.vobiz_username,
        vobiz_server: cfg.vobiz_server,
        sip_number: cfg.sip_number,
        options: cfg.options.length ? cfg.options : [{ ...EMPTY_OPTION }],
      }));
    },
  } as any);

  const { data: analytics } = useQuery<IVRAnalytics>({
    queryKey: ["ivr-analytics"],
    queryFn: () => api.get("/api/v1/ivr/analytics").then(r => r.data),
    enabled: tab === "analytics",
  });

  const saveMutation = useMutation({
    mutationFn: (body: typeof form) => api.put("/api/v1/ivr/config", body).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ivr-config"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    },
  });

  const previewMutation = useMutation({
    mutationFn: (body: typeof form) => api.post("/api/v1/ivr/config/preview", body).then(r => r.data),
    onSuccess: (data) => setPreviewText(data.greeting_text),
  });

  function setField(key: string, value: unknown) {
    setForm(f => ({ ...f, [key]: value }));
  }

  function addOption() {
    const usedDigits = new Set(form.options.map(o => o.digit));
    const nextDigit = [1,2,3,4,5,6,7,8,9].find(d => !usedDigits.has(d)) ?? 1;
    setForm(f => ({
      ...f,
      options: [...f.options, { ...EMPTY_OPTION, digit: nextDigit }],
    }));
  }

  function removeOption(idx: number) {
    setForm(f => ({ ...f, options: f.options.filter((_, i) => i !== idx) }));
  }

  function updateOption(idx: number, key: keyof IVROption, value: string | number) {
    setForm(f => ({
      ...f,
      options: f.options.map((o, i) => i === idx ? { ...o, [key]: value } : o),
    }));
  }

  function handleSave() {
    saveMutation.mutate(form);
  }

  if (configLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-teal-500" size={28} />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-teal-50 flex items-center justify-center">
            <Phone size={18} className="text-teal-600" />
          </div>
          <div>
            <h1 className="haip-page-title">IVR Call Routing</h1>
            <p className="text-xs text-gray-500">Who calls ring, and what plays before they connect</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setTab(tab === "config" ? "analytics" : "config")}
            className="text-xs text-gray-500 hover:text-teal-600 flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 hover:border-teal-200 transition-colors"
          >
            {tab === "config" ? <><BarChart3 size={13} /> Analytics</> : <><Phone size={13} /> Config</>}
          </button>
        </div>
      </div>

      {tab === "analytics" ? (
        <AnalyticsPanel analytics={analytics} />
      ) : (
        <>
          {/* Webhook URL info */}
          {config?.webhook_url && (
            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 flex items-start gap-3">
              <Info size={15} className="text-blue-500 mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-blue-700">Dograh webhook URL</p>
                <p className="text-xs text-blue-600 font-mono truncate mt-0.5">{config.webhook_url}</p>
              </div>
              <button
                onClick={() => navigator.clipboard.writeText(config.webhook_url!)}
                className="text-blue-400 hover:text-blue-600 flex-shrink-0"
              >
                <Copy size={13} />
              </button>
            </div>
          )}

          {/* Call routing -- separate from the DTMF menu config below, this
              is what the live Vobiz answer webhook actually reads. */}
          <CallRoutingSection />

          {/* The SIP Credentials + Greeting/DTMF sections below write to a
              separate ivr_configs table that the live Vobiz answer webhook
              (webhooks_vobiz.py) never reads -- confirmed live, not a
              guess. Your actual Vobiz auth (Auth ID / Auth Secret / forward
              number) lives on the Vobiz card under Settings > Integrations,
              editable there since the "Edit" button was added. This banner
              exists so filling in SIP Server/Username/Password below
              doesn't look like it should do something it doesn't. */}
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
            <AlertCircle size={15} className="text-amber-500 mt-0.5 flex-shrink-0" />
            <div className="text-xs text-amber-800 leading-relaxed">
              <p className="font-semibold mb-1">The sections below aren't connected to live calls</p>
              <p>
                Your real Vobiz connection (Auth ID, Auth Secret, forward
                number) is set on the{" "}
                <Link href="/dashboard/settings/integrations" className="underline hover:text-amber-900">
                  Vobiz card under Integrations
                </Link>
                {" "}— edit it there. "SIP Credentials" and "Greeting &amp;
                Language" here are a separate DTMF-menu builder that isn't
                wired into any active call path yet; changes here won't
                affect what happens when someone calls.
              </p>
            </div>
          </div>

          {/* SIP Credentials */}
          <Section title="Vobiz SIP Credentials (not currently active)" icon={<PhoneCall size={14} />}>
            <div className="grid grid-cols-2 gap-3">
              <Field label="SIP Server">
                <input
                  className={inputCls}
                  placeholder="sip.vobiz.ai"
                  value={form.vobiz_server}
                  onChange={e => setField("vobiz_server", e.target.value)}
                />
              </Field>
              <Field label="SIP Number (E.164)">
                <input
                  className={inputCls}
                  placeholder="+919876543210"
                  value={form.sip_number}
                  onChange={e => setField("sip_number", e.target.value)}
                />
              </Field>
              <Field label="Username">
                <input
                  className={inputCls}
                  placeholder="your-username"
                  value={form.vobiz_username}
                  onChange={e => setField("vobiz_username", e.target.value)}
                />
              </Field>
              <Field label="Password">
                <div className="relative">
                  <input
                    className={inputCls}
                    type={showPassword ? "text" : "password"}
                    placeholder="SIP password"
                    value={form.vobiz_password}
                    onChange={e => setField("vobiz_password", e.target.value)}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400"
                  >
                    {showPassword ? <EyeOff size={13} /> : <Eye size={13} />}
                  </button>
                </div>
              </Field>
            </div>
          </Section>

          {/* Greeting */}
          <Section title="Greeting & Language (not currently active)" icon={<Phone size={14} />}>
            <div className="space-y-3">
              <Field label="Language">
                <select
                  className={inputCls}
                  value={form.language}
                  onChange={e => setField("language", e.target.value)}
                >
                  {LANGUAGES.map(l => (
                    <option key={l.value} value={l.value}>{l.label}</option>
                  ))}
                </select>
              </Field>
              <Field label="Greeting text (read to caller)">
                <textarea
                  className={cn(inputCls, "h-24 resize-none")}
                  placeholder="Welcome to Sharat Homes. Please listen to the following options."
                  value={form.greeting_text}
                  onChange={e => setField("greeting_text", e.target.value)}
                />
              </Field>
              <button
                onClick={() => previewMutation.mutate(form)}
                disabled={previewMutation.isPending}
                className="text-xs text-teal-600 hover:text-teal-700 flex items-center gap-1"
              >
                {previewMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Eye size={12} />}
                Preview full greeting
              </button>
              {previewText && (
                <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs text-gray-700 italic">
                  "{previewText}"
                </div>
              )}
            </div>
          </Section>

          {/* Menu Builder */}
          <Section title="DTMF Menu Options (not currently active)" icon={<BarChart3 size={14} />}>
            <div className="space-y-2">
              {form.options.map((opt, idx) => (
                <div key={idx} className="grid grid-cols-12 gap-2 items-start p-3 bg-gray-50 rounded-xl border border-gray-100">
                  <div className="col-span-1">
                    <label className="text-[10px] text-gray-400 block mb-1">Digit</label>
                    <select
                      className={cn(inputCls, "text-center font-mono")}
                      value={opt.digit}
                      onChange={e => updateOption(idx, "digit", parseInt(e.target.value))}
                    >
                      {[1,2,3,4,5,6,7,8,9].map(d => (
                        <option key={d} value={d}>{d}</option>
                      ))}
                    </select>
                  </div>
                  <div className="col-span-3">
                    <label className="text-[10px] text-gray-400 block mb-1">Label</label>
                    <input
                      className={inputCls}
                      placeholder="Booking"
                      value={opt.label}
                      onChange={e => updateOption(idx, "label", e.target.value)}
                    />
                  </div>
                  <div className="col-span-4">
                    <label className="text-[10px] text-gray-400 block mb-1">Spoken text</label>
                    <input
                      className={inputCls}
                      placeholder="for booking inquiries"
                      value={opt.spoken_text}
                      onChange={e => updateOption(idx, "spoken_text", e.target.value)}
                    />
                  </div>
                  <div className="col-span-3">
                    <label className="text-[10px] text-gray-400 block mb-1">Route to (E.164)</label>
                    <input
                      className={inputCls}
                      placeholder="+919876543210"
                      value={opt.route_number}
                      onChange={e => updateOption(idx, "route_number", e.target.value)}
                    />
                  </div>
                  <div className="col-span-1 flex items-end pb-1">
                    <button
                      onClick={() => removeOption(idx)}
                      disabled={form.options.length <= 1}
                      className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 disabled:opacity-30 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              ))}
              {form.options.length < 9 && (
                <button
                  onClick={addOption}
                  className="w-full py-2 border-2 border-dashed border-gray-200 rounded-xl text-xs text-gray-400 hover:border-teal-300 hover:text-teal-600 flex items-center justify-center gap-1.5 transition-colors"
                >
                  <Plus size={13} /> Add option
                </button>
              )}
            </div>
          </Section>

          {/* Save */}
          <div className="flex items-center justify-between pt-2">
            {saveMutation.isError && (
              <div className="flex items-center gap-1.5 text-xs text-red-600">
                <AlertCircle size={13} />
                {(saveMutation.error as any)?.response?.data?.detail || "Save failed"}
              </div>
            )}
            {saved && (
              <div className="flex items-center gap-1.5 text-xs text-green-600">
                <CheckCircle2 size={13} /> Saved & pushed to Dograh
              </div>
            )}
            {!saveMutation.isError && !saved && <div />}
            <button
              onClick={handleSave}
              disabled={saveMutation.isPending}
              className="flex items-center gap-2 px-5 py-2 bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium rounded-xl disabled:opacity-60 transition-colors"
            >
              {saveMutation.isPending ? (
                <><Loader2 size={14} className="animate-spin" /> Saving…</>
              ) : (
                <><Save size={14} /> Save configuration</>
              )}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ── Analytics panel ───────────────────────────────────────────────────────────

function AnalyticsPanel({ analytics }: { analytics?: IVRAnalytics }) {
  if (!analytics) {
    return (
      <div className="flex items-center justify-center h-40">
        <Loader2 className="animate-spin text-teal-400" size={22} />
      </div>
    );
  }

  const maxCount = Math.max(...Object.values(analytics.calls_by_option), 1);

  return (
    <div className="space-y-4">
      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Total calls" value={analytics.total_calls} sub={`last ${analytics.days} days`} icon={<PhoneCall size={15} />} />
        <StatCard label="Calls today" value={analytics.calls_today} sub="today" icon={<RefreshCw size={15} />} />
        <StatCard label="Avg duration" value={`${Math.round(analytics.avg_duration_seconds)}s`} sub="per call" icon={<Clock size={15} />} />
      </div>

      {/* Calls by option */}
      <Section title="Calls by menu option" icon={<BarChart3 size={14} />}>
        {Object.keys(analytics.calls_by_option).length === 0 ? (
          <p className="text-xs text-gray-400 py-4 text-center">No IVR calls in this period</p>
        ) : (
          <div className="space-y-2">
            {Object.entries(analytics.calls_by_option)
              .sort((a, b) => b[1] - a[1])
              .map(([digit, count]) => (
                <div key={digit} className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-teal-50 flex items-center justify-center text-sm font-bold text-teal-600 flex-shrink-0">
                    {digit}
                  </div>
                  <div className="flex-1">
                    <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-teal-400 rounded-full transition-all"
                        style={{ width: `${(count / maxCount) * 100}%` }}
                      />
                    </div>
                  </div>
                  <span className="text-xs font-medium text-gray-600 w-8 text-right">{count}</span>
                </div>
              ))}
          </div>
        )}
      </Section>
    </div>
  );
}

// ── Call routing ───────────────────────────────────────────────────────────────
// Reads/writes /tenants/me/ivr-routing + /tenants/me/ivr-greeting-audio --
// separate from the greeting_text/options DTMF menu above, which the live
// Vobiz answer webhook doesn't consult at all. This is what it does read.

interface IVRRoutingSettings {
  ivr_routing_strategy: string;
  has_greeting_audio: boolean;
}

const ROUTING_STRATEGIES = [
  {
    id: "single", label: "Single number", icon: <Phone size={14} />,
    desc: "Ring one agent (today's behaviour). Falls back here automatically if no one is opted into routing.",
  },
  {
    id: "round_robin", label: "Round robin", icon: <RefreshCw size={14} />,
    desc: "Rotate through opted-in agents one call at a time, so the same person doesn't take every call.",
  },
  {
    id: "parallel", label: "Parallel ring", icon: <Shuffle size={14} />,
    desc: "Ring every opted-in agent's phone at once. Whoever picks up first gets the call, the rest stop ringing.",
  },
];

function CallRoutingSection() {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const { data, isLoading } = useQuery<IVRRoutingSettings>({
    queryKey: ["ivr-routing"],
    queryFn: () => api.get("/tenants/me/ivr-routing").then(r => r.data),
  });

  const saveStrategy = useMutation({
    mutationFn: (strategy: string) =>
      api.patch("/tenants/me/ivr-routing", { ivr_routing_strategy: strategy }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ivr-routing"] }),
  });

  const uploadGreeting = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api.post("/tenants/me/ivr-greeting-audio", body, {
        headers: { "Content-Type": "multipart/form-data" },
      }).then(r => r.data);
    },
    onSuccess: () => {
      setUploadError(null);
      qc.invalidateQueries({ queryKey: ["ivr-routing"] });
    },
    onError: (err: any) => {
      setUploadError(err?.response?.data?.detail || "Upload failed. Try an MP3 under 10 MB.");
    },
  });

  if (isLoading) {
    return (
      <div className="haip-card p-5 flex items-center justify-center">
        <Loader2 className="animate-spin text-teal-500" size={20} />
      </div>
    );
  }

  return (
    <Section title="Call Routing" icon={<GitBranch size={14} />}>
      <p className="text-xs text-gray-400 -mt-1">
        Who an inbound call rings, and what plays before it connects. Agents
        opt in from{" "}
        <Link href="/dashboard/settings/team" className="text-teal-600 hover:underline">
          Settings → Team
        </Link>
        {" "}(needs a phone number on file).
      </p>

      <div className="space-y-2">
        {ROUTING_STRATEGIES.map(s => (
          <label
            key={s.id}
            className={cn(
              "flex items-start gap-3 p-3 rounded-xl border-2 cursor-pointer transition-colors",
              data?.ivr_routing_strategy === s.id ? "border-teal-500 bg-teal-50" : "border-gray-200 hover:border-gray-300"
            )}
          >
            <input
              type="radio" name="ivr_strategy" className="mt-0.5 accent-teal-500"
              checked={data?.ivr_routing_strategy === s.id}
              onChange={() => saveStrategy.mutate(s.id)}
            />
            <span className="text-teal-500 mt-0.5">{s.icon}</span>
            <div>
              <div className="text-sm font-semibold text-gray-900">{s.label}</div>
              <div className="text-xs text-gray-500">{s.desc}</div>
            </div>
          </label>
        ))}
      </div>

      <div className="pt-2 border-t border-gray-100">
        <Field label="Greeting played before the call connects">
          <div className="flex items-center gap-3">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadGreeting.isPending}
              className="flex items-center gap-1.5 text-xs font-medium text-gray-600 bg-white hover:bg-gray-50 border border-gray-200 px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
            >
              {uploadGreeting.isPending ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
              {data?.has_greeting_audio ? "Replace recording" : "Upload recording"}
            </button>
            <input
              ref={fileInputRef} type="file" accept="audio/mpeg,audio/mp3,audio/wav,audio/m4a,.mp3,.wav,.m4a"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) uploadGreeting.mutate(f); e.target.value = ""; }}
            />
            {data?.has_greeting_audio && !uploadGreeting.isPending && (
              <span className="flex items-center gap-1 text-xs text-teal-600">
                <CheckCircle2 size={13} /> Configured
              </span>
            )}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Plays once the call is answered, before the agent's phone starts
            ringing. MP3, WAV or M4A, up to 10 MB. No recording uploaded means
            the call rings straight through, same as today.
          </p>
          {uploadError && (
            <p className="text-xs text-red-600 mt-1 flex items-center gap-1">
              <AlertCircle size={12} /> {uploadError}
            </p>
          )}
        </Field>
      </div>
    </Section>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

const inputCls = "w-full text-sm px-3 py-2 bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-300 focus:border-transparent placeholder-gray-300";

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="haip-card p-5 space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-teal-500">{icon}</span>
        <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-500">{label}</label>
      {children}
    </div>
  );
}

function StatCard({ label, value, sub, icon }: { label: string; value: string | number; sub: string; icon: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-teal-400">{icon}</span>
        <span className="text-xs text-gray-500">{label}</span>
      </div>
      <div className="text-2xl font-bold text-gray-800">{value}</div>
      <div className="text-[10px] text-gray-400 mt-0.5">{sub}</div>
    </div>
  );
}
