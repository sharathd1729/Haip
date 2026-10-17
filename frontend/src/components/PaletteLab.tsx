"use client";
// Palette lab: try the candidate colour combinations (app/palette-lab.css) on the real app. Per browser only: the choice is kept
// in localStorage and applied as <html data-palette="...">; nothing is saved to the workspace and no other viewer is affected.
// The picker shows in development, or in any environment after visiting a page once with ?palette=lab (?palette=off hides it
// and goes back to the shipped theme). ?palette=<id> picks one directly, which is how the comparison screenshots are taken.
// Swatch colours are written out as classes on purpose: this is a throwaway tool, deleted with palette-lab.css once a palette wins.
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const PALETTES = [
  { id: "",         name: "Shipped (plum)",       main: "bg-[#5A2D6B]", hl: "bg-[#D9930D]" },
  { id: "emerald",  name: "A · Emerald & Marigold", main: "bg-[#047857]", hl: "bg-[#D9930D]" },
  { id: "seagreen", name: "B · Sea Green & Coral",  main: "bg-[#1E7A5A]", hl: "bg-[#E0694A]" },
  { id: "cyan",     name: "C · Ocean Cyan & Sand",  main: "bg-[#0E7490]", hl: "bg-[#C98A3E]" },
  { id: "lagoon",   name: "D · Lagoon",             main: "bg-[#16775F]", hl: "bg-[#0891B2]" },
] as const;
const IDS = new Set<string>(PALETTES.map(p => p.id).filter(Boolean));
const KEY = "haip_palette";
const LAB_KEY = "haip_palette_lab";

const read = (k: string) => { try { return window.localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string | null) => { try { if (v === null) window.localStorage.removeItem(k); else window.localStorage.setItem(k, v); } catch { /* storage blocked */ } };
function apply(id: string) {
  if (id && IDS.has(id)) document.documentElement.dataset.palette = id;
  else delete document.documentElement.dataset.palette;
}

export function PaletteLab() {
  const [enabled, setEnabled] = useState(false);
  const [current, setCurrent] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("palette");
    if (q === "lab") write(LAB_KEY, "1");
    if (q === "off") { write(LAB_KEY, null); write(KEY, null); }
    if (q && IDS.has(q)) write(KEY, q);
    const id = read(KEY) ?? "";
    apply(id);
    setCurrent(IDS.has(id) ? id : "");
    setEnabled(process.env.NODE_ENV !== "production" || read(LAB_KEY) === "1");
  }, []);

  if (!enabled) return null;
  const pick = (id: string) => { write(KEY, id || null); apply(id); setCurrent(id); };
  const active = PALETTES.find(p => p.id === current) ?? PALETTES[0];

  return (
    <div className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] left-3 z-[70] md:bottom-4">
      {open && (
        <div role="dialog" aria-label="Try a colour palette"
          className="mb-2 w-72 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-2 shadow-[var(--haip-shadow-lg)]">
          <p className="px-2 pb-1.5 pt-1 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">Palette lab · only in this browser</p>
          {PALETTES.map(p => (
            <button key={p.id || "shipped"} type="button" onClick={() => pick(p.id)} aria-pressed={current === p.id}
              className={cn("flex min-h-11 w-full items-center gap-3 rounded-xl px-2 text-left text-[14px] transition-colors",
                current === p.id ? "bg-[var(--haip-primary-tint)] font-semibold text-primary" : "text-[var(--haip-fg)] hover:bg-[var(--hover-bg)]")}>
              <span className="flex shrink-0 -space-x-1.5" aria-hidden>
                <span className={cn("size-6 rounded-full ring-2 ring-[var(--haip-card)]", p.main)} />
                <span className={cn("size-6 rounded-full ring-2 ring-[var(--haip-card)]", p.hl)} />
              </span>
              {p.name}
            </button>
          ))}
          <p className="px-2 pb-1 pt-2 text-[11.5px] leading-snug text-[var(--haip-fg-subtle)]">Use the sun/moon button in the top bar to see each one in dark mode.</p>
        </div>
      )}
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
        className="flex min-h-11 items-center gap-2 rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] py-1.5 pl-1.5 pr-3.5 text-[13px] font-semibold text-[var(--haip-fg)] shadow-[var(--haip-shadow-md)]">
        <span className="flex -space-x-1.5" aria-hidden>
          <span className={cn("size-6 rounded-full ring-2 ring-[var(--haip-card)]", active.main)} />
          <span className={cn("size-6 rounded-full ring-2 ring-[var(--haip-card)]", active.hl)} />
        </span>
        Palette
      </button>
    </div>
  );
}
