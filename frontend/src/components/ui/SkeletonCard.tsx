/**
 * SkeletonCard — animate-pulse placeholder matching a Leads360 pipeline card.
 *
 * Show while AI summary is generating or while the leads list is loading.
 * Skeleton shape mirrors the actual LeadCard content rows exactly.
 */
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface SkeletonCardProps {
  className?: string;
}

export function SkeletonCard({ className }: SkeletonCardProps) {
  return (
    <div
      className={cn("haip-card p-4 space-y-3", className)}
    >
      {/* Row 1: Guest name + source icon */}
      <div className="flex items-center justify-between">
        <Skeleton className="h-3.5 w-28 rounded" />
        <Skeleton className="h-5 w-5 rounded-md" />
      </div>

      {/* Row 2: Occasion pill + group type pill */}
      <div className="flex items-center gap-1.5">
        <Skeleton className="h-4 w-16 rounded-full" />
        <Skeleton className="h-4 w-12 rounded-full" />
      </div>

      {/* Row 3: Property name */}
      <Skeleton className="h-3 w-36 rounded" />

      {/* Row 4: Completeness bar */}
      <Skeleton className="h-1 w-full rounded-full" />

      {/* Row 5: Timestamp */}
      <Skeleton className="h-3 w-20 rounded" />

      {/* Row 6: Agent avatar + AI summary snippet */}
      <div className="flex items-start gap-2 pt-1">
        <Skeleton className="h-5 w-5 rounded-full flex-shrink-0" />
        <div className="flex-1 space-y-1.5">
          <Skeleton className="h-3 w-full rounded" />
          <Skeleton className="h-3 w-3/4 rounded" />
        </div>
      </div>
    </div>
  );
}

/** Renders N skeleton cards — use for the full loading state of a pipeline column. */
export function SkeletonCardList({ count = 3, className }: { count?: number; className?: string }) {
  return (
    <div className={cn("space-y-3", className)}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}
