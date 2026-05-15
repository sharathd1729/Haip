"use client";

/**
 * useWhatsAppEmbeddedSignup
 *
 * Manages the Meta WhatsApp Embedded Signup flow:
 *  1. Loads the Facebook JavaScript SDK on demand
 *  2. Initialises it with the Meta App ID
 *  3. Attaches a window.message listener to capture waba_id + phone_number_id
 *     from the Embedded Signup postMessage event
 *  4. Opens the FB.login() popup with the ES config_id
 *  5. Collects the authorization code from FB.login callback
 *  6. Once both the postMessage data AND the auth code are available,
 *     calls onSuccess with all three values
 *
 * Reference:
 *   https://developers.facebook.com/docs/whatsapp/embedded-signup
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  WhatsAppEmbeddedSignupMessage,
  WhatsAppEmbeddedSignupFinishData,
} from "@/types/facebook";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EmbeddedSignupResult {
  code: string;
  waba_id: string;
  phone_number_id: string;
  business_id?: string;
}

interface UseWhatsAppEmbeddedSignupOptions {
  /** Meta App ID — fetched from /integrations/whatsapp_meta/init */
  appId: string;
  /** Embedded Signup config ID — fetched from /integrations/whatsapp_meta/init */
  configId: string;
  /** Called when the user completes the signup and all data is collected */
  onSuccess: (result: EmbeddedSignupResult) => void;
  /** Called when the user cancels or closes the popup */
  onCancel?: (step?: string) => void;
  /** Called on SDK or Meta API errors */
  onError?: (error: string) => void;
}

export interface UseWhatsAppEmbeddedSignupReturn {
  /** Open the Embedded Signup popup */
  launch: () => void;
  /** True while the SDK is loading or the popup is open */
  isLoading: boolean;
  /** Error message if something went wrong */
  error: string | null;
  /** Clear the error state */
  clearError: () => void;
}

// ---------------------------------------------------------------------------
// SDK loader
// ---------------------------------------------------------------------------

let sdkLoadPromise: Promise<void> | null = null;

