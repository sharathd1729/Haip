"use client";
// The blocks you can add, grouped like SMS9. Drag one onto the canvas, or tap it to add it under the selected block.
import { cn } from "@/lib/utils";
import { BLOCKS, BLOCK_GROUPS } from "./flowModel";
import { iconFor } from "./FlowNodeCard";

export const DRAG_BLOCK = "application/x-haip-flow-block";

export function BlockPalette({ onAdd, className }: { onAdd: (key: string) => void; className?: string }) {
  return (
    <div className={cn("space-y-4", className)}>
      {BLOCK_GROUPS.map(group => (
        <section key={group}>
          <h3 className="mb-1.5 text-[11.5px] font-bold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{group}</h3>
          <div className="grid grid-cols-2 gap-1.5">
            {BLOCKS.filter(b => b.group === group).map(b => {
              const Icon = iconFor(b.make());
              return (
                <button key={b.key} type="button" draggable
                  onDragStart={e => { e.dataTransfer.setData(DRAG_BLOCK, b.key); e.dataTransfer.effectAllowed = "copy"; }}
                  onClick={() => onAdd(b.key)}
                  className="flex min-h-11 cursor-grab items-center gap-2 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-left text-[13px] font-medium text-[var(--haip-fg-2)] transition-colors hover:border-primary hover:bg-[var(--haip-primary-tint)] active:cursor-grabbing">
                  <Icon size={15} className="shrink-0 text-[var(--haip-fg-subtle)]" />
                  <span className="truncate">{b.label}</span>
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
