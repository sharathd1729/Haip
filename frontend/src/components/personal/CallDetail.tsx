"use client";
// One call, the way it is remembered: what it was about, the decision, the reminders, the topics, what is still open,
// any dated plans, then the recording and the transcript. Share sends the WhatsApp-ready note.
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, AskBubble, Calendar, ChevronDown, Copy, Loader2, PhoneIncoming, PhoneOutgoing, Send } from "@/lib/icons";
import { Drawer } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { STATUS_TEXT, calendarLink, dayLabel, durationLabel, istDay, timeLabel, type CallDetail as Detail } from "@/lib/personal";
import { useCallDetail } from "./hooks";
import { AskYaad } from "./AskYaad";
import { Cite, MomentProvider } from "./Cite";
import { ChipsCard, HistoryButton, HistoryDrawer, OpenPointsCard, SummaryCard, TasksCard, TitleEdit } from "./MemoryEdit";

export function CallDetail({ id, backHref }: { id: string; backHref?: string }) {
  const q = useCallDetail(id);
  if (q.isPending) return <DetailSkeleton />;
  if (q.isError || !q.data) {
    const status = (q.error as { response?: { status?: number } } | null)?.response?.status;
    return (
      <Shell backHref={backHref}>
        <p className="text-[17px] font-semibold">{status === 404 ? "This call isn't here" : "Couldn't load this call"}</p>
        <p className="mt-2 text-[14.5px] text-[var(--y-ink-2)]">
          {status === 404 ? "It may have been removed." : "Check your connection and try again."}
        </p>
        {status !== 404 && (
          <button type="button" onClick={() => q.refetch()} className="y-press mt-4 min-h-11 rounded-full bg-[var(--y-brand)] px-5 text-[15px] font-semibold text-[var(--y-on-brand)]">Try again</button>
        )}
      </Shell>
    );
  }
  return <div key={q.data.id} className="y-enter"><Body call={q.data} backHref={backHref} /></div>;
}

