// Starting points offered on an empty canvas. No positions: fromStored() lays them out top to bottom.
import { uid, type StoredEdge, type StoredNode } from "./flowModel";

export interface FlowTemplate { key: string; title: string; hint: string; build: () => { nodes: StoredNode[]; edges: StoredEdge[] } }

/** Chains the nodes in order (each to the next with no label). */
function chain(nodes: StoredNode[]): StoredEdge[] {
  return nodes.slice(0, -1).map((n, i) => ({ id: uid("e"), from: n.id, to: nodes[i + 1].id, label: null }));
}

const trigger = (keywords: string[]): StoredNode =>
  ({ id: uid(), type: "trigger", label: "Start", trigger: "keyword", content: "keyword", keywords, match: "contains" });

export const FLOW_TEMPLATES: FlowTemplate[] = [
  {
    key: "greeting", title: "Greeting + brochure", hint: "hi / hello / hey, a welcome, then your brochure",
    build: () => {
      const nodes: StoredNode[] = [
        trigger(["hi", "hello", "hey"]),
        { id: uid(), type: "message", label: "Welcome", content: "Hi {first_name}, thanks for writing to us! Here is our brochure." },
        { id: uid(), type: "media", label: "Brochure", media_kind: "document", caption: "Our brochure" },
      ];
      return { nodes, edges: chain(nodes) };
    },
  },
  {
    key: "menu", title: "Menu with 3 choices", hint: "menu, then Villas / Weddings / Corporate, each with its own reply",
    build: () => {
      const choices = ["Villas", "Weddings", "Corporate"].map(title => ({ id: uid("b"), title }));
      const start = trigger(["menu"]);
      const menu: StoredNode = { id: uid(), type: "buttons", label: "Menu", content: "Hi {first_name}, what are you planning?", buttons: choices };
      const replies: StoredNode[] = choices.map(c => ({ id: uid(), type: "message", label: c.title, content: `Great, here is what we offer for ${c.title.toLowerCase()}.` }));
      return {
        nodes: [start, menu, ...replies],
        edges: [
          { id: uid("e"), from: start.id, to: menu.id, label: null },
          ...replies.map((r, i) => ({ id: uid("e"), from: menu.id, to: r.id, label: `btn:${choices[i].id}` })),
        ],
      };
    },
  },
  {
    key: "details", title: "Ask details", hint: "asks the guest's name and dates, then tells your team",
    build: () => {
      const nodes: StoredNode[] = [
        trigger(["book", "booking"]),
        { id: uid(), type: "question", label: "Name", content: "May I have your name?", save_as: "name" },
        { id: uid(), type: "question", label: "Dates", content: "Which dates are you looking at?", save_as: "notes" },
        { id: uid(), type: "action", label: "Notify team", action: "notify_agent", content: "notify_agent" },
      ];
      return { nodes, edges: chain(nodes) };
    },
  },
  {
    key: "drip", title: "Lead nurture drip", hint: "3 templates over 4 days, stops when they reply",
    build: () => {
      const wait = (days: number): StoredNode => ({ id: uid(), type: "delay", label: `Wait ${days} day${days > 1 ? "s" : ""}`, delay_minutes: days * 1440 });
      const still = (): StoredNode => ({ id: uid(), type: "condition", label: "Still no reply?", condition: "not_replied" });
      const tmpl = (label: string): StoredNode => ({ id: uid(), type: "template", label });
      const nodes: StoredNode[] = [
        { id: uid(), type: "trigger", label: "Start", trigger: "new_inquiry", content: "new_inquiry" },
        tmpl("Day 0: welcome"), wait(1), still(), tmpl("Day 1: follow-up"), wait(3), still(), tmpl("Day 4: last nudge"),
        { id: uid(), type: "end", label: "End" },
      ];
      // A condition continues on "yes" (still no reply).
      return { nodes, edges: chain(nodes).map(e => nodes.find(n => n.id === e.from)?.type === "condition" ? { ...e, label: "yes" } : e) };
    },
  },
];

/** A new flow: just the start block, waiting for a trigger. */
export function blankFlow(): { nodes: StoredNode[]; edges: StoredEdge[] } {
  return { nodes: [{ id: uid(), type: "trigger", label: "Start", trigger: "keyword", content: "keyword", keywords: [], match: "contains", position: { x: 0, y: 0 } }], edges: [] };
}
