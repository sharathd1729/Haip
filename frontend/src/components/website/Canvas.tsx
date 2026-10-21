"use client";
// The live page inside the editor: the real site sections at a chosen device width, scaled to fit the pane.
// Clicking a section selects it. Outlines and labels compensate for the scale (site.css .hs-edit uses --s).
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { SiteRenderer } from "@/site-blocks/SiteRenderer";
import type { LiveData, Page, SiteEnv } from "@/site-blocks/types";

export const DEVICES = { desktop: 1200, tablet: 768, phone: 390 } as const;
export type Device = keyof typeof DEVICES;

export function Canvas({ live, page, env, device, selectedId, flash, onSelect, fit = true }: {
  live: LiveData; page: Page; env: SiteEnv; device: Device; selectedId: string | null; flash?: Set<string>;
  onSelect: (id: string) => void; fit?: boolean;
}) {
  const stage = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [height, setHeight] = useState(0);
  const width = DEVICES[device];

  useLayoutEffect(() => {
    const el = stage.current;
    if (!el) return;
    const measure = () => setScale(fit ? Math.min(1, (el.clientWidth - 24) / width) : 1);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [width, fit]);

  useEffect(() => {
    const el = inner.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setHeight(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!selectedId || !stage.current) return;
    const node = stage.current.querySelector<HTMLElement>(`[id="${CSS.escape(selectedId)}"]`);
    if (!node) return;
    const top = node.offsetTop * scale;
    const st = stage.current;
    if (top < st.scrollTop || top > st.scrollTop + st.clientHeight - 80) {
      st.scrollTo({ top: Math.max(0, top - 40), behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }, [selectedId, scale]);

  return (
    <div ref={stage} className="h-full min-h-0 overflow-auto bg-[var(--haip-surface)] p-3" aria-label="Page preview">
      <div style={{ width: width * scale, height: height * scale, margin: "0 auto", position: "relative" }}>
        <div ref={inner} style={{ width, transform: `scale(${scale})`, transformOrigin: "0 0", position: "absolute", left: 0, top: 0,
          ["--s" as string]: scale } as CSSProperties} className="overflow-hidden rounded-md shadow-[var(--haip-shadow-lg)]">
          <SiteRenderer live={live} page={page} env={env} sel={{ selectedId, flash, onSelect }} />
        </div>
      </div>
    </div>
  );
}
