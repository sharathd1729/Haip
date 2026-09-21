import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { isWithinRefreshErrorGrace } from "@/lib/authGrace";

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
  //
  // Session-logout bug fix: a bare `req.auth.error` used to redirect
  // immediately, even for a single transient RefreshAccessTokenError (most
  // likely during the exact container-restart window a deploy creates) --
  // booting the user before the jwt callback's own self-heal (it retries
  // on the very next natural refresh cycle) ever got a chance to run.
  // Tolerate that specific error for a bounded grace window instead;
  // SessionExpired (the deliberate 12h "not remembered" cutoff) still
  // redirects immediately, same as before -- there's nothing to self-heal.
  const withinGrace = isWithinRefreshErrorGrace(req.auth?.error, req.auth?.errorSince);
  const isLoggedIn = !!req.auth && (!req.auth.error || withinGrace);

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
  // Protect all /dashboard/* routes, plus /connect/* -- the OAuth consent
  // screen an AI app (Claude, ChatGPT) sends the user to.
  if (!isLoggedIn && (pathname.startsWith("/dashboard") || pathname.startsWith("/connect"))) {
    // PWA-blank-data-fix plan, Section 3: distinguish "never logged in" from
    // "session died server-side" in the logs -- this is the one signal that
    // proves the middleware gate is actually catching real dead-refresh-token
    // cases (and how often) rather than just existing in theory.
    if (req.auth?.error) {
      console.warn("[auth] middleware redirect: session.error =", req.auth.error, "path =", pathname);
    }
    const loginUrl = new URL("/login", req.url);
    // Keep the query string: the consent screen's OAuth params live there,
    // and dropping them strands the user after login.
    loginUrl.searchParams.set("callbackUrl", pathname + req.nextUrl.search);
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
    "/connect/:path*",
  ],
};
