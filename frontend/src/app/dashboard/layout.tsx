import { Sidebar } from "@/components/layout/Sidebar";
import { MobileNav } from "@/components/layout/MobileNav";
import { MobileHeader } from "@/components/layout/MobileHeader";
import { TopBar } from "@/components/shell/TopBar";
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { DashboardSSEBridge } from "./DashboardSSEBridge";
import { FinishSetupBanner } from "./FinishSetupBanner";
import { BrandThemeProvider } from "@/components/providers/BrandThemeProvider";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session) redirect("/login");

  const user = session.user as {
    name?: string | null;
    email?: string | null;
    role?: string;
    organization_id?: string;
    onboarding_step?: number;
  };

  // Gate: require at least step 2 completed (brand + 1 property)
  const onboardingStep = user.onboarding_step ?? 0;
  if (onboardingStep < 2) {
    redirect("/onboarding");
  }

  // Steps 2–8 remain; show banner until all 9 are done
  const onboardingComplete = onboardingStep >= 9;

  return (
    <BrandThemeProvider>
      {/* ── Desktop layout ──────────────────────────────────────────── */}
      <div className="hidden md:flex h-screen overflow-hidden bg-gray-50">
        <Sidebar user={user} />
        <div className="flex-1 flex flex-col overflow-hidden">
          <TopBar user={user} />
          {!onboardingComplete && (
            <FinishSetupBanner currentStep={onboardingStep} />
          )}
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>
        <DashboardSSEBridge />
      </div>

      {/* ── Mobile layout ───────────────────────────────────────────── */}
      <div
        className="flex md:hidden flex-col bg-gray-50"
        style={{ minHeight: "100dvh" }}
      >
        <MobileHeader user={user} />
        {!onboardingComplete && (
          <FinishSetupBanner currentStep={onboardingStep} />
        )}
        <main
          className="flex-1 overflow-auto"
          style={{ paddingBottom: "calc(56px + env(safe-area-inset-bottom))" }}
        >
          {children}
        </main>
        <MobileNav user={user} />
        <DashboardSSEBridge />
      </div>
    </BrandThemeProvider>
  );
}
