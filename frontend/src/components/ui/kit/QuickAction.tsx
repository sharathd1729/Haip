"use client";
// A labelled 44px pill for a phone page's "make something" actions (New lead, Log a call). A floating "+"
// alone was missed (owner feedback after release #92), so phone pages also name the action in words where people look.
import type { ComponentType, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function QuickAction({ icon: Icon, children, onClick, primary, className }: {
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean }>; children: ReactNode; onClick: () => void; primary?: boolean; className?: string;
}) {
  return (
    <button type="button" onClick={onClick}
      className={cn("inline-flex min-h-11 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 text-[13.5px] font-semibold transition-transform active:scale-[0.97]",
        primary ? "bg-[var(--haip-action)] text-[var(--haip-on-action)]"
          : "border border-[var(--haip-btn-secondary-border)] bg-[var(--haip-btn-secondary-bg)] text-[var(--haip-btn-secondary-fg)]",
        className)}>
      <Icon size={16} aria-hidden />{children}
    </button>
  );
}
