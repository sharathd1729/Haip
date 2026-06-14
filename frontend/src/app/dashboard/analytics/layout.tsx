import { DeprecationBanner } from "@/components/ui/DeprecationBanner";

export default function AnalyticsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col h-full">
      <DeprecationBanner message="These views are now available as dashboard widgets." href="/dashboard" />
      <div className="flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
