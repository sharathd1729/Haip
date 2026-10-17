"use client";
// The comparison page. Each preview is a real frame of the chosen width (so media queries behave exactly as on that
// device), scaled down to fit. "One concept" shows desktop and phone together; "Compare all" shows the same screen in all
// six. The current choice lives in the URL so a view can be shared.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ExternalLink, Monitor, Smartphone } from "lucide-react";
import { cn } from "@/lib/utils";
import { CONCEPTS, CONCEPT_BY_ID, SCREENS, type ConceptId, type Screen } from "./concepts";

const DESKTOP_WIDTHS = [768, 1024, 1280, 1440] as const;
const PHONE_WIDTHS = [320, 360, 375, 390, 430] as const;
const PHONE_HEIGHT = 820;

function src(c: ConceptId, s: Screen) {
  return `/design-lab/preview?c=${c}&s=${s}`;
}

/** A frame rendered at `width` x `height` CSS pixels and scaled to fit its container's width (never enlarged). */
function ScaledFrame({ url, width, height, title, maxScale = 1 }: { url: string; width: number; height: number; title: string; maxScale?: number }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.5);
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => setScale(Math.min(maxScale, el.clientWidth / width));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [width, maxScale]);
  return (
    <div ref={wrap} className="w-full">
      <div className="relative overflow-hidden rounded-[10px] border border-[var(--line-strong)] bg-[var(--surface)] shadow-[0_8px_24px_-12px_rgba(0,0,0,0.25)]"
        style={{ height: height * scale, width: width * scale }}>
        <iframe title={title} src={url} loading="lazy"
          style={{ width, height, transform: `scale(${scale})`, transformOrigin: "0 0", border: 0 }} />
      </div>
      <p className="num mt-1.5 text-[11.5px] text-[var(--muted)]">{width} × {height} px{scale < 1 ? ` · shown at ${Math.round(scale * 100)}%` : ""}</p>
    </div>
  );
}

function Segmented<T extends string | number>({ label, value, options, onChange, render }: {
  label: string; value: T; options: readonly T[]; onChange: (v: T) => void; render?: (v: T) => React.ReactNode;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap rounded-lg border border-[var(--line)] bg-[var(--surface)] p-0.5">
      {options.map(o => (
        <button key={String(o)} type="button" role="radio" aria-checked={o === value} onClick={() => onChange(o)}
          className={cn("press h-9 min-w-11 rounded-md px-2.5 text-[13px]", o === value ? "bg-[var(--accent)] font-medium text-[var(--on-accent)]" : "text-[var(--muted)] hover:bg-[var(--raised)] hover:text-[var(--ink)]")}>
          {render ? render(o) : String(o)}
        </button>
      ))}
    </div>
  );
}

