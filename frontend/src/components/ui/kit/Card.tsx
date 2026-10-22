import type { ComponentType, HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

/** The one surface: white, green-bordered, softly lifted, themed radius. Use instead of ad-hoc `bg-white border rounded-*`. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("haip-card", className)} {...props} />;
}

export type CardHeaderTone = "band" | "olive" | "plain";

// Written out in full so Tailwind sees every class. The band's top corners follow the card's (radius + 4px, minus the border).
const HEADER_TONES: Record<CardHeaderTone, string> = {
  band: "mb-1 rounded-t-[calc(var(--radius)+3px)] border-b border-[var(--haip-band-border)] bg-[var(--haip-band-bg)] py-3 text-[var(--haip-band-fg)]",
  olive: "mb-1 rounded-t-[calc(var(--radius)+3px)] border-b border-[var(--haip-olive-border)] bg-[var(--haip-olive-bg)] py-3 text-[var(--haip-olive-fg)]",
  plain: "pb-1 pt-4 text-[var(--haip-fg)]",
};

/** Title row for a card: a tinted header band (mint by default, `tone="olive"` for the alternative, `tone="plain"` for the
 *  old borderless title) with an optional icon. `actions` sit on the right and wrap under the title on narrow screens.
 *  Put it first inside a `Card`. */
export function CardHeader({ title, description, actions, icon: Icon, tone = "band", className }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode;
  icon?: ComponentType<{ size?: number; className?: string }>; tone?: CardHeaderTone; className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-2 px-4 sm:px-5", HEADER_TONES[tone], className)}>
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        {Icon && <Icon size={18} className="shrink-0 opacity-90" />}
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-[family-name:var(--font-display)] text-[16px] font-semibold tracking-[-0.01em]">{title}</h2>
          {description && (
            <p className={cn("mt-0.5 text-[13px]", tone === "plain" ? "text-[var(--haip-fg-subtle)]" : "opacity-80")}>{description}</p>
          )}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-4 pb-4 pt-3 sm:px-5", className)} {...props} />;
}
