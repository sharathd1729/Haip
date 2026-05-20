"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import Link from "next/link";
import { Eye, EyeOff, ArrowRight, Check } from "lucide-react";

const PERKS = [
  "14-day free trial, no credit card required",
  "AI call answering live in under 10 minutes",
  "WhatsApp inbox + call intelligence in one platform",
];

function PasswordStrength({ password }: { password: string }) {
  const checks = [
    { label: "8+ characters", ok: password.length >= 8 },
    { label: "Uppercase letter", ok: /[A-Z]/.test(password) },
    { label: "Number or symbol", ok: /[0-9!@#$%^&*]/.test(password) },
  ];
  if (!password) return null;
  const score = checks.filter(c => c.ok).length;
  const colors = ["bg-red-400", "bg-amber-400", "bg-teal-500"];
  const labels = ["Weak", "Fair", "Strong"];

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex gap-1">
        {[0, 1, 2].map(i => (
          <div key={i} className={`h-1 flex-1 rounded-full transition-colors ${i < score ? colors[score - 1] : "bg-gray-100"}`} />
        ))}
      </div>
      {score > 0 && (
        <p className={`text-xs font-medium ${score === 3 ? "text-teal-600" : score === 2 ? "text-amber-600" : "text-red-500"}`}>
          {labels[score - 1]}
        </p>
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">
        {checks.map(c => (
          <span key={c.label} className={`text-[11px] flex items-center gap-1 ${c.ok ? "text-teal-600" : "text-gray-400"}`}>
            <Check size={10} className={c.ok ? "text-teal-500" : "text-gray-300"} />
            {c.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function RegisterPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [agreed, setAgreed] = useState(false);
  // O8 — granular DPDP consents (default off per DPDP-correct posture)
  const [consentMarketing, setConsentMarketing] = useState(false);
  const [consentAnalytics, setConsentAnalytics] = useState(false);
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    tenant_name: "",
    tenant_slug: "",
  });

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  const handleTenantName = (v: string) => {
    set("tenant_name", v);
    set("tenant_slug", v.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agreed) { setError("Please accept the terms to continue."); return; }
    if (form.password.length < 8) { setError("Password must be at least 8 characters."); return; }

    setLoading(true);
    setError("");

    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/auth/register`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: form.name,
            email: form.email,
            password: form.password,
            tenant_name: form.tenant_name,
            tenant_slug: form.tenant_slug,
            // O8 — per-purpose consents
            consent_transactional: true,
            consent_marketing: consentMarketing,
            consent_analytics: consentAnalytics,
          }),
        }
      );

      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d.detail ?? "Registration failed. Please try again.");
        return;
      }

      // Auto sign-in so NextAuth session is established with real JWT
      const result = await signIn("credentials", {
        redirect: false,
        email: form.email,
        password: form.password,
      });
      if (result?.error) {
        setError("Account created but sign-in failed. Please log in manually.");
        router.push("/login");
        return;
      }
      router.push("/onboarding");
    } catch {
      setError("Could not reach the server. Please check your connection.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* ── Left panel: perks ── */}
      <div className="hidden lg:flex lg:w-[44%] flex-col justify-between bg-[#0B1F3A] p-12 relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-[-100px] right-[-100px] w-[400px] h-[400px] rounded-full bg-teal-500/10 blur-3xl" />
          <div className="absolute bottom-[-80px] left-[-80px] w-[300px] h-[300px] rounded-full bg-blue-500/8 blur-3xl" />
        </div>

        <div className="relative">
          <Link href="/" className="inline-flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-xl bg-teal-500 flex items-center justify-center text-[#0B1F3A] font-bold text-lg shadow-lg shadow-teal-500/30">
              H
            </div>
            <span className="text-white font-bold text-xl tracking-tight">HAIP</span>
          </Link>
        </div>

        <div className="relative space-y-8">
          <div>
            <div className="inline-block px-3 py-1 rounded-full bg-teal-500/10 border border-teal-500/20 text-teal-400 text-xs font-semibold mb-4">
              14-day free trial
            </div>
            <h1 className="text-3xl font-bold text-white leading-tight mb-3">
              Set up your hospitality<br />AI in minutes
            </h1>
            <p className="text-blue-200/70 text-base leading-relaxed">
              No complex setup. No sales calls. Connect WhatsApp and IVR, and your AI goes live.
            </p>
          </div>

          <div className="space-y-3">
            {PERKS.map(p => (
              <div key={p} className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-teal-500/20 border border-teal-500/30 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={11} className="text-teal-400" />
                </div>
                <span className="text-blue-100/80 text-sm">{p}</span>
              </div>
            ))}
          </div>

          <div>
            <p className="text-blue-300/50 text-xs mb-3 uppercase tracking-wide font-semibold">Trusted by hospitality teams</p>
            <div className="flex items-center gap-4">
              {["Ratha Travels", "Jade Resorts", "Amara Villas"].map(name => (
                <div key={name} className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10">
                  <span className="text-white/60 text-xs font-medium">{name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="relative text-blue-300/40 text-xs">
          © {new Date().getFullYear()} HAIP Technologies Pvt. Ltd.
        </div>
      </div>

      {/* ── Right panel: form ── */}
      <div className="flex-1 flex flex-col items-center justify-center bg-gray-50 px-6 py-12 overflow-y-auto">
        <div className="lg:hidden mb-8">
          <Link href="/" className="inline-flex items-center gap-2">
            <div className="w-9 h-9 rounded-xl bg-teal-500 flex items-center justify-center text-[#0B1F3A] font-bold text-base">H</div>
            <span className="text-[#0B1F3A] font-bold text-xl tracking-tight">HAIP</span>
          </Link>
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-7">
            <h2 className="text-2xl font-bold text-gray-900 mb-1">Create your account</h2>
            <p className="text-gray-500 text-sm">Start your 14-day free trial — no card required</p>
          </div>

          {error && (
            <div className="mb-5 p-3.5 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Full name</label>
              <input
                type="text"
                required
                autoComplete="name"
                value={form.name}
                onChange={e => set("name", e.target.value)}
                placeholder="Sharath D."
                className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                suppressHydrationWarning
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Work email</label>
              <input
                type="email"
                required
                autoComplete="email"
                value={form.email}
                onChange={e => set("email", e.target.value)}
                placeholder="you@company.com"
                className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                suppressHydrationWarning
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Password</label>
              <div className="relative">
                <input
                  type={showPw ? "text" : "password"}
                  required
                  autoComplete="new-password"
                  value={form.password}
                  onChange={e => set("password", e.target.value)}
                  placeholder="Min. 8 characters"
                  className="w-full px-4 py-3 pr-11 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                  suppressHydrationWarning
                />
                <button
                  type="button"
                  onClick={() => setShowPw(v => !v)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                >
                  {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <PasswordStrength password={form.password} />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Business / brand name</label>
              <input
                type="text"
                required
                value={form.tenant_name}
                onChange={e => handleTenantName(e.target.value)}
                placeholder="Ratha Travels"
                className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                suppressHydrationWarning
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Workspace URL</label>
              <div className="flex items-center border border-gray-200 rounded-xl overflow-hidden bg-white focus-within:ring-2 focus-within:ring-teal-500 focus-within:border-transparent transition-shadow">
                <span className="px-3 py-3 bg-gray-50 text-gray-400 text-sm border-r border-gray-200 whitespace-nowrap select-none">
                  haip.app/
                </span>
                <input
                  value={form.tenant_slug}
                  onChange={e => set("tenant_slug", e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                  placeholder="ratha-travels"
                  required
                  className="flex-1 px-3 py-3 text-sm focus:outline-none bg-transparent"
                  suppressHydrationWarning
                />
              </div>
            </div>

            {/* O8 — Granular DPDP consents (DPDP-correct: separate checkboxes, default-off) */}
            <div className="space-y-2.5 pt-1 border-t border-gray-100">
              <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider pt-1">Data usage consents</p>

              {/* Transactional — required */}
              <div className="flex items-start gap-2.5">
                <input
                  id="agree"
                  type="checkbox"
                  checked={agreed}
                  onChange={e => setAgreed(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 text-teal-500 focus:ring-teal-500 cursor-pointer mt-0.5 flex-shrink-0"
                />
                <label htmlFor="agree" className="text-xs text-gray-600 cursor-pointer leading-relaxed">
                  <span className="font-semibold text-gray-800">Service communications</span>{" "}
                  <span className="text-red-500 font-semibold text-[10px]">required</span>
                  <span className="block text-gray-400 mt-0.5">Account notifications, billing, security alerts. Required to use HAIP.</span>
                  {" "}
                  <Link href="/terms" target="_blank" className="text-teal-600 hover:underline font-medium">Terms</Link>
                  {" "}·{" "}
                  <Link href="/privacy" target="_blank" className="text-teal-600 hover:underline font-medium">Privacy Policy</Link>
                </label>
              </div>

              {/* Marketing — optional, default off */}
              <div className="flex items-start gap-2.5">
                <input
                  id="consent-marketing"
                  type="checkbox"
                  checked={consentMarketing}
                  onChange={e => setConsentMarketing(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 text-teal-500 focus:ring-teal-500 cursor-pointer mt-0.5 flex-shrink-0"
                />
                <label htmlFor="consent-marketing" className="text-xs text-gray-600 cursor-pointer leading-relaxed">
                  <span className="font-semibold text-gray-800">Marketing communications</span>{" "}
                  <span className="text-gray-400 text-[10px]">optional</span>
                  <span className="block text-gray-400 mt-0.5">Product updates, tips, and offers from HAIP. You can unsubscribe anytime.</span>
                </label>
              </div>

              {/* Analytics — optional, default off */}
              <div className="flex items-start gap-2.5">
                <input
                  id="consent-analytics"
                  type="checkbox"
                  checked={consentAnalytics}
                  onChange={e => setConsentAnalytics(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 text-teal-500 focus:ring-teal-500 cursor-pointer mt-0.5 flex-shrink-0"
                />
                <label htmlFor="consent-analytics" className="text-xs text-gray-600 cursor-pointer leading-relaxed">
                  <span className="font-semibold text-gray-800">Product analytics</span>{" "}
                  <span className="text-gray-400 text-[10px]">optional</span>
                  <span className="block text-gray-400 mt-0.5">Help us improve HAIP by sharing anonymous usage data.</span>
                </label>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading || !agreed}
              className="w-full py-3 bg-teal-500 hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2 shadow-sm shadow-teal-200 mt-2"
            >
              {loading ? (
                <>
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Creating your account…
                </>
              ) : (
                <>Create account <ArrowRight size={15} /></>
              )}
            </button>
          </form>

          <div className="mt-6 pt-6 border-t border-gray-100 text-center text-sm text-gray-500">
            Already have an account?{" "}
            <Link href="/login" className="text-teal-600 font-semibold hover:text-teal-700 transition-colors">
              Sign in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
