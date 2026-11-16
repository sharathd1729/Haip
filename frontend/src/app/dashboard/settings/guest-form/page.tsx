"use client";
// Settings › Business › Guest details form. The builder lives in components/ops/GuestFormBuilder.tsx; owners and managers
// edit (ops.manage on the server), everyone else with Ops access sees it read-only.
import { useSession } from "next-auth/react";
import { GuestFormBuilder } from "@/components/ops/GuestFormBuilder";

export default function GuestFormSettingsPage() {
  const role = (useSession().data?.user as { role?: string } | undefined)?.role;
  return <GuestFormBuilder canEdit={role === "owner" || role === "manager"} />;
}
