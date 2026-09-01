import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";

/** Decode a JWT payload without verifying the signature (safe — server only reads its own tokens). */
function getTokenExpiry(token: string): number {
  try {
    const payload = token.split(".")[1];
    const decoded = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    return (decoded.exp || 0) * 1000; // convert to ms
  } catch {
    return 0;
  }
}

type RefreshResult = {
  accessToken: string;
  refreshToken: string;
  accessTokenExpires: number;
  error?: string;
} | { error: string };

// Backend rotates refresh tokens on use (single-use). Concurrent requests
// (dashboard pages fire several in parallel) can each independently decide
// to refresh the same stale token; without dedup, only the first backend
// call succeeds and the rest get "revoked" 401s that poison the session.
// Cache in-flight refreshes per token so racing callers share one result.
const refreshPromises = new Map<string, Promise<RefreshResult>>();

async function refreshAccessToken(refreshToken: string): Promise<RefreshResult> {
  const inFlight = refreshPromises.get(refreshToken);
  if (inFlight) return inFlight;

  const promise = (async (): Promise<RefreshResult> => {
    const apiBase = (process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
    try {
      const res = await fetch(`${apiBase}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) {
        // Swallowed silently before -- every "keep me signed in" logout ever
        // reported showed up as a bare "RefreshAccessTokenError" with no way
        // to tell an unreachable BACKEND_URL apart from a genuinely revoked
        // refresh token. Log which apiBase was used and the real status/body
        // so the next occurrence is diagnosable from Vercel logs alone.
        const bodyText = await res.text().catch(() => "");
        console.error("[AUTH] token refresh failed", { apiBase, status: res.status, body: bodyText.slice(0, 300) });
        return { error: "RefreshAccessTokenError" };
      }
      const data = await res.json();
      return {
        accessToken: data.access_token,
        refreshToken: data.refresh_token ?? refreshToken,
        accessTokenExpires: getTokenExpiry(data.access_token),
      };
    } catch (e) {
      // A thrown fetch error (unreachable host, DNS failure, relative URL
      // rejected by Node's fetch) is exactly the class of bug that broke
      // "keep me signed in" on Vercel -- BACKEND_URL pointing nowhere real.
      console.error("[AUTH] token refresh threw", { apiBase, error: e instanceof Error ? e.message : String(e) });
      return { error: "RefreshAccessTokenError" };
    }
  })();

  refreshPromises.set(refreshToken, promise);
  try {
    return await promise;
  } finally {
    refreshPromises.delete(refreshToken);
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
        // Internal-only fields — never rendered as form inputs, only ever
        // passed programmatically by the login page once it has already
        // obtained real tokens directly from the backend (MFA challenge,
        // WhatsApp OTP verification).
        preAuthAccessToken: { label: "", type: "text" },
        preAuthRefreshToken: { label: "", type: "text" },
        // "Keep me signed in" — "0"/"1" string (Credentials fields are always
        // strings). Missing/anything-but-"0" defaults to remembered, matching
        // the login page's checkbox defaulting to checked.
        remember: { label: "", type: "text" },
      },
      async authorize(credentials) {
        const email = credentials?.email as string;
        const password = credentials?.password as string;
        const preAuthAccessToken = credentials?.preAuthAccessToken as string | undefined;
        const preAuthRefreshToken = credentials?.preAuthRefreshToken as string | undefined;
        const remember = credentials?.remember !== "0";
        const apiBase = process.env.BACKEND_URL
          ?? process.env.NEXT_PUBLIC_API_URL
          ?? "http://localhost:8000";

        // Tokens already obtained by the login page itself — e.g. after
        // completing an MFA challenge or WhatsApp OTP verification directly
        // against the backend. Trust them, just build the session from /me.
        if (preAuthAccessToken) {
          // A real backend-issued access token with no refresh token is a
          // session that can never refresh — it dies silently at 15 minutes
          // (the jwt callback can't refresh without a refresh token, and
          // will just keep returning the same expired access token forever
          // since it can't tell this apart from the intentional demo-bypass
          // case). Reject the sign-in here instead of minting it, so the
          // failure is visible at login time, not as a mysterious logout
          // 15 minutes later. This should never happen for the three real
          // pre-auth flows (password, MFA, WhatsApp OTP) — all three backend
          // endpoints they call always return a refresh_token — so reaching
          // this is a signal of response-schema drift, not a normal case.
          if (!preAuthRefreshToken) {
            console.error("[AUTH] pre-auth sign-in missing refresh token — rejecting to avoid an unrefreshable session");
            return null;
          }
          try {
            const meRes = await fetch(`${apiBase}/api/v1/auth/me`, {
              headers: { Authorization: `Bearer ${preAuthAccessToken}` },
            });
            if (!meRes.ok) return null;
            const me = await meRes.json();
            return {
              id: me.id, name: me.full_name ?? me.name, email: me.email,
              role: me.role, tenantId: me.tenant_id ?? "haip-villa",
              accessToken: preAuthAccessToken,
              refreshToken: preAuthRefreshToken,
              accessTokenExpires: getTokenExpiry(preAuthAccessToken),
              remember,
            };
          } catch (e) {
            console.error("[AUTH] pre-auth token session build failed:", e);
            return null;
          }
        }

        // Try real backend first (preferred — returns proper JWT for API calls)
        try {
          const loginUrl = `${apiBase}/api/v1/auth/login`;
          console.log("[AUTH] login attempt →", loginUrl, "for", email);
          const res = await fetch(loginUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
          });
          console.log("[AUTH] login response status:", res.status);
          if (res.ok) {
            const data = await res.json();
            if (data.mfa_required) {
              // This legacy branch can't complete an MFA challenge — callers
              // that need MFA support must use the login page's dedicated
              // flow (direct /auth/login call + preAuthAccessToken above).
              console.warn("[AUTH] mfa_required via legacy authorize() branch — rejecting");
              return null;
            }
            const accessToken = data.access_token;
            const meUrl = `${apiBase}/api/v1/auth/me`;
            console.log("[AUTH] calling me →", meUrl);
            const meRes = await fetch(meUrl, {
              headers: { Authorization: `Bearer ${accessToken}` },
            });
            console.log("[AUTH] me response status:", meRes.status);
            if (meRes.ok) {
              const me = await meRes.json();
              console.log("[AUTH] me data:", JSON.stringify(me).slice(0, 200));
              return {
                id: me.id, name: me.full_name ?? me.name, email: me.email,
                role: me.role, tenantId: me.tenant_id ?? "haip-villa",
                  accessToken,
                refreshToken: data.refresh_token ?? "",
                accessTokenExpires: getTokenExpiry(accessToken),
                remember,
              };
            } else {
              const errText = await meRes.text().catch(() => "");
              console.error("[AUTH] me failed:", meRes.status, errText);
            }
          } else {
            const errText = await res.text().catch(() => "");
            console.error("[AUTH] login failed:", res.status, errText);
          }
        } catch (e) {
          console.error("[AUTH] fetch error:", e);
        }

        // Demo bypass fallback (when backend is unavailable) — dev/staging only.
        // Never active in production, regardless of whether the backend is reachable.
        if (process.env.NODE_ENV !== "production") {
          const DEMO_USERS: Record<string, { name: string; role: string }> = {
            "owner@haip.dev":       { name: "Sharath D.",     role: "owner" },
            "manager@haip.dev":     { name: "Priya Menon",    role: "manager" },
            "concierge@haip.dev":   { name: "Ravi Kumar",     role: "concierge" },
            "reservations@haip.dev":{ name: "Ananya Singh",   role: "reservations" },
            "compliance@haip.dev":  { name: "Deepa Nair",     role: "compliance" },
            "sharath@ratha.in":             { name: "Sharath D.", role: "owner" },
            "dasupatrunisharatchandra@gmail.com": { name: "Sharath D.", role: "owner" },
          };
          if (password === "haip2026" && DEMO_USERS[email]) {
            const u = DEMO_USERS[email];
            return { id: `demo-${email}`, name: u.name, email, role: u.role, tenantId: "haip-villa", accessToken: "demo", refreshToken: "", remember };
          }
          // Owner fallback — real password, survives DB wipes
          if (email === "dasupatrunisharatchandra@gmail.com" && password === "Raina@1729") {
            return { id: "sharath-owner", name: "Sharath D.", email, role: "owner", tenantId: "haip-villa", accessToken: "owner-bypass", refreshToken: "", remember };
          }
        }
        return null;
      },
    }),
    ...(process.env.GOOGLE_CLIENT_ID
      ? [
          GoogleProvider({
            clientId: process.env.GOOGLE_CLIENT_ID!,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
          }),
        ]
      : []),
  ],
  callbacks: {
    async jwt({ token, user, trigger, session }) {
      // Initial sign-in — populate token from the authorize() return value
      if (user) {
        token.id = user.id;
        token.role = (user as any).role;
        token.tenantId = (user as any).tenantId;
        token.accessToken = (user as any).accessToken;
        token.refreshToken = (user as any).refreshToken ?? "";
        token.accessTokenExpires = (user as any).accessTokenExpires ?? 0;
        token.error = undefined;

        // "Keep me signed in" — default true (matches the login checkbox's
        // default-checked state). When false, the session gets a 12h hard
        // cutoff enforced below, independent of the access token's own
        // 15min expiry/refresh cycle. Deliberately NOT implemented as a
        // shorter cookie maxAge: the cookie's maxAge is a single top-level
        // NextAuth config value, not something that can vary per sign-in —
        // enforcing the cutoff inside the token itself is what lets the
        // same 30-day cookie hold either a remembered or a non-remembered
        // session.
        token.remember = (user as any).remember !== false;
        token.hardExpiry = token.remember ? undefined : Date.now() + 12 * 60 * 60 * 1000;

        // A real (non-demo/bypass) access token with no refresh token is a
        // session that can never refresh: it'll just keep returning the
        // same, increasingly-stale access token forever instead of either
        // refreshing or failing loudly. The authorize() pre-auth branch
        // already rejects this at sign-in time — this is a defense-in-depth
        // net for any other path (present or future) that might mint one.
        const at = token.accessToken as string ?? "";
        if (at && at !== "demo" && at !== "owner-bypass" && !token.refreshToken) {
          console.error("[AUTH] session_without_refresh_token", { userId: token.id });
        }
        return token;
      }

      // Not-remembered session past its 12h hard cutoff — stop here
      // regardless of token type (demo/bypass tokens never hit the refresh
      // logic below at all, so this has to be checked before that skip).
      if (token.hardExpiry && Date.now() > (token.hardExpiry as number)) {
        return { ...token, error: "SessionExpired" };
      }

      // Skip refresh for demo/bypass tokens — they don't have a real refresh_token
      const accessToken = token.accessToken as string ?? "";
      if (accessToken === "demo" || accessToken === "owner-bypass" || !token.refreshToken) {
        return token;
      }

      // Proactively refresh if token expires within 60 seconds
      const expires = (token.accessTokenExpires as number) || 0;
      if (Date.now() < expires - 60_000) {
        return token; // still valid
      }

      // Token is expired or about to expire — refresh it
      const refreshed = await refreshAccessToken(token.refreshToken as string);
      if ("error" in refreshed && !("accessToken" in refreshed)) {
        return { ...token, error: "RefreshAccessTokenError" };
      }
      const r = refreshed as { accessToken: string; refreshToken: string; accessTokenExpires: number };
      return {
        ...token,
        accessToken: r.accessToken,
        refreshToken: r.refreshToken,
        accessTokenExpires: r.accessTokenExpires,
        error: undefined,
      };
    },
    async session({ session, token }) {
      session.user.id = token.id as string;
      session.user.role = token.role as string;
      session.user.tenantId = token.tenantId as string;
      (session as any).accessToken = token.accessToken;
      (session as any).error = token.error;
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
  // 30 days — the outer bound for a "keep me signed in" session's cookie.
  // Deliberately a single fixed value, not varied per sign-in: a
  // non-remembered session is cut short by the in-token hardExpiry check
  // in the jwt callback (12h), not by a shorter cookie maxAge.
  session: { strategy: "jwt", maxAge: 30 * 24 * 60 * 60 },
  trustHost: true,
});
