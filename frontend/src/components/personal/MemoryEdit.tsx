"use client";
// Correcting a call's memory (layout B, owner pick 15 Nov): chips save the moment they change; each card has its own
// Edit, then Save / Cancel; History lists every change with Undo. Saves go through PATCH /me/calls/{id}/memory.
import { useState } from "react";
import { History, Pencil, Plus, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Drawer } from "@/components/ui/kit";
import { CATEGORIES, FIELD_LABEL, dayLabel, folderColor, istDay, timeLabel, type Folder, type Memory, type MemoryPatch } from "@/lib/personal";
import { useEditMemory, useFolderCall, useFolders, useMemoryHistory, useUndoChange } from "./hooks";
import { ReminderRow } from "./ReminderRow";
import { Cite } from "./Cite";

const field = "min-h-11 w-full rounded-xl border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3 text-[16px] text-[var(--y-ink)] focus:border-[var(--y-ink)] focus:outline-none";
const chip = "inline-flex min-h-9 items-center gap-1.5 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3 text-[13.5px]";

function useSave(callId: string) {
  const { toast } = useToast();
  const edit = useEditMemory(callId);
  const save = (patch: MemoryPatch, done?: () => void) =>
    edit.mutate(patch, {
      onSuccess: () => done?.(),
      onError: () => toast({ variant: "error", title: "Couldn't save that", description: "Check your connection and try again." }),
    });
  return { save, saving: edit.isPending };
}

/** Category, tags and people: each change saves at once (small, easy to undo from History). */
export function ChipsCard({ callId, m, folders = [] }: { callId: string; m: Memory; folders?: Pick<Folder, "id" | "name" | "color">[] }) {
  const { save } = useSave(callId);
  const [adding, setAdding] = useState<"tag" | "person" | null>(null);
  const [text, setText] = useState("");
  const add = () => {
    const v = text.trim();
    if (v && adding === "tag" && !m.tags.includes(v)) save({ tags: [...m.tags, v] });
    if (v && adding === "person") save({ participants: [...m.participants, { name: v, role: "" }] });
    setText("");
    setAdding(null);
  };
  return (
    <div className="mt-5 grid gap-3 rounded-[20px] border border-[var(--y-line)] bg-[var(--y-card)] p-4 shadow-[var(--y-shadow)]">
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="memory-category">Category</label>
        <select id="memory-category" value={m.category} onChange={e => save({ category: e.target.value })}
          className="y-press min-h-9 rounded-full border-0 bg-[var(--y-brand)] px-3 text-[13.5px] font-semibold text-[var(--y-on-brand)]">
          {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        {m.tags.map(t => (
          <span key={t} className={chip}>{t}
            <button type="button" aria-label={`Remove tag ${t}`} onClick={() => save({ tags: m.tags.filter(x => x !== t) })}
              className="-mr-1 flex size-6 items-center justify-center rounded-full text-[var(--y-ink-3)] hover:text-[var(--y-ink)]"><X size={13} aria-hidden /></button>
          </span>
        ))}
        <AddButton label="Tag" on={() => setAdding("tag")} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-[13px] font-semibold text-[var(--y-ink-2)]">People</span>
        {m.participants.map((p, i) => (
          <span key={`${p.name}-${i}`} className={chip}>
            <span className="flex size-6 items-center justify-center rounded-full bg-[var(--y-soft)] text-[11px] font-bold text-[var(--y-soft-ink)]" aria-hidden>{p.name.slice(0, 1)}</span>
            {p.name}{p.role && <span className="text-[var(--y-ink-3)]">· {p.role}</span>}
            <button type="button" aria-label={`Remove ${p.name}`} onClick={() => save({ participants: m.participants.filter((_, j) => j !== i) })}
              className="-mr-1 flex size-6 items-center justify-center rounded-full text-[var(--y-ink-3)] hover:text-[var(--y-ink)]"><X size={13} aria-hidden /></button>
          </span>
        ))}
        <AddButton label="Person" on={() => setAdding("person")} />
      </div>
      <FolderRow callId={callId} folders={folders} />
      {adding && (
        <form className="y-enter flex gap-2" onSubmit={e => { e.preventDefault(); add(); }}>
          <label className="sr-only" htmlFor="memory-add">{adding === "tag" ? "New tag" : "Person's name"}</label>
          <input id="memory-add" autoFocus value={text} maxLength={adding === "tag" ? 40 : 80} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === "Escape") setAdding(null); }} placeholder={adding === "tag" ? "New tag" : "Their name"} className={field} />
          <button type="submit" className="y-press min-h-11 shrink-0 rounded-full bg-[var(--y-brand)] px-4 text-[15px] font-semibold text-[var(--y-on-brand)]">Add</button>
        </form>
      )}
    </div>
  );
}

