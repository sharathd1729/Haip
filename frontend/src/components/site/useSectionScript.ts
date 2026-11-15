"use client";

import { useEffect, type RefObject } from "react";
import { animate, inView, scroll, stagger } from "framer-motion";

/**
 * Runs a section's behaviour script (ported from the approved mockup) once the section is mounted.
 * Every timer, frame, observer and listener the script makes goes through `ctx`, so unmounting (or React's
 * dev double-mount) stops all of it and puts the section's markup back as it was.
 */
export type SectionCtx = {
  reduce: boolean;
  Motion: {
    animate: typeof animate;
    inView: typeof inView;
    scroll: typeof scroll;
    stagger: typeof stagger;
  };
  setTimeout: (fn: () => void, ms?: number) => number;
  clearTimeout: (id: number | null | undefined) => void;
  setInterval: (fn: () => void, ms?: number) => number;
  clearInterval: (id: number | null | undefined) => void;
  raf: (fn: FrameRequestCallback) => number;
  io: (
    cb: IntersectionObserverCallback,
    opts?: IntersectionObserverInit,
  ) => IntersectionObserver;
  on: (
    el: EventTarget,
    type: string,
    fn: EventListenerOrEventListenerObject,
    opts?: boolean | AddEventListenerOptions,
  ) => void;
  cleanup: (fn: unknown) => void;
};

export function useSectionScript(
  ref: RefObject<HTMLElement | null>,
  init: (ctx: SectionCtx) => void,
) {
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const snapshot = root.innerHTML;
    const timeouts = new Set<number>();
    const intervals = new Set<number>();
    const frames = new Set<number>();
    const undo: Array<() => void> = [];
    const ctx: SectionCtx = {
      reduce: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      Motion: { animate, inView, scroll, stagger },
      setTimeout(fn, ms) {
        const id = window.setTimeout(() => {
          timeouts.delete(id);
          fn();
        }, ms);
        timeouts.add(id);
        return id;
      },
      clearTimeout(id) {
        if (id == null) return;
        window.clearTimeout(id);
        timeouts.delete(id);
      },
      setInterval(fn, ms) {
        const id = window.setInterval(fn, ms);
        intervals.add(id);
        return id;
      },
      clearInterval(id) {
        if (id == null) return;
        window.clearInterval(id);
        intervals.delete(id);
      },
      raf(fn) {
        const id = window.requestAnimationFrame((t) => {
          frames.delete(id);
          fn(t);
        });
        frames.add(id);
        return id;
      },
      io(cb, opts) {
        const o = new IntersectionObserver(cb, opts);
        undo.push(() => o.disconnect());
        return o;
      },
      on(el, type, fn, opts) {
        el.addEventListener(type, fn, opts);
        undo.push(() => el.removeEventListener(type, fn, opts));
      },
      cleanup(fn) {
        if (typeof fn === "function") undo.push(fn as () => void);
      },
    };
    try {
      init(ctx);
    } catch (err) {
      // A broken animation must never take the page down; the static markup stays readable.
      console.error("site section script failed", err);
    }
    return () => {
      timeouts.forEach((id) => window.clearTimeout(id));
      intervals.forEach((id) => window.clearInterval(id));
      frames.forEach((id) => window.cancelAnimationFrame(id));
      undo
        .splice(0)
        .reverse()
        .forEach((fn) => fn());
      root.innerHTML = snapshot;
    };
  }, [ref, init]);
}
