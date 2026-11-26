"use client";
// What the guest sees on the first path through the flow (first button / row, "yes" on a condition), as a WhatsApp-style
// chat. Read-only: it shows the saved blocks, nothing is sent.
import { ExternalLink, FileText, List, MapPin } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Drawer } from "@/components/ui/kit";
import { blockTitle, summarize, triggerOf, type NodeData, type StoredEdge, type StoredNode } from "./flowModel";
import { previewPath } from "./flowGraph";

const SAMPLE_NAME = "Priya";
const fill = (s?: string) => (s ?? "").replaceAll("{first_name}", SAMPLE_NAME).replaceAll("{{name}}", SAMPLE_NAME);

function Bubble({ d }: { d: NodeData }) {
  const text = fill(d.content);
  return (
    <div className="max-w-[85%] self-start overflow-hidden rounded-2xl rounded-tl-sm bg-[var(--haip-card)] text-[14px] text-[var(--haip-fg)] shadow-sm">
      {d.type === "media" && (
        <div className="flex items-center gap-2 border-b border-[var(--haip-border)] bg-[var(--haip-surface)] px-3 py-2 text-[13px]">
          <FileText size={15} className="shrink-0 text-[var(--haip-fg-subtle)]" />
          <span className="truncate">{d.filename || `${blockTitle(d)} (no file yet)`}</span>
        </div>
      )}
      {d.type === "location" && (
        <div className="flex items-center gap-2 px-3 py-2"><MapPin size={15} className="text-primary" /><span>{d.name || summarize(d)}</span></div>
      )}
      {d.type === "template" && <p className="px-3 py-2 italic text-[var(--haip-fg-muted)]">{d.label || "Approved template"}</p>}
      {(text || (d.type === "media" && d.caption)) && <p className="whitespace-pre-wrap px-3 py-2">{text || fill(d.caption)}</p>}
      {d.type === "buttons" && (d.buttons ?? []).map(b => (
        <p key={b.id} className="border-t border-[var(--haip-border)] px-3 py-2 text-center font-semibold text-primary">{b.title}</p>
      ))}
      {d.type === "list" && (
        <p className="flex items-center justify-center gap-1.5 border-t border-[var(--haip-border)] px-3 py-2 font-semibold text-primary">
          <List size={14} /> {d.button_label || "Options"}
        </p>
      )}
      {d.type === "cta_url" && (
        <p className="flex items-center justify-center gap-1.5 border-t border-[var(--haip-border)] px-3 py-2 font-semibold text-primary">
          <ExternalLink size={14} /> {d.button_label || "Open"}
        </p>
      )}
    </div>
  );
}

function systemLine(d: NodeData): string {
  if (d.type === "condition") return `Checks: ${summarize(d)}, continues on Yes`;
  if (d.type === "end") return "Flow ends";
  if (d.type === "http") return `Calls ${summarize(d)}`;
  return [blockTitle(d), summarize(d)].filter(Boolean).join(": ");
}

export function FlowPreview({ open, onOpenChange, nodes, edges }: {
  open: boolean; onOpenChange: (o: boolean) => void; nodes: StoredNode[]; edges: StoredEdge[];
}) {
  const steps = previewPath(nodes, edges);
  return (
    <Drawer open={open} onOpenChange={onOpenChange} title="Preview" description="The first path, as the guest would see it.">
      <div className="flex min-h-full flex-col gap-2 rounded-2xl bg-[var(--haip-surface)] p-3">
        {steps.length <= 1 && <p className="py-8 text-center text-sm text-[var(--haip-fg-subtle)]">Connect a block to the start block to see a preview.</p>}
        {steps.map(s => {
          if (s.from === "guest") {
            const t = triggerOf(s.data);
            return (
              <p key={s.nodeId} className={cn("max-w-[85%] self-end rounded-2xl rounded-tr-sm px-3 py-2 text-[14px]",
                "bg-[var(--haip-primary-tint)] text-[var(--haip-fg)]")}>
                {t === "keyword" ? (s.data.keywords?.[0] ?? "hi") : summarize(s.data)}
              </p>
            );
          }
          if (s.from === "system") return <p key={s.nodeId} className="self-center text-center text-[12px] text-[var(--haip-fg-subtle)]">{systemLine(s.data)}</p>;
          return (
            <div key={s.nodeId} className="flex flex-col gap-2">
              <Bubble d={s.data} />
              {s.data.type === "buttons" && s.data.buttons?.[0] && (
                <p className="max-w-[85%] self-end rounded-2xl rounded-tr-sm bg-[var(--haip-primary-tint)] px-3 py-2 text-[14px]">{s.data.buttons[0].title}</p>
              )}
              {s.data.type === "list" && s.data.rows?.[0] && (
                <p className="max-w-[85%] self-end rounded-2xl rounded-tr-sm bg-[var(--haip-primary-tint)] px-3 py-2 text-[14px]">{s.data.rows[0].title}</p>
              )}
              {s.data.type === "question" && (
                <p className="max-w-[85%] self-end rounded-2xl rounded-tr-sm bg-[var(--haip-primary-tint)] px-3 py-2 text-[14px] italic text-[var(--haip-fg-muted)]">Guest answers</p>
              )}
            </div>
          );
        })}
      </div>
    </Drawer>
  );
}