/** The call's folders: take it out of one (automatic sorting then leaves it out), or put it in another. */
function FolderRow({ callId, folders }: { callId: string; folders: Pick<Folder, "id" | "name" | "color">[] }) {
  const all = useFolders().data?.folders ?? [];
  const move = useFolderCall();
  const { toast } = useToast();
  const others = all.filter(f => !folders.some(x => x.id === f.id));
  const run = (folderId: string, add: boolean) =>
    move.mutate({ folderId, callId, add }, { onError: () => toast({ variant: "error", title: "Couldn't change the folder" }) });
  if (!all.length && !folders.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 text-[13px] font-semibold text-[var(--y-ink-2)]">Folders</span>
      {folders.map(f => (
        <span key={f.id} className={chip}>
          <span aria-hidden className="size-2.5 rounded-[3px]" style={{ background: folderColor(f.color) }} />{f.name}
          <button type="button" aria-label={`Take out of ${f.name}`} onClick={() => run(f.id, false)}
            className="-mr-1 flex size-6 items-center justify-center rounded-full text-[var(--y-ink-3)] hover:text-[var(--y-ink)]"><X size={13} aria-hidden /></button>
        </span>
      ))}
      {!folders.length && <span className="text-[13px] text-[var(--y-ink-3)]">Unclassified</span>}
      {others.length > 0 && (
        <label className={cn(chip, "y-press border-dashed text-[var(--y-ink-2)]")}>
          <Plus size={13} aria-hidden /><span className="sr-only">Add to folder</span>
          <select value="" onChange={e => e.target.value && run(e.target.value, true)} className="bg-transparent text-[13.5px] focus:outline-none">
            <option value="">Add to folder</option>
            {others.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}

function AddButton({ label, on }: { label: string; on: () => void }) {
  return (
    <button type="button" onClick={on} className={cn(chip, "y-press border-dashed text-[var(--y-ink-2)]")}>
      <Plus size={13} aria-hidden /> {label}
    </button>
  );
}

/** A card with its own Edit, then Save / Cancel. `form` builds the edit view from a draft the card keeps. */
function EditCard<T>({ title, count, start, toPatch, view, form, callId, empty }: {
  title: string; count?: number; callId: string; empty?: boolean;
  start: () => T; toPatch: (draft: T) => MemoryPatch;
  view: React.ReactNode; form: (draft: T, set: (d: T) => void) => React.ReactNode;
}) {
  const { save, saving } = useSave(callId);
  const [draft, setDraft] = useState<T | null>(null);
  return (
    <section className={cn("mt-5 rounded-[20px] border bg-[var(--y-card)] p-4 shadow-[var(--y-shadow)] sm:p-5", draft ? "border-[var(--y-ink)]" : "border-[var(--y-line)]")}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-[17px] font-semibold">
          {title}{draft && <span className="text-[13px] font-normal text-[var(--y-ink-3)]">· editing</span>}
          {!draft && !!count && <span className="rounded-full bg-[var(--y-due)] px-2 py-0.5 text-[12px] font-bold text-[var(--y-on-due)]">{count}</span>}
        </h2>
        {draft ? (
          <div className="flex gap-2">
            <button type="button" onClick={() => setDraft(null)} className="y-press min-h-10 rounded-full border border-[var(--y-line-strong)] px-4 text-[14px] font-medium">Cancel</button>
            <button type="button" disabled={saving} onClick={() => save(toPatch(draft), () => setDraft(null))}
              className="y-press min-h-10 rounded-full bg-[var(--y-brand)] px-4 text-[14px] font-semibold text-[var(--y-on-brand)] disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
          </div>
        ) : (
          <button type="button" aria-label={`Edit ${title}`} onClick={() => setDraft(start())}
            className="y-press flex size-10 items-center justify-center rounded-full border border-[var(--y-line-strong)] text-[var(--y-ink)]"><Pencil size={15} aria-hidden /></button>
        )}
      </div>
      <div key={draft ? "edit" : "view"} className="y-enter mt-3">
        {draft ? form(draft, setDraft) : empty ? <p className="text-[14.5px] text-[var(--y-ink-3)]">Nothing yet. Tap the pencil to add.</p> : view}
      </div>
    </section>
  );
}

const lines = (text: string) => text.split("\n").map(l => l.trim()).filter(Boolean);

type SummaryDraft = { decision: string; sections: { heading: string; bullets: string }[]; learning: string };

export function SummaryCard({ callId, m }: { callId: string; m: Memory }) {
  return (
    <EditCard<SummaryDraft>
      title="Summary" callId={callId} empty={!m.decision && !m.sections.length}
      start={() => ({ decision: m.decision, learning: m.learning, sections: m.sections.map(s => ({ heading: s.heading, bullets: s.bullets.join("\n") })) })}
      toPatch={d => ({ decision: d.decision.trim(), learning: d.learning.trim(),
        sections: d.sections.filter(s => s.heading.trim()).map(s => ({ heading: s.heading.trim(), bullets: lines(s.bullets) })) })}
      view={
        <div className="grid gap-4 text-[15px] leading-relaxed">
          {m.decision && <p className="rounded-[14px] bg-[var(--y-soft)] px-3.5 py-2.5"><span className="font-semibold text-[var(--y-soft-ink)]">Decision: </span>{m.decision}<Cite text={m.decision} /></p>}
          {m.sections.map((s, i) => (
            <div key={i}>
              <h3 className="font-semibold">{s.heading}</h3>
              <ul className="mt-1.5 grid list-disc gap-1 pl-5 marker:text-[var(--y-brand)]">{s.bullets.map((b, j) => <li key={j}>{b}<Cite text={b} /></li>)}</ul>
            </div>
          ))}
          {m.learning && <p className="text-[var(--y-ink-2)]"><span className="font-semibold">Worth remembering: </span>{m.learning}</p>}
        </div>
      }
      form={(d, set) => (
        <div className="grid gap-4">
          <label className="grid gap-1.5 text-[13px] font-semibold text-[var(--y-ink-2)]">Decision
            <input value={d.decision} maxLength={400} onChange={e => set({ ...d, decision: e.target.value })} className={field} />
          </label>
          {d.sections.map((s, i) => (
            <fieldset key={i} className="grid gap-2 rounded-[14px] border border-[var(--y-line)] p-3">
              <legend className="sr-only">Topic {i + 1}</legend>
              <div className="flex gap-2">
                <input aria-label="Topic heading" value={s.heading} maxLength={80} placeholder="Topic"
                  onChange={e => set({ ...d, sections: d.sections.map((x, j) => (j === i ? { ...x, heading: e.target.value } : x)) })} className={cn(field, "font-semibold")} />
                <button type="button" aria-label="Remove topic" onClick={() => set({ ...d, sections: d.sections.filter((_, j) => j !== i) })}
                  className="flex size-11 shrink-0 items-center justify-center rounded-full border border-[var(--y-line-strong)]"><X size={15} aria-hidden /></button>
              </div>
              <textarea aria-label="Points, one per line" rows={Math.max(3, s.bullets.split("\n").length)} value={s.bullets}
                onChange={e => set({ ...d, sections: d.sections.map((x, j) => (j === i ? { ...x, bullets: e.target.value } : x)) })}
                className={cn(field, "py-2.5 leading-relaxed")} />
            </fieldset>
          ))}
          <button type="button" onClick={() => set({ ...d, sections: [...d.sections, { heading: "", bullets: "" }] })}
            className="y-press justify-self-start text-[14.5px] font-medium text-[var(--y-ink-2)]">+ Add a topic</button>
          <label className="grid gap-1.5 text-[13px] font-semibold text-[var(--y-ink-2)]">Worth remembering
            <input value={d.learning} maxLength={400} onChange={e => set({ ...d, learning: e.target.value })} className={field} />
          </label>
          <p className="text-[12.5px] text-[var(--y-ink-3)]">Your edits stay even if Yaad reads this call again.</p>
        </div>
      )}
    />
  );
}

type TaskDraft = { id?: string; text: string; owner: string; due: string; done?: boolean }[];

export function TasksCard({ callId, m }: { callId: string; m: Memory }) {
  return (
    <EditCard<TaskDraft>
      title="Reminders" callId={callId} count={m.action_items.filter(a => !a.done).length} empty={!m.action_items.length}
      start={() => m.action_items.map(a => ({ id: a.id, text: a.text, owner: a.owner, due: a.due, done: a.done }))}
      toPatch={d => ({ action_items: d.filter(t => t.text.trim()).map(t => ({ ...t, text: t.text.trim(), owner: t.owner.trim() || "me" })) })}
      view={<ul className="grid">{m.action_items.map(a => <ReminderRow key={a.id} item={a} callId={callId} cite={<Cite text={a.text} />} />)}</ul>}
      form={(d, set) => (
        <div className="grid gap-2.5">
          {d.map((t, i) => (
            <div key={t.id ?? `new-${i}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 rounded-[14px] border border-[var(--y-line)] p-2.5 sm:grid-cols-[minmax(0,1fr)_130px_150px_auto]">
              <input aria-label="Task" value={t.text} maxLength={300} placeholder="What needs doing"
                onChange={e => set(d.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} className={cn(field, "col-span-2 sm:col-span-1")} />
              <input aria-label="Who" value={t.owner} maxLength={80} placeholder="me" onChange={e => set(d.map((x, j) => (j === i ? { ...x, owner: e.target.value } : x)))} className={field} />
              <input aria-label="Due" type="date" value={t.due} onChange={e => set(d.map((x, j) => (j === i ? { ...x, due: e.target.value } : x)))} className={field} />
              <button type="button" aria-label="Remove task" onClick={() => set(d.filter((_, j) => j !== i))}
                className="flex size-11 items-center justify-center justify-self-end rounded-full border border-[var(--y-line-strong)]"><X size={15} aria-hidden /></button>
            </div>
          ))}
          <button type="button" onClick={() => set([...d, { text: "", owner: "me", due: "" }])}
            className="y-press justify-self-start text-[14.5px] font-medium text-[var(--y-ink-2)]">+ Add a task</button>
        </div>
      )}
    />
  );
}

export function OpenPointsCard({ callId, m }: { callId: string; m: Memory }) {
  return (
    <EditCard<string>
      title="Still open" callId={callId} empty={!m.open_points.length}
      start={() => m.open_points.join("\n")} toPatch={d => ({ open_points: lines(d) })}
      view={<ul className="grid list-disc gap-1.5 pl-5 text-[15px] leading-relaxed marker:text-[var(--y-ink-3)]">{m.open_points.map((p, i) => <li key={i}>{p}<Cite text={p} /></li>)}</ul>}
      form={(d, set) => (
        <textarea aria-label="Open points, one per line" rows={Math.max(3, d.split("\n").length)} value={d} onChange={e => set(e.target.value)} className={cn(field, "py-2.5 leading-relaxed")} />
      )}
    />
  );
}

/** Title: tap the pencil, type, Enter saves, Escape cancels. */
export function TitleEdit({ callId, title }: { callId: string; title: string }) {
  const { save } = useSave(callId);
  const [draft, setDraft] = useState<string | null>(null);
  if (draft === null) {
    return (
      <h1 className="group mt-2 flex items-start gap-2 text-[26px] font-semibold leading-[1.18] tracking-[-0.02em] [text-wrap:balance] sm:text-[32px]">
        <span>{title}</span>
        <button type="button" aria-label="Edit title" onClick={() => setDraft(title)}
          className="y-press mt-1 flex size-9 shrink-0 items-center justify-center rounded-full text-[var(--y-ink-3)] hover:bg-[var(--y-soft)] hover:text-[var(--y-ink)]"><Pencil size={16} aria-hidden /></button>
      </h1>
    );
  }
  const commit = () => { if (draft.trim() && draft.trim() !== title) save({ title: draft.trim() }); setDraft(null); };
  return (
    <form className="mt-2" onSubmit={e => { e.preventDefault(); commit(); }}>
      <label className="sr-only" htmlFor="memory-title">Title</label>
      <input id="memory-title" autoFocus value={draft} maxLength={120} onChange={e => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={e => { if (e.key === "Escape") setDraft(null); }} className={cn(field, "min-h-14 text-[22px] font-semibold")} />
    </form>
  );
}

export function HistoryButton({ count, onOpen }: { count: number; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full px-3 text-[13.5px] font-medium text-[var(--y-ink-2)] hover:bg-[var(--y-soft)]">
      <History size={15} aria-hidden /> {count ? `Edited ${count === 1 ? "once" : `${count} times`} · History` : "History"}
    </button>
  );
}

function when(iso: string) {
  return `${dayLabel(istDay(new Date(iso)))} ${timeLabel(iso)}`;
}

export function HistoryDrawer({ callId, open, onOpenChange }: { callId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const q = useMemoryHistory(callId, open);
  const undo = useUndoChange(callId);
  const { toast } = useToast();
  return (
    <Drawer open={open} onOpenChange={onOpenChange} title="History" description="Every change to this memory, newest first." className="yaad">
      {q.isPending ? (
        <div className="grid gap-3" aria-busy="true">{[0, 1, 2].map(i => <div key={i} className="h-16 animate-pulse rounded-xl bg-[var(--y-line)]" />)}</div>
      ) : q.isError ? (
        <p className="text-[15px] text-[var(--y-late)]">Couldn't load the history. <button type="button" className="underline" onClick={() => q.refetch()}>Try again</button></p>
      ) : (
        <ol className="grid">
          {q.data.changes.map(c => (
            <li key={c.id} className="y-enter border-b border-[var(--y-line)] py-3 text-[14.5px]">
              <p className="text-[12.5px] text-[var(--y-ink-3)]">{when(c.at)} · {c.by === "you" ? "You" : "Someone"}{c.undo_of ? " · undo" : ""}</p>
              <p className="mt-0.5">Changed {c.fields.map(f => FIELD_LABEL[f] ?? f).join(", ")}</p>
              {typeof c.before.title === "string" && <p className="mt-0.5 text-[13.5px] text-[var(--y-ink-2)]">Was “{c.before.title}”</p>}
              <button type="button" disabled={undo.isPending}
                onClick={() => undo.mutate(c.id, { onError: () => toast({ variant: "error", title: "Couldn't undo that" }) })}
                className="y-press mt-1.5 min-h-9 rounded-full border border-[var(--y-line-strong)] px-3 text-[13.5px] font-medium disabled:opacity-50">Undo</button>
            </li>
          ))}
          {q.data.summarised_at && <li className="py-3 text-[14px] text-[var(--y-ink-2)]">{when(q.data.summarised_at)} · Yaad wrote the first summary from the call</li>}
        </ol>
      )}
    </Drawer>
  );
}
