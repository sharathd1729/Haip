"use client";
// Phone or not, by the app's one breakpoint: below 768px (Tailwind `md`) is a phone. Same query the calendar's month grid uses.
// Starts false on the server and the first client render, so desktop markup hydrates unchanged; a phone switches right after
// mount. Pages use it to render their phone layout INSTEAD of the desktop one (never both), so desktop stays byte-for-byte.
import { useEffect, useState } from "react";

export const PHONE_QUERY = "(max-width: 767px)";

export function useIsPhone(): boolean {
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(PHONE_QUERY);
    const apply = () => setPhone(mq.matches);
    apply();
    mq.addEventListener?.("change", apply);
    return () => mq.removeEventListener?.("change", apply);
  }, []);
  return phone;
}
