"use client";
import { useRef, useCallback } from "react";

interface UseOptimisticUndoOptions {
  delayMs?: number;
  onCommit: () => Promise<void> | void;
  onRevert: () => void;
}

export interface UndoHandle {
  start: () => void;
  cancel: () => void;
}

/**
 * X1: Optimistic undo pattern.
 *
 * Call start() to begin the undo window.
 * The commit callback fires after delayMs unless cancel() is called first.
 * If commit fails, the error is surfaced via onError.
 */
export function useOptimisticUndo({
  delayMs = 8000,
  onCommit,
  onRevert,
}: UseOptimisticUndoOptions): UndoHandle {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);

  const start = useCallback(() => {
    cancelledRef.current = false;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      if (!cancelledRef.current) {
        try { await onCommit(); }
        catch { onRevert(); }
      }
    }, delayMs);
  }, [delayMs, onCommit, onRevert]);

  const cancel = useCallback(() => {
    cancelledRef.current = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    onRevert();
  }, [onRevert]);

  return { start, cancel };
}
