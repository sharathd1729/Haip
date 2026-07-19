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

  const isLoggedIn = !!req.auth;

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
