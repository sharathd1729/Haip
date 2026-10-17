"use client";
// Behaviour shared by all six concepts (what is selected, what is open), so the concepts differ only in design.
import { useState } from "react";
import { CAL_DAYS, CAL_TODAY_INDEX, CONVERSATIONS, LEADS, RESERVATIONS, SELECTED_RES, TREND, type Reservation } from "./data";
import type { Screen } from "./concepts";

export interface ScreenProps { screen: Screen; go: (s: Screen) => void }

export function useInbox() {
  const [selected, setSelected] = useState(CONVERSATIONS[0].id);
  // On phones the list and the thread are two steps; `open` is the thread step.
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<"all" | "waiting" | "mine">("all");
  const [draft, setDraft] = useState<"ai" | "edited" | "sent">("ai");
  const list = CONVERSATIONS.filter(c => filter === "all" || (filter === "waiting" ? !!c.waiting : c.agent === "Asha Menon"));
  return {
    list, filter, setFilter, selected, open, draft, setDraft,
    conversation: CONVERSATIONS.find(c => c.id === selected)!,
    pick: (id: string) => { setSelected(id); setOpen(true); },
    back: () => setOpen(false),
  };
}

export function useLeads() {
  const [view, setView] = useState<"board" | "list">("board");
  const [active, setActive] = useState<string | null>(null);
  const [stage, setStage] = useState<string>("all");
  const list = LEADS.filter(l => stage === "all" || l.stage === stage);
  return { view, setView, active, setActive, stage, setStage, list, lead: LEADS.find(l => l.id === active) ?? null };
}

export function useCalendar() {
  const [selected, setSelected] = useState<string | null>(SELECTED_RES);
  const [day, setDay] = useState(CAL_TODAY_INDEX);
  const res = RESERVATIONS.find(r => r.id === selected) ?? null;
  const onDay = (i: number) => RESERVATIONS.filter(r => r.start <= i && r.end > i);
  return { selected, setSelected, res, day, setDay, onDay };
}

/** Bar geometry inside a timeline row: percentages of the visible window, check-in afternoon to check-out morning. */
export function barStyle(r: Reservation, days = CAL_DAYS): { left: string; width: string } {
  const start = (r.start + 0.5) / days;
  const end = (r.end + 0.5) / days;
  return { left: `${start * 100}%`, width: `${(end - start) * 100}%` };
}

/** An SVG path for the 14-day trend, in a viewBox of w x h. */
export function trendPath(w: number, h: number, pad = 2): { line: string; area: string; points: [number, number][] } {
  const max = Math.max(...TREND) || 1;
  const pts: [number, number][] = TREND.map((v, i) => [pad + (i * (w - pad * 2)) / (TREND.length - 1), h - pad - (v / max) * (h - pad * 2)]);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return { line, area: `${line} L${pts[pts.length - 1][0]},${h} L${pts[0][0]},${h} Z`, points: pts };
}
