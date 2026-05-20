"use client";

/**
 * D6 — Public Grievance Officer page
 *
 * Publicly accessible at /grievance (no auth required).
 * DPDP Act 2023 §13(2) requires a Data Fiduciary to appoint a grievance officer
 * and publish their contact details. SLA: 30 days per §13(3).
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Shield, Mail, Phone, Clock, CheckCircle2, AlertCircle, ChevronDown } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

const GRIEVANCE_TYPES = [
  { value: "data_access",     label: "Request access to my data" },
  { value: "data_correction", label: "Correct inaccurate data" },
  { value: "data_erasure",    label: "Delete my data (Right to Erasure)" },
  { value: "consent_withdraw", label: "Withdraw consent / Opt-out" },
  { value: "data_breach",     label: "Report a suspected data breach" },
  { value: "spam",            label: "Unwanted marketing messages" },
  { value: "other",           label: "Other privacy concern" },
];

interface FormState {
  name: string;
  email: string;
  phone: string;
  grievance_type: string;
  description: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  email: "",
  phone: "",
  grievance_type: "",
  description: "",
};

export default function GrievancePage() {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<Partial<FormState>>({});
  const [submitted, setSubmitted] = useState(false);
  const [referenceNo, setReferenceNo] = useState("");

  const mutation = useMutation({
    mutationFn: async (data: FormState) => {
      const res = await fetch("/api/v1/grievance/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("Submission failed");
      return res.json();
    },
    onSuccess: (data) => {
      setReferenceNo(data.reference_no || data.id?.slice(0, 8).toUpperCase() || "GRV-" + Date.now().toString(36).toUpperCase());
      setSubmitted(true);
      setForm(EMPTY_FORM);
    },
  });

  const validate = (): boolean => {
    const e: Partial<FormState> = {};
    if (!form.name.trim()) e.name = "Name is required";
    if (!form.email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) e.email = "Valid email required";
    if (!form.grievance_type) e.grievance_type = "Please select a grievance type";
    if (!form.description.trim() || form.description.trim().length < 20) e.description = "Please describe your concern (min 20 characters)";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    mutation.mutate(form);
  };

  const set = (field: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    setForm(f => ({ ...f, [field]: e.target.value }));
    if (errors[field]) setErrors(er => ({ ...er, [field]: undefined }));
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-[#060e1c] text-white py-16 px-5">
        <div className="max-w-3xl mx-auto text-center">
          <div className="w-14 h-14 rounded-2xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center mx-auto mb-5">
            <Shield size={26} className="text-teal-400" />
          </div>
          <h1 className="text-3xl font-bold mb-3">Privacy &amp; Grievances</h1>
          <p className="text-white/60 text-base leading-relaxed max-w-xl mx-auto">
            HAIP is committed to protecting your personal data under the{" "}
            <strong className="text-white/80">Digital Personal Data Protection Act, 2023</strong>.
            Use this form to exercise your data rights or raise a concern.
          </p>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-5 py-14 grid md:grid-cols-5 gap-10">
        {/* Sidebar — officer info */}
        <div className="md:col-span-2 space-y-6">
          {/* Officer card */}
          <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-4">Grievance Officer</p>
            <p className="text-sm font-semibold text-gray-900">HAIP Privacy Team</p>
            <div className="mt-4 space-y-3">
              <div className="flex items-center gap-2.5">
                <Mail size={14} className="text-teal-500 flex-shrink-0" />
                <a href="mailto:privacy@haip.in" className="text-sm text-teal-600 hover:text-teal-700 font-medium">
                  privacy@haip.in
                </a>
              </div>
              <div className="flex items-center gap-2.5">
                <Clock size={14} className="text-gray-400 flex-shrink-0" />
                <span className="text-sm text-gray-600">Response within <strong>30 days</strong></span>
              </div>
            </div>
          </div>

          {/* Your rights */}
          <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-4">Your Rights under DPDP</p>
            <ul className="space-y-3 text-sm text-gray-700">
              {[
                ["Access", "Know what data we hold about you"],
                ["Correction", "Fix inaccurate information"],
                ["Erasure", "Request deletion of your data"],
                ["Withdraw consent", "Reply STOP to any message"],
                ["Nominate", "Appoint someone to act on your behalf"],
                ["Complaint", "Escalate to the Data Protection Board"],
              ].map(([right, desc]) => (
                <li key={right} className="flex gap-2.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-teal-400 mt-1.5 flex-shrink-0" />
                  <div>
                    <span className="font-semibold text-gray-900">{right}</span>
                    <span className="text-gray-500 ml-1 text-xs">{desc}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {/* Quick opt-out */}
          <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5">
            <p className="text-xs font-bold uppercase tracking-wider text-amber-600 mb-2">Quick Opt-out</p>
            <p className="text-sm text-amber-800 leading-relaxed">
              To stop marketing messages instantly, reply{" "}
              <strong className="font-mono bg-amber-100 px-1 rounded">STOP</strong> to any WhatsApp message from us.
              Takes effect in under 30 seconds.
            </p>
          </div>
        </div>

        {/* Form */}
        <div className="md:col-span-3">
          {submitted ? (
            <div className="bg-white rounded-2xl border border-gray-200 p-10 shadow-sm text-center">
              <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-5">
                <CheckCircle2 size={30} className="text-green-600" />
              </div>
              <h2 className="text-xl font-bold text-gray-900 mb-2">Grievance Submitted</h2>
              <p className="text-gray-500 mb-4 text-sm leading-relaxed">
                Your reference number is{" "}
                <span className="font-mono font-semibold text-gray-800 bg-gray-100 px-2 py-0.5 rounded">
                  {referenceNo}
                </span>
              </p>
              <p className="text-gray-500 text-sm mb-8">
                We will respond to <strong>privacy@haip.in</strong> within <strong>30 days</strong> as required by the DPDP Act.
              </p>
              <button
                onClick={() => setSubmitted(false)}
                className="text-sm text-teal-600 hover:text-teal-700 font-medium underline underline-offset-4"
              >
                Submit another grievance
              </button>
            </div>
          ) : (
            <div className="bg-white rounded-2xl border border-gray-200 p-8 shadow-sm">
              <h2 className="text-lg font-bold text-gray-900 mb-6">Submit a Grievance</h2>

              {mutation.isError && (
                <div className="mb-5 flex items-center gap-2.5 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
                  <AlertCircle size={14} className="text-red-500 flex-shrink-0" />
                  <p className="text-sm text-red-700">Something went wrong. Please try again or email us directly.</p>
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-5">
                {/* Name + Email */}
                <div className="grid sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1.5">Full name *</label>
                    <input
                      type="text"
                      value={form.name}
                      onChange={set("name")}
                      placeholder="Rahul Sharma"
                      className={cn(
                        "w-full text-sm border rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:border-transparent transition-colors",
                        errors.name ? "border-red-300 focus:ring-red-300" : "border-gray-200 focus:ring-teal-500"
                      )}
                    />
                    {errors.name && <p className="text-xs text-red-600 mt-1">{errors.name}</p>}
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1.5">Email address *</label>
                    <input
                      type="email"
                      value={form.email}
                      onChange={set("email")}
                      placeholder="rahul@email.com"
                      className={cn(
                        "w-full text-sm border rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:border-transparent transition-colors",
                        errors.email ? "border-red-300 focus:ring-red-300" : "border-gray-200 focus:ring-teal-500"
                      )}
                    />
                    {errors.email && <p className="text-xs text-red-600 mt-1">{errors.email}</p>}
                  </div>
                </div>

                {/* Phone (optional) */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1.5">Phone number <span className="font-normal text-gray-400">(optional)</span></label>
                  <input
                    type="tel"
                    value={form.phone}
                    onChange={set("phone")}
                    placeholder="+91 98765 43210"
                    className="w-full text-sm border border-gray-200 rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-colors"
                  />
                </div>

                {/* Grievance type */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1.5">Nature of grievance *</label>
                  <div className="relative">
                    <select
                      value={form.grievance_type}
                      onChange={set("grievance_type")}
                      className={cn(
                        "w-full text-sm border rounded-xl px-3.5 py-2.5 appearance-none focus:outline-none focus:ring-2 focus:border-transparent bg-white pr-10 transition-colors",
                        errors.grievance_type ? "border-red-300 focus:ring-red-300" : "border-gray-200 focus:ring-teal-500"
                      )}
                    >
                      <option value="">Select type…</option>
                      {GRIEVANCE_TYPES.map(t => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                      ))}
                    </select>
                    <ChevronDown size={14} className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                  </div>
                  {errors.grievance_type && <p className="text-xs text-red-600 mt-1">{errors.grievance_type}</p>}
                </div>

                {/* Description */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1.5">Description *</label>
                  <textarea
                    value={form.description}
                    onChange={set("description")}
                    rows={5}
                    placeholder="Please describe your concern in detail. Include dates, which service, and what resolution you are seeking."
                    className={cn(
                      "w-full text-sm border rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:border-transparent resize-none transition-colors",
                      errors.description ? "border-red-300 focus:ring-red-300" : "border-gray-200 focus:ring-teal-500"
                    )}
                  />
                  <div className="flex items-center justify-between mt-1">
                    {errors.description
                      ? <p className="text-xs text-red-600">{errors.description}</p>
                      : <span />}
                    <p className="text-[11px] text-gray-400">{form.description.length} chars</p>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={mutation.isPending}
                  className="w-full py-3 rounded-xl bg-[#0B1F3A] hover:bg-[#163458] text-white text-sm font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {mutation.isPending ? (
                    <>
                      <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Submitting…
                    </>
                  ) : "Submit grievance"}
                </button>

                <p className="text-[11px] text-gray-400 text-center leading-relaxed">
                  By submitting, you agree that HAIP may process your information to respond to this grievance per our{" "}
                  <Link href="/privacy" className="text-teal-500 hover:underline">Privacy Policy</Link>.
                  We will respond within 30 days.
                </p>
              </form>
            </div>
          )}
        </div>
      </div>

      {/* Bottom bar */}
      <div className="border-t border-gray-200 py-8 text-center">
        <p className="text-xs text-gray-400">
          HAIP Hospitality AI Intelligence Platform · privacy@haip.in ·{" "}
          <Link href="/privacy" className="text-teal-500 hover:underline">Privacy Policy</Link>{" "}
          · Regulated under the Digital Personal Data Protection Act, 2023
        </p>
      </div>
    </div>
  );
}
