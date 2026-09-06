import axios from "axios";
import { getSession, signOut } from "next-auth/react";
import { queryClient, QUERY_PERSIST_STORAGE_KEY } from "@/lib/queryClient";
import { useConnectionStatusStore } from "@/store/connectionStatus";
import { isWithinRefreshErrorGrace } from "@/lib/authGrace";

// Ensure base URL always ends with /api/v1 regardless of how NEXT_PUBLIC_API_URL is set.
// e.g. "https://72.61.228.243" → "https://72.61.228.243/api/v1"
// e.g. "https://72.61.228.243/api/v1" → stays as-is
const _raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const API_BASE = _raw.endsWith("/api/v1") ? _raw : `${_raw}/api/v1`;
// /health lives at the API root, not under /api/v1 -- ConnectionBanner pings
// this directly to detect recovery rather than reusing an authed endpoint.
export const API_ROOT = _raw.endsWith("/api/v1") ? _raw.slice(0, -"/api/v1".length) : _raw;

const api = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  // Without this, a request that goes out while the API container is
  // mid-restart (connection accepted but never answered, as opposed to a
  // fast connection-refused) hangs forever -- axios' default timeout is 0.
  // react-query's isLoading never flips to false, so every page sits on its
  // skeleton loader indefinitely until a manual hard refresh.
  timeout: 20_000,
});

// ─── Access-token cache ───────────────────────────────────────────────────────
// getSession() from next-auth/react is a NETWORK round-trip to
// /api/auth/session and is not cached. Calling it in the request interceptor
// meant every API call made an extra auth round-trip first: a dashboard page
// firing 8 queries did 8 sequential session fetches before any data request
// started. Each of those also runs the server-side jwt callback, which is
// where refresh happens — so 8 concurrent callbacks would race to rotate a
// single-use refresh token and kill the session.
//
// Cache the token in memory and decode its own exp to know when to refetch.
// `inflight` makes concurrent callers share one fetch (single-flight) rather
// than stampeding.

let cachedToken: string | null = null;
let cachedExp = 0; // ms epoch, decoded from the JWT
let inflight: Promise<string | null> | null = null;

/** Read `exp` out of a JWT payload without verifying it — we only need the
 *  expiry to decide when to refetch; the server is the one that validates. */
function decodeExp(jwt: string): number {
  try {
    const payload = jwt.split(".")[1];
    if (!payload) return 0;
    // base64url → base64 before atob
    const b64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const exp = JSON.parse(atob(b64)).exp;
    return typeof exp === "number" ? exp * 1000 : 0;
  } catch {
    return 0;
  }
}

/** Fallback cache lifetime for tokens we can't read an `exp` out of — opaque
 *  tokens, or the dev-only "demo"/"owner-bypass" sentinels. Without this,
 *  decodeExp() returns 0, the freshness check never passes, and we go
 *  straight back to a getSession() per request. */
const OPAQUE_TOKEN_TTL_MS = 60_000;

async function getToken(force = false): Promise<string | null> {
  // 30s skew so we never send a token that expires mid-flight
  if (!force && cachedToken && Date.now() < cachedExp - 30_000) return cachedToken;
  // `force` only means "don't trust the cached token's freshness" — it must
  // NOT skip in-flight dedup too. Without this, N concurrent 401s (e.g. every
  // request failing at once because the token just expired) each called
  // getToken(true) and each bypassed both fast paths, so N requests produced
  // N independent getSession() calls instead of sharing one. Reusing inflight
  // here regardless of force means a burst of forced callers still collapses
  // to a single fetch.
  if (inflight) return inflight;

  inflight = (async () => {
    const session = await getSession();
    const token = (session as { accessToken?: string } | null)?.accessToken ?? null;
    cachedToken = token;
    if (!token) {
      cachedExp = 0;
    } else {
      const exp = decodeExp(token);
      // +30s so the skew subtraction above still leaves a usable window
      cachedExp = exp > 0 ? exp : Date.now() + OPAQUE_TOKEN_TTL_MS + 30_000;
    }
    return token;
  })();

  try {
    return await inflight;
  } finally {
    inflight = null;
  }
}

