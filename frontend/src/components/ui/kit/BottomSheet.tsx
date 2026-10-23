"use client";
// A sheet that slides up from the bottom on a phone: a row's details without leaving the list, or the Filters for a list.
// Built on the Base UI dialog the app's Sheet uses, so focus is trapped inside, Esc closes it, the scrim closes it and focus
// goes back to whatever opened it. On top of that: drag the grab handle (or the header) down to close it.
// Motion is transform + opacity only, ~260ms, ease-out cubic-bezier(0.32,0.72,0,1); globals.css collapses it under
// prefers-reduced-motion. Max 88% of the screen tall; the body scrolls, the header and footer stay put.
import { useRef, type PointerEvent, type ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { X } from "@/lib/icons";
import { cn } from "@/lib/utils";

const EASE = "ease-[cubic-bezier(0.32,0.72,0,1)]";
/** How far (px) a drag must travel down before letting go closes the sheet. */
export const SWIPE_CLOSE_PX = 80;

export function BottomSheet({ open, onOpenChange, title, description, footer, children, className }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  /** Sticky action row (Collect / WhatsApp / Full page). */
  footer?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const popupRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ y: number; dy: number } | null>(null);

  // The drag moves the popup directly (no React state per pointer move) and snaps back unless it went far enough.
  const setOffset = (dy: number, animate: boolean) => {
    const el = popupRef.current;
    if (!el) return;
    el.style.transition = animate ? "" : "none";
    el.style.transform = dy > 0 ? `translateY(${dy}px)` : "";
  };
  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("button,a,input,select,textarea")) return;
    drag.current = { y: e.clientY, dy: 0 };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current.dy = Math.max(0, e.clientY - drag.current.y);
    setOffset(drag.current.dy, false);
  };
  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    setOffset(0, true);
    if (d.dy >= SWIPE_CLOSE_PX) onOpenChange(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={next => onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Backdrop
          className={cn("fixed inset-0 z-[70] bg-[color-mix(in_srgb,var(--haip-nav-bg)_40%,transparent)] transition-opacity duration-[260ms]", EASE,
            "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0")} />
        <Dialog.Popup ref={popupRef} data-slot="bottom-sheet"
          className={cn(
            "fixed inset-x-0 bottom-0 z-[70] flex max-h-[88dvh] flex-col rounded-t-[20px] bg-[var(--haip-card)] shadow-[var(--haip-shadow-lg)] outline-none",
            "transition-[transform,opacity] duration-[260ms]", EASE,
            "data-[starting-style]:translate-y-full data-[ending-style]:translate-y-full",
            className,
          )}>
          <div className="touch-none select-none px-4 pt-2" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
            data-testid="bottom-sheet-handle">
            <span aria-hidden className="mx-auto block h-1 w-10 rounded-full bg-[var(--haip-border-strong)]" />
            <div className="flex items-start gap-2 pb-2 pt-2">
              <div className="min-w-0 flex-1">
                <Dialog.Title className="font-[family-name:var(--font-display)] text-[17px] font-semibold leading-snug text-[var(--haip-fg)]">{title}</Dialog.Title>
                {description && <Dialog.Description className="mt-0.5 text-[13px] text-[var(--haip-fg-subtle)]">{description}</Dialog.Description>}
              </div>
              <Dialog.Close aria-label="Close" className="-mr-2 -mt-1 flex size-11 shrink-0 items-center justify-center rounded-xl text-[var(--haip-icon-neutral)] hover:bg-[var(--hover-bg)]">
                <X size={18} />
              </Dialog.Close>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4">{children}</div>
          {footer && (
            <div className="border-t border-[var(--haip-border)] px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">{footer}</div>
          )}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A label / value line inside a sheet ("Still due   ₹5,000"). `tone="due"` paints it in the money-due terracotta. */
export function SheetLine({ label, value, tone, strong }: { label: ReactNode; value: ReactNode; tone?: "due"; strong?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 border-t border-[var(--haip-border)] py-2.5 text-[14px] first:border-t-0",
      tone === "due" ? "text-[var(--haip-accent-ink)]" : "text-[var(--haip-fg-2)]")}>
      <span>{label}</span>
      <span className={cn("tabular-nums", strong || tone === "due" ? "font-bold" : "font-medium", tone !== "due" && strong && "text-[var(--haip-fg)]")}>{value}</span>
    </div>
  );
}

/** The big action buttons at the bottom of a sheet: up to three, equal width, 52px tall. */
export function SheetActions({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("grid auto-cols-fr grid-flow-col gap-2", className)}>{children}</div>;
}

export function sheetActionCls(primary?: boolean): string {
  return cn(
    "inline-flex min-h-[52px] flex-col items-center justify-center gap-0.5 rounded-xl px-2 text-[12.5px] font-bold transition-transform active:scale-[0.97] disabled:opacity-50",
    primary ? "bg-[var(--haip-action)] text-[var(--haip-on-action)]" : "border border-[var(--haip-border)] bg-[var(--haip-surface)] text-primary",
  );
}
