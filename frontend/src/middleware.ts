import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Subdomains that map directly to a marketing page path.
// e.g. status.haip.app/ → /status, docs.haip.app/ → /docs
const SUBDOMAIN_MAP: Record<string, string> = {
  status: "/status",
  docs:   "/docs",
};

export default auth((req: NextRequest & { auth: any }) => {
  const { pathname } = req.nextUrl;
  const hostname = req.headers.get("host") ?? "";

  // ── Subdomain routing ──────────────────────────────────────────────────────
  // Extract the first label of the hostname (e.g. "status" from "status.haip.app")
  const subdomain = hostname.split(".")[0];
  if (subdomain && SUBDOMAIN_MAP[subdomain]) {
    const targetPath = SUBDOMAIN_MAP[subdomain];
    // Only rewrite the root — let /status/anything pass through normally
    if (pathname === "/") {
      const rewriteUrl = req.nextUrl.clone();
      rewriteUrl.pathname = targetPath;
      return NextResponse.rewrite(rewriteUrl);
    }
  }

  // A session with a dead refresh token (expired past 30 days, revoked by
  // A2's reuse-detection, or rotated server-side but the new token never
  // made it back into the client's cookie because the app process was
  // killed mid-request while backgrounded -- the PWA case) still has a
  // truthy req.auth object; only session.error distinguishes it. Checking
  // existence alone let the dashboard shell render fully (sidebar, topbar,
  // user name -- all readable straight off the still-valid JWT payload)
  // before every data query 401'd with no valid token to attach, which is
  // what produced the reported "blank/zero" PWA symptom.
  const isLoggedIn = !!req.auth && !req.auth.error;

  // ── Logged-in users ────────────────────────────────────────────────────────
  if (isLoggedIn) {
    // Send away from auth/marketing entry pages straight into the app.
    // (The multi-step /onboarding wizard was removed — signup collects
    // business type inline and lands directly on the dashboard.)
    if (pathname === "/" || pathname === "/login" || pathname === "/register" || pathname === "/onboarding") {
      return NextResponse.redirect(new URL("/dashboard", req.url));
    }
  }

  // ── Logged-out users ───────────────────────────────────────────────────────
  // Protect all /dashboard/* routes
  if (!isLoggedIn && pathname.startsWith("/dashboard")) {
    // PWA-blank-data-fix plan, Section 3: distinguish "never logged in" from
    // "session died server-side" in the logs -- this is the one signal that
    // proves the middleware gate is actually catching real dead-refresh-token
    // cases (and how often) rather than just existing in theory.
    if (req.auth?.error) {
      console.warn("[auth] middleware redirect: session.error =", req.auth.error, "path =", pathname);
    }
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
});

export const config = {
  // Run on these paths only — skip static files, _next internals, API routes
  matcher: [
    "/",
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/onboarding",
    "/dashboard/:path*",
  ],
};