function Body({ call, backHref }: { call: Detail; backHref?: string }) {
  const m = call.memory;
  const Dir = call.direction === "in" ? PhoneIncoming : PhoneOutgoing;
  const day = call.at ? dayLabel(istDay(new Date(call.at))) : "";
  const [panel, setPanel] = useState<"history" | "ask" | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const play = useCallback((at: number, start = true) => {
    const el = audio.current;
    if (!el) return;
    el.currentTime = at;
    el.closest("section")?.scrollIntoView({ behavior: "smooth", block: "center" });
    if (start) el.play().catch(() => { /* the browser wants a tap on play first */ });
  }, []);
  // ?t=42 (a source chip on Reminders, Calendar or Ask): open the recording at that moment, ready to play.
  const t = Number(useSearchParams().get("t"));
  useEffect(() => { if (t > 0) play(t, false); }, [t, play]);
  const body = (
    // Layout B on a wide screen (xl, 1280px+): Ask Yaad stays docked beside the memory; below that it is a drawer.
    <div className="xl:grid xl:grid-cols-[minmax(0,1fr)_380px] xl:items-start xl:gap-8">
    <Shell backHref={backHref}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-[var(--y-ink-3)] [font-variant-numeric:tabular-nums]">
          <Dir size={14} aria-hidden />
          {[day, timeLabel(call.at), durationLabel(call.duration_sec)].filter(Boolean).join(" · ")}
        </p>
        {m && (
          <div className="flex items-center gap-1">
            <HistoryButton count={m.history?.length ?? 0} onOpen={() => setPanel("history")} />
            <button type="button" onClick={() => setPanel("ask")}
              className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full bg-[var(--y-brand)] px-3.5 text-[13.5px] font-semibold text-[var(--y-on-brand)] xl:hidden">
              <AskBubble size={15} aria-hidden /> Ask Yaad
            </button>
          </div>
        )}
      </div>
      {m ? <TitleEdit callId={call.id} title={m.title} /> : (
        <h1 className="mt-2 text-[26px] font-semibold leading-[1.18] tracking-[-0.02em] [text-wrap:balance] sm:text-[30px]">{call.contact}</h1>
      )}
      <p className="mt-2 text-[15px] text-[var(--y-ink-2)]">
        {m ? `With ${call.contact}` : call.contact !== call.number ? call.number : call.direction === "in" ? "Incoming call" : "Outgoing call"}
      </p>

      {m && <ChipsCard callId={call.id} m={m} folders={call.folders ?? []} />}

      {!m && <Pending call={call} />}
      {m && call.share_text && <ShareBar text={call.share_text} />}

      {m && <SummaryCard callId={call.id} m={m} />}
      {m && <TasksCard callId={call.id} m={m} />}
      {m && <OpenPointsCard callId={call.id} m={m} />}

      {m && m.upcoming.length > 0 && (
        <Section title="Coming up">
          <ul className="grid gap-2">
            {m.upcoming.map((u, i) => (
              <li key={i} className="flex items-start gap-3 rounded-[14px] border border-[var(--y-line)] bg-[var(--y-card)] p-3">
                <Calendar size={18} className="mt-0.5 shrink-0 text-[var(--y-brand)]" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-medium">{u.what}<Cite text={u.what} /></span>
                  <span className="text-[13px] text-[var(--y-ink-2)]">{[dayLabel(u.date), u.time, u.place].filter(Boolean).join(" · ")}</span>
                </span>
                <a
                  href={calendarLink({ title: u.what, date: u.date, time: u.time, place: u.place, details: `From your call with ${call.contact}` })}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="y-press inline-flex min-h-11 shrink-0 items-center rounded-full border border-[var(--y-line-strong)] px-3 text-[13px] font-semibold text-[var(--y-ink)]"
                >
                  Add to calendar
                </a>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {call.recording_url && (
        <Section title="Recording">
          <audio ref={audio} controls preload="none" src={call.recording_url} className="w-full [accent-color:var(--y-brand)]">
            Your browser can't play this recording.
          </audio>
        </Section>
      )}

      {call.transcript.length > 0 && <Transcript turns={call.transcript} />}

      {m && <HistoryDrawer callId={call.id} open={panel === "history"} onOpenChange={o => setPanel(o ? "history" : null)} />}
      <Drawer open={panel === "ask"} onOpenChange={o => setPanel(o ? "ask" : null)} title="Ask Yaad" className="yaad">
        <AskYaad compact />
      </Drawer>
    </Shell>
    {m && (
      <aside aria-label="Ask Yaad" className="sticky top-0 hidden max-h-[calc(100dvh-6rem)] flex-col overflow-y-auto rounded-[24px] border border-[var(--y-line)] bg-[var(--y-card)] p-5 shadow-[var(--y-shadow)] xl:flex">
        <h2 className="mb-3 flex items-center gap-2 text-[16px] font-semibold"><AskBubble size={18} aria-hidden /> Ask Yaad</h2>
        <AskYaad compact />
      </aside>
    )}
    </div>
  );
  return m ? <MomentProvider memory={m} play={call.recording_url ? play : undefined}>{body}</MomentProvider> : body;
}

function Shell({ children, backHref }: { children: React.ReactNode; backHref?: string }) {
  return (
    <article className="mx-auto w-full max-w-[760px] pb-10">
      {backHref && (
        <Link href={backHref} className="y-press -ml-2 mb-3 inline-flex min-h-11 items-center gap-1.5 rounded-full px-2 text-[15px] font-medium text-[var(--y-brand)]">
          <ArrowLeft size={18} aria-hidden /> Memories
        </Link>
      )}
      {children}
    </article>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 flex items-center gap-2 text-[18px] font-semibold tracking-[-0.01em]">
        {title}
        {!!count && <span className="rounded-full bg-[var(--y-due)] px-2 py-0.5 text-[12px] font-bold text-[var(--y-on-due)]">{count}</span>}
      </h2>
      {children}
    </section>
  );
}

function Pending({ call }: { call: Detail }) {
  const working = call.status === "transcribing" || call.status === "analysing";
  const why: Record<string, string> = {
    transcribing: "The recording arrived and is being written out. The summary follows in a minute or two.",
    analysing: "The transcript is ready; the summary and reminders are being written now.",
    no_recording: "Yaad has the call but no recording yet. Check that your phone's dialer records calls and that the recordings folder is picked in the Yaad app.",
    too_short: "This call was too short to have anything worth summarising.",
    failed: "Something went wrong writing this summary. Yaad tries again by itself.",
  };
  return (
    <div className="mt-6 flex items-start gap-3 rounded-[18px] border border-[var(--y-line)] bg-[var(--y-card)] p-4">
      {working && <Loader2 size={18} className="mt-0.5 shrink-0 animate-spin text-[var(--y-brand)]" aria-hidden />}
      <div>
        <p className="text-[15px] font-semibold">{STATUS_TEXT[call.status] || "Summary not ready"}</p>
        <p className="mt-1 text-[14px] leading-relaxed text-[var(--y-ink-2)]">{why[call.status] ?? ""}</p>
      </div>
    </div>
  );
}

function ShareBar({ text }: { text: string }) {
  const { toast } = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast({ variant: "success", title: "Copied" });
    } catch {
      toast({ variant: "error", title: "Couldn't copy", description: "Long-press the summary to copy it instead." });
    }
  };
  return (
    <div className="mt-5 flex flex-wrap gap-2">
      {/* wa.me opens WhatsApp both in a browser and inside the Yaad app (its WebView hands other sites to their apps). */}
      <a
        href={`https://wa.me/?text=${encodeURIComponent(text)}`}
        target="_blank"
        rel="noopener noreferrer"
        className="y-press inline-flex min-h-11 items-center gap-2 rounded-full bg-[var(--y-brand)] px-5 text-[15px] font-semibold text-[var(--y-on-brand)] hover:bg-[var(--y-brand-hover)]"
      >
        <Send size={16} aria-hidden /> Share on WhatsApp
      </a>
      <button
        type="button"
        onClick={copy}
        className="y-press inline-flex min-h-11 items-center gap-2 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-4 text-[15px] font-medium text-[var(--y-ink)]"
      >
        <Copy size={16} aria-hidden /> Copy
      </button>
    </div>
  );
}

function Transcript({ turns }: { turns: Detail["transcript"] }) {
  const [open, setOpen] = useState(false);
  const speakers = Array.from(new Set(turns.map(t => t.speaker)));
  return (
    <section className="mt-8">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        className="y-press flex min-h-11 w-full items-center justify-between rounded-[14px] border border-[var(--y-line)] bg-[var(--y-card)] px-4 text-left text-[16px] font-semibold"
      >
        Transcript
        <ChevronDown size={18} className={cn("transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <ol className="mt-3 grid gap-3">
          {turns.map((t, i) => (
            <li key={i} className="text-[14.5px] leading-relaxed">
              <span className={cn("mr-2 text-[12.5px] font-semibold", speakers.indexOf(t.speaker) === 0 ? "text-[var(--y-brand)]" : "text-[var(--y-ink-2)]")}>
                Speaker {speakers.indexOf(t.speaker) + 1}
              </span>
              {t.text}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function DetailSkeleton() {
  return (
    <div className="mx-auto grid w-full max-w-[680px] gap-4" aria-busy="true" aria-label="Loading call">
      <div className="h-4 w-40 animate-pulse rounded bg-[var(--y-line)]" />
      <div className="h-9 w-4/5 animate-pulse rounded-lg bg-[var(--y-line)]" />
      <div className="h-20 w-full animate-pulse rounded-[18px] bg-[var(--y-line)]" />
      <div className="h-40 w-full animate-pulse rounded-[18px] bg-[var(--y-line)]" />
    </div>
  );
}
