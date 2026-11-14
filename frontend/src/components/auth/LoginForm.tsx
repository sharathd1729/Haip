"use client";
// The email + password sign-in form (with the MFA step), shared by HAIP's /login and Yaad's /yaad/login. Branding comes
// in as props; the sign-in logic is the same for both.
import { useState, useEffect } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff, ArrowRight, Shield } from "@/lib/icons";
import api, { clearTokenCache } from "@/lib/api";

// Only same-origin paths: an absolute or protocol-relative callbackUrl
// ("https://evil.example", "//evil.example") would make login an open
// redirector.
function safeCallback(raw: string | null, fallback: string): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  return raw;
}

export interface LoginBrand {
  title: string;
  subtitle: string;
  signupPrompt: string;
  signupLabel: string;
  signupHref: string;
  defaultCallback: string;   // where to go when no (safe) callbackUrl was given
}

export const HAIP_LOGIN: LoginBrand = {
  title: "Welcome back", subtitle: "Sign in to your workspace", signupPrompt: "Don't have an account?",
  signupLabel: "Start free trial", signupHref: "/register", defaultCallback: "/dashboard",
};

// Uses useSearchParams, so it must be rendered inside <Suspense>.
export function LoginForm({ brand = HAIP_LOGIN }: { brand?: LoginBrand }) {
  const router = useRouter();
  const params = useSearchParams();
  // Set by middleware when a protected page (e.g. the AI-assistant consent
  // screen) bounced a logged-out user here.
  const callbackUrl = safeCallback(params.get("callbackUrl"), brand.defaultCallback);

  // Email+password
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [remember, setRemember] = useState(true);

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
        clearTokenCache();   // never show the previous account's cached data
        router.push(callbackUrl);
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
        clearTokenCache();   // never show the previous account's cached data
        router.push(callbackUrl);
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
        clearTokenCache();   // never show the previous account's cached data
        router.push(callbackUrl);
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e?.response?.data?.detail || "Invalid code. Please try again.");
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-sm">
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-foreground mb-1">{brand.title}</h2>
        <p className="text-muted-foreground text-sm">{brand.subtitle}</p>
      </div>

      {successMsg && (
        <div className="mb-5 p-3.5 bg-primary/10 border border-primary/30 rounded-xl text-primary text-sm flex items-start gap-2">
          <svg className="w-4 h-4 mt-0.5 flex-shrink-0 fill-primary" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd" />
          </svg>
          {successMsg}
        </div>
      )}

      {error && (
        <div className="mb-5 p-3.5 bg-[var(--haip-status-danger-fg)]/10 border border-[var(--haip-status-danger-fg)]/30 rounded-xl text-[var(--haip-status-danger-fg)] text-sm">
          {error}
        </div>
      )}

      {/* ── MFA challenge step ── */}
      {mfaRequired && (
        <form onSubmit={handleVerifyMfa} className="space-y-4">
          <div className="p-4 bg-primary/10 border border-primary/30 rounded-xl text-sm text-primary text-center">
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
              className="w-full px-4 py-3 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow text-center tracking-widest text-xl font-mono"
              placeholder="______"
            />
          </div>
          <button
            type="submit"
            disabled={loading || mfaCode.length !== 6}
            className="w-full py-3 bg-primary hover:bg-primary disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2 shadow-sm"
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
      {!mfaRequired && (
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
              className="w-full px-4 py-3 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow"
              placeholder="you@company.com"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-sm font-medium text-foreground">Password</label>
              <Link href="/forgot-password" className="text-xs text-primary hover:text-primary font-medium">
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
                className="w-full px-4 py-3 pr-11 border border-border rounded-xl text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow"
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
              className="w-4 h-4 rounded border-border text-primary focus:ring-primary cursor-pointer accent-primary"
            />
            <label htmlFor="remember" className="text-sm text-muted-foreground cursor-pointer select-none">
              Keep me signed in
            </label>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-primary hover:bg-primary disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2 shadow-sm"
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

      <div className="mt-6 pt-6 border-t border-border text-center text-sm text-muted-foreground">
        {brand.signupPrompt}{" "}
        <Link href={brand.signupHref} className="text-primary font-semibold hover:text-primary transition-colors">
          {brand.signupLabel}
        </Link>
      </div>
    </div>
  );
}
