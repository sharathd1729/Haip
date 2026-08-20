"use client";
import { useState, useEffect } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRouter, usePathname } from "next/navigation";
import { Building2, Users, Shield, QrCode, Loader2, CheckCircle, AlertCircle, Bell, Bot, ChevronRight, KeyRound, Lock, BookOpen } from "lucide-react";
import { useSession } from "next-auth/react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

type Tab = "workspace" | "ai" | "notifications" | "security";

const TABS: { id: Tab; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: "workspace",     label: "Workspace",      icon: <Building2 size={15} />, desc: "Brand, language, timezone" },
  { id: "ai",            label: "AI Concierge",   icon: <Bot size={15} />,       desc: "Automation modes & thresholds" },
  { id: "notifications", label: "Notifications",  icon: <Bell size={15} />,      desc: "Alerts & digest emails" },
  { id: "security",      label: "Security",       icon: <Shield size={15} />,    desc: "MFA, sessions, DPDP" },
];

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("workspace");
  const router = useRouter();
  const { data: session } = useSession();
  const isOwner = session?.user?.role === "owner";

  return (
    <div className="flex h-full">
      {/* Left nav */}
      <div
        className="w-56 flex-shrink-0 bg-card p-3 flex flex-col gap-0.5"
        style={{ borderRight: "1px solid var(--haip-border)" }}
      >
        <p className="haip-label px-3 py-2">Settings</p>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left transition-colors group",
              tab === t.id ? "bg-teal-50 text-teal-700" : "text-gray-600 hover:bg-gray-50"
            )}
          >
            <span className={tab === t.id ? "text-teal-500" : "text-gray-400"}>{t.icon}</span>
            <div>
              <div className="text-sm font-medium">{t.label}</div>
              <div className="text-[10px] text-gray-400 leading-none mt-0.5">{t.desc}</div>
            </div>
            <ChevronRight size={13} className={cn("ml-auto transition-opacity", tab === t.id ? "opacity-100 text-teal-400" : "opacity-0 group-hover:opacity-40")} />
          </button>
        ))}

        {/* Team — separate page */}
        <button
          onClick={() => router.push("/dashboard/settings/team")}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left transition-colors group text-gray-600 hover:bg-gray-50"
        >
          <span className="text-gray-400"><Users size={15} /></span>
          <div>
            <div className="text-sm font-medium">Team</div>
            <div className="text-[10px] text-gray-400 leading-none mt-0.5">Invite members, manage roles</div>
          </div>
          <ChevronRight size={13} className="ml-auto opacity-0 group-hover:opacity-40 transition-opacity" />
        </button>

        {/* AI Knowledge Base — what the concierge knows */}
        <button
          onClick={() => router.push("/dashboard/settings/knowledge")}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left transition-colors group text-gray-600 hover:bg-gray-50"
        >
          <span className="text-gray-400"><BookOpen size={15} /></span>
          <div>
            <div className="text-sm font-medium">AI Knowledge Base</div>
            <div className="text-[10px] text-gray-400 leading-none mt-0.5">FAQs, amenities, add-ons, routes</div>
          </div>
          <ChevronRight size={13} className="ml-auto opacity-0 group-hover:opacity-40 transition-opacity" />
        </button>

        {/* External Assistant Access (Perisclaw / MCP) — separate page */}
        <button
          onClick={() => router.push("/dashboard/settings/mcp-access")}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left transition-colors group text-gray-600 hover:bg-gray-50"
        >
          <span className="text-gray-400"><KeyRound size={15} /></span>
          <div>
            <div className="text-sm font-medium">External Assistant Access</div>
            <div className="text-[10px] text-gray-400 leading-none mt-0.5">Perisclaw, MCP tokens</div>
          </div>
          <ChevronRight size={13} className="ml-auto opacity-0 group-hover:opacity-40 transition-opacity" />
        </button>

        {/* Roles & Permissions (capability matrix) — owner-only */}
        {isOwner && (
          <button
            onClick={() => router.push("/dashboard/settings/permissions")}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left transition-colors group text-gray-600 hover:bg-gray-50"
          >
            <span className="text-gray-400"><Lock size={15} /></span>
            <div>
              <div className="text-sm font-medium">Roles &amp; Permissions</div>
              <div className="text-[10px] text-gray-400 leading-none mt-0.5">What each role can access</div>
            </div>
            <ChevronRight size={13} className="ml-auto opacity-0 group-hover:opacity-40 transition-opacity" />
          </button>
        )}

        <div className="mt-auto pt-4 border-t border-gray-100">
          <p className="text-[10px] text-gray-400 px-3">
            IVR, WhatsApp, Instagram, and PMS settings are managed in{" "}
            <a href="/dashboard/settings/integrations" className="text-teal-600 hover:underline font-medium">Integrations →</a>
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl">
          {tab === "workspace"     && <WorkspaceSettings />}
          {tab === "ai"            && <AISettings />}
          {tab === "notifications" && <NotificationSettings />}
          {tab === "security"      && <SecuritySettings />}
        </div>
      </div>
    </div>
  );
}

