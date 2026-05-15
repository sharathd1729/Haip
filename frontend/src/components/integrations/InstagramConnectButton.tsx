"use client";

/**
 * InstagramConnectButton
 * Facebook Embedded Signup flow for Instagram Business accounts.
 * Flow: FB.login() → code + instagram_business_account_id → POST /integrations/instagram/connect-embedded
 */

import { useState, useCallback } from "react";
import { Loader2, AlertCircle, CheckCircle2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { useWhatsAppEmbeddedSignup } from "@/hooks/useWhatsAppEmbeddedSignup";
import type { EmbeddedSignupResult } from "@/hooks/useWhatsAppEmbeddedSignup";

interface OAuthInitResponse {
  state: string;
  auth_type: string;
  config_id: string | null;
  app_id: string | null;
}

interface InstagramConnectButtonProps {
  onSuccess?: () => void;
  label?: string;
  className?: string;
  compact?: boolean;
}

function WaitingOverlay({ onCancel }: { onCancel: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-pink-50 flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" className="text-pink-500">
                <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900">Instagram Setup</p>
              <p className="text-[11px] text-gray-400">Complete the steps in the popup</p>
            </div>
          </div>
          <button onClick={onCancel} className="text-gray-300 hover:text-gray-500 transition-colors"><X size={16} /></button>
        </div>
        <div className="px-6 py-4">
          <p className="text-[11px] text-gray-400 leading-relaxed">
            A Facebook popup has opened. Select your Instagram Business Account to link it with HAIP.
          </p>
          <p className="text-[11px] text-amber-600 mt-2">Keep this window open while completing setup.</p>
        </div>
        <div className="px-6 pb-5 flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 size={13} className="animate-spin text-pink-500" />
            Waiting for Facebook…
          </div>
          <button onClick={onCancel} className="ml-auto text-xs text-gray-400 hover:text-gray-600 transition-colors">Cancel</button>
        </div>
      </div>
    </div>
  );
}

export function InstagramConnectButton({
  onSuccess,
  label = "Connect Instagram",
  className,
  compact = false,
}: InstagramConnectButtonProps) {
  const [showOverlay, setShowOverlay] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [initData, setInitData] = useState<OAuthInitResponse | null>(null);

  const saveToBackend = useCallback(async (result: EmbeddedSignupResult) => {
    setShowOverlay(false);
    setIsSaving(true);
    try {
      await api.post("/integrations/instagram/connect-embedded", {
        code: result.code,
        instagram_business_account_id: result.waba_id,  // reusing waba_id field from hook
        business_id: result.business_id,
      });
      onSuccess?.();
    } catch (err: any) {
      setLocalError(err?.response?.data?.detail || "Failed to connect Instagram. Please try again.");
    } finally {
      setIsSaving(false);
    }
  }, [onSuccess]);

  const { launch, isLoading: sdkLoading, error: sdkError, clearError } = useWhatsAppEmbeddedSignup({
    appId: initData?.app_id ?? "",
    configId: initData?.config_id ?? "",
    onSuccess: saveToBackend,
    onCancel: (step) => {
      setShowOverlay(false);
      if (step) setLocalError(`Setup cancelled at step: ${step}. You can try again.`);
    },
    onError: (err) => { setShowOverlay(false); setLocalError(err); },
  });

  const isWorking = sdkLoading || isSaving;
  const displayError = localError || sdkError;

  const handleClick = useCallback(async () => {
    setLocalError(null);
    clearError();
    let init = initData;
    if (!init) {
      try {
        const res = await api.post<OAuthInitResponse>("/integrations/instagram/init");
        init = res.data;
        setInitData(init);
      } catch {
        setLocalError("Could not reach HAIP server to start Instagram setup.");
        return;
      }
    }
    if (!init.app_id || !init.config_id) {
      setLocalError("Instagram Embedded Signup is not configured. Ask your administrator to set META_APP_ID.");
      return;
    }
    setShowOverlay(true);
    setTimeout(() => launch(), 50);
  }, [initData, launch, clearError]);

  return (
    <>
      <div className="flex flex-col gap-2">
        <button
          onClick={handleClick}
          disabled={isWorking}
          className={cn(
            "inline-flex items-center justify-center gap-2 font-semibold transition-all duration-150",
            "bg-gradient-to-r from-pink-500 via-purple-500 to-orange-400 hover:opacity-90 text-white",
            "disabled:opacity-50 disabled:cursor-not-allowed shadow-sm shadow-pink-300/40",
            compact ? "px-3 py-2 rounded-lg text-xs" : "w-full px-4 py-2.5 rounded-xl text-xs",
            className
          )}
        >
          {isWorking ? <Loader2 size={compact ? 13 : 14} className="animate-spin" /> : (
            <svg width={compact ? 13 : 14} height={compact ? 13 : 14} viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
            </svg>
          )}
          {isWorking ? (isSaving ? "Saving…" : "Opening Facebook…") : label}
        </button>
        {displayError && (
          <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-xl p-2.5 text-xs text-red-700">
            <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
            <span className="flex-1">{displayError}</span>
            <button onClick={() => { setLocalError(null); clearError(); }} className="text-red-400 hover:text-red-600"><X size={12} /></button>
          </div>
        )}
      </div>
      {showOverlay && <WaitingOverlay onCancel={() => setShowOverlay(false)} />}
    </>
  );
}
