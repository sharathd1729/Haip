import { Sidebar } from "@/components/layout/Sidebar";
import { MobileNav } from "@/components/layout/MobileNav";
import { MobileHeader } from "@/components/layout/MobileHeader";
import { TopBar } from "@/components/shell/TopBar";
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { isWithinRefreshErrorGrace } from "@/lib/authGrace";
import { DashboardSSEBridge } from "./DashboardSSEBridge";
import { DashboardClientShell, StatusBarSlot } from "@/components/dashboard/DashboardClientShell";
import { SampleDataBanner } from "@/components/dashboard/SampleDataBanner";
import { BrandThemeProvider } from "@/components/providers/BrandThemeProvider";
import { WorkspaceProvider } from "@/components/providers/WorkspaceProvider";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  // A session whose refresh token died (expired, revoked by reuse-detection,
  // or rotated server-side but never persisted client-side -- the PWA
  // resume case) still passes `!!session`; only session.error distinguishes
  // it. Missing this let the full shell (sidebar, topbar, user name -- all
  // readable off the still-valid JWT payload) render before every data
  // query 401'd, which is what produced the reported blank/zero PWA state.
  //
  // Must use the SAME grace rule as middleware.ts. Middleware treats a
  // RefreshAccessTokenError inside its grace window as still logged in and
  // bounces /login -> /dashboard; if this layout then bounced /dashboard ->
  // /login on any error, the two looped until the browser gave up with
  // ERR_TOO_MANY_REDIRECTS (seen right after deploys, when a refresh fails).
  const s = session as { error?: string; errorSince?: number } | null;
  if (!session || !s || (s.error && !isWithinRefreshErrorGrace(s.error, s.errorSince))) {
    console.warn("[auth] dashboard layout redirect: session.error =", (session as { error?: string } | null)?.error ?? "no session");
    redirect("/login");
  }

  const user = session.user as {
    name?: string | null;
    email?: string | null;
    role?: string;
    tenantId?: string;
  };

  return (
    <BrandThemeProvider>
    <WorkspaceProvider>
      {/*
        Single layout — children render exactly once.
        Shell elements (sidebar, topbar, bottom nav) are shown/hidden via CSS.
      */}
      <div
        className="flex"
        style={{
          minHeight: "100dvh",
          maxHeight: "100dvh",
          overflow: "hidden",
          // Grey app canvas so white cards read as raised surfaces. Scoped
          // here rather than on --background, which stays white for the
          // marketing site and auth pages.
          background: "var(--haip-app-bg)",
        }}
      >
        {/* ── Sidebar (desktop only) ───────────────────────────────── */}
        <div className="hidden md:flex flex-shrink-0">
          <Sidebar user={user} />
        </div>

        {/* ── Main column ─────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Desktop topbar */}
          <div className="hidden md:block">
            <TopBar user={user} />
          </div>

          {/* Mobile header */}
          <div className="md:hidden">
            <MobileHeader user={user} />
          </div>

          {/* Health status bar (X8) — visible only when degraded; desktop
              only, it took too much room above the content on phones. */}
          <div className="hidden md:block">
            <StatusBarSlot />
          </div>

          {/* Sample data banner (O2) — amber strip when viewing sample data */}
          <SampleDataBanner />

          {/* Page content — flex column so children can use h-full */}
          <main
            className="flex-1 overflow-hidden flex flex-col"
          >
            {/* Scroll wrapper — flex-1 gives it a defined height for h-full children. On phones the fixed bottom tab bar
                (48px + the device's safe-area inset) sits over the bottom of the viewport, so the content ends above it. */}
            <div className="flex-1 overflow-y-auto overscroll-contain min-h-0 pb-[calc(3rem+env(safe-area-inset-bottom))] md:pb-0">
              {children}
            </div>
          </main>
        </div>

        {/* ── Mobile bottom nav (fixed, outside flow) ─────────────── */}
        <MobileNav user={user} />
      </div>

      {/* SSE bridge — rendered once, outside layout columns */}
      <DashboardSSEBridge />

      {/* Client-side overlays: CommandPalette, StatusBar */}
      <DashboardClientShell />
    </WorkspaceProvider>
    </BrandThemeProvider>
  );
}
