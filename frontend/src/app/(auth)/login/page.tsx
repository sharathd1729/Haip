"use client";
import { useState, useEffect, Suspense } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff, ArrowRight, Zap, Shield, BarChart3, Phone, MessageSquare } from "lucide-react";
import api from "@/lib/api";

const SELLING_POINTS = [
  { icon: Zap, text: "AI answers every missed call, 24/7" },
  { icon: BarChart3, text: "Revenue insights from call transcripts" },
  { icon: Shield, text: "DPDP-compliant guest data handling" },
];

// Inner component — uses useSearchParams, must be inside <Suspense>
function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();

  // Email+password
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [remember, setRemember] = useState(true);

  // Phone+OTP
  const [loginMode, setLoginMode] = useState<"email" | "phone">("email");
  const [phone, setPhone] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("");
  const [otpExpiry, setOtpExpiry] = useState(0); // seconds remaining

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");

  // MFA challenge step (shown when the account has TOTP enabled)
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaToken, setMfaToken] = useState("");
  const [mfaCode, setMfaCode] = useState("");

  useEffect(() => {
    if (params.get("registered") === "1") {
      setSuccessMsg("Account created! Please sign in to continue.");
    }
  }, [params]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const data = await api.post("/auth/login", { email, password }).then(r => r.data);
      if (data.mfa_required) {
        setMfaToken(data.mfa_token);
        setMfaRequired(true);
        setLoading(false);
        return;
      }
      const res = await signIn("credentials", {
        preAuthAccessToken: data.access_token,
        preAuthRefreshToken: data.refresh_token,
        remember: remember ? "1" : "0",
        redirect: false,
      });
      setLoading(false);
      if (res?.error) {
        setError("Sign-in failed. Please try again.");
      } else {
        router.push("/dashboard");
      }
    } catch (err: unknown) {
      const e = err as { response?: { status?: number; data?: { detail?: string } } };
      if (e?.response?.status === 401) {
        setError("Invalid email or password. Please try again.");
        setLoading(false);
        return;
      }
      // Backend unreachable — fall back to the legacy authorize() path,
      // which still allows the dev-only demo bypass when applicable.
      const res = await signIn("credentials", { email, password, remember: remember ? "1" : "0", redirect: false });
      setLoading(false);
      if (res?.error) {
        setError("Invalid email or password. Please try again.");
      } else {
        router.push("/dashboard");
      }
    }
  };

  const handleVerifyMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api
        .post("/auth/mfa/verify", { code: mfaCode }, { headers: { Authorization: `Bearer ${mfaToken}` } })
        .then(r => r.data);
      const res = await signIn("credentials", {
        preAuthAccessToken: data.access_token,
        preAuthRefreshToken: data.refresh_token,
        remember: remember ? "1" : "0",
        redirect: false,
      });
      setLoading(false);
      if (res?.error) {
        setError("Sign-in failed. Please try again.");
      } else {
        router.push("/dashboard");
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e?.response?.data?.detail || "Invalid code. Please try again.");
      setLoading(false);
    }
  };

  const handleSendOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.post("/auth/otp/send", { phone }).then(r => r.data);
      setOtpSent(true);
      setOtpExpiry(data.expires_in ?? 300);
      const timer = setInterval(() => setOtpExpiry(t => {
        if (t <= 1) { clearInterval(timer); return 0; }
        return t - 1;
      }), 1000);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e?.response?.data?.detail || "Failed to send OTP. Check your phone number.");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.post("/auth/otp/verify", { phone, code: otp }).then(r => r.data);
      const res = await signIn("credentials", {
        preAuthAccessToken: data.access_token,
        preAuthRefreshToken: data.refresh_token,
        remember: remember ? "1" : "0",
        redirect: false,
      });
      if (res?.error) {
        setError("Sign-in failed. Please try again.");
        return;
      }
      router.push("/dashboard");
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e?.response?.data?.detail || "Invalid OTP. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-sm">
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-foreground mb-1">Welcome back</h2>
        <p className="text-muted-foreground text-sm">Sign in to your workspace</p>
      </div>

      {/* Login mode toggle */}
      <div className="flex gap-1 p-1 bg-muted rounded-xl mb-6">
        <button
          type="button"
          onClick={() => { setLoginMode("email"); setError(""); setOtpSent(false); }}
          className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium transition-all ${
            loginMode === "email"
              ? "bg-card shadow-sm text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Eye size={13} /> Email
        </button>
        <button
          type="button"
          onClick={() => { setLoginMode("phone"); setError(""); }}
          className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium transition-all ${
            loginMode === "phone"
              ? "bg-card shadow-sm text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <MessageSquare size={13} /> WhatsApp OTP
        </button>
      </div>

      {successMsg && (
        <div className="mb-5 p-3.5 bg-teal-500/10 border border-teal-500/30 rounded-xl text-teal-400 text-sm flex items-start gap-2">
          <svg className="w-4 h-4 mt-0.5 flex-shrink-0 fill-teal-400" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd" />
          </svg>
          {successMsg}
        </div>
      )}

      {error && (
        <div className="mb-5 p-3.5 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* ── MFA challenge step ── */}
      {mfaRequired && (
        <form onSubmit={handleVerifyMfa} className="space-y-4">
          <div className="p-4 bg-teal-500/10 border border-teal-500/30 rounded-xl text-sm text-teal-400 text-center">
            <Shield size={18} className="mx-auto mb-1.5" />
            Enter the 6-digit code from your authenticator app.
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">Authentication code</label>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              required
              autoFocus
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              className="w-full px-4 py-3 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow text-center tracking-widest text-xl font-mono"
              placeholder="______"
            />
          </div>
          <button
            type="submit"
            disabled={loading || mfaCode.length !== 6}
            className="w-full py-3 bg-teal-600 hover:bg-teal-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2 shadow-sm"
          >
            {loading ? "Verifying…" : <>Verify <ArrowRight size={15} /></>}
          </button>
          <button
            type="button"
            onClick={() => { setMfaRequired(false); setMfaCode(""); setMfaToken(""); setError(""); }}
            className="w-full text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            ← Back to sign in
          </button>
        </form>
      )}

      {/* ── Email + password form ── */}
      {!mfaRequired && loginMode === "email" && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">
              Email address
            </label>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-3 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
              placeholder="you@company.com"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-sm font-medium text-foreground">Password</label>
              <Link href="/forgot-password" className="text-xs text-teal-500 hover:text-teal-400 font-medium">
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <input
                type={showPw ? "text" : "password"}
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 pr-11 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPw(v => !v)}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
              >
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <input
              id="remember"
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="w-4 h-4 rounded border-border text-teal-500 focus:ring-teal-500 cursor-pointer accent-teal-500"
            />
            <label htmlFor="remember" className="text-sm text-muted-foreground cursor-pointer select-none">
              Keep me signed in
            </label>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-teal-600 hover:bg-teal-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2 shadow-sm"
          >
            {loading ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Signing in…
              </>
            ) : (
              <>Sign in <ArrowRight size={15} /></>
            )}
          </button>
        </form>
      )}

      {/* ── Phone + OTP form ── */}
      {loginMode === "phone" && (
        <div className="space-y-4">
          {!otpSent ? (
            <form onSubmit={handleSendOtp} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">
                  WhatsApp number
                </label>
                <div className="relative">
                  <Phone size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="tel"
                    required
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="w-full pl-10 pr-4 py-3 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow"
                    placeholder="+91 98765 43210"
                  />
                </div>
                <p className="text-[11px] text-muted-foreground mt-1.5">
                  Enter your number in international format. OTP will be sent via WhatsApp.
                </p>
              </div>

              <button
                type="submit"
                disabled={loading || !phone}
                className="w-full py-3 bg-green-600 hover:bg-green-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2 shadow-sm"
              >
                {loading ? (
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : <MessageSquare size={14} />}
                {loading ? "Sending OTP…" : "Send OTP via WhatsApp"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleVerifyOtp} className="space-y-4">
              <div className="p-4 bg-green-500/10 border border-green-500/30 rounded-xl text-sm text-green-400 text-center">
                <MessageSquare size={18} className="mx-auto mb-1.5 text-green-400" />
                OTP sent to <strong>{phone}</strong> via WhatsApp.
                {otpExpiry > 0 && (
                  <span className="block text-xs text-green-500/70 mt-0.5">
                    Expires in {Math.floor(otpExpiry / 60)}:{String(otpExpiry % 60).padStart(2, "0")}
                  </span>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">
                  Enter 6-digit OTP
                </label>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  autoFocus
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  className="w-full px-4 py-3 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow text-center tracking-widest text-xl font-mono"
                  placeholder="______"
                />
              </div>

              <button
                type="submit"
                disabled={loading || otp.length !== 6}
                className="w-full py-3 bg-teal-600 hover:bg-teal-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2 shadow-sm"
              >
                {loading ? (
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : null}
                {loading ? "Verifying…" : <>Verify OTP <ArrowRight size={15} /></>}
              </button>

              <button
                type="button"
                disabled={otpExpiry > 0 && loading}
                onClick={() => { setOtpSent(false); setOtp(""); setError(""); }}
                className="w-full text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                ← Change number or resend OTP
              </button>
            </form>
          )}
        </div>
      )}

      <div className="mt-6 pt-6 border-t border-border text-center text-sm text-muted-foreground">
        Don&apos;t have an account?{" "}
        <Link href="/register" className="text-teal-500 font-semibold hover:text-teal-400 transition-colors">
          Start free trial
        </Link>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-screen flex">
      {/* ── Left panel: always-dark brand marketing ── */}
      <div className="hidden lg:flex lg:w-[52%] flex-col justify-between bg-[#0a1422] p-12 relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-[-80px] right-[-80px] w-[360px] h-[360px] rounded-full bg-teal-500/10 blur-3xl" />
          <div className="absolute bottom-[-60px] left-[-60px] w-[280px] h-[280px] rounded-full bg-blue-500/10 blur-3xl" />
        </div>

        <div className="relative">
          <Link href="/" className="inline-flex items-center">
            <div className="bg-white rounded-xl px-2.5 py-1 inline-flex items-center">
              <img src="/logo.png" alt="HAIP" className="h-7 w-auto object-contain" />
            </div>
          </Link>
        </div>

        <div className="relative space-y-10">
          <div>
            <h1 className="text-4xl font-bold text-white leading-tight mb-4">
              Your hospitality team,<br />
              <span className="text-teal-400">supercharged by AI</span>
            </h1>
            <p className="text-blue-200/80 text-lg leading-relaxed max-w-sm">
              Every call answered, every guest remembered, every opportunity captured — automatically.
            </p>
          </div>

          <div className="space-y-4">
            {SELLING_POINTS.map(({ icon: Icon, text }) => (
              <div key={text} className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0">
                  <Icon size={15} className="text-teal-400" />
                </div>
                <span className="text-blue-100/80 text-sm">{text}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="relative">
          <div className="bg-white/5 border border-white/10 rounded-xl p-5 max-w-sm">
            <div className="flex items-center gap-1 mb-3">
              {[...Array(5)].map((_, i) => (
                <svg key={i} className="w-4 h-4 fill-amber-400" viewBox="0 0 20 20">
                  <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                </svg>
              ))}
            </div>
            <p className="text-white/80 text-sm leading-relaxed italic mb-3">
              &ldquo;HAIP cut our missed-call rate to zero. The AI handles guest queries before we even wake up.&rdquo;
            </p>
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-full bg-teal-500/20 border border-teal-500/30 flex items-center justify-center text-teal-300 text-xs font-bold">
                RK
              </div>
              <div>
                <p className="text-white text-xs font-semibold">Rahul K.</p>
                <p className="text-blue-300/60 text-xs">Villa manager, Goa</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Right panel: theme-adaptive form ── */}
      <div className="flex-1 flex flex-col items-center justify-center bg-background px-6 py-12">
        {/* Mobile logo */}
        <div className="lg:hidden mb-8">
          <Link href="/" className="inline-flex items-center">
            <img src="/logo.png" alt="HAIP" className="h-10 w-auto object-contain" />
          </Link>
        </div>

        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>

        <p className="mt-auto pt-12 text-xs text-muted-foreground text-center">
          © {new Date().getFullYear()} HAIP Technologies Pvt. Ltd. ·{" "}
          <Link href="/privacy" className="hover:text-foreground transition-colors">Privacy</Link>
          {" · "}
          <Link href="/terms" className="hover:text-foreground transition-colors">Terms</Link>
        </p>
      </div>
    </div>
  );
}