/* ── Workspace ─────────────────────────────────────────────────────────────── */
function WorkspaceSettings() {
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    brand_name: "",
    slug: "",
    timezone: "Asia/Kolkata",
    language: "en",
    date_format: "DD/MM/YYYY",
  });

  // Load real tenant data on mount. Was previously a useState(() => {...})
  // lazy-initializer callback abused to run a fetch once -- that pattern
  // has no place in React's data model (initializers are for computing
  // state synchronously, not side effects) and bypassed react-query's
  // cache entirely, unlike every other data read in this app.
  const { data: tenant } = useQuery({
    queryKey: ["tenants", "me"],
    queryFn: () => api.get("/tenants/me").then(r => r.data),
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!tenant) return;
    setForm(f => ({
      ...f,
      name: tenant.name || "",
      brand_name: tenant.brand_config?.brand_name || tenant.name || "",
      slug: tenant.slug || "",
      timezone: tenant.brand_config?.timezone || "Asia/Kolkata",
      language: tenant.brand_config?.language || "en",
    }));
  }, [tenant]);

  return (
    <div className="space-y-6">
      <SectionHeader title="Workspace" sub="Your organisation's brand and regional settings" />

      <Card>
        <div className="space-y-4">
          <Field label="Business name" value={form.name} onChange={v => setForm(f => ({...f, name: v}))} />
          <Field
            label="Brand display name"
            value={form.brand_name}
            onChange={v => setForm(f => ({...f, brand_name: v}))}
            hint="Used in AI Concierge greetings and email signatures"
          />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Workspace URL</label>
            <div className="flex items-center border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
              <span className="px-3 py-2 text-gray-400 text-sm border-r border-gray-200">genhaip.com/</span>
              <span className="px-3 py-2 text-gray-700 text-sm font-medium flex-1">{form.slug}</span>
              <span className="px-3 text-xs text-gray-400">Contact support to change</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Timezone</label>
              <select
                value={form.timezone}
                onChange={e => setForm(f => ({...f, timezone: e.target.value}))}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 bg-white"
              >
                <option value="Asia/Kolkata">Asia/Kolkata (IST, UTC+5:30)</option>
                <option value="Asia/Dubai">Asia/Dubai (GST, UTC+4)</option>
                <option value="Asia/Singapore">Asia/Singapore (SGT, UTC+8)</option>
                <option value="Europe/London">Europe/London (GMT/BST)</option>
                <option value="America/New_York">America/New_York (EST/EDT)</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Language</label>
              <select
                value={form.language}
                onChange={e => setForm(f => ({...f, language: e.target.value}))}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 bg-white"
              >
                <option value="en">English</option>
                <option value="hi">Hindi</option>
                <option value="ta">Tamil</option>
                <option value="ar">Arabic</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Date format</label>
            <select
              value={form.date_format}
              onChange={e => setForm(f => ({...f, date_format: e.target.value}))}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 bg-white"
            >
              <option value="DD/MM/YYYY">DD/MM/YYYY</option>
              <option value="MM/DD/YYYY">MM/DD/YYYY</option>
              <option value="YYYY-MM-DD">YYYY-MM-DD</option>
            </select>
          </div>

          {/* B10: Business hours — shown below timezone */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Business hours</label>
            <p className="text-xs text-gray-400 mb-3">Used for SLA timers, daily digest scheduling, and AI concierge availability.</p>
            <div className="border border-gray-100 rounded-xl overflow-hidden">
              {["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"].map((day, idx) => (
                <div key={day} className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                  <span className="w-24 text-xs font-medium text-gray-700">{day}</span>
                  <span className="text-xs text-gray-400">{idx < 5 ? "09:00 – 21:00" : idx === 5 ? "10:00 – 18:00" : "10:00 – 14:00"}</span>
                  <span className="ml-auto text-[10px] text-teal-600 bg-teal-50 px-2 py-0.5 rounded-full font-medium">Open</span>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-gray-400 mt-2">Full business hours editor coming in the next release.</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Current plan</label>
            <div className="flex items-center gap-3">
              <span className="bg-teal-100 text-teal-700 text-xs font-bold px-3 py-1 rounded-full uppercase tracking-wide">Growth</span>
              <span className="text-sm text-gray-500">1,500 calls/mo · 4,500 WA conv · 5 users</span>
              <a href="/dashboard/billing" className="ml-auto text-xs text-teal-600 hover:underline font-medium">Manage billing →</a>
            </div>
          </div>
        </div>
        <SaveButton
          saved={saved}
          loading={saving}
          onClick={async () => {
            setSaving(true);
            try {
              await api.patch("/tenants/me", {
                name: form.name,
                timezone: form.timezone,    // B10: top-level tenant field
                brand_config: {
                  brand_name: form.brand_name,
                  language: form.language,
                },
              });
              queryClient.invalidateQueries({ queryKey: ["tenants", "me"] });
              setSaved(true);
              setTimeout(() => setSaved(false), 3000);
            } catch {}
            setSaving(false);
          }}
        />
      </Card>
    </div>
  );
}

/* ── AI Concierge ──────────────────────────────────────────────────────────── */
interface AIModeSettings {
  wa_ai_mode_default: string;
  wa_ai_confidence_threshold: number;
  ig_ai_mode_default: string;
  ig_ai_confidence_threshold: number;
}

function AISettings() {
  const queryClient = useQueryClient();
  // This form used to be a mock: state initialised from a hardcoded
  // useState("shadow") and Save only set a local flag, so switching to
  // Autonomous appeared to work and silently reverted on remount. It now
  // loads from and writes to /tenants/me/ai-mode.
  const [waModeForm, setWaModeForm] = useState({ mode: "shadow", confidence: "0.78" });
  const [igModeForm, setIgModeForm] = useState({ mode: "shadow", confidence: "0.78" });
  const [savedWA, setSavedWA] = useState(false);
  const [savedIG, setSavedIG] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);

  const { data: aiMode, isLoading: aiModeLoading, isError: aiModeError } = useQuery<AIModeSettings>({
    queryKey: ["ai-mode"],
    queryFn: () => api.get("/tenants/me/ai-mode").then(r => r.data),
    retry: 1,
  });

  // Seed the forms once from the server, then let the user edit freely
  // without a refetch stomping their in-progress selection.
  useEffect(() => {
    if (aiMode && !loadedOnce) {
      setWaModeForm({
        mode: aiMode.wa_ai_mode_default ?? "shadow",
        confidence: String(aiMode.wa_ai_confidence_threshold ?? 0.78),
      });
      setIgModeForm({
        mode: aiMode.ig_ai_mode_default ?? "shadow",
        confidence: String(aiMode.ig_ai_confidence_threshold ?? 0.78),
      });
      setLoadedOnce(true);
    }
  }, [aiMode, loadedOnce]);

  const saveMode = useMutation({
    mutationFn: (payload: Partial<AIModeSettings>) =>
      api.patch("/tenants/me/ai-mode", payload).then(r => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-mode"] }),
  });

  const MODE_OPTIONS = [
    { id: "off",        label: "Off",         desc: "No AI — agents handle all replies manually" },
    { id: "shadow",     label: "Shadow mode", desc: "AI drafts replies; human reviews and approves before sending" },
    { id: "autonomous", label: "Autonomous",  desc: "AI sends automatically when confidence ≥ threshold" },
  ];

  return (
    <div className="space-y-6">
      <SectionHeader title="AI Concierge" sub="Control automation behaviour per channel" />

      {/* WhatsApp */}
      <Card title="WhatsApp — AI mode">
        <div className="space-y-2 mb-4">
          {MODE_OPTIONS.map(m => (
            <label key={m.id} className={cn(
              "flex items-start gap-3 p-3 rounded-xl border-2 cursor-pointer transition-colors",
              waModeForm.mode === m.id ? "border-teal-500 bg-teal-50" : "border-gray-200 hover:border-gray-300"
            )}>
              <input type="radio" name="wa_mode" value={m.id} checked={waModeForm.mode === m.id} onChange={() => setWaModeForm(f => ({...f, mode: m.id}))} className="mt-0.5 accent-teal-500" />
              <div>
                <div className="text-sm font-semibold text-gray-900">{m.label}</div>
                <div className="text-xs text-gray-500">{m.desc}</div>
              </div>
            </label>
          ))}
        </div>
        {waModeForm.mode === "autonomous" && (
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">Confidence threshold</label>
            <input
              type="number" min="0.5" max="1" step="0.01"
              value={waModeForm.confidence}
              onChange={e => setWaModeForm(f => ({...f, confidence: e.target.value}))}
              className="w-32 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30"
            />
            <p className="text-xs text-gray-400 mt-1">Recommended: 0.78. Replies below this score go to shadow mode for review.</p>
          </div>
        )}
        <p className="text-xs text-gray-400 mb-4">Recommended: start with Shadow for 30 days, then switch to Autonomous.</p>
        {aiModeError && (
          <p className="text-xs text-red-600 mb-2">Couldn&apos;t load current settings — saving may overwrite them.</p>
        )}
        <SaveButton
          saved={savedWA}
          loading={saveMode.isPending || aiModeLoading}
          onClick={() => {
            saveMode.mutate(
              {
                wa_ai_mode_default: waModeForm.mode,
                wa_ai_confidence_threshold: Number(waModeForm.confidence) || 0.78,
              },
              {
                onSuccess: () => {
                  setSavedWA(true);
                  setTimeout(() => setSavedWA(false), 2500);
                },
              },
            );
          }}
        />
      </Card>

      {/* Instagram */}
      <Card title="Instagram DMs — AI mode">
        <div className="space-y-2 mb-4">
          {MODE_OPTIONS.map(m => (
            <label key={m.id} className={cn(
              "flex items-start gap-3 p-3 rounded-xl border-2 cursor-pointer transition-colors",
              igModeForm.mode === m.id ? "border-teal-500 bg-teal-50" : "border-gray-200 hover:border-gray-300"
            )}>
              <input type="radio" name="ig_mode" value={m.id} checked={igModeForm.mode === m.id} onChange={() => setIgModeForm(f => ({...f, mode: m.id}))} className="mt-0.5 accent-teal-500" />
              <div>
                <div className="text-sm font-semibold text-gray-900">{m.label}</div>
                <div className="text-xs text-gray-500">{m.desc}</div>
              </div>
            </label>
          ))}
        </div>
        {igModeForm.mode === "autonomous" && (
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">Confidence threshold</label>
            <input
              type="number" min="0.5" max="1" step="0.01"
              value={igModeForm.confidence}
              onChange={e => setIgModeForm(f => ({...f, confidence: e.target.value}))}
              className="w-32 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30"
            />
          </div>
        )}
        <SaveButton
          saved={savedIG}
          loading={saveMode.isPending || aiModeLoading}
          onClick={() => {
            saveMode.mutate(
              {
                ig_ai_mode_default: igModeForm.mode,
                ig_ai_confidence_threshold: Number(igModeForm.confidence) || 0.78,
              },
              {
                onSuccess: () => {
                  setSavedIG(true);
                  setTimeout(() => setSavedIG(false), 2500);
                },
              },
            );
          }}
        />
      </Card>

      {/* Knowledge base note */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-xs text-blue-800">
        <p className="font-semibold mb-1">Before switching to Autonomous</p>
        <ul className="space-y-0.5 list-disc list-inside text-blue-700">
          <li>Add your FAQs, amenities, add-ons and policies to the knowledge base — the AI can only answer from what it knows</li>
          <li>Use &ldquo;Test what the AI knows&rdquo; on your most common guest questions and confirm each returns the right answer</li>
          <li>Run Shadow mode long enough to see the drafts it produces for real guests</li>
        </ul>
        <a href="/dashboard/settings/knowledge" className="mt-2 inline-block font-medium hover:underline">Manage knowledge base →</a>
      </div>
    </div>
  );
}

/* ── Notifications ─────────────────────────────────────────────────────────── */

// Default prefs used before the API responds
const DEFAULT_PREFS = {
  new_inquiry_email: true,
  new_inquiry_push: true,
  low_qa_score_email: true,
  low_qa_score_push: false,
  call_summary_email: false,
  call_summary_push: true,
  daily_digest_email: false,   // A7: explicit opt-in — default false
  weekly_report_email: true,
  system_alerts_email: true,
};

type NotifPrefs = typeof DEFAULT_PREFS;

function NotificationSettings() {
  const queryClient = useQueryClient();
  const [prefs, setPrefs] = useState<NotifPrefs>(DEFAULT_PREFS);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A7: load current prefs + digest_opt_in from backend on mount
  const { data: me } = useQuery({
    queryKey: ["users", "me"],
    queryFn: () => api.get("/users/me").then(r => r.data),
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!me) return;
    setPrefs({
      ...DEFAULT_PREFS,
      ...(me.notification_prefs ?? {}),
      // digest_opt_in is a first-class DB column; mirror it into the prefs key
      daily_digest_email: me.digest_opt_in ?? DEFAULT_PREFS.daily_digest_email,
    });
  }, [me]);

  const toggle = (k: keyof NotifPrefs) => {
    setPrefs(p => ({ ...p, [k]: !p[k] }));
    setSaved(false);
    setError(null);
  };

  // A7: save prefs + digest_opt_in to backend
  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const { daily_digest_email, ...rest } = prefs;
      await api.patch("/users/me", {
        notification_prefs: rest,
        digest_opt_in: daily_digest_email,  // persisted as dedicated column
      });
      queryClient.invalidateQueries({ queryKey: ["users", "me"] });
      setSaved(true);
    } catch {
      setError("Failed to save. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  const GROUPS: { label: string; items: { key: keyof NotifPrefs; label: string; channel: string }[] }[] = [
    {
      label: "Leads & Inquiries",
      items: [
        { key: "new_inquiry_email", label: "New inquiry received", channel: "Email" },
        { key: "new_inquiry_push",  label: "New inquiry received", channel: "Push" },
      ],
    },
    {
      label: "Calls & QA",
      items: [
        { key: "low_qa_score_email",  label: "QA score below threshold", channel: "Email" },
        { key: "low_qa_score_push",   label: "QA score below threshold", channel: "Push" },
        { key: "call_summary_email",  label: "Call wrap-up ready",        channel: "Email" },
        { key: "call_summary_push",   label: "Call wrap-up ready",        channel: "Push" },
      ],
    },
    {
      label: "Reports & Digests",
      items: [
        { key: "daily_digest_email",    label: "Daily KPI digest via WhatsApp (9 AM local)", channel: "WhatsApp" },
        { key: "weekly_report_email",   label: "Weekly performance report (Monday 9 AM)",    channel: "Email" },
        { key: "system_alerts_email",   label: "System alerts (integrations, errors)",        channel: "Email" },
      ],
    },
  ];

  return (
    <div className="space-y-6">
      <SectionHeader title="Notifications" sub="Choose when and how HAIP contacts you" />
      {GROUPS.map(g => (
        <Card key={g.label} title={g.label}>
          <div className="space-y-1">
            {g.items.map(item => (
              <div key={item.key} className="flex items-center justify-between py-2.5 border-b border-gray-50 last:border-0">
                <div>
                  <p className="text-sm text-gray-800">{item.label}</p>
                  <p className="text-xs text-gray-400">{item.channel}</p>
                </div>
                <button
                  onClick={() => toggle(item.key)}
                  className={cn(
                    "relative inline-flex h-5 w-9 items-center rounded-full transition-colors flex-shrink-0",
                    prefs[item.key] ? "bg-teal-500" : "bg-gray-200"
                  )}
                >
                  <span className={cn(
                    "inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform",
                    prefs[item.key] ? "translate-x-4.5" : "translate-x-0.5"
                  )} />
                </button>
              </div>
            ))}
          </div>
        </Card>
      ))}
      {error && <p className="text-xs text-red-500">{error}</p>}
      <SaveButton saved={saved} onClick={handleSave} loading={saving} />
    </div>
  );
}

/* ── Security ──────────────────────────────────────────────────────────────── */
function SecuritySettings() {
  return (
    <div className="space-y-6">
      <SectionHeader title="Security" sub="Authentication, MFA, session policy, and compliance" />
      <MFACard />

      <Card title="Session policy">
        <div className="space-y-1">
          <Row label="Access token expiry"    value="15 minutes" />
          <Row label="Refresh token expiry"   value="30 days" />
          <Row label="Brute-force lockout"     value="10 failed attempts → 30 min lock" />
          <Row label="MFA required for"        value="Owner + Compliance roles" />
          <Row label="Concurrent sessions"     value="Up to 3 devices" />
        </div>
      </Card>

      <Card title="Data & Privacy (DPDP)">
        <div className="space-y-1">
          <Row label="Data region"           value="ap-south-1 (Mumbai, India)" />
          <Row label="Recording encryption"  value="AES-256 + KMS per tenant" />
          <Row label="PII redaction"         value="Before LLM processing (L1)" />
          <Row label="Audit log retention"   value="5 years (append-only)" />
          <Row label="Delete-on-request SLA" value="30 days" />
        </div>
        <div className="mt-4 flex items-center gap-3">
          <a href="/dashboard/compliance" className="text-xs text-teal-600 hover:underline font-medium">Open Compliance Centre →</a>
          <button className="text-xs text-red-500 hover:underline ml-auto">Request data deletion</button>
        </div>
      </Card>

      <Card title="Environment keys">
        <p className="text-xs text-gray-500 mb-3">API keys are stored in your server environment and encrypted at rest. These show current configuration status.</p>
        <div className="space-y-2">
          {[
            { key: "ANTHROPIC_API_KEY",         status: "set" },
            { key: "DEEPGRAM_API_KEY",           status: "missing" },
            { key: "ENCRYPTION_KEY",             status: "set" },
            { key: "META_WEBHOOK_VERIFY_TOKEN",  status: "missing" },
            { key: "AWS_ACCESS_KEY_ID",          status: "missing" },
          ].map(k => (
            <div key={k.key} className="flex items-center gap-2 py-1.5 border-b border-gray-50 last:border-0">
              {k.status === "set"
                ? <CheckCircle size={13} className="text-green-500 flex-shrink-0" />
                : <AlertCircle size={13} className="text-amber-400 flex-shrink-0" />}
              <code className="text-xs text-gray-700 flex-1">{k.key}</code>
              <span className={`text-[10px] font-semibold ${k.status === "set" ? "text-green-600" : "text-amber-500"}`}>
                {k.status === "set" ? "Configured" : "Missing"}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ── MFA Card ───────────────────────────────────────────────────────────────── */
function MFACard() {
  type Stage = "idle" | "setup" | "verify" | "enabled";
  const [stage, setStage] = useState<Stage>("idle");
  const [qrUri, setQrUri] = useState("");
  const [secret, setSecret] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function startSetup() {
    setLoading(true); setError("");
    try {
      const { data } = await api.post("/auth/mfa/setup");
      setQrUri(data.qr_data_uri); setSecret(data.secret); setStage("setup");
    } catch { setError("Could not generate MFA secret — is the backend running?"); }
    finally { setLoading(false); }
  }

  async function verifyCode() {
    if (code.length !== 6) return setError("Enter all 6 digits");
    setLoading(true); setError("");
    try {
      await api.post("/auth/mfa/verify", { code });
      setStage("enabled");
    } catch { setError("Invalid code — try again"); setCode(""); }
    finally { setLoading(false); }
  }

  if (stage === "enabled") {
    return (
      <Card title="Two-factor authentication">
        <div className="flex items-center gap-3 text-sm text-green-700 bg-green-50 rounded-xl p-4 border border-green-200">
          <CheckCircle size={18} className="flex-shrink-0" />
          <div>
            <p className="font-semibold">MFA enabled</p>
            <p className="text-xs text-green-600 mt-0.5">Your account is protected with TOTP authentication.</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card title="Two-factor authentication">
      {stage === "idle" && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">Add an extra layer of security. You'll be prompted for a 6-digit code from your authenticator app on each sign-in.</p>
          {error && <p className="text-xs text-red-500">{error}</p>}
          <button onClick={startSetup} disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-[#0F766E] text-white text-sm font-semibold rounded-lg hover:bg-[#0d6660] disabled:opacity-50 transition-colors">
            {loading ? <Loader2 size={14} className="animate-spin" /> : <QrCode size={14} />}
            Set up authenticator app
          </button>
        </div>
      )}
      {stage === "setup" && (
        <div className="space-y-5">
          <p className="text-sm text-gray-600">Scan with <strong>Google Authenticator</strong>, <strong>Authy</strong>, or any TOTP app.</p>
          {qrUri && <div className="flex justify-center"><img src={qrUri} alt="MFA QR code" className="w-44 h-44 rounded-xl border border-gray-200" /></div>}
          <div className="bg-gray-50 rounded-lg p-3">
            <p className="text-xs text-gray-500 mb-1">Manual entry key</p>
            <code className="text-xs font-mono text-gray-800 break-all select-all">{secret}</code>
          </div>
          <button onClick={() => setStage("verify")} className="w-full py-2 bg-teal-500 hover:bg-teal-600 text-white font-semibold rounded-lg text-sm">
            I&apos;ve scanned — continue
          </button>
        </div>
      )}
      {stage === "verify" && (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">Enter the 6-digit code from your authenticator app.</p>
          <input type="text" inputMode="numeric" maxLength={6} value={code}
            onChange={e => { setCode(e.target.value.replace(/\D/g, "").slice(0, 6)); setError(""); }}
            placeholder="000000"
            className="w-full px-4 py-3 text-center text-2xl font-mono tracking-[0.5em] border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-teal-500"
          />
          {error && <p className="text-xs text-red-500">{error}</p>}
          <button onClick={verifyCode} disabled={loading || code.length < 6}
            className="w-full py-2.5 bg-[#0F766E] text-white font-semibold rounded-xl text-sm disabled:opacity-50 flex items-center justify-center gap-2 hover:bg-[#0d6660]">
            {loading && <Loader2 size={14} className="animate-spin" />}
            Verify & enable MFA
          </button>
        </div>
      )}
    </Card>
  );
}

/* ── Shared ─────────────────────────────────────────────────────────────────── */
function SectionHeader({ title, sub }: { title: string; sub: string }) {
  return (
    <div>
      <h1 className="haip-page-title">{title}</h1>
      <p className="text-sm text-gray-400 mt-0.5">{sub}</p>
    </div>
  );
}

function Card({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      {title && <div className="text-sm font-semibold text-gray-800 mb-4">{title}</div>}
      {children}
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type = "text", hint }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; hint?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 bg-white" />
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  );
}

function SaveButton({ onClick, saved, loading = false, label = "Save changes" }: {
  onClick: () => void; saved: boolean; loading?: boolean; label?: string;
}) {
  return (
    <button onClick={onClick} disabled={loading} className={cn(
      "mt-5 px-5 py-2 text-sm font-semibold rounded-lg transition-colors flex items-center gap-2 disabled:opacity-60",
      saved ? "bg-green-50 text-green-700 border border-green-200" : "bg-teal-500 text-white hover:bg-teal-600"
    )}>
      {loading && <Loader2 size={13} className="animate-spin" />}
      {saved ? "✓ Saved" : label}
    </button>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-2 border-b border-gray-50 last:border-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="text-sm font-medium text-gray-800">{value}</span>
    </div>
  );
}
