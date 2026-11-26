// Canvas <-> stored shape, auto-layout for old position-less flows, client checks that mirror the backend's save
// validation, and the preview walk. Pure (React Flow types only), covered by flowGraph.test.ts.
import type { Edge, Node } from "@xyflow/react";
import { LIMITS, OUT, outputsOf, triggerOf, type NodeData, type StoredEdge, type StoredNode } from "./flowModel";

export type FlowNode = Node<NodeData, "flow">;
export type FlowEdge = Edge;

export const GAP_X = 280;
export const GAP_Y = 170;

/** Places nodes that have no `position` top to bottom: depth from the trigger (breadth first) picks the row, siblings
 *  spread sideways around x = 0. Nodes nothing reaches go in rows below. Nodes that already have a position keep it. */
export function autoLayout(nodes: StoredNode[], edges: StoredEdge[]): StoredNode[] {
  if (nodes.every(n => n.position)) return nodes;
  const depth = new Map<string, number>();
  const start = nodes.find(n => n.type === "trigger") ?? nodes[0];
  const queue: string[] = start ? [start.id] : [];
  if (start) depth.set(start.id, 0);
  while (queue.length) {
    const id = queue.shift()!;
    for (const e of edges) {
      if (e.from === id && !depth.has(e.to)) { depth.set(e.to, depth.get(id)! + 1); queue.push(e.to); }
    }
  }
  let next = Math.max(-1, ...depth.values()) + 1;
  for (const n of nodes) if (!depth.has(n.id)) depth.set(n.id, next++);
  const rows = new Map<number, string[]>();
  for (const n of nodes) rows.set(depth.get(n.id)!, [...(rows.get(depth.get(n.id)!) ?? []), n.id]);
  return nodes.map(n => {
    if (n.position) return n;
    const row = rows.get(depth.get(n.id)!)!;
    const i = row.indexOf(n.id);
    return { ...n, position: { x: (i - (row.length - 1) / 2) * GAP_X, y: depth.get(n.id)! * GAP_Y } };
  });
}

/** Old condition edges were labelled true/false. */
const LEGACY_HANDLE: Record<string, string> = { true: "yes", false: "no" };

export function fromStored(nodes: StoredNode[], edges: StoredEdge[]): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const placed = autoLayout(nodes, edges);
  const byId = new Map(placed.map(n => [n.id, n]));
  // Old flows keep the trigger / action key only in `content`; copy it to the spec's field (content stays for the engine).
  const flowNodes: FlowNode[] = placed.map(({ id, position, x: _x, y: _y, ...data }) => ({
    id, type: "flow", position: position!, deletable: data.type !== "trigger",
    data: (data.type === "trigger" && !data.trigger && data.content ? { ...data, trigger: data.content }
      : data.type === "action" && !data.action && data.content ? { ...data, action: data.content } : data) as NodeData,
  }));
  const flowEdges: FlowEdge[] = edges.filter(e => byId.has(e.from) && byId.has(e.to)).map(e => {
    const outs = outputsOf(byId.get(e.from)!).map(o => o.id);
    const raw = (e.label ?? "").toLowerCase();
    // No label = the old single edge (on a condition that was the "yes" path); an unknown label is dropped by pruneEdges.
    const handle = outs.includes(e.label ?? "") ? e.label! : outs.includes(LEGACY_HANDLE[raw]) ? LEGACY_HANDLE[raw] : !raw ? outs[0] ?? OUT : e.label!;
    return { id: e.id, source: e.from, target: e.to, sourceHandle: handle };
  });
  return { nodes: flowNodes, edges: pruneEdges(flowNodes, flowEdges) };
}

export function toStored(nodes: FlowNode[], edges: FlowEdge[]): { nodes: StoredNode[]; edges: StoredEdge[] } {
  return {
    nodes: nodes.map(n => ({ ...n.data, id: n.id, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } })),
    edges: edges.map(e => ({ id: e.id, from: e.source, to: e.target, label: !e.sourceHandle || e.sourceHandle === OUT ? null : e.sourceHandle })),
  };
}

