"use client";
// The floating "New" button on phone pages that create things (a lead, a booking). Sits above the bottom tab bar (60px + the
// device's safe-area inset) at the right thumb, 56px, terracotta action colour. Phones only: hidden from md up, where the
// page header keeps its own "New" button.
import Link from "next/link";
import type { ComponentType } from "react";
import { Plus } from "@/lib/icons";
import { cn } from "@/lib/utils";

const CLS = cn(
  "fixed bottom-[calc(3.75rem+env(safe-area-inset-bottom)+1rem)] right-4 z-40 inline-flex size-14 items-center justify-center rounded-2xl md:hidden",
  "bg-[var(--haip-action)] text-[var(--haip-on-action)] shadow-[var(--haip-shadow-lg)] transition-transform active:scale-95",
  "outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
);

export function Fab({ label, onClick, href, icon: Icon = Plus, className }: {
  label: string; onClick?: () => void; href?: string; icon?: ComponentType<{ size?: number }>; className?: string;
}) {
  if (href) return <Link href={href} aria-label={label} title={label} className={cn(CLS, className)}><Icon size={24} /></Link>;
  return <button type="button" aria-label={label} title={label} onClick={onClick} className={cn(CLS, className)}><Icon size={24} /></button>;
}
