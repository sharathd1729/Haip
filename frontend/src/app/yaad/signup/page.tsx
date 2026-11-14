"use client";
// Yaad sign-up: name, email, password. Creates a PERSONAL workspace (POST /auth/register, workspace_mode "personal"):
// no business type, no workspace URL, no onboarding. Signs in and opens the Calls screen.
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { ArrowRight, Eye, EyeOff, Loader2 } from "@/lib/icons";
import { clearTokenCache } from "@/lib/api";

const field = "mt-1.5 min-h-12 w-full rounded-xl border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3.5 text-[16px] text-[var(--y-ink)] placeholder:text-[var(--y-ink-3)] focus:border-[var(--y-ink)] focus:outline-none";

function apiBase(): string {
  const raw = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
  return raw.endsWith("/api/v1") ? raw.slice(0, -7) : raw;
}

export default function YaadSignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) { setError("Use at least 8 characters for your password."); return; }
    setLoading(true);
    try {
      const res = await fetch(`${apiBase()}/api/v1/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), email: email.trim(), password, workspace_mode: "personal",
                               consent_transactional: true, consent_marketing: false, consent_analytics: false }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = typeof data.detail === "string" ? data.detail : "";
        setError(d.includes("Email already registered")
          ? "That email already has an account. Sign in instead."
          : d || "Couldn't create your account. Please try again.");
        return;
      }
      const signed = await signIn("credentials", {
        preAuthAccessToken: data.access_token, preAuthRefreshToken: data.refresh_token, remember: "1", redirect: false,
      });
      if (signed?.error) {
        router.push("/yaad/login?registered=1");
        return;
      }
      clearTokenCache();
      router.push("/dashboard/me");
    } catch {
      setError("Couldn't reach Yaad. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <h1 className="text-[24px] font-semibold tracking-[-0.02em]">Create your account</h1>
      <p className="mt-1 text-[14.5px] text-[var(--y-ink-2)]">Your calls, summarised. Every promise and plan, remembered.</p>
      <form className="mt-6 grid gap-4" onSubmit={submit}>
        <label className="text-[14px] font-medium">Your name
          <input className={field} value={name} onChange={e => setName(e.target.value)} required maxLength={120} autoComplete="name" />
        </label>
        <label className="text-[14px] font-medium">Email
          <input className={field} type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label className="text-[14px] font-medium">Password
          <span className="relative block">
            <input className={`${field} pr-12`} type={show ? "text" : "password"} value={password} minLength={8}
              onChange={e => setPassword(e.target.value)} required autoComplete="new-password" />
            <button type="button" onClick={() => setShow(s => !s)} aria-label={show ? "Hide password" : "Show password"}
              className="absolute right-1 top-1/2 flex size-11 -translate-y-1/2 items-center justify-center text-[var(--y-ink-2)]">
              {show ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </span>
          <span className="mt-1 block text-[12.5px] font-normal text-[var(--y-ink-3)]">At least 8 characters.</span>
        </label>
        <label className="flex items-start gap-3 text-[13.5px] text-[var(--y-ink-2)]">
          <input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} required
            className="mt-0.5 size-5 shrink-0 accent-[var(--y-brand)]" />
          <span>I agree to the <Link href="/terms" className="underline">Terms</Link> and <Link href="/privacy" className="underline">Privacy policy</Link>. Yaad records and summarises my calls; I tell the people I call when the law needs it.</span>
        </label>
        {error && <p role="alert" className="rounded-xl bg-[var(--y-late-soft)] px-3 py-2 text-[14px] text-[var(--y-late)]">{error}</p>}
        <button type="submit" disabled={loading || !agree}
          className="y-press inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-[var(--y-brand)] text-[15px] font-semibold text-[var(--y-on-brand)] disabled:opacity-50">
          {loading ? <Loader2 size={16} className="animate-spin" /> : null} Create account {!loading && <ArrowRight size={16} />}
        </button>
      </form>
      <p className="mt-6 border-t border-[var(--y-line)] pt-5 text-center text-[14px] text-[var(--y-ink-2)]">
        Already have an account? <Link href="/yaad/login" className="font-semibold text-[var(--y-ink)] underline-offset-2 hover:underline">Sign in</Link>
      </p>
    </>
  );
}
