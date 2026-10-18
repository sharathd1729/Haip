"use client";
// One before / after tile: the owner-entered (or HAIP-measured) "before" figure, the measured "with HAIP" figure, the change,
// and what the number counts. Every figure says its period; a missing baseline shows no change at all.
import { useId, useState } from "react";
import { Info } from "lucide-react";
import { StatusPill } from "@/components/ui/kit";
import { formatChange, formatPeriod, formatValue, type Tile } from "./types";

export function ImpactTile({ tile }: { tile: Tile }) {
  const [open, setOpen] = useState(false);
  const defId = useId();
  const header = (
    <div className="flex items-start gap-2">
      <p className="min-w-0 flex-1 text-[13px] font-medium text-[var(--haip-fg-muted)]">{tile.label}</p>
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open} aria-controls={defId} title={tile.definition}
        aria-label={`What "${tile.label}" counts`}
        className="-m-2 flex size-11 shrink-0 items-center justify-center rounded-full text-[var(--haip-icon-neutral)] hover:bg-[var(--hover-bg)] sm:size-8 sm:m-0">
        <Info size={15} />
      </button>
    </div>
  );
  const definition = open && <p id={defId} className="mt-2 rounded-lg bg-[var(--haip-surface)] p-2.5 text-[12.5px] leading-relaxed text-[var(--haip-fg-subtle)]">{tile.definition}</p>;

  if (tile.restricted) {
    return (
      <div className="haip-card min-w-0 px-4 py-4">
        {header}
        <p className="mt-2 text-[13.5px] text-[var(--haip-fg-subtle)]">Needs revenue access to show.</p>
        {definition}
      </div>
    );
  }

  const { owner, measured } = tile.before;
  const beforeValue = owner ? owner.value : measured.value;
  const change = formatChange(tile.change);
  return (
    <div className="haip-card min-w-0 px-4 py-4">
      {header}
      <div className="mt-2 grid grid-cols-2 gap-3">
        <div className="min-w-0">
          <p className="text-[11.5px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Before HAIP</p>
          <p className="mt-1 font-[family-name:var(--font-display)] text-[22px] font-semibold leading-none tabular-nums text-[var(--haip-fg-muted)] [overflow-wrap:anywhere]">
            {formatValue(beforeValue, tile.unit)}
          </p>
          <p className="mt-1.5 text-[12px] leading-snug text-[var(--haip-fg-subtle)]">
            {owner ? <>Owner-entered · {owner.period_label}</>
              : measured.value != null ? <>Measured by HAIP · {formatPeriod(measured.period)}{measured.n != null && ` · ${measured.n} items`}</>
              : <>Not entered yet</>}
          </p>
        </div>
        <div className="min-w-0">
          <p className="text-[11.5px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">With HAIP</p>
          <p className="mt-1 font-[family-name:var(--font-display)] text-[22px] font-semibold leading-none tabular-nums text-[var(--haip-fg)] [overflow-wrap:anywhere]">
            {formatValue(tile.with.value, tile.unit)}
          </p>
          <p className="mt-1.5 text-[12px] leading-snug text-[var(--haip-fg-subtle)]">
            {formatPeriod(tile.with.period)}{tile.with.n != null && ` · ${tile.with.n} items`}
          </p>
        </div>
      </div>
      <div className="mt-3 flex min-h-5 flex-wrap items-center gap-2">
        {change
          ? <><StatusPill tone={change.tone}>{change.text}</StatusPill>
              <span className="text-[12px] text-[var(--haip-fg-subtle)]">vs {tile.change_against === "owner_entered" ? "owner-entered" : "measured"} before</span></>
          : <span className="text-[12px] text-[var(--haip-fg-subtle)]">No change shown: nothing to compare with yet</span>}
      </div>
      {definition}
    </div>
  );
}
