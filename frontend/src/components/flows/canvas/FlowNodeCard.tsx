"use client";
// One block on the canvas: icon, title, a one-line summary, an input handle on top and its outputs. Buttons / list /
// condition blocks list each output as a row with its own handle on the right; the rest have one handle at the bottom.
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { ComponentType } from "react";
import {
  Ban, Bell, Clock, Code2, FileText, Flag, HelpCircle, Image, LayoutTemplate, Link2, List, ListChecks, MapPin,
  MessageSquare, PlayCircle, Shuffle, Tag, UserPlus, Volume2, Zap,
} from "@/lib/icons";
import { cn } from "@/lib/utils";
import { OUT, actionOf, blockTitle, outputsOf, summarize, type NodeData } from "./flowModel";
import type { FlowNode } from "./flowGraph";

type Icon = ComponentType<{ size?: number; className?: string }>;

const MEDIA_ICON: Record<string, Icon> = { image: Image, video: PlayCircle, audio: Volume2, document: FileText };
const ACTION_ICON: Record<string, Icon> = { add_label: Tag, tag_vip: Tag, notify_agent: Bell, create_inquiry: UserPlus, opt_out: Ban };
const TYPE_ICON: Record<string, Icon> = {
  trigger: Zap, message: MessageSquare, location: MapPin, buttons: ListChecks, list: List, cta_url: Link2,
  template: LayoutTemplate, question: HelpCircle, condition: Shuffle, delay: Clock, http: Code2, end: Flag,
};

export function iconFor(d: NodeData): Icon {
  if (d.type === "media") return MEDIA_ICON[d.media_kind ?? "document"] ?? FileText;
  if (d.type === "action") return ACTION_ICON[actionOf(d)] ?? Tag;
  return TYPE_ICON[d.type] ?? MessageSquare;
}

/** Tone per family, from status tokens only. */
export function toneFor(d: NodeData): string {
  if (d.type === "trigger") return "border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]";
  if (["condition", "delay", "action", "http"].includes(d.type)) return "border-[var(--haip-status-info-border)] bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]";
  if (d.type === "end") return "border-[var(--haip-border-strong)] bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)]";
  return "border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-[var(--haip-primary-tint)] text-primary";
}

const HANDLE = "!h-3.5 !w-3.5 !border-2 !border-[var(--haip-card)] !bg-[var(--haip-border-strong)]";

export function FlowNodeCard({ data, selected }: NodeProps<FlowNode>) {
  const Icon = iconFor(data);
  const outs = outputsOf(data);
  const single = outs.length === 1 && outs[0].id === OUT;
  const summary = summarize(data);
  return (
    <div className={cn("w-60 rounded-2xl border-2 border-[var(--haip-border)] bg-[var(--haip-card)] shadow-sm", selected && "ring-2 ring-primary ring-offset-2")}>
      {data.type !== "trigger" && <Handle type="target" position={Position.Top} className={HANDLE} />}
      <div className={cn("flex items-center gap-2 rounded-t-[14px] border-b px-3 py-2", toneFor(data))}>
        <Icon size={15} className="shrink-0" />
        <span className="truncate text-[12px] font-bold uppercase tracking-wide">{blockTitle(data)}</span>
      </div>
      <div className="px-3 py-2">
        {data.label && data.label !== blockTitle(data) && <p className="truncate text-[13px] font-semibold text-[var(--haip-fg)]">{data.label}</p>}
        <p className="line-clamp-2 text-[12.5px] text-[var(--haip-fg-muted)]">{summary || " "}</p>
      </div>
      {!single && outs.length > 0 && (
        <ul className="border-t border-[var(--haip-border)] py-1">
          {outs.map(o => (
            <li key={o.id} className={cn("relative px-3 py-1 text-right text-[12px]", o.id === "other" ? "italic text-[var(--haip-fg-subtle)]" : "font-medium text-[var(--haip-fg-2)]")}>
              <span className="block truncate pr-2">{o.label}</span>
              <Handle type="source" id={o.id} position={Position.Right} className={HANDLE} />
            </li>
          ))}
        </ul>
      )}
      {single && <Handle type="source" id={OUT} position={Position.Bottom} className={HANDLE} />}
    </div>
  );
}
