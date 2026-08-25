"use client";
import { useState } from "react";
import { X, Plus, Shield } from "@/lib/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";

interface Props {
  inquiryId: string;
  onClose: () => void;
  onSuccess?: (newPct: number) => void;
}

const SIGNAL_TYPES = [
  { value: "phone",            label: "Phone number" },
  { value: "whatsapp_number",  label: "WhatsApp number" },
  { value: "email",            label: "Email address" },
];

const PLACEHOLDERS: Record<string, string> = {
  phone:           "+91 98765 43210",
  whatsapp_number: "+91 98765 43210",
  email:           "guest@example.com",
};

function validate(type: string, value: string): string | null {
  if (!value.trim()) return "Value is required";
  if (type === "phone" || type === "whatsapp_number") {
    // Basic E.164-ish check
    const stripped = value.replace(/[\s\-()]/g, "");
    if (!/^\+?[1-9]\d{7,14}$/.test(stripped)) return "Enter a valid phone number (e.g. +91 98765 43210)";
  }
  if (type === "email") {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return "Enter a valid email address";
  }
  return null;
}

export function SignalDrawer({ inquiryId, onClose, onSuccess }: Props) {
  const [signalType, setSignalType] = useState("phone");
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const { toast } = useToast();
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/leads/${inquiryId}/signals`, {
        type: signalType,
        value: value.trim(),
      });
      return res.data;
    },
    onSuccess: (data) => {
      toast({ title: "Signal added", description: `Profile completeness: ${data.profile_completeness_pct}%` });
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
      onSuccess?.(data.profile_completeness_pct);
      onClose();
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail ?? "Failed to add signal";
      setError(detail);
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const validErr = validate(signalType, value);
    if (validErr) { setError(validErr); return; }
    mutation.mutate();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />

      {/* Drawer */}
      <div className="relative bg-white rounded-t-2xl sm:rounded-2xl w-full max-w-sm mx-auto p-5 shadow-xl z-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold text-gray-900 text-[15px]">Add Identity Signal</h3>
            <p className="text-[11px] text-gray-500 mt-0.5">Enrich this lead's profile</p>
          </div>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 transition-colors">
            <X size={15} />
          </button>
        </div>

        {/* DPDP consent notice */}
        <div className="flex items-start gap-2 bg-teal-50 border border-teal-100 rounded-lg p-2.5 mb-4">
          <Shield size={13} className="text-teal-600 flex-shrink-0 mt-0.5" />
          <p className="text-[10px] text-teal-700 leading-relaxed">
            By adding this signal, you confirm the guest has consented to data collection. A consent record will be created automatically per DPDP compliance.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Signal type selector */}
          <div>
            <label className="block text-[11px] font-medium text-gray-700 mb-1">Signal type</label>
            <div className="flex gap-2 flex-wrap">
              {SIGNAL_TYPES.map(st => (
                <button
                  key={st.value}
                  type="button"
                  onClick={() => { setSignalType(st.value); setValue(""); setError(""); }}
                  className={`text-[11px] px-2.5 py-1 rounded-lg border transition-colors ${
                    signalType === st.value
                      ? "border-teal-500 bg-teal-50 text-teal-700 font-medium"
                      : "border-gray-200 text-gray-600 hover:border-gray-300"
                  }`}
                >
                  {st.label}
                </button>
              ))}
            </div>
          </div>

          {/* Value input */}
          <div>
            <label className="block text-[11px] font-medium text-gray-700 mb-1">Value</label>
            <input
              type={signalType === "email" ? "email" : "tel"}
              value={value}
              onChange={e => { setValue(e.target.value); setError(""); }}
              placeholder={PLACEHOLDERS[signalType]}
              className="w-full text-[13px] border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
            />
            {error && <p className="text-[11px] text-red-500 mt-1">{error}</p>}
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={mutation.isPending || !value.trim()}
            className="w-full flex items-center justify-center gap-2 bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white font-medium text-[13px] py-2.5 rounded-xl transition-colors"
          >
            {mutation.isPending ? (
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <Plus size={14} />
            )}
            Add Signal
          </button>
        </form>
      </div>
    </div>
  );
}
