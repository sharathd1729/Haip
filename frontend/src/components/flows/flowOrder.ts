// Linear Flow Builder steps (WhatsApp step 4): moving or inserting a step re-links the chain so every step points at the
// next one. The trigger stays first, "end" steps never point onward, and a link that already existed keeps its label.
export interface ChainNode { id: string; type: string }
export interface ChainEdge { id: string; from: string; to: string; label?: string }

let seq = 0;
const edgeId = () => `e${Date.now()}_${++seq}`;

export function relink<N extends ChainNode>(nodes: N[], edges: ChainEdge[]): ChainEdge[] {
  const out: ChainEdge[] = [];
  for (let i = 0; i < nodes.length - 1; i++) {
    const from = nodes[i], to = nodes[i + 1];
    if (from.type === "end") continue;
    const old = edges.find(e => e.from === from.id && e.to === to.id);
    out.push(old ?? { id: edgeId(), from: from.id, to: to.id });
  }
  return out;
}

/** Move a step to a new position (index in the list after removal). The trigger can't move and nothing goes above it. */
export function moveNode<N extends ChainNode>(nodes: N[], edges: ChainEdge[], id: string, toIndex: number): { nodes: N[]; edges: ChainEdge[] } {
  const from = nodes.findIndex(n => n.id === id);
  if (from < 0 || nodes[from].type === "trigger") return { nodes, edges };
  const rest = nodes.filter(n => n.id !== id);
  const firstFree = rest[0]?.type === "trigger" ? 1 : 0;
  const at = Math.max(firstFree, Math.min(toIndex, rest.length));
  const next = [...rest.slice(0, at), nodes[from], ...rest.slice(at)];
  return { nodes: next, edges: relink(next, edges) };
}

/** Insert a new step at a position (never above the trigger). */
export function insertNode<N extends ChainNode>(nodes: N[], edges: ChainEdge[], node: N, atIndex: number): { nodes: N[]; edges: ChainEdge[] } {
  const firstFree = nodes[0]?.type === "trigger" ? 1 : 0;
  const at = Math.max(firstFree, Math.min(atIndex, nodes.length));
  const next = [...nodes.slice(0, at), node, ...nodes.slice(at)];
  return { nodes: next, edges: relink(next, edges) };
}

/** Where a new step dropped "at the end" goes: just before a trailing End step. */
export function appendIndex(nodes: ChainNode[]): number {
  return nodes.length && nodes[nodes.length - 1].type === "end" ? nodes.length - 1 : nodes.length;
}

export const DELAY_UNITS = [
  { value: "minutes", label: "minutes", minutes: 1 },
  { value: "hours", label: "hours", minutes: 60 },
  { value: "days", label: "days", minutes: 1440 },
] as const;

export function describeDelay(minutes: number): string {
  if (minutes % 1440 === 0) { const d = minutes / 1440; return `Wait ${d} day${d === 1 ? "" : "s"}`; }
  if (minutes % 60 === 0) { const h = minutes / 60; return `Wait ${h} hour${h === 1 ? "" : "s"}`; }
  return `Wait ${minutes} min`;
}

export function splitDelay(minutes: number): { amount: number; unit: (typeof DELAY_UNITS)[number]["value"] } {
  if (minutes % 1440 === 0) return { amount: minutes / 1440, unit: "days" };
  if (minutes % 60 === 0) return { amount: minutes / 60, unit: "hours" };
  return { amount: minutes, unit: "minutes" };
}
