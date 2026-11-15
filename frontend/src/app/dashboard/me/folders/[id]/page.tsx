"use client";
// One Yaad folder (layout A, owner spec 15 Nov): its calls, the rule Yaad sorts by, and Ask about this folder beside it
// (docked from 1280px, a drawer below). /dashboard/me/folders/unclassified = summarised calls in no folder.
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AskBubble, Pencil } from "@/lib/icons";
import { Drawer } from "@/components/ui/kit";
import { AskYaad } from "@/components/personal/AskYaad";
import { CallList } from "@/components/personal/CallList";
import { FolderDot, FolderSheet } from "@/components/personal/Folders";
import { useFolders } from "@/components/personal/hooks";

export default function YaadFolderPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const q = useFolders();
  const [editing, setEditing] = useState(false);
  const [asking, setAsking] = useState(false);
  const unclassified = id === "unclassified";
  const folder = q.data?.folders.find(f => f.id === id) ?? null;
  const missing = !unclassified && q.isSuccess && !folder;

  return (
    <div className="yaad min-h-full px-4 py-5 sm:px-8 sm:py-8">
      <div className="mx-auto max-w-[1240px] xl:grid xl:grid-cols-[minmax(0,1fr)_380px] xl:items-start xl:gap-8">
        <div className="mx-auto grid w-full max-w-[860px] gap-4">
          {missing ? (
            <p className="rounded-[22px] border border-dashed border-[var(--y-line-strong)] bg-[var(--y-card)] px-6 py-12 text-center text-[15px]">This folder was deleted.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                {folder ? <FolderDot color={folder.color} size={14} /> : <span aria-hidden className="size-3.5 rounded-[3px] border border-dashed border-[var(--y-ink-3)]" />}
                <h1 className="text-[26px] font-semibold tracking-[-0.02em] sm:text-[30px]">{unclassified ? "Unclassified" : folder?.name ?? " "}</h1>
                <div className="ml-auto flex gap-2">
                  {folder && (
                    <button type="button" onClick={() => setEditing(true)} className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-3.5 text-[13.5px] font-medium">
                      <Pencil size={14} aria-hidden /> Edit folder
                    </button>
                  )}
                  {folder && (
                    <button type="button" onClick={() => setAsking(true)} className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full bg-[var(--y-brand)] px-3.5 text-[13.5px] font-semibold text-[var(--y-on-brand)] xl:hidden">
                      <AskBubble size={15} aria-hidden /> Ask
                    </button>
                  )}
                </div>
              </div>
              <p className="text-[14.5px] leading-relaxed text-[var(--y-ink-2)]">
                {unclassified ? "Summarised calls that are in no folder yet. Open one to put it in a folder."
                  : folder ? [folder.prompt && `Rule: ${folder.prompt}`, folder.keywords.length && `Keywords: ${folder.keywords.join(", ")}`].filter(Boolean).join(" · ") || "No keywords or rule yet: add calls by hand, or edit the folder."
                  : ""}
              </p>
              {(folder || unclassified) && <CallList filter={{ folder: id }} onSelect={cid => router.push(`/dashboard/me/calls/${cid}`)} />}
            </>
          )}
        </div>
        {folder && (
          <aside aria-label={`Ask about ${folder.name}`} className="sticky top-0 hidden max-h-[calc(100dvh-6rem)] flex-col overflow-y-auto rounded-[24px] border border-[var(--y-line)] bg-[var(--y-card)] p-5 shadow-[var(--y-shadow)] xl:flex">
            <h2 className="text-[16px] font-semibold">Ask about {folder.name}</h2>
            <p className="mb-3 mt-0.5 text-[12.5px] text-[var(--y-ink-3)]">Answers only from this folder's calls</p>
            <AskYaad compact folderId={folder.id} />
          </aside>
        )}
      </div>
      {folder && editing && <FolderSheet open onOpenChange={setEditing} folder={folder} onDeleted={() => router.push("/dashboard/me")} />}
      {folder && (
        <Drawer open={asking} onOpenChange={setAsking} title={`Ask about ${folder.name}`} description="Answers only from this folder's calls" className="yaad">
          <AskYaad compact folderId={folder.id} />
        </Drawer>
      )}
    </div>
  );
}