/** Drops edges whose source handle no longer exists (a removed button/row) and keeps one edge per handle. */
export function pruneEdges(nodes: FlowNode[], edges: FlowEdge[]): FlowEdge[] {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const seen = new Set<string>();
  return edges.filter(e => {
    const src = byId.get(e.source);
    if (!src || !byId.has(e.target)) return false;
    const handle = e.sourceHandle ?? OUT;
    if (!outputsOf(src.data).some(o => o.id === handle)) return false;
    const key = `${e.source}|${handle}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// ─── Client checks (mirror the backend's save validation) ────────────────────

export interface Problem { nodeId?: string; message: string }
const isHttps = (u?: string) => { try { return new URL(u ?? "").protocol === "https:" && !!new URL(u!).hostname } catch { return false } };

export function validateFlow(nodes: StoredNode[], edges: StoredEdge[]): Problem[] {
  const out: Problem[] = [];
  const add = (message: string, nodeId?: string) => out.push({ nodeId, message });
  const triggers = nodes.filter(n => n.type === "trigger");
  if (triggers.length !== 1) add(triggers.length ? "A flow can have only one start block." : "The flow needs a start block.");
  const ids = new Set<string>();
  for (const n of nodes) {
    if (ids.has(n.id)) add(`Two blocks share the id ${n.id}.`, n.id);
    ids.add(n.id);
  }
  for (const n of nodes) {
    const at = (m: string) => add(m, n.id);
    if ((n.content ?? "").length > 1024 && n.type !== "trigger" && n.type !== "action") at("Keep the message to 1024 characters.");
    switch (n.type) {
      case "trigger":
        if (!triggerOf(n)) at("Choose what starts the flow.");
        else if (triggerOf(n) === "keyword" && !(n.keywords ?? []).some(k => k.trim())) at("Add at least one keyword.");
        break;
      case "message": case "question":
        if (!(n.content ?? "").trim()) at(`${n.type === "question" ? "A question" : "A text block"} is empty.`);
        if (n.type === "question" && !/^(name|email|notes|custom:\S+)$/.test(n.save_as ?? "")) at("Choose where to save the answer.");
        break;
      case "media": if (!n.file_key) at("Upload a file for each media block."); break;
      case "location":
        if (typeof n.latitude !== "number" || typeof n.longitude !== "number" || Math.abs(n.latitude) > 90 || Math.abs(n.longitude) > 180)
          at("A location needs a valid latitude and longitude.");
        break;
      case "buttons": case "list": {
        const opts = (n.type === "buttons" ? n.buttons : n.rows) ?? [];
        const max = n.type === "buttons" ? LIMITS.buttons : LIMITS.rows;
        const titleMax = n.type === "buttons" ? LIMITS.buttonTitle : LIMITS.rowTitle;
        if (!(n.content ?? "").trim()) at("Write the message shown above the options.");
        if (opts.length < 1 || opts.length > max) at(`Use 1 to ${max} ${n.type === "buttons" ? "buttons" : "rows"}.`);
        if (new Set(opts.map(o => o.id)).size !== opts.length) at("Two options share an id.");
        if (new Set(opts.map(o => o.title.trim().toLowerCase())).size !== opts.length) at("Two options have the same title.");
        for (const o of opts) {
          if (!o.title.trim()) at("Every option needs a title.");
          else if (o.title.length > titleMax) at(`"${o.title}" is longer than ${titleMax} characters.`);
          if ((o.description ?? "").length > LIMITS.rowDescription) at(`A row description is longer than ${LIMITS.rowDescription} characters.`);
        }
        if (n.type === "list") checkButtonLabel(n, at);
        break;
      }
      case "cta_url":
        checkButtonLabel(n, at);
        if (!(n.content ?? "").trim()) at("Write the message shown above the link button.");
        if (!isHttps(n.url)) at("The link must start with https://");
        break;
      case "http": if (!isHttps(n.url)) at("The HTTP API address must start with https://"); break;
      case "template": if (!n.template_id) at("Choose an approved template."); break;
      case "action": if ((n.action ?? n.content) === "add_label" && !(n.tag ?? "").trim()) at("Write the label to add."); break;
    }
  }
  const edgeIds = new Set<string>();
  for (const e of edges) {
    if (edgeIds.has(e.id)) add(`Two connections share the id ${e.id}.`);
    edgeIds.add(e.id);
    if (!ids.has(e.from) || !ids.has(e.to)) add("A connection points at a block that no longer exists.");
  }
  return out;
}

function checkButtonLabel(n: StoredNode, at: (m: string) => void) {
  const l = (n.button_label ?? "").trim();
  if (!l) at("The button needs a label.");
  else if (l.length > LIMITS.buttonLabel) at(`The button label is longer than ${LIMITS.buttonLabel} characters.`);
}

// ─── Preview: walk the first path ─────────────────────────────────────────────

export interface PreviewStep { nodeId: string; from: "guest" | "business" | "system"; data: NodeData }

/** From the start block, follow the first connection of each block (the first button / row, "yes" on a condition) until
 *  a block has no way on, or a block repeats. */
export function previewPath(nodes: StoredNode[], edges: StoredEdge[], limit = 30): PreviewStep[] {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const steps: PreviewStep[] = [];
  const seen = new Set<string>();
  let cur = nodes.find(n => n.type === "trigger");
  while (cur && !seen.has(cur.id) && steps.length < limit) {
    seen.add(cur.id);
    const kind = cur.type === "trigger" ? "guest" : ["condition", "delay", "action", "http", "end"].includes(cur.type) ? "system" : "business";
    steps.push({ nodeId: cur.id, from: kind, data: cur });
    const outs = outputsOf(cur).map(o => o.id);
    const mine = edges.filter(e => e.from === cur!.id);
    const next = outs.map(h => mine.find(e => (e.label ?? OUT) === h)).find(Boolean) ?? mine[0];
    cur = next ? byId.get(next.to) : undefined;
  }
  return steps;
}
