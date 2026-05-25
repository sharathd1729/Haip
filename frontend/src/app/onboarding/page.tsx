"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import {
  Home, Building2, UmbrellaOff, Globe, HelpCircle,
  Users, ArrowRight, ArrowLeft,
  CheckCircle2, Sparkles, Loader2, X,
  Mic, Zap, Shield, Bell,
  Truck, Key,
} from "lucide-react";

// ─── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 6;

const SEGMENTS = [
  { id: "villa",            icon: <Home size={20} />,        label: "Luxury Villa" },
  { id: "resort",           icon: <UmbrellaOff size={20} />, label: "Resort" },
  { id: "hotel",            icon: <Building2 size={20} />,   label: "Boutique Hotel" },
  { id: "rental_apartment", icon: <Key size={20} />,         label: "Rental / Airbnb" },
  { id: "travel",           icon: <Globe size={20} />,       label: "Travel Operator" },
  { id: "caravan",          icon: <Truck size={20} />,       label: "Caravan / Glamping" },
  { id: "other",            icon: <HelpCircle size={20} />,  label: "Other" },
];

// ─── Shared components ────────────────────────────────────────────────────────

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} className={cn(
          "h-1 rounded-full transition-all duration-300",
          i < current ? "bg-teal-500 w-6" : i === current ? "bg-teal-500/70 w-10" : "bg-white/10 w-6"
        )} />
      ))}
    </div>
  );
}

function SetupLaterButton({ onSkip, label = "Set up later" }: { onSkip: () => void; label?: string }) {
  return (
    <button
      onClick={onSkip}
      className="w-full py-2.5 rounded-2xl border border-white/10 text-white/40 hover:text-white/70 hover:border-white/20 text-xs font-medium transition-all flex items-center justify-center gap-1.5"
    >
      {label} — I&apos;ll finish this from Settings
    </button>
  );
}

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null;
  return <p className="text-xs text-red-400 mt-1 flex items-center gap-1"><X size={10} />{msg}</p>;
}

function BackButton({ onBack }: { onBack: () => void }) {
  return (
    <button onClick={onBack}
      className="flex items-center gap-1.5 text-xs text-white/30 hover:text-white/60 mb-6 transition-colors">
      <ArrowLeft size={14} /> Back
    </button>
  );
}

