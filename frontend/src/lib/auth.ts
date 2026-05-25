import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const email = credentials?.email as string;
        const password = credentials?.password as string;
        const apiBase = process.env.BACKEND_URL
          ?? process.env.NEXT_PUBLIC_API_URL
          ?? "http://localhost:8000";

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
                onboardingStep: me.onboarding_step ?? 0,
                accessToken, refreshToken: "",
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

        // Demo bypass fallback (when backend is unavailable)
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
          return { id: `demo-${email}`, name: u.name, email, role: u.role, tenantId: "haip-villa", onboardingStep: 9, accessToken: "demo", refreshToken: "" };
        }
        // Owner fallback — real password, survives DB wipes
        if (email === "dasupatrunisharatchandra@gmail.com" && password === "Raina@1729") {
          return { id: "sharath-owner", name: "Sharath D.", email, role: "owner", tenantId: "haip-villa", onboardingStep: 9, accessToken: "demo", refreshToken: "" };
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
        token.onboardingStep = (user as any).onboardingStep ?? 0;
        token.accessToken = (user as any).accessToken;
        token.refreshToken = (user as any).refreshToken;
      }
      // updateSession({ onboarding_step: X }) calls — must update the JWT so
      // the new value survives a full page reload and server components see it
      if (trigger === "update" && (session as any)?.onboarding_step !== undefined) {
        token.onboardingStep = (session as any).onboarding_step;
      }
      return token;
    },
    async session({ session, token }) {
      session.user.id = token.id as string;
      session.user.role = token.role as string;
      session.user.tenantId = token.tenantId as string;
      session.user.onboarding_step = token.onboardingStep as number ?? 0;
      (session as any).accessToken = token.accessToken;
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
  session: { strategy: "jwt" },
});
