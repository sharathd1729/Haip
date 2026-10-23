"use client";
// The producer (studio plan phase 4): a 6-15 s template Reel from 2-5 library photos (rendered by HAIP's own reel
// renderer, with a cover frame). Drafts from a shoot brief are made on Plan > Strategy.
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState } from "@/components/ui/kit";
import { STUDIO, btnPrimary, inputCls, studioError, studioHref, type Asset } from "./types";

export function ProduceTab() {
  const { toast } = useToast();
  const [picked, setPicked] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [lines, setLines] = useState("");
  const [trial, setTrial] = useState(false);
  const media = useQuery<Asset[]>({ queryKey: ["studio-media"], queryFn: () => api.get(`${STUDIO}/media`).then(r => r.data) });
  const make = useMutation({
    mutationFn: () => api.post(`${STUDIO}/produce/reel-from-photos`, { title, caption, asset_ids: picked, trial,
      lines: lines.split("\n").map(l => l.trim()).filter(Boolean) }),
    onSuccess: () => { setPicked([]); setTitle(""); setCaption(""); setLines("");
      toast({ variant: "success", title: "Reel draft made", description: "Find it under Create > Content." }); },
    onError: e => toast({ variant: "error", title: "Not made", description: studioError(e, "Try again.") }),
  });
  const photos = (media.data ?? []).filter(a => a.mime_type.startsWith("image/") && (a.status ?? "active") === "active" && a.url);
  const toggle = (id: string) => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : p.length < 5 ? [...p, id] : p);
  return (
    <Card>
      <CardHeader title="Template Reel from photos" description="Pick 2 to 5 photos in order, one caption line each. HAIP makes a 6-15 second vertical Reel with your brand look and a cover frame, as a draft for approval." />
      <CardBody className="space-y-3">
        {media.isLoading ? <Skeleton className="h-32 w-full" /> : media.isError ? <EmptyState title="Could not load the library" hint={studioError(media.error, "Try again.")} />
          : photos.length < 2 ? <EmptyState title="Add photos first" hint="A template Reel needs at least 2 approved photos." action={<a className={btnPrimary} href={studioHref("library")}>Upload photos</a>} /> : (
          <ul className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            {photos.slice(0, 36).map(a => {
              const n = picked.indexOf(a.id);
              return (
                <li key={a.id}>
                  <button type="button" onClick={() => toggle(a.id)} aria-pressed={n >= 0} aria-label={a.alt_text ?? "Library photo"}
                    className={`relative block aspect-[9/16] w-full overflow-hidden rounded-lg border-2 ${n >= 0 ? "border-[var(--primary)]" : "border-transparent"}`}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={a.url as string} alt={a.alt_text ?? ""} className="h-full w-full object-cover" />
                    {n >= 0 && <span className="absolute left-1 top-1 rounded-full bg-[var(--primary)] px-2 text-xs font-bold text-primary-foreground">{n + 1}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <form className="grid gap-2" onSubmit={e => { e.preventDefault(); make.mutate(); }}>
          <input className={inputCls} placeholder="Title (e.g. Kabini nights)" maxLength={160} value={title} onChange={e => setTitle(e.target.value)} />
          <textarea className={inputCls} rows={3} placeholder={"One caption line per photo\nWe woke up here"} value={lines} onChange={e => setLines(e.target.value)} />
          <textarea className={inputCls} rows={2} placeholder="Post caption" maxLength={2200} value={caption} onChange={e => setCaption(e.target.value)} />
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="h-5 w-5" checked={trial} onChange={e => setTrial(e.target.checked)} /> Post as a trial Reel (shown to non-followers first)</label>
          <button type="submit" className={btnPrimary} disabled={make.isPending || picked.length < 2 || !caption.trim()}>Make the Reel draft</button>
        </form>
      </CardBody>
    </Card>
  );
}
