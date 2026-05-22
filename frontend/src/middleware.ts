import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export default auth((req: NextRequest & { auth: any }) => {
  const { pathname } = req.nextUrl;
  const isLoggedIn = !!req.auth;
  const onboardingStep: number = (req.auth?.user as any)?.onboarding_step ?? 0;
  const onboardingDone = onboardingStep >= 9;

  // ── Logged-in users ────────────────────────────────────────────────────────
  if (isLoggedIn) {
    // Send away from auth pages → into the app
    if (pathname === "/" || pathname === "/login" || pathname === "/register") {
      const dest = onboardingDone ? "/dashboard" : "/onboarding";
      return NextResponse.redirect(new URL(dest, req.url));
    }
    // Already finished onboarding → skip the onboarding page
    if (pathname === "/onboarding" && onboardingDone) {
      return NextResponse.redirect(new URL("/dashboard", req.url));
    }
  }

  // ── Logged-out users ───────────────────────────────────────────────────────
  // Protect all /dashboard/* and /onboarding routes
  if (!isLoggedIn && (pathname.startsWith("/dashboard") || pathname === "/onboarding")) {
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