function ContinueButton({ label = "Continue", disabled = false, loading = false, onClick }: {
  label?: string; disabled?: boolean; loading?: boolean; onClick?: () => void;
}) {
  return (
    <button onClick={onClick} disabled={disabled || loading}
      type={onClick ? "button" : "submit"}
      className="w-full py-3.5 bg-teal-500 hover:bg-teal-400 disabled:opacity-40 text-white font-bold rounded-2xl transition-all flex items-center justify-center gap-2">
      {loading ? <Loader2 size={18} className="animate-spin" /> : null}
      {label} {!loading && <ArrowRight size={18} />}
    </button>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const router = useRouter();
  const { data: session, status, update: updateSession } = useSession();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const clearFieldError = (key: string) => setFieldErrors(e => { const n = { ...e }; delete n[key]; return n; });

  // Step 0 — Brand basics
  const [brandName, setBrandName] = useState("");
  const [brandSlug, setBrandSlug] = useState("");
  const [brandCity, setBrandCity] = useState("");
  const [segment, setSegment] = useState("");

  // Step 1 — Brand voice
  const [brandVoice, setBrandVoice] = useState("");
  const [brandPersonality, setBrandPersonality] = useState("");

  // Step 2 — Team invites
  const [inviteEmails, setInviteEmails] = useState<string[]>([]);
  const [inviteInput, setInviteInput] = useState("");

  // Step 3 — Concierge mode
  const [conciergeMode, setConciergeMode] = useState<"shadow" | "autonomous">("shadow");

  // Step 4 — DPDP consent
  const [dpdpAcknowledged, setDpdpAcknowledged] = useState(false);

  const accessToken = (session as any)?.accessToken;

  // Fetch real step from backend on mount — do NOT trust the stale JWT
  useEffect(() => {
    if (status === "loading") return;
    if (status === "unauthenticated" || !accessToken || accessToken === "demo") {
      router.replace("/login");
      return;
    }
    // Owner-bypass (no real JWT) — use step from JWT directly, skip API call
    if (accessToken === "owner-bypass") {
      const jwtStep = (session?.user as any)?.onboarding_step ?? 0;
      if (jwtStep >= TOTAL_STEPS) router.replace("/dashboard");
      return;
    }
    api.get("/me").then(res => {
      const backendStep: number = res.data?.onboarding_step ?? 0;
      if (backendStep >= TOTAL_STEPS) {
        router.replace("/dashboard");
        return;
      }
      if (backendStep > 0) setStep(backendStep);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, accessToken]);

  const persistStep = useCallback(async (nextStep: number) => {
    try {
      await api.patch("/tenants/me", { config: { onboarding_step: nextStep } });
      await updateSession({ onboarding_step: nextStep });
    } catch { /* non-fatal */ }
  }, [updateSession]);

  const goNext = useCallback(async () => {
    const next = step + 1;
    await persistStep(next);
    if (next >= TOTAL_STEPS) {
      router.replace("/dashboard");
      return;
    }
    setStep(next);
  }, [step, persistStep, router]);

  const goBack = () => setStep(s => Math.max(s - 1, 0));

  const skipStep = async (stepNum: number) => {
    try { await api.patch("/tenants/me", { config: { [`step_${stepNum}_skipped`]: true } }); } catch { /* non-fatal */ }
    const next = stepNum + 1;
    await persistStep(next);
    if (next >= TOTAL_STEPS) { router.replace("/dashboard"); return; }
    setStep(next);
  };

  // ── Step 0 submit ──────────────────────────────────────────────────────────
  const handleBrandSubmit = useCallback(async () => {
    const errs: Record<string, string> = {};
    if (!brandName.trim()) errs.brandName = "Business name is required";
    if (!brandCity.trim()) errs.brandCity = "City is required";
    if (!segment) errs.segment = "Please select your business segment";
    if (Object.keys(errs).length) { setFieldErrors(errs); return; }
    setSaving(true); setError(""); setFieldErrors({});
    try {
      await api.patch("/tenants/me", {
        name: brandName,
        slug: brandSlug || brandName.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        brand_config: { city: brandCity, segment },
      });
      await goNext();
    } catch (err: any) {
      const s = err?.response?.status;
      if (s === 401 || s === 403) {
        await signOut({ callbackUrl: "/login?reason=session_expired" });
        return;
      }
      setError(err?.response?.data?.detail
        ? `Save failed: ${err.response.data.detail}`
        : "Could not save brand details. Please try again.");
    } finally { setSaving(false); }
  }, [brandName, brandSlug, brandCity, segment, goNext]);

  // ── Step 2 submit ──────────────────────────────────────────────────────────
  const handleInviteSubmit = useCallback(async () => {
    if (inviteEmails.length > 0) {
      try { for (const email of inviteEmails) { await api.post("/users", { email, role: "concierge" }); } }
      catch { /* non-fatal */ }
    }
    await goNext();
  }, [inviteEmails, goNext]);

  const addEmail = () => {
    const email = inviteInput.trim().toLowerCase();
    if (email.includes("@") && !inviteEmails.includes(email)) {
      setInviteEmails(prev => [...prev, email]);
      setInviteInput("");
    }
  };
  const removeEmail = (email: string) => setInviteEmails(prev => prev.filter(e => e !== email));

  // ── Finish ─────────────────────────────────────────────────────────────────
  const handleFinish = useCallback(async () => {
    setSaving(true);
    try {
      await api.patch("/tenants/me", { config: { onboarding_complete: true, onboarding_step: 9 } });
      await updateSession({ onboarding_step: 9 });
    } catch { /* non-fatal */ }
    finally { setSaving(false); }
    router.replace("/dashboard");
  }, [router, updateSession]);

  if (status === "unauthenticated") { router.replace("/login"); return null; }

  return (
    <div className="min-h-screen bg-[#0E1210] flex flex-col items-center justify-center p-5">
      {/* Brand */}
      <div className="flex items-center gap-2.5 mb-8">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center text-[#0E1210] font-bold text-sm">H</div>
        <span className="text-white font-bold text-xl tracking-tight">HA<span className="text-teal-400">IP</span></span>
      </div>

      <div className="w-full max-w-xl">
        {/* Progress */}
        <div className="flex items-center justify-between mb-6 px-1">
          <StepIndicator current={step} total={TOTAL_STEPS} />
          <span className="text-xs text-white/30 font-medium">Step {step + 1} of {TOTAL_STEPS}</span>
        </div>

        {/* Error banner */}
        {error && (
          <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400 flex items-start gap-2">
            <X size={14} className="mt-0.5 flex-shrink-0" />
            {error}
            <button onClick={() => setError("")} className="ml-auto text-red-400/50 hover:text-red-400"><X size={12} /></button>
          </div>
        )}

        {/* Card */}
        <div className="bg-[#141B15] rounded-3xl border border-white/8 shadow-2xl shadow-black/40 overflow-hidden">

          {/* ── Step 0: Brand basics ───────────────────────────────────────── */}
          {step === 0 && (
            <div className="p-8">
              <div className="text-center mb-8">
                <Sparkles size={28} className="text-teal-400 mx-auto mb-3" />
                <h1 className="text-2xl font-black text-white mb-2">Welcome to HAIP!</h1>
                <p className="text-white/45 text-sm">Let&apos;s set up your workspace in a few quick steps.</p>
              </div>

              <div className="space-y-5 mb-7">
                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">Business / brand name *</label>
                  <input
                    value={brandName}
                    onChange={e => {
                      setBrandName(e.target.value);
                      setBrandSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
                      clearFieldError("brandName");
                    }}
                    placeholder="Ratha Travels"
                    className={cn(
                      "w-full px-4 py-3 bg-white/5 border rounded-xl text-sm text-white placeholder-white/25 focus:outline-none transition-all",
                      fieldErrors.brandName ? "border-red-500/60" : "border-white/10 focus:border-teal-500/50"
                    )}
                  />
                  <FieldError msg={fieldErrors.brandName} />
                </div>

                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">City / headquarters *</label>
                  <input
                    value={brandCity}
                    onChange={e => { setBrandCity(e.target.value); clearFieldError("brandCity"); }}
                    placeholder="Goa"
                    className={cn(
                      "w-full px-4 py-3 bg-white/5 border rounded-xl text-sm text-white placeholder-white/25 focus:outline-none transition-all",
                      fieldErrors.brandCity ? "border-red-500/60" : "border-white/10 focus:border-teal-500/50"
                    )}
                  />
                  <FieldError msg={fieldErrors.brandCity} />
                </div>

                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-3">Business segment *</label>
                  <div className="grid grid-cols-4 gap-2">
                    {SEGMENTS.map(s => (
                      <button key={s.id} onClick={() => { setSegment(s.id); clearFieldError("segment"); }}
                        className={cn(
                          "flex flex-col items-center p-3 rounded-xl border text-center transition-all",
                          segment === s.id
                            ? "bg-teal-500/15 border-teal-500/40 text-teal-300"
                            : "bg-white/3 border-white/8 text-white/40 hover:bg-white/6 hover:text-white/70"
                        )}>
                        <div className={cn("mb-1", segment === s.id ? "text-teal-400" : "text-white/25")}>{s.icon}</div>
                        <div className="text-[10px] font-bold leading-tight">{s.label}</div>
                      </button>
                    ))}
                  </div>
                  <FieldError msg={fieldErrors.segment} />
                </div>
              </div>

              <ContinueButton
                disabled={!brandName.trim() || !brandCity.trim() || !segment}
                loading={saving}
                onClick={handleBrandSubmit}
              />
            </div>
          )}

          {/* ── Step 1: Brand voice ────────────────────────────────────────── */}
          {step === 1 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center">
                  <Mic size={18} className="text-purple-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">Brand voice & personality</h2>
                  <p className="text-white/40 text-xs">How should your AI concierge speak to guests?</p>
                </div>
              </div>

              <div className="space-y-5 mb-7">
                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">Brand personality (2–3 words)</label>
                  <input value={brandPersonality} onChange={e => setBrandPersonality(e.target.value)}
                    placeholder="e.g. warm, professional, luxurious"
                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">Brand voice guide <span className="text-white/20 font-normal normal-case">(optional)</span></label>
                  <textarea value={brandVoice} onChange={e => setBrandVoice(e.target.value)} rows={4}
                    placeholder="Describe how your team communicates. E.g. 'We speak formally but warmly. We always use the guest's first name.'"
                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all resize-none" />
                </div>
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton onClick={async () => {
                  if (brandPersonality || brandVoice) {
                    await api.patch("/tenants/me", { brand_config: { voice_guide: brandVoice, personality: brandPersonality } }).catch(() => {});
                  }
                  goNext();
                }} />
                <SetupLaterButton onSkip={() => skipStep(1)} />
              </div>
            </div>
          )}

          {/* ── Step 2: Team invites ───────────────────────────────────────── */}
          {step === 2 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center">
                  <Users size={18} className="text-purple-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">Invite your team</h2>
                  <p className="text-white/40 text-xs">Add concierge, reservations, and manager roles</p>
                </div>
              </div>

              <div className="space-y-3 mb-6">
                <div className="flex gap-2">
                  <input type="email" value={inviteInput} onChange={e => setInviteInput(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addEmail(); } }}
                    placeholder="colleague@company.com"
                    className="flex-1 px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
                  <button onClick={addEmail} disabled={!inviteInput.trim()}
                    className="px-4 py-3 bg-teal-500/20 hover:bg-teal-500/30 disabled:opacity-40 text-teal-400 rounded-xl text-sm font-bold transition-all border border-teal-500/20">
                    Add
                  </button>
                </div>
                {inviteEmails.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {inviteEmails.map(email => (
                      <div key={email} className="flex items-center gap-1.5 bg-teal-500/15 border border-teal-500/20 rounded-lg px-2.5 py-1.5">
                        <span className="text-xs text-teal-300">{email}</span>
                        <button onClick={() => removeEmail(email)} className="text-teal-400/50 hover:text-teal-400 transition-colors"><X size={11} /></button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton loading={saving} onClick={handleInviteSubmit}
                  label={inviteEmails.length > 0 ? `Invite ${inviteEmails.length} & Continue` : "Continue"} />
                <SetupLaterButton onSkip={() => skipStep(2)} />
              </div>
            </div>
          )}

          {/* ── Step 3: Concierge mode ─────────────────────────────────────── */}
          {step === 3 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center">
                  <Zap size={18} className="text-teal-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">AI Concierge mode</h2>
                  <p className="text-white/40 text-xs">Choose how the AI replies to guests</p>
                </div>
              </div>

              <div className="space-y-3 mb-7">
                {[
                  { id: "shadow",     color: "teal",  title: "Shadow mode (recommended)", desc: "AI drafts a reply and waits for agent approval before sending. Safe to start with." },
                  { id: "autonomous", color: "amber", title: "Autonomous mode",             desc: "AI sends replies directly when confidence is high (≥78%). Enable after KB is trained." },
                ].map(opt => (
                  <button key={opt.id} onClick={() => setConciergeMode(opt.id as "shadow" | "autonomous")}
                    className={cn(
                      "w-full p-5 rounded-2xl border text-left transition-all",
                      conciergeMode === opt.id
                        ? opt.color === "teal" ? "bg-teal-500/10 border-teal-500/30" : "bg-amber-500/10 border-amber-500/30"
                        : "bg-white/3 border-white/8 hover:bg-white/5"
                    )}>
                    <div className="flex items-start gap-3">
                      <div className={cn("w-4 h-4 rounded-full border-2 flex-shrink-0 mt-0.5 flex items-center justify-center",
                        conciergeMode === opt.id
                          ? opt.color === "teal" ? "border-teal-400" : "border-amber-400"
                          : "border-white/20")}>
                        {conciergeMode === opt.id && (
                          <div className={cn("w-2 h-2 rounded-full", opt.color === "teal" ? "bg-teal-400" : "bg-amber-400")} />
                        )}
                      </div>
                      <div>
                        <div className={cn("font-bold text-sm mb-1",
                          conciergeMode === opt.id
                            ? opt.color === "teal" ? "text-teal-300" : "text-amber-300"
                            : "text-white/70")}>{opt.title}</div>
                        <p className="text-xs text-white/40 leading-relaxed">{opt.desc}</p>
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton onClick={async () => {
                  await api.patch("/tenants/me", { brand_config: { concierge_mode: conciergeMode } }).catch(() => {});
                  goNext();
                }} />
                <SetupLaterButton onSkip={() => skipStep(3)} />
              </div>
            </div>
          )}

          {/* ── Step 4: DPDP compliance ────────────────────────────────────── */}
          {step === 4 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-blue-500/20 border border-blue-500/30 flex items-center justify-center">
                  <Shield size={18} className="text-blue-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">DPDP compliance</h2>
                  <p className="text-white/40 text-xs">India&apos;s Digital Personal Data Protection Act</p>
                </div>
              </div>

              <div className="bg-white/3 border border-white/8 rounded-2xl p-5 mb-6 space-y-4">
                <p className="text-sm text-white/60 leading-relaxed">
                  HAIP processes guest personal data (name, phone, call recordings) on your behalf. As the data fiduciary, you must:
                </p>
                <ul className="space-y-2">
                  {[
                    "Notify guests that calls are recorded for quality purposes",
                    "Honour data deletion requests within 30 days",
                    "Not retain guest data beyond the retention window you configure",
                    "Obtain consent before using data for marketing",
                  ].map(item => (
                    <li key={item} className="flex items-start gap-2.5 text-xs text-white/50">
                      <CheckCircle2 size={14} className="text-teal-400 flex-shrink-0 mt-0.5" />
                      {item}
                    </li>
                  ))}
                </ul>
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" checked={dpdpAcknowledged} onChange={e => setDpdpAcknowledged(e.target.checked)}
                    className="w-4 h-4 mt-0.5 rounded border-white/20 text-teal-500 flex-shrink-0" />
                  <span className="text-xs text-white/60">
                    I acknowledge that I am the data fiduciary for my guests&apos; personal data and will comply with DPDP Act obligations.
                  </span>
                </label>
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton disabled={!dpdpAcknowledged} onClick={async () => {
                  await api.patch("/tenants/me", { brand_config: { dpdp_acknowledged: true } }).catch(() => {});
                  goNext();
                }} label="Acknowledge & Continue" />
                <SetupLaterButton onSkip={() => skipStep(4)} label="Review DPDP later" />
              </div>
            </div>
          )}

          {/* ── Step 5: All set ────────────────────────────────────────────── */}
          {step === 5 && (
            <div className="p-8">
              <div className="text-center mb-8">
                <div className="w-16 h-16 rounded-2xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center mx-auto mb-4">
                  <CheckCircle2 size={32} className="text-teal-400" />
                </div>
                <h2 className="text-2xl font-black text-white mb-2">You&apos;re all set!</h2>
                <p className="text-white/40 text-sm max-w-xs mx-auto">
                  {brandName || "Your workspace"} is ready. Here&apos;s what to do next.
                </p>
              </div>

              <div className="space-y-2 mb-8">
                {[
                  { icon: <Bell size={16} />,  color: "text-teal-400",  label: "Add your properties",         desc: "Go to Settings → Properties to add your villas, hotels, or units" },
                  { icon: <Bell size={16} />,  color: "text-blue-400",  label: "Connect your IVR or WhatsApp", desc: "Go to Settings → Integrations to connect CallerDesk, Acefone, or WhatsApp" },
                  { icon: <Bell size={16} />,  color: "text-amber-400", label: "Invite your team",             desc: "Add concierge and manager accounts from Settings → Team" },
                ].map(item => (
                  <div key={item.label} className="flex items-start gap-3 p-4 bg-white/3 border border-white/6 rounded-2xl">
                    <div className={cn("w-8 h-8 rounded-xl bg-white/5 flex items-center justify-center flex-shrink-0", item.color)}>{item.icon}</div>
                    <div>
                      <div className="text-sm font-semibold text-white/80">{item.label}</div>
                      <div className="text-xs text-white/35 mt-0.5">{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>

              <button onClick={handleFinish} disabled={saving}
                className="w-full py-3.5 bg-teal-500 hover:bg-teal-400 disabled:opacity-60 text-white font-bold rounded-2xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-teal-500/25">
                {saving ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
                {saving ? "Setting up…" : "Go to dashboard"}
              </button>
            </div>
          )}

        </div>

        <p className="text-center text-xs text-white/20 mt-6">
          Already set up?{" "}
          <Link href="/dashboard" className="text-teal-400 hover:text-teal-300">Go to dashboard</Link>
        </p>
      </div>
    </div>
  );
}