function loadFacebookSDK(appId: string): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();

  // Already loaded and initialised
  if (window.FB) return Promise.resolve();

  // Already in-flight
  if (sdkLoadPromise) return sdkLoadPromise;

  sdkLoadPromise = new Promise<void>((resolve, reject) => {
    window.fbAsyncInit = function () {
      window.FB.init({
        appId,
        autoLogAppEvents: true,
        xfbml: true,
        version: "v21.0",
        cookie: true,
      });
      resolve();
    };

    const script = document.createElement("script");
    script.id = "facebook-jssdk";
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.defer = true;
    script.crossOrigin = "anonymous";
    script.onerror = () => {
      sdkLoadPromise = null;
      reject(new Error("Failed to load the Facebook SDK. Check your network connection."));
    };

    // Inject after the first script tag (or append to body)
    const firstScript = document.getElementsByTagName("script")[0];
    if (firstScript?.parentNode) {
      firstScript.parentNode.insertBefore(script, firstScript);
    } else {
      document.body.appendChild(script);
    }
  });

  return sdkLoadPromise;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useWhatsAppEmbeddedSignup({
  appId,
  configId,
  onSuccess,
  onCancel,
  onError,
}: UseWhatsAppEmbeddedSignupOptions): UseWhatsAppEmbeddedSignupReturn {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Collected data refs — populated independently from two async sources
  const collected = useRef<{
    code?: string;
    waba_id?: string;
    phone_number_id?: string;
    business_id?: string;
  }>({});

  // Stable refs to callbacks (avoids stale closures in event listeners)
  const onSuccessRef = useRef(onSuccess);
  const onCancelRef = useRef(onCancel);
  const onErrorRef = useRef(onError);
  onSuccessRef.current = onSuccess;
  onCancelRef.current = onCancel;
  onErrorRef.current = onError;

  // When popup resolves, setIsLoading must be called. Track with a ref so
  // the message handler (which doesn't re-render) can still call it.
  const setIsLoadingRef = useRef(setIsLoading);
  setIsLoadingRef.current = setIsLoading;

  /**
   * Attempt to call onSuccess if all required fields have been collected.
   * Safe to call multiple times — exits immediately if anything is missing.
   */
  const tryComplete = useCallback(() => {
    const { code, waba_id, phone_number_id, business_id } = collected.current;
    if (!code || !waba_id || !phone_number_id) return;

    // Reset collected data so repeated opens don't refire
    collected.current = {};
    setIsLoadingRef.current(false);

    onSuccessRef.current({ code, waba_id, phone_number_id, business_id });
  }, []);

  /**
   * postMessage listener — captures waba_id and phone_number_id from the
   * Embedded Signup popup hosted on facebook.com.
   *
   * IMPORTANT: The message can arrive before OR after the FB.login() callback.
   * We collect both independently and call onSuccess only when both are ready.
   */
  useEffect(() => {
    if (typeof window === "undefined") return;

    function handleMessage(event: MessageEvent) {
      // Only accept messages from Meta's domain
      if (!event.origin.endsWith(".facebook.com")) return;

      let msg: WhatsAppEmbeddedSignupMessage;
      try {
        msg =
          typeof event.data === "string"
            ? (JSON.parse(event.data) as WhatsAppEmbeddedSignupMessage)
            : (event.data as WhatsAppEmbeddedSignupMessage);
      } catch {
        return;
      }

      if (msg.type !== "WA_EMBEDDED_SIGNUP") return;

      if (msg.event === "FINISH") {
        const finish = msg as WhatsAppEmbeddedSignupFinishData;
        collected.current.waba_id = finish.data.waba_id;
        collected.current.phone_number_id = finish.data.phone_number_id;
        tryComplete();
      }

      if (msg.event === "CANCEL") {
        setIsLoadingRef.current(false);
        collected.current = {}; // clear partial data
        onCancelRef.current?.(
          (msg as Extract<WhatsAppEmbeddedSignupMessage, { event: "CANCEL" }>).data.current_step
        );
      }

      if (msg.event === "ERROR") {
        setIsLoadingRef.current(false);
        collected.current = {};
        const errMsg =
          (msg as Extract<WhatsAppEmbeddedSignupMessage, { event: "ERROR" }>).data.error_message ||
          "Meta Embedded Signup encountered an error.";
        setError(errMsg);
        onErrorRef.current?.(errMsg);
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [tryComplete]);

  /**
   * Launch the Embedded Signup popup.
   */
  const launch = useCallback(async () => {
    if (!appId || !configId) {
      const msg =
        "WhatsApp Embedded Signup is not configured. " +
        "Ask your administrator to set META_APP_ID and META_EMBEDDED_SIGNUP_CONFIG_ID.";
      setError(msg);
      onErrorRef.current?.(msg);
      return;
    }

    setError(null);
    setIsLoading(true);
    collected.current = {}; // reset any leftover state from a previous attempt

    try {
      await loadFacebookSDK(appId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load Facebook SDK.";
      setError(msg);
      setIsLoading(false);
      onErrorRef.current?.(msg);
      return;
    }

    if (!window.FB) {
      const msg = "Facebook SDK failed to initialise. Please refresh and try again.";
      setError(msg);
      setIsLoading(false);
      onErrorRef.current?.(msg);
      return;
    }

    window.FB.login(
      (response) => {
        if (response.authResponse?.code) {
          collected.current.code = response.authResponse.code;
          tryComplete();
        } else if (response.status !== "connected") {
          // User closed the popup without completing (no code returned)
          setIsLoading(false);
          collected.current = {};
          onCancelRef.current?.();
        }
      },
      {
        config_id: configId,
        response_type: "code",
        override_default_response_type: true,
        extras: {
          setup: {},
          featureType: "",
          sessionInfoVersion: "3",
        },
      }
    );
  }, [appId, configId, tryComplete]);

  return {
    launch,
    isLoading,
    error,
    clearError: () => setError(null),
  };
}
