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
          <div key={i} className={`h-1 flex-1 rounded-full transition-colors ${i < score ? colors[score - 1] : "bg-border"}`} />
        ))}
      </div>
      {score > 0 && (
        <p className={`text-xs font-medium ${score === 3 ? "text-teal-500" : score === 2 ? "text-amber-500" : "text-red-500"}`}>
          {labels[score - 1]}
        </p>
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">
        {checks.map(c => (
          <span key={c.label} className={`text-[11px] flex items-center gap-1 ${c.ok ? "text-teal-500" : "text-muted-foreground"}`}>
            <Check size={10} className={c.ok ? "text-teal-500" : "text-muted-foreground/50"} />
            {c.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// Map raw backend error strings → human-readable messages + which field to highlight
function friendlyError(detail: string): { msg: string; field?: string } {
  const d = detail.toLowerCase();
  if (d.includes("slug already taken") || (d.includes("slug") && d.includes("taken")))
    return { msg: "That workspace URL is already in use. Try adding a city or number (e.g. haip-homes-blr).", field: "slug" };
  if (d.includes("email already") || (d.includes("email") && d.includes("exist")))
    return { msg: "An account with this email already exists. Try logging in instead.", field: "email" };
  if (d.includes("invalid email"))
    return { msg: "Please enter a valid work email address.", field: "email" };
  if (d.includes("password") && d.includes("short"))
    return { msg: "Password must be at least 8 characters.", field: "password" };
  if (d.includes("tenant name"))
    return { msg: "Please enter your business or brand name.", field: "tenant_name" };
  return { msg: detail };
}

export default function RegisterPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [showPw, setShowPw] = useState(false);
  const [agreed, setAgreed] = useState(false);
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
    if (!agreed) { setError("Please accept the terms to continue."); setFieldError(undefined); return; }
    if (form.password.length < 8) { setError("Password must be at least 8 characters."); setFieldError("password"); return; }

    setLoading(true);
    setError("");
    setFieldError(undefined);

    try {
      // Normalise base URL — NEXT_PUBLIC_API_URL may already end with /api/v1.
      // Fall back to "" (same-origin) so requests go through the Next.js proxy
      // rewrite (/api/v1/* → backend) when no explicit URL is configured.
      const _rawBase = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
      const _apiBase = _rawBase.endsWith("/api/v1") ? _rawBase.slice(0, -7) : _rawBase;
      const res = await fetch(
        `${_apiBase}/api/v1/auth/register`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: form.name,
            email: form.email,
            password: form.password,
            tenant_name: form.tenant_name,
            tenant_slug: form.tenant_slug,
            consent_transactional: true,
            consent_marketing: consentMarketing,
            consent_analytics: consentAnalytics,
          }),
        }
      );

      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        const raw = typeof d.detail === "string" ? d.detail : "Registration failed. Please try again.";
        const { msg, field } = friendlyError(raw);
        setError(msg);
        setFieldError(field);
        return;
      }

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
      {/* ── Left panel: always-dark brand ── */}
      <div className="hidden lg:flex lg:w-[44%] flex-col justify-between bg-[#0a1422] p-12 relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-[-100px] right-[-100px] w-[400px] h-[400px] rounded-full bg-teal-500/10 blur-3xl" />
          <div className="absolute bottom-[-80px] left-[-80px] w-[300px] h-[300px] rounded-full bg-blue-500/8 blur-3xl" />
        </div>

        <div className="relative">
          <Link href="/" className="inline-flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-xl bg-[#C8964A] flex items-center justify-center text-[#0a1422] font-bold text-lg shadow-lg shadow-[#C8964A]/30">
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
            <div className="flex items-center gap-4 flex-wrap">
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

      {/* ── Right panel: theme-adaptive form ── */}
      <div className="flex-1 flex flex-col items-center justify-center bg-background px-6 py-12 overflow-y-auto">
        <div className="lg:hidden mb-8">
          <Link href="/" className="inline-flex items-center gap-2">
            <div className="w-10 h-10 rounded-xl bg-[#C8964A] flex items-center justify-center text-[#0a1422] font-bold text-lg">
              H
            </div>
            <span className="text-foreground font-bold text-xl tracking-tight">HAIP</span>
          </Link>
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-7">
            <h2 className="text-2xl font-bold text-foreground mb-1">Create your account</h2>
            <p className="text-muted-foreground text-sm">Start your 14-day free trial — no card required</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Full name</label>
              <input
                type="text"
                required
                autoComplete="name"
                value={form.name}
                onChange={e => set("name", e.target.value)}
                placeholder="Sharath D."
                className="w-full px-4 py-3 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                suppressHydrationWarning
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Work email</label>
              <input
                type="email"
                required
                autoComplete="email"
                value={form.email}
                onChange={e => { set("email", e.target.value); if (fieldError === "email") setFieldError(undefined); }}
                placeholder="you@company.com"
                className={`w-full px-4 py-3 border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:border-transparent transition-shadow ${fieldError === "email" ? "border-red-400 focus:ring-red-400" : "border-border focus:ring-teal-500"}`}
                suppressHydrationWarning
              />
              {fieldError === "email" && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Password</label>
              <div className="relative">
                <input
                  type={showPw ? "text" : "password"}
                  required
                  autoComplete="new-password"
                  value={form.password}
                  onChange={e => set("password", e.target.value)}
                  placeholder="Min. 8 characters"
                  className="w-full px-4 py-3 pr-11 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                  suppressHydrationWarning
                />
                <button
                  type="button"
                  onClick={() => setShowPw(v => !v)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <PasswordStrength password={form.password} />
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Business / brand name</label>
              <input
                type="text"
                required
                value={form.tenant_name}
                onChange={e => { handleTenantName(e.target.value); if (fieldError === "slug") setFieldError(undefined); }}
                placeholder="Ratha Travels"
                className="w-full px-4 py-3 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                suppressHydrationWarning
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Workspace URL</label>
              <div className={`flex items-center border rounded-xl overflow-hidden bg-background focus-within:ring-2 focus-within:border-transparent transition-shadow ${fieldError === "slug" ? "border-red-400 focus-within:ring-red-400" : "border-border focus-within:ring-teal-500"}`}>
                <span className="px-3 py-3 bg-muted text-muted-foreground text-sm border-r border-border whitespace-nowrap select-none">
                  genhaip.com/
                </span>
                <input
                  value={form.tenant_slug}
                  onChange={e => { set("tenant_slug", e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")); if (fieldError === "slug") setFieldError(undefined); }}
                  placeholder="ratha-travels"
                  required
                  className="flex-1 px-3 py-3 text-sm focus:outline-none bg-transparent text-foreground placeholder:text-muted-foreground"
                  suppressHydrationWarning
                />
              </div>
              {fieldError === "slug" && (
                <p className="mt-1.5 text-xs text-red-400">{error}</p>
              )}
            </div>

            {/* DPDP consents */}
            <div className="space-y-2.5 pt-1 border-t border-border">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider pt-1">Data usage consents</p>

              <div className="flex items-start gap-2.5">
                <input
                  id="agree"
                  type="checkbox"
                  checked={agreed}
                  onChange={e => setAgreed(e.target.checked)}
                  className="w-4 h-4 rounded border-border text-teal-500 focus:ring-teal-500 cursor-pointer mt-0.5 flex-shrink-0 accent-teal-500"
                />
                <label htmlFor="agree" className="text-xs text-muted-foreground cursor-pointer leading-relaxed">
                  <span className="font-semibold text-foreground">Service communications</span>{" "}
                  <span className="text-red-400 font-semibold text-[10px]">required</span>
                  <span className="block text-muted-foreground/70 mt-0.5">Account notifications, billing, security alerts. Required to use HAIP.</span>
                  {" "}
                  <Link href="/terms" target="_blank" className="text-teal-500 hover:underline font-medium">Terms</Link>
                  {" "}·{" "}
                  <Link href="/privacy" target="_blank" className="text-teal-500 hover:underline font-medium">Privacy Policy</Link>
                </label>
              </div>

              <div className="flex items-start gap-2.5">
                <input
                  id="consent-marketing"
                  type="checkbox"
                  checked={consentMarketing}
                  onChange={e => setConsentMarketing(e.target.checked)}
                  className="w-4 h-4 rounded border-border text-teal-500 focus:ring-teal-500 cursor-pointer mt-0.5 flex-shrink-0 accent-teal-500"
                />
                <label htmlFor="consent-marketing" className="text-xs text-muted-foreground cursor-pointer leading-relaxed">
                  <span className="font-semibold text-foreground">Marketing communications</span>{" "}
                  <span className="text-muted-foreground/50 text-[10px]">optional</span>
                  <span className="block text-muted-foreground/70 mt-0.5">Product updates, tips, and offers from HAIP. You can unsubscribe anytime.</span>
                </label>
              </div>

              <div className="flex items-start gap-2.5">
                <input
                  id="consent-analytics"
                  type="checkbox"
                  checked={consentAnalytics}
                  onChange={e => setConsentAnalytics(e.target.checked)}
                  className="w-4 h-4 rounded border-border text-teal-500 focus:ring-teal-500 cursor-pointer mt-0.5 flex-shrink-0 accent-teal-500"
                />
                <label htmlFor="consent-analytics" className="text-xs text-muted-foreground cursor-pointer leading-relaxed">
                  <span className="font-semibold text-foreground">Product analytics</span>{" "}
                  <span className="text-muted-foreground/50 text-[10px]">optional</span>
                  <span className="block text-muted-foreground/70 mt-0.5">Help us improve HAIP by sharing anonymous usage data.</span>
                </label>
              </div>
            </div>

            {error && !fieldError && (
              <div className="p-3.5 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !agreed}
              className="w-full py-3 bg-teal-600 hover:bg-teal-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2 shadow-sm mt-2"
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

          <div className="mt-6 pt-6 border-t border-border text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="text-teal-500 font-semibold hover:text-teal-400 transition-colors">
              Sign in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
