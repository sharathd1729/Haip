"use client";
import { Filter } from "@/lib/icons";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

/**
 * Mobile-only filter drawer — wraps the existing Sheet primitive (side=
 * "bottom") so Leads360/Calls/Bookings can each move their already-built
 * filter controls into a collapsed trigger on small screens instead of an
 * always-visible row that wraps across multiple lines. Desktop layouts are
 * untouched; this only renders where the trigger button itself is
 * (rendered `md:hidden` by each caller).
 */
export function MobileFilterSheet({
  open,
  onOpenChange,
  title = "Filters",
  hasActiveFilters,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  hasActiveFilters?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="max-h-[80dvh] overflow-y-auto rounded-t-2xl">
        <SheetHeader className="border-b border-[var(--haip-border)] pb-3">
          <SheetTitle className="flex items-center gap-2 font-[family-name:var(--font-display)] text-[18px] font-semibold">
            <Filter size={16} />
            {title}
            {hasActiveFilters && (
              <span className="size-2 rounded-full bg-primary" />
            )}
          </SheetTitle>
        </SheetHeader>
        <div className="pt-3 pb-2 flex flex-col gap-3">{children}</div>
      </SheetContent>
    </Sheet>
  );
}

/** The phone "Filters" button: a pill like the kit's FilterChip, tinted plum while any filter is on, so it reads as the
 * same family of control everywhere it appears. */
export function MobileFilterTrigger({
  onClick,
  hasActiveFilters,
  className,
}: {
  onClick: () => void;
  hasActiveFilters?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "md:hidden flex min-h-11 items-center gap-1.5 rounded-full border px-4 text-[14px] font-semibold transition-colors duration-150",
        hasActiveFilters
          ? "border-[color-mix(in_srgb,var(--primary)_35%,transparent)] bg-[var(--haip-primary-tint)] text-primary"
          : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-muted)]",
        className,
      )}
    >
      <Filter size={15} /> Filters
      {hasActiveFilters && <span className="size-2 rounded-full bg-primary" />}
    </button>
  );
}
