/**
 * TypeScript declarations for the Facebook JavaScript SDK.
 * https://developers.facebook.com/docs/javascript/reference
 */

// ── Internal FB SDK types (not exported — used only for Window augmentation) ──

interface FBAuthResponse {
  accessToken: string;
  expiresIn: number;
  signedRequest: string;
  userID: string;
  code?: string;
  grantedScopes?: string;
}

interface FBLoginStatusResponse {
  status: "connected" | "not_authorized" | "unknown";
  authResponse: FBAuthResponse | null;
}

interface FBLoginOptions {
  scope?: string;
  config_id?: string;
  response_type?: "code" | "token" | "granted_scopes";
  override_default_response_type?: boolean;
  extras?: {
    setup?: Record<string, unknown>;
    featureType?: string;
    sessionInfoVersion?: string;
  };
}

interface FBInitOptions {
  appId: string;
  autoLogAppEvents?: boolean;
  xfbml?: boolean;
  version?: string;
  cookie?: boolean;
  status?: boolean;
}

interface FB {
  init(options: FBInitOptions): void;
  login(callback: (response: FBLoginStatusResponse) => void, options?: FBLoginOptions): void;
  logout(callback?: (response: FBLoginStatusResponse) => void): void;
  getLoginStatus(callback: (response: FBLoginStatusResponse) => void, roundTrip?: boolean): void;
  api(path: string, callback: (response: Record<string, unknown>) => void): void;
  api(path: string, params: Record<string, unknown>, callback: (response: Record<string, unknown>) => void): void;
  api(path: string, method: string, params: Record<string, unknown>, callback: (response: Record<string, unknown>) => void): void;
}

// ── Global Window augmentation ─────────────────────────────────────────────
declare global {
  interface Window {
    FB: FB;
    fbAsyncInit?: () => void;
  }
}

// ── Exported types used by hooks ───────────────────────────────────────────

export interface WhatsAppEmbeddedSignupFinishData {
  type: "WA_EMBEDDED_SIGNUP";
  event: "FINISH";
  data: {
    phone_number_id: string;
    waba_id: string;
  };
  version: string;
}

export interface WhatsAppEmbeddedSignupCancelData {
  type: "WA_EMBEDDED_SIGNUP";
  event: "CANCEL";
  data: {
    current_step: string;
  };
  version: string;
}

export interface WhatsAppEmbeddedSignupErrorData {
  type: "WA_EMBEDDED_SIGNUP";
  event: "ERROR";
  data: {
    error_message: string;
  };
  version: string;
}

export type WhatsAppEmbeddedSignupMessage =
  | WhatsAppEmbeddedSignupFinishData
  | WhatsAppEmbeddedSignupCancelData
  | WhatsAppEmbeddedSignupErrorData;
