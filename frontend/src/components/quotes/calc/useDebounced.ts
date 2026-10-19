"use client";
import { useEffect, useState } from "react";

/** `value`, but only after it stopped changing for `ms` (live pricing and search without a request per keystroke). */
export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
