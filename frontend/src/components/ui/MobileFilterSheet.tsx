"use client";
import { Filter } from "lucide-react";
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
      <SheetContent side="bottom" className="max-h-[80vh] overflow-y-auto rounded-t-2xl">
        <SheetHeader className="pb-3 border-b" style={{ borderColor: "var(--haip-border)" }}>
          <SheetTitle className="flex items-center gap-1.5">
            <Filter size={14} />
            {title}
            {hasActiveFilters && (
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--primary)" }} />
            )}
          </SheetTitle>
        </SheetHeader>
        <div className="pt-3 pb-2 flex flex-col gap-3">{children}</div>
      </SheetContent>
    </Sheet>
  );
}

/** Matches the Calls page's canonical header-button styling
 * (text-xs px-3 py-1.5 rounded-lg font-medium) so the mobile filter
 * trigger reads as the same family of control everywhere it appears. */
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
        "md:hidden flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors duration-150",
        className,
      )}
      style={hasActiveFilters
        ? { background: "color-mix(in srgb, var(--primary) 8%, transparent)", borderColor: "var(--primary)", color: "var(--primary)" }
        : { background: "transparent", borderColor: "var(--haip-border)", color: "var(--haip-fg-muted)" }}
    >
      <Filter size={12} /> Filters
      {hasActiveFilters && <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--primary)" }} />}
    </button>
  );
}
