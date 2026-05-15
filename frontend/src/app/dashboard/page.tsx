import { auth } from "@/lib/auth";
import { DashboardOverview } from "@/components/dashboard/overview";

export default async function DashboardPage() {
  const session = await auth();
  return <DashboardOverview user={session?.user} />;
}
