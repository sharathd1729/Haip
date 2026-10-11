"use client";
import type { ReactNode } from "react";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

/** Side panel for a record (booking, lead, call). A bottom sheet on phones so thumbs reach the actions,
 *  a right-hand panel from `sm` up. Header and footer stay put; the body scrolls. */
export function Drawer({ open, onOpenChange, title, description, footer, children, wide, className }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  /** Wider panel for records with tabs or tables. */
  wide?: boolean;
  className?: string;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className={cn(
          "flex w-full flex-col gap-0 p-0",
          // phones: full width, capped height from the bottom edge feels like a sheet; sm+: side panel
          wide ? "sm:max-w-2xl" : "sm:max-w-md",
          className,
        )}
      >
        <SheetHeader className="border-b border-[var(--haip-border)] px-5 py-4 pr-12 text-left">
          <SheetTitle className="text-[15px] font-bold">{title}</SheetTitle>
          {description && <SheetDescription>{description}</SheetDescription>}
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <SheetFooter className="border-t border-[var(--haip-border)] px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            {footer}
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}
