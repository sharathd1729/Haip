/**
 * Session-logout bug fix: a transient refresh failure (a deploy's brief
 * container-restart window cutting an in-flight `/auth/refresh` request,
 * or any momentary network blip) must not be treated as fatal the instant
 * it's first seen. The `jwt` callback (auth.ts) is already designed to
 * retry and self-heal on the *next* natural refresh cycle -- the backend
 * even tolerates a retried request within its own 60s reuse-grace window
 * (auth.py's `_REFRESH_GRACE_WINDOW_SECONDS`) by re-issuing a fresh working
 * pair instead of erroring. The bug was that middleware.ts/api.ts never
 * gave that self-heal a chance: they redirected/logged out on the very
 * first `session.error` sighting.
 *
 * This grace window is comfortably longer than the backend's own 60s
 * window (so a client retry that lands inside the backend's window still
 * has time to reach the app before this side gives up) and longer than any
 * realistic single refresh-retry cycle (auth.ts's REFRESH_RETRY_ATTEMPTS *
 * REFRESH_RETRY_DELAY_MS is ~1.8s worst case) -- it exists to cover the gap
 * between "this request's refresh failed" and "the next natural request
 * that will retry it", which depends on user navigation, not a fixed timer.
 *
 * Deliberately NOT applied to `SessionExpired` -- that's the "Keep me
 * signed in" 12h hard cutoff, a real, deliberate expiry with nothing to
 * self-heal (the jwt callback returns early there, before ever attempting
 * a refresh again).
 */
export const REFRESH_ERROR_GRACE_MS = 45_000;

export function isWithinRefreshErrorGrace(
  sessionError: string | undefined | null,
  errorSince: number | undefined | null,
): boolean {
  if (sessionError !== "RefreshAccessTokenError") return false;
  if (!errorSince) return false;
  return Date.now() - errorSince < REFRESH_ERROR_GRACE_MS;
}
