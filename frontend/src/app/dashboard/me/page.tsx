"use client";
// Yaad home: the calls list. On a wide screen (an unfolded Galaxy Z Fold, a tablet, a laptop) the open call sits beside
// the list; on a narrow one (the Fold's cover screen, any phone) a call opens on its own page.
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ListChecks } from "@/lib/icons";
import { CallDetail } from "@/components/personal/CallDetail";
import { CallList } from "@/components/personal/CallList";
import { useCallsPages } from "@/components/personal/hooks";
import { YaadWordmark } from "@/components/personal/YaadMark";

const WIDE = "(min-width: 600px)";

function useWide(): boolean {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(WIDE);
    const on = () => setWide(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return wide;
}

function Home() {
  const wide = useWide();
  const router = useRouter();
  const params = useSearchParams();
  // Open the newest summarised call by default; a call still being processed has nothing to read yet.
  const firstPage = useCallsPages().data?.pages[0]?.calls ?? [];
  const first = (firstPage.find(c => c.status === "ready") ?? firstPage[0])?.id ?? null;
  const selected = params.get("call") ?? first;

  const open = (id: string) => {
    if (wide) router.replace(`/dashboard/me?call=${id}`, { scroll: false });
    else router.push(`/dashboard/me/calls/${id}`);
  };

  return (
    <div className="yaad min-h-full px-4 py-5 sm:px-6">
      <div className="mx-auto max-w-[1180px]">
        <div className="mb-5 hidden items-center justify-between gap-3 min-[600px]:flex md:hidden">{/* md+: the Yaad sidebar shows these */}
          <YaadWordmark />
          <Link href="/dashboard/me/reminders" className="y-press inline-flex min-h-11 items-center gap-2 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-4 text-[15px] font-medium">
            <ListChecks size={17} aria-hidden /> Reminders
          </Link>
        </div>
        <div className="grid gap-6 min-[600px]:grid-cols-[minmax(270px,360px)_minmax(0,1fr)] lg:gap-10">
          <div className="min-w-0"><CallList selectedId={wide ? selected : null} onSelect={open} /></div>
          {wide && (
            <div className="min-w-0 self-start rounded-[24px] border border-[var(--y-line)] bg-[var(--y-card)] p-5 shadow-[var(--y-shadow)] min-[600px]:sticky min-[600px]:top-20 min-[600px]:max-h-[calc(100dvh-104px)] min-[600px]:overflow-y-auto lg:p-8">
              {selected ? <CallDetail id={selected} /> : <p className="py-16 text-center text-[15px] text-[var(--y-ink-2)]">Pick a call to see what was said.</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function YaadHomePage() {
  return (
    <Suspense fallback={null}>
      <Home />
    </Suspense>
  );
}
