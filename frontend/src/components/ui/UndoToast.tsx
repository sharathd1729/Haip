"use client";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";

interface UndoToastProps {
  message: string;
  delayMs?: number;
  onUndo: () => void;
  onDismiss: () => void;
}

export function UndoToast({ message, delayMs = 8000, onUndo, onDismiss }: UndoToastProps) {
  const [remaining, setRemaining] = useState(Math.ceil(delayMs / 1000));

  useEffect(() => {
    if (remaining <= 0) { onDismiss(); return; }
    const t = setTimeout(() => setRemaining(r => r - 1), 1000);
    return () => clearTimeout(t);
  }, [remaining, onDismiss]);

  const pct = (remaining / Math.ceil(delayMs / 1000)) * 100;

  return (
    <div className={cn(
      "fixed bottom-6 left-1/2 -translate-x-1/2 z-[100]",
      "bg-gray-900 text-white rounded-2xl shadow-2xl overflow-hidden",
      "min-w-[280px] max-w-sm"
    )}>
      {/* Countdown bar */}
      <div className="h-0.5 bg-gray-700">
        <div
          className="h-full bg-indigo-400 transition-all duration-1000 ease-linear"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex items-center gap-3 px-4 py-3">
        <span className="text-sm flex-1">{message}</span>
        <button
          onClick={() => { onUndo(); onDismiss(); }}
          className="text-sm font-bold text-indigo-400 hover:text-indigo-300 transition-colors flex-shrink-0"
        >
          Undo
        </button>
        <button onClick={onDismiss} className="text-gray-400 hover:text-white transition-colors flex-shrink-0">
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
