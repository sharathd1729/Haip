"use client";
// "Send quote": opens the rate calculator sheet prefilled from wherever the agent is. Shown only to roles that can quote
// (quotes.write default holders; the server re-checks) and only for a caravan workspace (unknown while loading = shown).
import type { MouseEvent } from "react";
import { useSession } from "next-auth/react";
import { Calculator } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { canWriteQuotes } from "@/lib/permissions";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";
import { useQuoteSheet } from "./QuoteSheetProvider";
import type { QuoteOpenArgs } from "./calc/types";

export function useCanQuote(): boolean {
  const { data: session } = useSession();
  const role = (session?.user as { role?: string } | undefined)?.role;
  const bt = useBusinessType();
  return canWriteQuotes(role) && (bt === null || bt === "caravan");
}

const VARIANT = {
  primary: "bg-primary text-primary-foreground hover:bg-[var(--haip-primary-hover)]",
  outline: "border border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]",
  link: "px-1 text-primary hover:underline",
} as const;

export function SendQuoteButton({ args, label = "Send quote", variant = "outline", iconOnlyBelowSm, className }: {
  args: QuoteOpenArgs; label?: string; variant?: keyof typeof VARIANT; iconOnlyBelowSm?: boolean; className?: string;
}) {
  const canQuote = useCanQuote();
  const sheet = useQuoteSheet();
  if (!canQuote) return null;
  const onClick = (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();                         // inside a clickable row or card: open the sheet, not the row
    sheet.open(args);
  };
  return (
    <button type="button" onClick={onClick} aria-label={iconOnlyBelowSm ? label : undefined}
      className={cn("inline-flex min-h-11 shrink-0 items-center justify-center gap-1.5 rounded-lg px-3 text-[13px] font-semibold transition-colors sm:min-h-9",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40", VARIANT[variant], className)}>
      <Calculator size={14} aria-hidden />
      <span className={cn(iconOnlyBelowSm && "hidden sm:inline")}>{label}</span>
    </button>
  );
}
