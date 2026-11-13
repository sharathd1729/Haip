"use client";
// Yaad settings (GET/PUT /me/settings, DELETE /me/account): custom words the summaries spell exactly, the phone
// notifications and the daily email, and deleting the account. Every change saves at once.
import { useState } from "react";
import { signOut } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api, { clearTokenCache } from "@/lib/api";
import { Loader2, Plus, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";

interface Settings {
  custom_words: string[];
  daily_email: boolean;
  notify_summary: boolean;
  notify_due: boolean;
  notify_day: boolean;
}
type Switch = Exclude<keyof Settings, "custom_words">;

const MAX_WORDS = 100;
const SWITCHES: { key: Switch; label: string; hint: string }[] = [
  { key: "notify_summary", label: "Call summary ready", hint: "A notification on your phone when a call's notes are ready." },
  { key: "notify_due", label: "Reminders due today", hint: "One notification in the morning, from 9 AM." },
  { key: "notify_day", label: "Your day at a glance", hint: "One notification at 10 PM on days you had calls." },
  { key: "daily_email", label: "Daily summary email", hint: "Your day at a glance by email at 10 PM, on days with calls." },
];

function detail(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

function Card({ title, hint, children, danger }: { title: string; hint?: string; children: React.ReactNode; danger?: boolean }) {
  return (
    <section className={cn("rounded-[20px] border bg-[var(--y-card)] p-4 sm:p-5", danger ? "border-[var(--y-late)]/40" : "border-[var(--y-line)]")}>
      <h2 className={cn("text-[17px] font-semibold", danger && "text-[var(--y-late)]")}>{title}</h2>
      {hint && <p className="mt-1 text-[14px] leading-relaxed text-[var(--y-ink-2)]">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function YaadSettings() {
  const { toast } = useToast();
  const qc = useQueryClient();
  const q = useQuery<Settings>({ queryKey: ["me", "settings"], queryFn: () => api.get("/me/settings").then(r => r.data) });
  const save = useMutation({
    mutationFn: (change: Partial<Settings>) => api.put<Settings>("/me/settings", change).then(r => r.data),
    onSuccess: data => qc.setQueryData(["me", "settings"], data),
    onError: e => toast({ variant: "error", title: "Couldn't save", description: detail(e, "Check your connection and try again.") }),
  });
  const [word, setWord] = useState("");

  if (q.isPending) {
    return (
      <div className="grid gap-4" aria-busy="true" aria-label="Loading settings">
        {[0, 1, 2].map(i => <div key={i} className="h-32 animate-pulse rounded-[20px] bg-[var(--y-line)]" />)}
      </div>
    );
  }
  if (q.isError || !q.data) {
    return (
      <div className="rounded-[18px] border border-[var(--y-line)] bg-[var(--y-card)] p-6 text-center">
        <p className="font-semibold">Couldn't load your settings</p>
        <button type="button" onClick={() => q.refetch()} className="y-press mt-3 min-h-11 rounded-full bg-[var(--y-brand)] px-5 text-[15px] font-semibold text-[var(--y-on-brand)]">Try again</button>
      </div>
    );
  }
  const s = q.data;
  const words = s.custom_words;
  const add = () => {
    const w = word.trim().replace(/\s+/g, " ");
    if (!w) return;
    if (words.some(x => x.toLowerCase() === w.toLowerCase())) { setWord(""); return; }
    save.mutate({ custom_words: [...words, w] }, { onSuccess: () => setWord("") });
  };

  return (
    <div className="grid gap-4">
      <Card title="Custom words" hint="Names, places and brands Yaad should spell exactly in your call notes, like a client's name or your company.">
        {words.length > 0 && (
          <ul className="mb-3 flex flex-wrap gap-2" aria-label="Your custom words">
            {words.map(w => (
              <li key={w} className="inline-flex min-h-10 items-center gap-1 rounded-full border border-[var(--y-line-strong)] pl-3.5 pr-1 text-[14.5px]">
                <span className="max-w-[24ch] truncate">{w}</span>
                <button type="button" aria-label={`Remove ${w}`} disabled={save.isPending}
                  onClick={() => save.mutate({ custom_words: words.filter(x => x !== w) })}
                  className="flex size-8 items-center justify-center rounded-full text-[var(--y-ink-2)] hover:bg-[var(--y-soft)]">
                  <X size={14} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
        <form className="flex gap-2" onSubmit={e => { e.preventDefault(); add(); }}>
          <label htmlFor="yaad-word" className="sr-only">Add a word</label>
          <input id="yaad-word" value={word} maxLength={40} onChange={e => setWord(e.target.value)} placeholder="Add a word"
            disabled={words.length >= MAX_WORDS}
            className="min-h-12 min-w-0 flex-1 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-4 text-[16px] text-[var(--y-ink)] placeholder:text-[var(--y-ink-3)] focus:border-[var(--y-ink)] focus:outline-none" />
          <button type="submit" disabled={!word.trim() || save.isPending || words.length >= MAX_WORDS}
            className="y-press inline-flex min-h-12 shrink-0 items-center gap-1.5 rounded-full bg-[var(--y-brand)] px-5 text-[15px] font-semibold text-[var(--y-on-brand)] disabled:opacity-40">
            <Plus size={16} aria-hidden /> Add
          </button>
        </form>
        <p className="mt-2 text-[13px] text-[var(--y-ink-3)]">{words.length} of {MAX_WORDS}. Used for calls from now on.</p>
      </Card>

      <Card title="Notifications" hint="Phone notifications come from the Yaad app on your phone.">
        <ul className="divide-y divide-[var(--y-line)]">
          {SWITCHES.map(sw => (
            <li key={sw.key}>
              <label className="flex min-h-14 cursor-pointer items-center justify-between gap-4 py-3">
                <span>
                  <span className="block text-[15.5px] font-medium">{sw.label}</span>
                  <span className="block text-[13.5px] text-[var(--y-ink-2)]">{sw.hint}</span>
                </span>
                <input type="checkbox" role="switch" checked={s[sw.key]} disabled={save.isPending}
                  onChange={e => save.mutate({ [sw.key]: e.target.checked })}
                  className="size-6 shrink-0 accent-[var(--y-brand)]" />
              </label>
            </li>
          ))}
        </ul>
      </Card>

      <DeleteAccount />
    </div>
  );
}

function DeleteAccount() {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const del = useMutation({
    mutationFn: () => api.delete("/me/account", { data: { confirm: typed.trim() } }),
    onSuccess: () => { clearTokenCache(); signOut({ callbackUrl: "/login" }); },
    onError: e => toast({ variant: "error", title: "Couldn't delete your account", description: detail(e, "Try again in a minute.") }),
  });

  return (
    <Card danger title="Delete my account" hint="Erases all your calls, recordings, transcripts, notes and reminders, unlinks your phones and signs you out. This cannot be undone.">
      {!open ? (
        <button type="button" onClick={() => setOpen(true)}
          className="y-press min-h-11 rounded-full border border-[var(--y-late)] px-5 text-[15px] font-semibold text-[var(--y-late)]">
          Delete my account
        </button>
      ) : (
        <form onSubmit={e => { e.preventDefault(); if (typed.trim() === "DELETE") del.mutate(); }}>
          <label htmlFor="yaad-delete" className="block text-[14.5px] font-medium">Type DELETE to confirm</label>
          <input id="yaad-delete" value={typed} onChange={e => setTyped(e.target.value)} autoComplete="off" autoCapitalize="characters"
            className="mt-2 min-h-12 w-full rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-4 text-[16px] focus:border-[var(--y-late)] focus:outline-none" />
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="submit" disabled={typed.trim() !== "DELETE" || del.isPending}
              className="y-press inline-flex min-h-11 items-center gap-2 rounded-full bg-[var(--y-late)] px-5 text-[15px] font-semibold text-white disabled:opacity-40">
              {del.isPending && <Loader2 size={16} className="animate-spin" aria-hidden />} Delete everything
            </button>
            <button type="button" onClick={() => { setOpen(false); setTyped(""); }} disabled={del.isPending}
              className="y-press min-h-11 rounded-full border border-[var(--y-line-strong)] px-5 text-[15px] font-medium">
              Keep my account
            </button>
          </div>
        </form>
      )}
    </Card>
  );
}