/** Drop the cached token — call on sign-out so a subsequent sign-in as a
 *  different user can't reuse the previous session's token.
 *
 *  Also wipes the persisted react-query cache (Fix 4, PWA-blank-data-fix
 *  plan) -- Sharath's explicit PII scope decision was "persist everything,
 *  wipe on sign-out", so a device shared between staff (or simply
 *  recovered/resold) must never have one concierge's guest conversations,
 *  phone numbers, or call transcripts still readable in localStorage after
 *  they've signed out. queryClient.clear() empties the in-memory cache;
 *  removing the localStorage key directly is the belt-and-suspenders half,
 *  since the persister writes on a debounce and sign-out is immediately
 *  followed by navigation away. */
export function clearTokenCache() {
  cachedToken = null;
  cachedExp = 0;
  inflight = null;
  queryClient.clear();
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(QUERY_PERSIST_STORAGE_KEY);
    } catch {
      // Storage unavailable (private browsing, quota) -- in-memory clear above still applied.
    }
  }
}

api.interceptors.request.use(async (config) => {
  const token = await getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => {
    // A response came back at all -- the API is reachable. If ConnectionBanner
    // was showing "trouble connecting", clear it and refetch everything that
    // may have silently failed/gone stale during the outage, rather than
    // leaving pages stuck on whatever empty/error state they landed in.
    if (useConnectionStatusStore.getState().offline) {
      useConnectionStatusStore.getState().setOffline(false);
      queryClient.invalidateQueries();
    }
    return res;
  },
  async (error) => {
    const originalRequest = error.config;

    // No `error.response` means the request never got a reply at all --
    // network error, DNS failure, or (most relevant here) our own 20s
    // timeout firing while the API container is mid-restart. A 4xx/5xx
    // *with* a response means the server is up and answering, so that's
    // deliberately excluded here.
    if (!error.response) {
      useConnectionStatusStore.getState().setOffline(true);
    }

    // On 401: the JWT callback may have already refreshed the token — retry once.
    // Guard with _retry to prevent infinite loops.
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;

      // Force past the cache — the cached token is the one that just 401'd.
      const token = await getToken(true);
      const session = await getSession();

      // Only tear the whole session down when it is genuinely unrecoverable.
      // Previously ANY surviving 401 called signOut(), so a single
      // permission-denied endpoint or one bad widget query logged the user
      // out of the entire app.
      const sessionError = (session as { error?: string } | null)?.error;
      // Session-logout bug fix: a transient RefreshAccessTokenError gets the
      // same bounded grace period middleware.ts applies -- don't sign the
      // user out for a single failed refresh (a deploy's brief
      // container-restart window, a dropped connection) before the jwt
      // callback's own self-heal gets a chance on the next natural cycle.
      // SessionExpired (the deliberate 12h cutoff) is unaffected.
      const sessionErrorSince = (session as { errorSince?: number } | null)?.errorSince;
      const withinGrace = isWithinRefreshErrorGrace(sessionError, sessionErrorSince);
      const unrecoverable =
        !token && (!session || (sessionError === "RefreshAccessTokenError" && !withinGrace) || sessionError === "SessionExpired");

      if (unrecoverable) {
        clearTokenCache();
        signOut({ callbackUrl: "/login", redirect: true }).catch(() => {});
        // PWA-blank-data-fix plan, Fix 2: signOut()'s redirect is a
        // programmatic navigation fired from inside a promise chain --
        // mobile browsers are known to throttle/drop exactly that kind of
        // redirect on a page that was just resumed from background, which
        // is precisely when this branch is most likely to fire. A direct
        // location assignment isn't subject to the same throttling; only
        // fires if the soft redirect above hasn't already landed.
        setTimeout(() => {
          if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
            console.warn("[auth] hard redirect fallback fired -- signOut() redirect did not land in time");
            window.location.href = "/login";
          }
        }, 1500);
        return Promise.reject(error);
      }

      if (!token) {
        // No token but the session isn't dead — let the caller render an
        // error state rather than bouncing the user to /login.
        return Promise.reject(error);
      }

      originalRequest.headers = originalRequest.headers ?? {};
      originalRequest.headers.Authorization = `Bearer ${token}`;
      return api(originalRequest);
    }

    return Promise.reject(error);
  }
);

export default api;
