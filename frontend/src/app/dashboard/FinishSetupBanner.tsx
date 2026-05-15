"use client";
import Link from "next/link";
import { AlertCircle, ArrowRight, X } from "lucide-react";
import { useState } from "react";

const TOTAL_STEPS = 9;

const STEP_LABELS: Record<number, string> = {
  2: "Add brand voice",
  3: "Connect telephony",
  4: "Connect WhatsApp",
  5: "Invite your team",
  6: "Set concierge mode",
  7: "DPDP compliance",
  8: "Test & finish",
};

interface FinishSetupBannerProps {
  currentStep: number;
}

export function FinishSetupBanner({ currentStep }: FinishSetupBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const remaining = TOTAL_STEPS - currentStep;
  const nextStepLabel = STEP_LABELS[currentStep] ?? "Continue setup";
  const progressPct = Math.round((currentStep / TOTAL_STEPS) * 100);

  return (
    <div className="flex-shrink-0 bg-amber-50 border-b border-amber-200 px-4 py-2.5 flex items-center gap-3">
      <AlertCircle size={15} className="text-amber-500 flex-shrink-0" />

      {/* Progress bar */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <div className="w-24 h-1.5 bg-amber-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-amber-500 rounded-full transition-all"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <span className="text-xs font-semibold text-amber-700">
          {currentStep}/{TOTAL_STEPS}
        </span>
      </div>

      <p className="text-xs text-amber-700 flex-1">
        <span className="font-semibold">Setup incomplete</span>
        {" · "}
        {remaining} step{remaining !== 1 ? "s" : ""} remaining. Next:{" "}
        <span className="font-medium">{nextStepLabel}</span>
      </p>

      <Link
        href="/onboarding"
        className="flex items-center gap-1 text-xs font-semibold text-amber-800 hover:text-amber-900 flex-shrink-0 bg-amber-100 hover:bg-amber-200 px-3 py-1.5 rounded-lg transition-colors"
      >
        Finish setup <ArrowRight size={12} />
      </Link>

      <button
        onClick={() => setDismissed(true)}
        className="text-amber-400 hover:text-amber-600 flex-shrink-0 transition-colors"
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}
