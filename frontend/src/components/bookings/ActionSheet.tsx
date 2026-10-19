"use client";
// A short task over the page (Filters, Collect, WhatsApp): a bottom sheet on a phone so thumbs reach it, a centred dialog from 768px.
// The header stays put and has a 44px close button; the body scrolls.
import type { ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { X } from "@/lib/icons";
import { cn } from "@/lib/utils";

export function ActionSheet({ open, onClose, title, children, className }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={o => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-[60] bg-black/45" />
        <Dialog.Popup
          className={cn(
            "fixed inset-x-0 bottom-0 z-[61] flex max-h-[92dvh] flex-col rounded-t-[20px] bg-[var(--haip-bg,var(--background))] outline-none",
            "md:inset-auto md:left-1/2 md:top-1/2 md:max-h-[86dvh] md:w-[min(560px,calc(100vw-48px))] md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-[20px]",
            className,
          )}>
          <div className="flex items-center justify-between gap-3 border-b border-[var(--haip-border)] px-4 py-2">
            <Dialog.Title className="min-w-0 truncate font-[family-name:var(--font-display)] text-[19px] font-semibold tracking-[-0.01em] text-[var(--haip-fg)]">
              {title}
            </Dialog.Title>
            <Dialog.Close aria-label="Close" className="flex size-11 shrink-0 items-center justify-center rounded-xl text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
              <X size={18} />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 space-y-3.5 overflow-y-auto px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-3.5">{children}</div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A choice chip inside a sheet (Filters): pressed = picked. 44px tall on touch screens. */
export function SheetChip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={cn("min-h-10 rounded-full border px-3.5 text-[14px] font-semibold pointer-coarse:min-h-11",
        on ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border-strong)] bg-[var(--haip-card)] text-[var(--haip-fg-2)]")}>
      {children}
    </button>
  );
}

/** One option of a two-way choice inside a sheet (Collect: link or record). */
export function SheetOption({ on, onClick, title, hint }: { on: boolean; onClick: () => void; title: ReactNode; hint?: ReactNode }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={cn("flex min-h-[52px] w-full flex-col items-start justify-center rounded-xl border bg-[var(--haip-card)] px-3 py-2 text-left text-[14.5px] text-[var(--haip-fg)]",
        on ? "border-primary ring-1 ring-inset ring-primary" : "border-[var(--haip-border)]")}>
      <span className="font-semibold">{title}</span>
      {hint && <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{hint}</span>}
    </button>
  );
}

export const sheetBtn = {
  primary: "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-50",
  secondary: "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-4 text-[14px] font-semibold text-[var(--haip-fg)] disabled:opacity-50",
};
export const sheetInput = "min-h-11 w-full rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary/30";
export const sheetLabel = "grid gap-1 text-[12.5px] font-semibold text-[var(--haip-fg-2)]";
