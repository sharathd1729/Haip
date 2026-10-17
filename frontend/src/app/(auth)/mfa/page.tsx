"use client";
import { useState, useRef, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Shield, Loader2, AlertCircle } from "@/lib/icons";
import api from "@/lib/api";

function MFAForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") ?? "/dashboard";

  const [code, setCode] = useState(["", "", "", "", "", ""]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    inputRefs.current[0]?.focus();
  }, []);

  const handleChange = (i: number, val: string) => {
    const digit = val.replace(/\D/g, "").slice(-1);
    const next = [...code];
    next[i] = digit;
    setCode(next);
    setError("");

    if (digit && i < 5) {
      inputRefs.current[i + 1]?.focus();
    }

    if (digit && i === 5) {
      const full = [...next].join("");
      if (full.length === 6) submitCode(full);
    }
  };

  const handleKeyDown = (i: number, e: React.KeyboardEvent) => {
    if (e.key === "Backspace" && !code[i] && i > 0) {
      inputRefs.current[i - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (pasted.length === 6) {
      setCode(pasted.split(""));
      submitCode(pasted);
    }
  };

  async function submitCode(otp: string) {
    setLoading(true);
    setError("");
    try {
      await api.post("/auth/mfa/verify", { code: otp });
      router.push(callbackUrl);
    } catch {
      setError("Invalid code. Please try again.");
      setCode(["", "", "", "", "", ""]);
      inputRefs.current[0]?.focus();
    } finally {
      setLoading(false);
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const otp = code.join("");
    if (otp.length < 6) return setError("Enter all 6 digits");
    submitCode(otp);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="flex justify-center gap-2" onPaste={handlePaste}>
        {code.map((digit, i) => (
          <input
            key={i}
            ref={el => { inputRefs.current[i] = el; }}
            type="text"
            inputMode="numeric"
            maxLength={1}
            value={digit}
            onChange={e => handleChange(i, e.target.value)}
            onKeyDown={e => handleKeyDown(i, e)}
            className={`w-11 h-14 text-center text-xl font-bold border rounded-xl
              focus:outline-none focus:ring-2 focus:ring-primary focus:border-primary
              transition-all ${error ? "border-red-400 bg-red-50" : "border-[var(--haip-border)] bg-[var(--haip-surface)]"}
              ${digit ? "text-[var(--haip-fg)] bg-white border-[var(--haip-border-strong)]" : "text-[var(--haip-fg-subtle)]"}`}
          />
        ))}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
          <AlertCircle size={14} className="flex-shrink-0" />
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={loading || code.join("").length < 6}
        className="w-full py-3 bg-primary hover:bg-[var(--haip-primary-hover)] disabled:opacity-50 text-white font-bold rounded-xl transition-colors flex items-center justify-center gap-2"
      >
        {loading && <Loader2 size={16} className="animate-spin" />}
        Verify
      </button>
    </form>
  );
}

export default function MFAPage() {
  return (
    <div className="min-h-screen bg-[var(--haip-surface)] flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg w-full max-w-sm p-8">
        <div className="text-center mb-8">
          <div className="w-14 h-14 bg-primary rounded-2xl flex items-center justify-center mx-auto mb-5">
            <Shield size={26} className="text-primary" />
          </div>
          <h1 className="text-xl font-black text-[var(--haip-fg)] mb-2">
            Two-factor authentication
          </h1>
          <p className="text-sm text-[var(--haip-fg-subtle)]">
            Enter the 6-digit code from your authenticator app
          </p>
        </div>

        <Suspense fallback={null}>
          <MFAForm />
        </Suspense>

        <p className="text-center text-xs text-[var(--haip-fg-subtle)] mt-6">
          Lost access to your authenticator?{" "}
          <a href="mailto:support@haip.app" className="text-primary hover:underline">
            Contact support
          </a>
        </p>
      </div>
    </div>
  );
}
