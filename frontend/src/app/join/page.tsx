"use client";
import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { Eye, EyeOff, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import api from "@/lib/api";

function JoinForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token") ?? "";

  const [form, setForm] = useState({ password: "", confirm: "" });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [invite, setInvite] = useState<{ name: string; email: string; role: string; tenant_name?: string } | null>(null);

  useEffect(() => {
    if (!token) { setError("Invalid invitation link — token is missing."); return; }
    // Load invitation preview so we can show name/role/tenant before accepting
    api.get(`/auth/invitation/${token}`)
      .then(r => setInvite(r.data))
      .catch(() => {}); // non-fatal — page still works without preview
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.password.length < 8) { setError("Password must be at least 8 characters."); return; }
    if (form.password !== form.confirm) { setError("Passwords don't match."); return; }
    setError("");
    setLoading(true);
    try {
      const res = await api.post("/auth/accept-invitation", { token, password: form.password });
      const data = res.data;

      // Sign in with the email from the response
      const result = await signIn("credentials", {
        redirect: false,
        email: data.user.email,
        password: form.password,
      });
      setDone(true);
      setTimeout(() => router.push(result?.error ? "/login" : "/dashboard"), 1500);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Something went wrong. Please try again.");
      setLoading(false);
    }
  };

  if (done) {
    return (
      <div className="text-center py-8">
        <CheckCircle2 size={48} className="text-teal-500 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-gray-900 mb-2">Welcome to the workspace!</h2>
        <p className="text-sm text-gray-500">Redirecting you to the dashboard…</p>
      </div>
    );
  }

  return (
    <>
      <div className="px-8 pt-8 pb-6 border-b border-gray-100 text-center">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center text-white font-bold text-lg mx-auto mb-4 shadow-lg shadow-teal-500/30">
          H
        </div>
        <h1 className="text-xl font-bold text-gray-900">
          {invite ? `Hi, ${invite.name.split(" ")[0]}!` : "Join your workspace"}
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          {invite
            ? <>You&apos;ve been invited to <strong>{invite.tenant_name ?? "the workspace"}</strong> as <span className="text-teal-600 capitalize font-medium">{invite.role.replace("_", " ")}</span>. Set a password to get started.</>
            : "Set a password to activate your account and start using HAIP."
          }
        </p>
      </div>
      <div className="px-8 py-7">
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="text-xs font-semibold text-gray-700 block mb-1.5">Set your password <span className="text-red-500">*</span></label>
        <div className="relative">
          <input
            type={showPassword ? "text" : "password"}
            value={form.password}
            onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
            placeholder="At least 8 characters"
            className="w-full px-4 pr-10 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30"
            required
          />
          <button type="button" onClick={() => setShowPassword(v => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      </div>
      <div>
        <label className="text-xs font-semibold text-gray-700 block mb-1.5">Confirm password <span className="text-red-500">*</span></label>
        <input
          type="password"
          value={form.confirm}
          onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))}
          placeholder="Re-enter password"
          className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30"
          required
        />
      </div>
      {error && (
        <div className="flex items-center gap-2 text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2">
          <AlertCircle size={13} /> {error}
        </div>
      )}
      <button
        type="submit"
        disabled={loading || !token}
        className="w-full py-3 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
      >
        {loading ? <Loader2 size={15} className="animate-spin" /> : null}
        {loading ? "Setting up your account…" : "Join workspace"}
      </button>
    </form>
      </div>
    </>
  );
}

export default function JoinPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-[#0B1F3A] to-slate-900 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
        <Suspense fallback={<div className="text-center text-sm text-gray-400 py-8">Loading…</div>}>
          <JoinForm />
        </Suspense>
      </div>
    </div>
  );
}
