"use client";
// Yaad folders (owner spec 15 Nov): the person makes a folder with keywords and a sorting rule in their own words; Yaad
// files summarised calls into it by those. FolderSheet makes / edits one; FolderLinks lists them (desktop sidebar, phone row).
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Drawer } from "@/components/ui/kit";
import { FOLDER_COLORS, folderColor, type Folder } from "@/lib/personal";
import { useDeleteFolder, useFolders, useSaveFolder } from "./hooks";

const field = "min-h-11 w-full rounded-xl border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3 text-[16px] text-[var(--y-ink)] focus:border-[var(--y-ink)] focus:outline-none";

export function FolderDot({ color, size = 10 }: { color: string; size?: number }) {
  return <span aria-hidden className="shrink-0 rounded-[3px]" style={{ width: size, height: size, background: folderColor(color) }} />;
}

/** Make a folder (no `folder`) or edit one. Saving with new keywords or a new rule re-sorts recent calls. */
export function FolderSheet({ open, onOpenChange, folder, onDeleted }: {
  open: boolean; onOpenChange: (o: boolean) => void; folder?: Folder | null; onDeleted?: () => void;
}) {
  const { toast } = useToast();
  const save = useSaveFolder();
  const del = useDeleteFolder();
  const [name, setName] = useState(folder?.name ?? "");
  const [color, setColor] = useState(folder?.color ?? "mango");
  const [keywords, setKeywords] = useState<string[]>(folder?.keywords ?? []);
  const [word, setWord] = useState("");
  const [prompt, setPrompt] = useState(folder?.prompt ?? "");
  const addWord = () => {
    const w = word.trim();
    if (w && !keywords.some(k => k.toLowerCase() === w.toLowerCase())) setKeywords([...keywords, w]);
    setWord("");
  };
  const submit = () =>
    save.mutate({ id: folder?.id, name: name.trim(), color, keywords, prompt: prompt.trim() }, {
      onSuccess: () => {
        toast({ variant: "success", title: folder ? "Folder saved" : "Folder made", description: "Yaad is sorting your recent calls into it." });
        onOpenChange(false);
      },
      onError: e => toast({ variant: "error", title: "Couldn't save the folder", description: (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Try again." }),
    });
  return (
    <Drawer open={open} onOpenChange={onOpenChange} title={folder ? "Edit folder" : "New folder"} className="yaad"
      description="Yaad files calls here when they match your keywords or your rule. You can still add or take out calls by hand.">
      <form className="grid gap-5" onSubmit={e => { e.preventDefault(); if (name.trim()) submit(); }}>
        <label className="grid gap-1.5 text-[13px] font-semibold text-[var(--y-ink-2)]">Name
          <input autoFocus value={name} maxLength={80} onChange={e => setName(e.target.value)} placeholder="Kitchen renovation" className={field} />
        </label>
        <fieldset className="grid gap-2">
          <legend className="mb-1.5 text-[13px] font-semibold text-[var(--y-ink-2)]">Colour</legend>
          <div className="flex gap-2">
            {FOLDER_COLORS.map(c => (
              <button key={c} type="button" aria-label={c} aria-pressed={color === c} onClick={() => setColor(c)}
                className={cn("flex size-10 items-center justify-center rounded-full border-2", color === c ? "border-[var(--y-ink)]" : "border-transparent")}>
                <FolderDot color={c} size={22} />
              </button>
            ))}
          </div>
        </fieldset>
        <div className="grid gap-1.5">
          <label htmlFor="folder-word" className="text-[13px] font-semibold text-[var(--y-ink-2)]">Keywords</label>
          <div className="flex flex-wrap gap-1.5">
            {keywords.map(k => (
              <span key={k} className="inline-flex min-h-9 items-center gap-1 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] pl-3 pr-1 text-[13.5px]">{k}
                <button type="button" aria-label={`Remove ${k}`} onClick={() => setKeywords(keywords.filter(x => x !== k))}
                  className="flex size-7 items-center justify-center rounded-full text-[var(--y-ink-3)]"><X size={13} aria-hidden /></button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input id="folder-word" value={word} maxLength={40} onChange={e => setWord(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addWord(); } }}
              placeholder="A name, place or word, then Enter" className={field} />
            <button type="button" onClick={addWord} className="y-press min-h-11 shrink-0 rounded-full border border-[var(--y-line-strong)] px-4 text-[14px] font-medium">Add</button>
          </div>
          <p className="text-[12.5px] text-[var(--y-ink-3)]">A call that mentions any of these goes into the folder.</p>
        </div>
        <label className="grid gap-1.5 text-[13px] font-semibold text-[var(--y-ink-2)]">Sorting rule (optional)
          <textarea rows={4} value={prompt} maxLength={1000} onChange={e => setPrompt(e.target.value)}
            placeholder="Calls about the kitchen work at home: the designer, the tile dealer, the carpenter, money for it."
            className={cn(field, "py-2.5 leading-relaxed")} />
          <span className="text-[12.5px] font-normal text-[var(--y-ink-3)]">Say in your own words which calls belong here; Yaad reads each new call against it.</span>
        </label>
        <div className="flex gap-2">
          {folder && (
            <button type="button" disabled={del.isPending}
              onClick={() => { if (window.confirm(`Delete the folder “${folder.name}”? Its calls stay in Memories.`)) del.mutate(folder.id, { onSuccess: () => { onOpenChange(false); onDeleted?.(); } }); }}
              className="y-press min-h-12 rounded-full border border-[var(--y-late)] px-4 text-[15px] font-semibold text-[var(--y-late)]">Delete</button>
          )}
          <button type="submit" disabled={!name.trim() || save.isPending}
            className="y-press min-h-12 flex-1 rounded-full bg-[var(--y-brand)] text-[15px] font-semibold text-[var(--y-on-brand)] disabled:opacity-50">
            {save.isPending ? "Saving…" : folder ? "Save" : "Make folder"}
          </button>
        </div>
      </form>
    </Drawer>
  );
}

/** The folders list: `variant="side"` for the desktop sidebar, `"row"` for the phone's chip row on Memories. */
export function FolderLinks({ variant }: { variant: "side" | "row" }) {
  const q = useFolders();
  const pathname = usePathname() ?? "";
  const [making, setMaking] = useState(false);
  const folders = q.data?.folders ?? [];
  const active = (id: string) => pathname === `/dashboard/me/folders/${id}`;
  const sheet = making && <FolderSheet open onOpenChange={setMaking} />;

  if (variant === "row") {
    return (
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] md:hidden" aria-label="Folders">
        {folders.map(f => (
          <Link key={f.id} href={`/dashboard/me/folders/${f.id}`} className="y-press inline-flex min-h-10 shrink-0 items-center gap-2 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3.5 text-[14px]">
            <FolderDot color={f.color} />{f.name}<span className="text-[12px] text-[var(--y-ink-3)]">{f.count}</span>
          </Link>
        ))}
        {!!q.data?.unclassified && (
          <Link href="/dashboard/me/folders/unclassified" className="y-press inline-flex min-h-10 shrink-0 items-center gap-2 rounded-full border border-dashed border-[var(--y-line-strong)] px-3.5 text-[14px] text-[var(--y-ink-2)]">
            Unclassified <span className="text-[12px]">{q.data.unclassified}</span>
          </Link>
        )}
        <button type="button" onClick={() => setMaking(true)} className="y-press inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-full px-3 text-[14px] font-medium text-[var(--y-ink-2)]">
          <Plus size={14} aria-hidden /> New folder
        </button>
        {sheet}
      </div>
    );
  }
  const link = "flex min-h-10 items-center gap-3 rounded-xl px-3 text-[14px] transition-colors";
  return (
    <div className="mb-4">
      <p className="px-3 pb-1.5 text-[11.5px] font-semibold uppercase tracking-[0.06em] text-[var(--y-ink-3)]">Folders</p>
      {q.isPending ? (
        <div className="grid gap-1.5 px-3" aria-busy="true">{[0, 1].map(i => <div key={i} className="h-7 animate-pulse rounded-lg bg-[var(--y-line)]" />)}</div>
      ) : (
        <ul className="grid gap-0.5">
          {folders.map(f => (
            <li key={f.id}>
              <Link href={`/dashboard/me/folders/${f.id}`} aria-current={active(f.id) ? "page" : undefined}
                className={cn(link, active(f.id) ? "bg-[var(--y-soft)] font-semibold text-[var(--y-soft-ink)]" : "text-[var(--y-ink-2)] hover:bg-[var(--y-card)] hover:text-[var(--y-ink)]")}>
                <FolderDot color={f.color} /><span className="min-w-0 flex-1 truncate">{f.name}</span><span className="text-[12px] text-[var(--y-ink-3)]">{f.count}</span>
              </Link>
            </li>
          ))}
          <li>
            <Link href="/dashboard/me/folders/unclassified" aria-current={active("unclassified") ? "page" : undefined}
              className={cn(link, active("unclassified") ? "bg-[var(--y-soft)] font-semibold text-[var(--y-soft-ink)]" : "text-[var(--y-ink-2)] hover:bg-[var(--y-card)]")}>
              <span aria-hidden className="size-2.5 shrink-0 rounded-[3px] border border-dashed border-[var(--y-ink-3)]" />
              <span className="flex-1">Unclassified</span><span className="text-[12px] text-[var(--y-ink-3)]">{q.data?.unclassified ?? 0}</span>
            </Link>
          </li>
          <li>
            <button type="button" onClick={() => setMaking(true)} className={cn(link, "w-full text-[var(--y-ink-3)] hover:text-[var(--y-ink)]")}>
              <Plus size={15} aria-hidden /> New folder
            </button>
          </li>
        </ul>
      )}
      {sheet}
    </div>
  );
}
