/**
 * TypeScript declarations for the Facebook JavaScript SDK.
 * https://developers.facebook.com/docs/javascript/reference
 */

interface FBAuthResponse {
  accessToken: string;
  expiresIn: number;
  signedRequest: string;
  userID: string;
  /** Present when response_type=code (Embedded Signup flow) */
  code?: string;
  /** Present in older flows */
  grantedScopes?: string;
}

interface FBLoginStatusResponse {
  status: "connected" | "not_authorized" | "unknown";
  authResponse: FBAuthResponse | null;
}

interface FBLoginOptions {
  /** Comma-separated list of permissions to request */
  scope?: string;
  /** Embedded Signup config ID (from Meta Business Suite) */
  config_id?: string;
  /** Override default response type ("code" for ES) */
  response_type?: "code" | "token" | "granted_scopes";
  /** Required when using response_type=code in Embedded Signup */
  override_default_response_type?: boolean;
  /** Extra parameters for Embedded Signup */
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
  login(
    callback: (response: FBLoginStatusResponse) => void,
    options?: FBLoginOptions
  ): void;
  logout(callback?: (response: FBLoginStatusResponse) => void): void;
  getLoginStatus(
    callback: (response: FBLoginStatusResponse) => void,
    roundTrip?: boolean
  ): void;
  api(
    path: string,
    callback: (response: Record<string, unknown>) => void
  ): void;
  api(
    path: string,
    params: Record<string, unknown>,
    callback: (response: Record<string, unknown>) => void
  ): void;
  api(
    path: string,
    method: string,
    params: Record<string, unknown>,
    callback: (response: Record<string, unknown>) => void
  ): void;
}

interface Window {
  FB: FB;
  fbAsyncInit?: () => void;
}

/**
 * Message event data from Meta Embedded Signup popup.
 * Fired via window.postMessage from https://www.facebook.com
 */
interface WhatsAppEmbeddedSignupFinishData {
  type: "WA_EMBEDDED_SIGNUP";
  event: "FINISH";
  data: {
    phone_number_id: string;
    waba_id: string;
  };
  version: string;
}

interface WhatsAppEmbeddedSignupCancelData {
  type: "WA_EMBEDDED_SIGNUP";
  event: "CANCEL";
  data: {
    current_step: string;
  };
  version: string;
}

interface WhatsAppEmbeddedSignupErrorData {
  type: "WA_EMBEDDED_SIGNUP";
  event: "ERROR";
  data: {
    error_message: string;
  };
  version: string;
}

type WhatsAppEmbeddedSignupMessage =
  | WhatsAppEmbeddedSignupFinishData
  | WhatsAppEmbeddedSignupCancelData
  | WhatsAppEmbeddedSignupErrorData;
