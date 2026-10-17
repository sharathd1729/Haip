import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

/** The one surface: bordered, softly lifted, themed radius. Use instead of ad-hoc `bg-white border rounded-*`. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("haip-card", className)} {...props} />;
}

/** Title row for a card. `actions` sit on the right and wrap under the title on narrow screens. */
export function CardHeader({ title, description, actions, className }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-start gap-x-3 gap-y-2 px-4 pb-1 pt-4 sm:px-5", className)}>
      <div className="min-w-0 flex-1">
        <h2 className="truncate font-[family-name:var(--font-display)] text-[16px] font-semibold tracking-[-0.01em] text-[var(--haip-fg)]">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] text-[var(--haip-fg-subtle)]">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-4 pb-4 pt-3 sm:px-5", className)} {...props} />;
}
