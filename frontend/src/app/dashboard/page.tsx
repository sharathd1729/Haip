"use client";
// Landing page after sign-in. Owners and managers get the Owner Command Center (leads, bookings and revenue on one
// page); every other role keeps the operations view they had, which scopes its numbers to the person.
import { useSession } from "next-auth/react";
import { Skeleton } from "@/components/ui/skeleton";
import { CommandCenter } from "@/components/dashboard/command/CommandCenter";
import { OperationsHome } from "@/components/dashboard/home/OperationsHome";

export default function DashboardPage() {
  const { data: session, status } = useSession();
  if (status === "loading") {
    return <div className="mx-auto max-w-[1360px] space-y-5 px-4 py-5 sm:px-6" aria-busy="true"><Skeleton className="h-10 w-72" /><Skeleton className="h-72 w-full" /></div>;
  }
  const role = session?.user?.role;
  return role === "owner" || role === "manager" ? <CommandCenter /> : <OperationsHome />;
}
