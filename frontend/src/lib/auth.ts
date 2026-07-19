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
      if (!res.ok) return { error: "RefreshAccessTokenError" };
      const data = await res.json();
      return {
        accessToken: data.access_token,
        refreshToken: data.refresh_token ?? refreshToken,
        accessTokenExpires: getTokenExpiry(data.access_token),
      };
    } catch {
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
      },
      async authorize(credentials) {
        const email = credentials?.email as string;
        const password = credentials?.password as string;
        const preAuthAccessToken = credentials?.preAuthAccessToken as string | undefined;
        const preAuthRefreshToken = credentials?.preAuthRefreshToken as string | undefined;
        const apiBase = process.env.BACKEND_URL
          ?? process.env.NEXT_PUBLIC_API_URL
          ?? "http://localhost:8000";

        // Tokens already obtained by the login page itself — e.g. after
        // completing an MFA challenge or WhatsApp OTP verification directly
        // against the backend. Trust them, just build the session from /me.
        if (preAuthAccessToken) {
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
              refreshToken: preAuthRefreshToken ?? "",
              accessTokenExpires: getTokenExpiry(preAuthAccessToken),
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
            return { id: `demo-${email}`, name: u.name, email, role: u.role, tenantId: "haip-villa", accessToken: "demo", refreshToken: "" };
          }
          // Owner fallback — real password, survives DB wipes
          if (email === "dasupatrunisharatchandra@gmail.com" && password === "Raina@1729") {
            return { id: "sharath-owner", name: "Sharath D.", email, role: "owner", tenantId: "haip-villa", accessToken: "owner-bypass", refreshToken: "" };
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
        return token;
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
  session: { strategy: "jwt" },
  trustHost: true,
});
