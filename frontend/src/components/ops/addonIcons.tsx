// HAIP's own add-on icons (drawn for HAIP, Nov 2026; brand rules on the design canvas "HAIP guest pages, by hand"):
// 24 px grid, 1.75 stroke, round ends and joins, ONE solid "spark" shape per icon. On a sea-green tile the line is mint and
// the spark lime (`--haip-tile-fg`); on a light surface the spark takes the line colour. Objects from an Indian villa stay:
// handi (cook), seekh grill (barbecue), marigold toran (decor), key + sunrise (early check-in), open door + setting sun
// (late check-out), charpai + moon (extra night). Deliberately not a stock icon pack.
import type { ReactNode, SVGProps } from "react";

export type AddonIconKind = "cook" | "bbq" | "decor" | "early" | "late" | "night";

const PATHS: Record<AddonIconKind, ReactNode> = {
  cook: (<>
    <path d="M3.5 11.5h17" /><path d="M5 11.5c0 4.6 3.1 7.5 7 7.5s7-2.9 7-7.5" /><path d="M9.5 19.5v1h5v-1" />
    <path d="M10 8.5c-1.1-1 1.1-2.2 0-3.7" /><path d="M14 8.5c-1.1-1 1.1-2.2 0-3.7" />
    <path data-spark="" d="M6.4 14h11.2c-.3.9-.7 1.7-1.2 2.3H7.6c-.5-.6-.9-1.4-1.2-2.3z" />
  </>),
  bbq: (<>
    <path d="M3.5 8.5h17" /><rect x="6" y="6.5" width="3" height="4" rx="1.5" /><rect x="10.5" y="6.5" width="3" height="4" rx="1.5" />
    <rect x="15" y="6.5" width="3" height="4" rx="1.5" /><path d="M4.5 13h15" /><path d="M5 13c.6 2.9 3.4 4.8 7 4.8s6.4-1.9 7-4.8" />
    <path d="M8.6 17.2 7.2 20.5" /><path d="M15.4 17.2l1.4 3.3" />
    <circle data-spark="" cx="9.5" cy="14.9" r="1" /><circle data-spark="" cx="12" cy="15.5" r="1" /><circle data-spark="" cx="14.5" cy="14.9" r="1" />
  </>),
  decor: (<>
    <path d="M3 4.5h18" /><path d="M4.5 4.5c2.2 4.6 4.9 6.5 7.5 6.5s5.3-1.9 7.5-6.5" /><path d="M8 8.9v4.1" /><path d="M16 8.9v4.1" />
    <path d="M12 11v3.8" /><circle cx="8" cy="14.6" r="1.6" /><circle cx="16" cy="14.6" r="1.6" /><circle data-spark="" cx="12" cy="17.2" r="2.4" />
  </>),
  early: (<>
    <path data-spark="" d="M8.5 10a3.5 3.5 0 0 1 7 0z" /><path d="M5.5 10h13" /><path d="M12 3.5v1.6" /><path d="M7.2 5.4l1.1 1.1" />
    <path d="M16.8 5.4l-1.1 1.1" /><circle cx="7" cy="16.5" r="3" /><path d="M10 16.5h10.5" /><path d="M17.5 16.5v2.5" /><path d="M14.8 16.5v1.8" />
  </>),
  late: (<>
    <path d="M2.5 21h19" /><path d="M5 21V4a1 1 0 0 1 1-1h7.5a1 1 0 0 1 1 1v17" /><path d="M5 3.3l5.5 1.9v14.6L5 21" />
    <circle cx="8.6" cy="12.6" r=".9" fill="currentColor" stroke="none" /><path data-spark="" d="M16 21a2.75 2.75 0 0 1 5.5 0z" />
    <path d="M18.75 15.4v1.3" /><path d="M21.6 16.9l-.9.8" />
  </>),
  night: (<>
    <path d="M3.5 20.5v-9" /><path d="M3.5 15.5h17v5" /><path d="M3.5 18.3h17" /><rect x="5.5" y="12.5" width="4.5" height="3" rx="1.5" />
    <path data-spark="" d="M17.5 3.2a3.8 3.8 0 1 0 3.3 6 3.2 3.2 0 0 1-3.3-6z" /><circle data-spark="" cx="12.5" cy="6" r=".9" />
  </>),
};

/** One of HAIP's add-on icons. The spark (`[data-spark]`) is filled by CSS: `.spark` on an ancestor, else currentColor. */
export function AddonIcon({ kind, ...rest }: { kind: AddonIconKind } & SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" {...rest}>{PATHS[kind]}</svg>
  );
}

/** Which drawing an add-on gets: its stay change first, then words in its name, then its category. */
export function iconFor(a: { name: string; category?: string | null; stay_change?: string | null }): AddonIconKind {
  if (a.stay_change === "early_check_in") return "early";
  if (a.stay_change === "late_check_out") return "late";
  if (a.stay_change === "extra_night") return "night";
  const n = a.name.toLowerCase();
  if (/barbe|bbq|grill|bonfire|kebab|tandoor/.test(n)) return "bbq";
  if (/decor|décor|celebrat|birthday|anniversar|flower|balloon|cake/.test(n)) return "decor";
  if (a.category === "meal" || /cook|chef|meal|dinner|breakfast|lunch/.test(n)) return "cook";
  return "decor";
}

const line = { fill: "none", stroke: "currentColor", strokeLinecap: "round", strokeLinejoin: "round" } as const;

export function TickIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" strokeWidth={2.2} aria-hidden="true" {...line} {...props}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
}
export function PlusIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" strokeWidth={2.2} aria-hidden="true" {...line} {...props}><path d="M6 12h12M12 6v12" /></svg>;
}
export function MinusIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" strokeWidth={2.2} aria-hidden="true" {...line} {...props}><path d="M6 12h12" /></svg>;
}
export function ClockIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" strokeWidth={1.75} aria-hidden="true" {...line} {...props}><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>;
}
export function LockIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" strokeWidth={1.75} aria-hidden="true" {...line} {...props}>
      <rect x="5" y="10.5" width="14" height="10" rx="2.5" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" />
      <circle cx="12" cy="15.5" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}
export function CalendarIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" strokeWidth={1.75} aria-hidden="true" {...line} {...props}>
      <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" /><path d="M3.5 10h17M8 3v4M16 3v4" />
      <rect x="13.5" y="13" width="3.5" height="3.5" rx="1" fill="currentColor" stroke="none" />
    </svg>
  );
}
