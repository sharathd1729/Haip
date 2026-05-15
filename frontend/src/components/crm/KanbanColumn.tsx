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
  onDrop?: (cardId: string, newStage: string) => void;
  className?: string;
}

export function KanbanColumn({
  id,
  title,
  color,
  cards,
  count,
  onCardClick,
  onDrop,
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
  };

  const handleDragStart = (e: React.DragEvent, cardId: string) => {
    e.dataTransfer.setData("cardId", cardId);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div
      className={cn(
        "flex flex-col bg-gray-50/60 rounded-2xl border border-gray-100 min-w-[260px] max-w-[300px]",
        className
      )}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Column header */}
      <div className={cn("px-4 py-3 border-b border-gray-100 flex items-center gap-2", color)}>
        <span className="text-sm font-bold text-gray-800">{title}</span>
        <span className="ml-auto text-xs font-semibold text-gray-500 bg-white border border-gray-200 rounded-full px-2 py-0.5">
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
          >
            <KanbanCard
              card={card}
              onClick={onCardClick}
              draggable={false} // drag handled by parent div
            />
          </div>
        ))}
        {cards.length === 0 && (
          <p className="text-xs text-gray-400 text-center py-6">Drop inquiries here</p>
        )}
      </div>
    </div>
  );
}
