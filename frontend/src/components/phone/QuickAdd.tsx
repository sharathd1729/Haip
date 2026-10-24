"use client";
// "New lead" on the phone Leads page: opens the EXISTING AddLeadModal (POST /leads, the same form as the desktop Add Lead
// button). The floating "+" alone was missed on phones (owner feedback after release #92), so the action is named in words.
import { useState } from "react";
import dynamic from "next/dynamic";
import { Plus } from "@/lib/icons";
import { QuickAction } from "@/components/ui/kit";

const AddLeadModal = dynamic(() => import("@/components/leads/AddLeadModal").then(m => m.AddLeadModal), { ssr: false });

export function NewLeadAction({ primary, className }: { primary?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <QuickAction icon={Plus} primary={primary} className={className} onClick={() => setOpen(true)}>New lead</QuickAction>
      {open && <AddLeadModal onClose={() => setOpen(false)} onCreated={() => setOpen(false)} />}
    </>
  );
}
