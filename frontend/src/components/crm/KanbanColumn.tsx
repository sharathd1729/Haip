"use client";
import { cn } from "@/lib/utils";
import { KanbanCard, type KanbanCardData } from "./KanbanCard";

interface KanbanColumnProps {
  id: string;
  title: string;
  color: string; // Tailwind border color
  cards: KanbanCardData[];
  count: number;
  onCardClick?: (id: string) => void;
  onNoteClick?: (id: string, guestName: string) => void;  // K15
  onDrop?: (cardId: string, newStage: string) => void;
  onDragStart?: (cardId: string) => void;
  onDragEnd?: () => void;
  className?: string;
}

export function KanbanColumn({
  id,
  title,
  color,
  cards,
  count,
  onCardClick,
  onNoteClick,
  onDrop,
  onDragStart: notifyDragStart,
  onDragEnd: notifyDragEnd,
  className,
}: KanbanColumnProps) {
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const cardId = e.dataTransfer.getData("cardId");
    if (cardId) onDrop?.(cardId, id);
    notifyDragEnd?.();
  };

  const handleDragStart = (e: React.DragEvent, cardId: string) => {
    e.dataTransfer.setData("cardId", cardId);
    e.dataTransfer.effectAllowed = "move";
    notifyDragStart?.(cardId);
  };

  return (
    <div
      className={cn(
        "flex flex-col rounded-2xl min-w-[260px] max-w-[300px] flex-shrink-0",
        "bg-white/[0.03] dark:bg-white/[0.03] border border-white/[0.08]",
        "light:bg-gray-50/60 light:border-gray-100",
        className
      )}
      style={{ scrollSnapAlign: "start" }}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Column header */}
      <div className={cn(
        "px-4 py-3 border-b border-white/[0.08] flex items-center gap-2",
        color
      )}>
        <span className="text-sm font-bold text-foreground">{title}</span>
        <span className="ml-auto text-xs font-semibold text-muted-foreground bg-white/10 border border-white/10 rounded-full px-2 py-0.5">
          {count}
        </span>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {cards.map(card => (
          <div
            key={card.id}
            draggable
            onDragStart={e => handleDragStart(e, card.id)}
            onDragEnd={() => notifyDragEnd?.()}
          >
            <KanbanCard
              card={card}
              onClick={onCardClick}
              onNoteClick={onNoteClick}
              draggable={false} // drag handled by parent div
            />
          </div>
        ))}
        {cards.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-6">Drop inquiries here</p>
        )}
      </div>
    </div>
  );
}
