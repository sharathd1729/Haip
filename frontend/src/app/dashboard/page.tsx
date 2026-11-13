"use client";
// Landing page after sign-in. Owners and managers get the Owner Command Center (leads, bookings and revenue on one
// page); every other role keeps the operations view they had, which scopes its numbers to the person. A personal call
// workspace (one person's own calls) goes straight to its Calls page.
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { Skeleton } from "@/components/ui/skeleton";
import { CommandCenter } from "@/components/dashboard/command/CommandCenter";
import { OperationsHome } from "@/components/dashboard/home/OperationsHome";
import { PERSONAL_HOME } from "@/components/layout/nav";
import { useWorkspace } from "@/components/providers/WorkspaceProvider";

export default function DashboardPage() {
  const { data: session, status } = useSession();
  const workspace = useWorkspace();
  const router = useRouter();
  const personal = workspace?.mode === "personal";
  useEffect(() => {
    if (personal) router.replace(PERSONAL_HOME);
  }, [personal, router]);
  // Not waiting on the workspace context: if it fails to load, business users must still get their home.
  if (status === "loading" || personal) {
    return <div className="mx-auto max-w-[1360px] space-y-5 px-4 py-5 sm:px-6" aria-busy="true"><Skeleton className="h-10 w-72" /><Skeleton className="h-72 w-full" /></div>;
  }
  const role = session?.user?.role;
  return role === "owner" || role === "manager" ? <CommandCenter /> : <OperationsHome />;
}
