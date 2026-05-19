"use client";
import { useEffect, RefObject } from "react";

export function useAutoGrow(ref: RefObject<HTMLTextAreaElement | null>, value: string, maxRows = 6) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const lineHeight = parseInt(getComputedStyle(el).lineHeight) || 20;
    const maxHeight = maxRows * lineHeight + 16; // +16 for padding
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [ref, value, maxRows]);
}
