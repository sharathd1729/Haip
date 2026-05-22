import { Sidebar } from "@/components/layout/Sidebar";
import { MobileNav } from "@/components/layout/MobileNav";
import { MobileHeader } from "@/components/layout/MobileHeader";
import { TopBar } from "@/components/shell/TopBar";
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { DashboardSSEBridge } from "./DashboardSSEBridge";
import { DashboardClientShell, StatusBarSlot } from "@/components/dashboard/DashboardClientShell";
import { SampleDataBanner } from "@/components/dashboard/SampleDataBanner";
import { FinishSetupBanner } from "./FinishSetupBanner";
import { BrandThemeProvider } from "@/components/providers/BrandThemeProvider";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session) redirect("/login");

  const user = session.user as {
    name?: string | null;
    email?: string | null;
    role?: string;
    tenantId?: string;
    onboarding_step?: number;
  };

  const onboardingStep = user.onboarding_step ?? 0;
  // NOTE: Do NOT hard-redirect to /onboarding here. The JWT value is cached
  // and may be stale for existing accounts. The FinishSetupBanner shows an
  // inline prompt for users with incomplete setup instead of blocking them.
  const onboardingComplete = onboardingStep >= 9;

  return (
    <BrandThemeProvider>
      {/*
        Single layout — children render exactly once.
        Shell elements (sidebar, topbar, bottom nav) are shown/hidden via CSS.
      */}
      <div
        className="flex bg-gray-50 dark:bg-gray-950"
        style={{ minHeight: "100dvh", maxHeight: "100dvh", overflow: "hidden" }}
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

          {/* Health status bar (X8) — visible only when degraded */}
          <StatusBarSlot />

          {/* Sample data banner (O2) — amber strip when viewing sample data */}
          <SampleDataBanner />

          {/* Setup banner (both breakpoints) */}
          {!onboardingComplete && (
            <FinishSetupBanner currentStep={onboardingStep} />
          )}

          {/* Page content — scrollable, padded for mobile bottom nav */}
          <main
            className="flex-1 overflow-y-auto"
            style={{ paddingBottom: "calc(env(safe-area-inset-bottom))" }}
          >
            {/* Extra bottom padding on mobile so content clears the bottom nav */}
            <div className="md:pb-0 pb-20">
              {children}
            </div>
          </main>
        </div>

        {/* ── Mobile bottom nav (fixed, outside flow) ─────────────── */}
        <MobileNav user={user} />
      </div>

      {/* SSE bridge — rendered once, outside layout columns */}
      <DashboardSSEBridge />

      {/* Client-side overlays: CommandPalette, StatusBar, ChecklistWidget */}
      <DashboardClientShell />
    </BrandThemeProvider>
  );
}
