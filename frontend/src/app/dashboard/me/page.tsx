"use client";
// Yaad home = Memories (layout B, owner pick 15 Nov): one full-width timeline of calls by day, searchable (titles,
// summaries, tags, people, numbers: server-side) and filtered by category. A memory opens on its own page.
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { CATEGORIES } from "@/lib/personal";
import { CallList } from "@/components/personal/CallList";
import { FolderLinks } from "@/components/personal/Folders";
import { useDebounced } from "@/components/quotes/calc/useDebounced";

export default function YaadHomePage() {
  const router = useRouter();
  const [text, setText] = useState("");
  const q = useDebounced(text, 300);
  const [category, setCategory] = useState<string | null>(null);

  return (
    <div className="yaad min-h-full px-4 py-5 sm:px-8 sm:py-8">
      <div className="mx-auto grid max-w-[860px] gap-4">
        <h1 className="text-[26px] font-semibold tracking-[-0.02em] max-md:sr-only sm:text-[30px]">Memories</h1>
        <FolderLinks variant="row" />
        <label className="flex min-h-12 items-center gap-2 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-4 shadow-[var(--y-shadow)] focus-within:border-[var(--y-ink)]">
          <Search size={17} className="shrink-0 text-[var(--y-ink-3)]" aria-hidden />
          <span className="sr-only">Search memories</span>
          <input value={text} maxLength={100} onChange={e => setText(e.target.value)} placeholder="Search titles, summaries, tags, people"
            className="min-w-0 flex-1 bg-transparent text-[16px] text-[var(--y-ink)] placeholder:text-[var(--y-ink-3)] focus:outline-none" />
          {text && (
            <button type="button" aria-label="Clear search" onClick={() => setText("")}
              className="flex size-8 items-center justify-center rounded-full text-[var(--y-ink-3)] hover:text-[var(--y-ink)]"><X size={15} aria-hidden /></button>
          )}
        </label>
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]" role="group" aria-label="Category">
          {[null, ...CATEGORIES].map(c => (
            <button key={c ?? "all"} type="button" aria-pressed={category === c} onClick={() => setCategory(c)}
              className={cn("y-press min-h-10 shrink-0 rounded-full px-4 text-[14px] font-medium transition-colors duration-150",
                category === c ? "bg-[var(--y-brand)] font-semibold text-[var(--y-on-brand)]" : "border border-[var(--y-line-strong)] bg-[var(--y-card)] text-[var(--y-ink)]")}>
              {c ?? "All"}
            </button>
          ))}
        </div>
        <CallList filter={{ q, category: category ?? undefined }} onSelect={id => router.push(`/dashboard/me/calls/${id}`)} />
      </div>
    </div>
  );
}
