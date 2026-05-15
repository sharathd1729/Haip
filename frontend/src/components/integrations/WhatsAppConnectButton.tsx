"use client";

/**
 * WhatsAppConnectButton
 *
 * A self-contained "Connect WhatsApp" button that drives the full
 * Meta Embedded Signup flow:
 *
 *   1. Click → POST /integrations/whatsapp_meta/init  (get config_id + app_id)
 *   2. Open Meta Embedded Signup popup via FB.login()
 *   3. Collect code (from FB.login callback) + waba_id/phone_number_id (from postMessage)
 *   4. POST /integrations/whatsapp_meta/connect-embedded
 *   5. Call onSuccess / onError
 *
 * Usage:
 *   <WhatsAppConnectButton onSuccess={refetchIntegrations} />
 */

import { useState, useCallback } from "react";
import { Loader2, MessageSquare, AlertCircle, CheckCircle2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { useWhatsAppEmbeddedSignup } from "@/hooks/useWhatsAppEmbeddedSignup";
import type { EmbeddedSignupResult } from "@/hooks/useWhatsAppEmbeddedSignup";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OAuthInitResponse {
  state: string;
  auth_type: string;
  config_id: string | null;
  app_id: string | null;
}

interface WhatsAppConnectButtonProps {
  /** Called with the connected integration data on success */
  onSuccess?: () => void;
  /** Override button label (default: "Connect WhatsApp") */
  label?: string;
  /** Additional class names for the button element */
  className?: string;
  /** Compact icon-only mode */
  compact?: boolean;
}

// ---------------------------------------------------------------------------
// Step indicator shown inside the popup-waiting state
// ---------------------------------------------------------------------------

function StepIndicator({ step }: { step: number }) {
  const steps = [
    "Connecting to Facebook",
    "Select WhatsApp Business Account",
    "Confirm phone number",
    "Grant permissions",
  ];
  return (
    <div className="flex flex-col gap-2 py-3">
      {steps.map((label, i) => (
        <div key={i} className="flex items-center gap-2.5">
          <div
            className={cn(
              "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0",
              i < step
                ? "bg-teal-500 text-white"
                : i === step
                ? "bg-teal-100 text-teal-700 ring-2 ring-teal-400 ring-offset-1"
                : "bg-gray-100 text-gray-400"
            )}
          >
            {i < step ? "✓" : i + 1}
          </div>
          <span
            className={cn(
              "text-xs",
              i === step ? "text-gray-800 font-semibold" : "text-gray-400"
            )}
          >
            {label}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Waiting overlay — shown while the popup is open
// ---------------------------------------------------------------------------

function WaitingOverlay({
  onCancel,
}: {
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-green-50 flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" className="text-green-500">
                <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900">WhatsApp Setup</p>
              <p className="text-[11px] text-gray-400">Complete the steps in the popup</p>
            </div>
          </div>
          <button
            onClick={onCancel}
            className="text-gray-300 hover:text-gray-500 transition-colors"
            title="Cancel"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-4">
          <StepIndicator step={1} />
          <p className="text-[11px] text-gray-400 mt-3 leading-relaxed">
            A Facebook popup has opened. Complete the steps there to link your
            WhatsApp Business Account to HAIP.
          </p>
          <p className="text-[11px] text-amber-600 mt-2">
            Keep this window open while you complete the setup.
          </p>
        </div>

        <div className="px-6 pb-5 flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 size={13} className="animate-spin text-teal-500" />
            Waiting for Facebook…
          </div>
          <button
            onClick={onCancel}
            className="ml-auto text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function WhatsAppConnectButton({
  onSuccess,
  label = "Connect WhatsApp",
  className,
  compact = false,
}: WhatsAppConnectButtonProps) {
  const [showOverlay, setShowOverlay] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [initData, setInitData] = useState<OAuthInitResponse | null>(null);

  // -------------------------------------------------------------------------
  // Save signup result to backend
  // -------------------------------------------------------------------------
  const saveToBackend = useCallback(
    async (result: EmbeddedSignupResult) => {
      setShowOverlay(false);
      setIsSaving(true);
      try {
        await api.post("/integrations/whatsapp_meta/connect-embedded", {
          code: result.code,
          waba_id: result.waba_id,
          phone_number_id: result.phone_number_id,
          business_id: result.business_id,
        });
        onSuccess?.();
      } catch (err: any) {
        const msg =
          err?.response?.data?.detail ||
          "Failed to save WhatsApp connection. Please try again.";
        setLocalError(msg);
      } finally {
        setIsSaving(false);
      }
    },
    [onSuccess]
  );

  // -------------------------------------------------------------------------
  // Embedded Signup hook
  // -------------------------------------------------------------------------
  const { launch, isLoading: sdkLoading, error: sdkError, clearError } = useWhatsAppEmbeddedSignup({
    appId: initData?.app_id ?? "",
    configId: initData?.config_id ?? "",
    onSuccess: saveToBackend,
    onCancel: (step) => {
      setShowOverlay(false);
      if (step) {
        setLocalError(`Setup cancelled at step: ${step}. You can try again.`);
      }
    },
    onError: (err) => {
      setShowOverlay(false);
      setLocalError(err);
    },
  });

  const isWorking = sdkLoading || isSaving;
  const displayError = localError || sdkError;

  // -------------------------------------------------------------------------
  // Click handler — fetch init data then launch popup
  // -------------------------------------------------------------------------
  const handleClick = useCallback(async () => {
    setLocalError(null);
    clearError();

    // Fetch config_id and app_id from backend (avoids hardcoding in frontend)
    let init = initData;
    if (!init) {
      try {
        const res = await api.post<OAuthInitResponse>("/integrations/whatsapp_meta/init");
        init = res.data;
        setInitData(init);
      } catch {
        setLocalError(
          "Could not reach HAIP server to start WhatsApp setup. Check your connection."
        );
        return;
      }
    }

    if (!init.app_id || !init.config_id) {
      setLocalError(
        "WhatsApp Embedded Signup is not configured on this HAIP instance. " +
          "Ask your administrator to set META_APP_ID and META_EMBEDDED_SIGNUP_CONFIG_ID."
      );
      return;
    }

    setShowOverlay(true);
    // Give React a tick to render the overlay before opening the popup
    setTimeout(() => launch(), 50);
  }, [initData, launch, clearError]);

  const handleCancel = useCallback(() => {
    setShowOverlay(false);
  }, []);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <>
      <div className="flex flex-col gap-2">
        <button
          onClick={handleClick}
          disabled={isWorking}
          className={cn(
            "inline-flex items-center justify-center gap-2 font-semibold transition-all duration-150",
            "bg-[#25D366] hover:bg-[#20ba59] active:bg-[#1aa34a] text-white",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "shadow-sm shadow-green-300/50",
            compact
              ? "px-3 py-2 rounded-lg text-xs"
              : "w-full px-4 py-2.5 rounded-xl text-xs",
            className
          )}
        >
          {isWorking ? (
            <Loader2 size={compact ? 13 : 14} className="animate-spin" />
          ) : (
            <svg
              width={compact ? 13 : 14}
              height={compact ? 13 : 14}
              viewBox="0 0 24 24"
              fill="currentColor"
            >
              <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z" />
            </svg>
          )}
          {isWorking
            ? isSaving
              ? "Saving…"
              : "Opening Facebook…"
            : label}
        </button>

        {displayError && (
          <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-xl p-2.5 text-xs text-red-700">
            <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
            <span className="flex-1">{displayError}</span>
            <button
              onClick={() => { setLocalError(null); clearError(); }}
              className="text-red-400 hover:text-red-600 flex-shrink-0"
            >
              <X size={12} />
            </button>
          </div>
        )}
      </div>

      {showOverlay && <WaitingOverlay onCancel={handleCancel} />}
    </>
  );
}
