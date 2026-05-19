"use client";
import { useEffect, useCallback } from "react";

type ShortcutHandler = (e: KeyboardEvent) => void;

interface Shortcut {
  key: string;
  meta?: boolean;
  ctrl?: boolean;
  shift?: boolean;
  /** If true, fires even when an input/textarea has focus */
  allowInInput?: boolean;
  handler: ShortcutHandler;
}

function isInputFocused(): boolean {
  const tag = (document.activeElement as HTMLElement)?.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/**
 * X2: Register global keyboard shortcuts.
 * Shortcuts are disabled when an input has focus, unless allowInInput is true.
 */
export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  const handleKey = useCallback((e: KeyboardEvent) => {
    for (const s of shortcuts) {
      if (s.key !== e.key) continue;
      if (s.meta  && !(e.metaKey || e.ctrlKey)) continue;
      if (s.ctrl  && !e.ctrlKey) continue;
      if (s.shift && !e.shiftKey) continue;
      if (!s.allowInInput && isInputFocused()) continue;
      e.preventDefault();
      s.handler(e);
      return;
    }
  }, [shortcuts]);

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);
}
