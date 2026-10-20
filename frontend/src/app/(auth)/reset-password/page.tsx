"use client";
import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff, CheckCircle2 } from "@/lib/icons";

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) setError("Invalid or missing reset token. Please request a new link.");
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }

    setLoading(true);
    try {
      const _raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
      const _base = _raw.endsWith("/api/v1") ? _raw : `${_raw}/api/v1`;
      const res = await fetch(`${_base}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || "Something went wrong. Please try again.");
      } else {
        setDone(true);
        setTimeout(() => router.push("/login"), 3000);
      }
    } catch {
      setError("Unable to reach the server. Please check your connection.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--haip-surface)] flex flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center">
            <img src="/logo-wordmark.png" alt="HAIP" className="h-9 w-auto object-contain" />
          </Link>
        </div>

        <div className="bg-white rounded-2xl p-8 shadow-sm border border-[var(--haip-border)]">
          {done ? (
            <div className="text-center">
              <div className="w-14 h-14 rounded-2xl bg-[var(--haip-primary-tint)] border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 size={28} className="text-primary" />
              </div>
              <h2 className="text-xl font-bold text-[var(--haip-fg)] mb-2">Password updated!</h2>
              <p className="text-[var(--haip-fg-subtle)] text-sm leading-relaxed mb-4">
                Your password has been reset successfully. Redirecting you to sign in…
              </p>
              <Link href="/login" className="text-sm text-primary font-medium hover:underline">
                Go to sign in →
              </Link>
            </div>
          ) : (
            <>
              <h2 className="text-xl font-bold text-[var(--haip-fg)] mb-1">Set new password</h2>
              <p className="text-[var(--haip-fg-subtle)] text-sm mb-6 leading-relaxed">
                Choose a strong password for your account.
              </p>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--haip-fg-2)] mb-1.5">
                    New password
                  </label>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      required
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      placeholder="Min. 8 characters"
                      className="w-full px-4 py-3 pr-11 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow"
                      suppressHydrationWarning
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(v => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]"
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-[var(--haip-fg-2)] mb-1.5">
                    Confirm password
                  </label>
                  <input
                    type={showPassword ? "text" : "password"}
                    required
                    value={confirm}
                    onChange={e => setConfirm(e.target.value)}
                    placeholder="Repeat your password"
                    className="w-full px-4 py-3 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow"
                    suppressHydrationWarning
                  />
                </div>

                {error && (
                  <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={loading || !token}
                  className="w-full py-3 bg-primary hover:bg-[var(--haip-primary-hover)] disabled:opacity-60 text-white font-semibold rounded-xl text-sm transition-colors"
                >
                  {loading ? "Updating…" : "Update password"}
                </button>
              </form>

              <div className="mt-6 text-center">
                <Link href="/login" className="text-sm text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-2)] font-medium transition-colors">
                  Back to sign in
                </Link>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-[var(--haip-surface)] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#C8964A] border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <ResetPasswordForm />
    </Suspense>
  );
}
