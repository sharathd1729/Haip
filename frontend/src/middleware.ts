import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { isWithinRefreshErrorGrace } from "@/lib/authGrace";
import { isYaadScreen } from "@/lib/authRedirect";

// Subdomains that map directly to a marketing page path.
// e.g. status.haip.app/ → /status, docs.haip.app/ → /docs
const SUBDOMAIN_MAP: Record<string, string> = {
  status: "/status",
  docs:   "/docs",
};

// Yaad's host and the pages it may show (its own screens plus the shared profile, help and phones pages).
const isYaadHost = (host: string) => host.split(":")[0].toLowerCase().startsWith("yaad.");
const YAAD_PATHS = ["/dashboard/me", "/dashboard/profile", "/dashboard/help", "/dashboard/settings/calls-app"];

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
  // The AI-assistant consent screen (/connect) gets no grace window: it
  // makes one authenticated call the moment it renders, with no later
  // refresh cycle to self-heal into -- a stale session there just shows an
  // error. Send it through login instead.
  const graceAllowed = withinGrace && !pathname.startsWith("/connect");
  const isLoggedIn = !!req.auth && (!req.auth.error || graceAllowed);

  // ── Yaad's own address (yaad.genhaip.com; yaad.localhost locally) ──────────
  // Only Yaad's screens and Yaad's sign-in live there: its own cookie, so a HAIP session in the same browser never mixes
  // in, and a HAIP page is never one click away. Anything else on that host goes back to Yaad.
  if (isYaadHost(hostname)) {
    const yaadPage = YAAD_PATHS.some(p => pathname === p || pathname.startsWith(p + "/"));
    // Redirects stay on the Yaad host (req.url can carry the upstream host behind nginx).
    const proto = req.headers.get("x-forwarded-proto") ?? req.nextUrl.protocol.replace(":", "");
    const here = (path: string) => new URL(path, `${proto}://${hostname}`);
    const entry = pathname === "/" || pathname === "/login" || pathname === "/register" || pathname === "/onboarding";
    if (!isLoggedIn && (entry || pathname.startsWith("/dashboard"))) {
      const loginUrl = here("/yaad/login");
      loginUrl.searchParams.set("callbackUrl", yaadPage ? pathname + req.nextUrl.search : "/dashboard/me");
      return NextResponse.redirect(loginUrl);
    }
    if (isLoggedIn && !req.auth?.error && (entry || pathname === "/yaad/login" || pathname === "/yaad/signup")) {
      return NextResponse.redirect(here("/dashboard/me"));
    }
    if (pathname.startsWith("/dashboard") && !yaadPage) return NextResponse.redirect(here("/dashboard/me"));
    return NextResponse.next();
  }

  // ── Logged-in users ────────────────────────────────────────────────────────
  if (isLoggedIn) {
    // Send away from auth/marketing entry pages straight into the app.
    // (The multi-step /onboarding wizard was removed — signup collects
    // business type inline and lands directly on the dashboard.)
    // Only a clean session is bounced off the entry pages: one that is
    // riding out a refresh error must be able to stay on /login and sign in
    // again, otherwise any disagreement with a server-side check becomes a
    // redirect loop (ERR_TOO_MANY_REDIRECTS).
    if (!req.auth?.error && (pathname === "/" || pathname === "/login" || pathname === "/register" || pathname === "/onboarding")) {
      return NextResponse.redirect(new URL("/dashboard", req.url));
    }
    // Yaad's own sign-in / sign-up: a signed-in person goes straight to their calls.
    if (!req.auth?.error && (pathname === "/yaad/login" || pathname === "/yaad/signup")) {
      return NextResponse.redirect(new URL("/dashboard/me", req.url));
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
    // Yaad's screens (the Yaad app opens /dashboard/me) sign in on Yaad's own page.
    const loginUrl = new URL(isYaadScreen(pathname) ? "/yaad/login" : "/login", req.url);
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
    "/yaad/:path*",
    "/dashboard/:path*",
    "/connect/:path*",
  ],
};