export function DesignLab({ initialConcept, initialScreen, initialMode }: { initialConcept: ConceptId; initialScreen: Screen; initialMode: "single" | "compare" }) {
  const [concept, setConcept] = useState<ConceptId>(initialConcept);
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [mode, setMode] = useState<"single" | "compare">(initialMode);
  const [desktopW, setDesktopW] = useState<number>(1280);
  const [phoneW, setPhoneW] = useState<number>(390);
  const [compareDevice, setCompareDevice] = useState<"desktop" | "phone">("desktop");
  const meta = CONCEPT_BY_ID[concept];

  // Keep the URL in step so a view can be shared or reloaded.
  useEffect(() => {
    const q = new URLSearchParams({ c: concept, s: screen, ...(mode === "compare" ? { m: "compare" } : {}) });
    window.history.replaceState(null, "", `/design-lab?${q}`);
  }, [concept, screen, mode]);

  return (
    <div className="lab-root lab-chrome">
      <header className="sticky top-0 z-30 border-b border-[var(--line)] bg-[var(--bg)]/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1680px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 md:px-6">
          <div className="mr-auto">
            <h1 className="text-[16px] font-semibold tracking-tight">HAIP design lab</h1>
            <p className="text-[12.5px] text-[var(--muted)]">Six directions, same synthetic data. Nothing here touches the live app.</p>
          </div>
          <Segmented label="View" value={mode} options={["single", "compare"] as const} onChange={setMode}
            render={v => (v === "single" ? "One concept" : "Compare all six")} />
        </div>
        <div className="mx-auto flex max-w-[1680px] flex-wrap items-center gap-2 px-4 pb-3 md:px-6">
          <Segmented label="Screen" value={screen} options={SCREENS.map(s => s.id)} onChange={setScreen}
            render={v => SCREENS.find(s => s.id === v)!.label} />
          {mode === "single" ? (
            <>
              <span className="ml-auto hidden items-center gap-1.5 text-[12.5px] text-[var(--muted)] lg:flex"><Monitor size={14} />Desktop</span>
              <div className="hidden lg:block"><Segmented label="Desktop width" value={desktopW} options={DESKTOP_WIDTHS} onChange={setDesktopW} /></div>
              <span className="flex items-center gap-1.5 text-[12.5px] text-[var(--muted)] max-lg:ml-auto"><Smartphone size={14} />Phone</span>
              <Segmented label="Phone width" value={phoneW} options={PHONE_WIDTHS} onChange={setPhoneW} />
            </>
          ) : (
            <div className="ml-auto"><Segmented label="Device" value={compareDevice} options={["desktop", "phone"] as const} onChange={setCompareDevice}
              render={v => (v === "desktop" ? "Desktop 1280" : "Phone 390")} /></div>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-[1680px] px-4 py-5 md:px-6">
        {mode === "single" ? (
          <>
            <nav aria-label="Concepts" className="scroll -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:grid md:grid-cols-3 md:overflow-visible md:px-0 xl:grid-cols-6">
              {CONCEPTS.map(c => (
                <button key={c.id} type="button" onClick={() => setConcept(c.id)} aria-pressed={c.id === concept}
                  className={cn("press w-[200px] shrink-0 rounded-lg border p-3 text-left md:w-auto",
                    c.id === concept ? "border-[var(--ink)] bg-[var(--surface)] shadow-[0_2px_8px_-4px_rgba(0,0,0,0.25)]" : "border-[var(--line)] bg-[var(--raised)] hover:border-[var(--line-strong)]")}>
                  <span className="flex items-center gap-2"><span className="num flex size-6 items-center justify-center rounded-md bg-[var(--ink)] text-[12px] font-semibold text-[var(--surface)]">{c.letter}</span><span className="text-[14px] font-semibold">{c.name}</span></span>
                  <span className="mt-2 flex h-2.5 overflow-hidden rounded-full border border-[var(--line)]">{c.swatches.map(s => <span key={s} className="flex-1" style={{ background: s }} />)}</span>
                  <span className="mt-2 line-clamp-2 block text-[12px] leading-snug text-[var(--muted)]">{c.thesis}</span>
                </button>
              ))}
            </nav>

            <section aria-label="About this concept" className="mt-4 grid gap-x-8 gap-y-2 rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4 text-[13px] lg:grid-cols-[1.3fr_1fr]">
              <div>
                <h2 className="text-[15px] font-semibold">{meta.letter} · {meta.name}</h2>
                <p className="mt-1 leading-relaxed text-[var(--muted)] max-sm:line-clamp-3">{meta.detail}</p>
              </div>
              <dl className="hidden grid-cols-[88px_1fr] gap-x-3 gap-y-1.5 sm:grid">
                <dt className="text-[var(--muted)]">Type</dt><dd>{meta.type}</dd>
                <dt className="text-[var(--muted)]">Navigation</dt><dd>{meta.nav}</dd>
                <dt className="text-[var(--muted)]">Signature</dt><dd>{meta.signature}</dd>
              </dl>
            </section>

            <div className="mt-5 flex items-center justify-between">
              <p className="hidden text-[13px] text-[var(--muted)] sm:block">Click around inside the frames: navigation, conversations, leads and bookings respond.</p>
              <a href={src(concept, screen)} target="_blank" rel="noreferrer" className="press ml-auto inline-flex h-10 items-center gap-1.5 whitespace-nowrap rounded-md border border-[var(--line)] bg-[var(--surface)] px-3 text-[13px] hover:bg-[var(--raised)]"><ExternalLink size={14} />Open full screen</a>
            </div>
            <div className="mt-3 grid items-start gap-6 lg:grid-cols-[1fr_auto]">
              <div className="hidden min-w-0 lg:block"><ScaledFrame key={`d-${concept}-${screen}-${desktopW}`} url={src(concept, screen)} width={desktopW} height={860} title={`${meta.name} ${screen} desktop`} /></div>
              <div className="mx-auto w-full" style={{ maxWidth: phoneW }}>
                <ScaledFrame key={`p-${concept}-${screen}-${phoneW}`} url={src(concept, screen)} width={phoneW} height={PHONE_HEIGHT} title={`${meta.name} ${screen} phone`} />
              </div>
            </div>
          </>
        ) : (
          <div className={cn("grid gap-5", compareDevice === "desktop" ? "md:grid-cols-2 2xl:grid-cols-3" : "grid-cols-2 md:grid-cols-3 xl:grid-cols-6")}>
            {CONCEPTS.map(c => (
              <section key={c.id} aria-label={c.name} className="min-w-0">
                <div className="mb-2 flex items-center gap-2">
                  <span className="num flex size-6 items-center justify-center rounded-md bg-[var(--ink)] text-[12px] font-semibold text-[var(--surface)]">{c.letter}</span>
                  <h2 className="truncate text-[14px] font-semibold">{c.name}</h2>
                  <button type="button" onClick={() => { setConcept(c.id); setMode("single"); }} className="press ml-auto h-8 shrink-0 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2.5 text-[12.5px] hover:bg-[var(--raised)]">Open</button>
                </div>
                {compareDevice === "desktop"
                  ? <ScaledFrame key={`cd-${c.id}-${screen}`} url={src(c.id, screen)} width={1280} height={800} title={`${c.name} ${screen} desktop`} />
                  : <ScaledFrame key={`cp-${c.id}-${screen}`} url={src(c.id, screen)} width={390} height={PHONE_HEIGHT} title={`${c.name} ${screen} phone`} />}
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
