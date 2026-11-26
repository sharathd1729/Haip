"use client";
// Drag-and-drop WhatsApp flow editor (SMS9-style) on @xyflow/react. Saves the stored node/edge shape from
// docs/whatsapp/FLOW_CANVAS_SPEC.md through PUT/POST /messaging/flows. Desktop: palette left, settings right.
// Phones: the canvas pans/zooms inside the page (nothing scrolls sideways), blocks come from a bottom sheet and the
// settings open in a Drawer.
import "@xyflow/react/dist/style.css";
import {
  Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider, addEdge, useEdgesState, useNodesState, useReactFlow,
  type Connection, type IsValidConnection,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { AlertCircle, CheckCircle2, ChevronLeft, Eye, Layers, Loader2, Save, Target, Trash2, X } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { BottomSheet, Drawer } from "@/components/ui/kit";
import { BLOCKS, OUT, blockTitle, outputsOf, triggerOf, uid, type NodeData, type StoredEdge, type StoredNode } from "./flowModel";
import { GAP_Y, fromStored, pruneEdges, toStored, validateFlow, type FlowEdge, type FlowNode, type Problem } from "./flowGraph";
import { FLOW_TEMPLATES } from "./flowTemplates";
import { BlockPalette, DRAG_BLOCK } from "./BlockPalette";
import { FlowNodeCard } from "./FlowNodeCard";
import { NodeFields } from "./NodeFields";
import { FlowPreview } from "./FlowPreview";

export interface FlowRecord {
  id?: string;
  name: string;
  description: string | null;
  nodes: StoredNode[];
  edges: StoredEdge[];
  is_active: boolean;
  trigger: string | null;
}

const NODE_TYPES = { flow: FlowNodeCard };
const btn = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl px-3 text-[13px] font-semibold transition-colors disabled:opacity-50";
const ghost = cn(btn, "border border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]");

/** FastAPI 422s carry either a plain string or a list of {msg}. */
function errorText(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(d => (d as { msg?: string })?.msg ?? String(d)).join("; ");
  return "Couldn't save the flow. Check your connection and try again.";
}

function usePhone() {
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const apply = () => setPhone(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return phone;
}

export function FlowCanvasEditor(props: { flow: FlowRecord; onBack: () => void; onSaved: (flow: FlowRecord) => void }) {
  return <ReactFlowProvider><Editor {...props} /></ReactFlowProvider>;
}

function Editor({ flow, onBack, onSaved }: { flow: FlowRecord; onBack: () => void; onSaved: (flow: FlowRecord) => void }) {
  const initial = useMemo(() => fromStored(flow.nodes ?? [], flow.edges ?? []), [flow]);
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>(initial.edges);
  const [name, setName] = useState(flow.name);
  const [flowId, setFlowId] = useState(flow.id);
  const [active, setActive] = useState(flow.is_active);
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [notice, setNotice] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const phone = usePhone();
  const { screenToFlowPosition, fitView, deleteElements } = useReactFlow<FlowNode, FlowEdge>();
  const wrapper = useRef<HTMLDivElement>(null);

  const stored = useMemo(() => toStored(nodes, edges), [nodes, edges]);
  const snapshot = (n: typeof stored, nm: string) => JSON.stringify([nm, n.nodes, n.edges]);
  const [savedSnap, setSavedSnap] = useState(() => snapshot(toStored(initial.nodes, initial.edges), flow.name));
  const dirty = snapshot(stored, name) !== savedSnap;

  const selected = nodes.filter(n => n.selected);
  const current = selected.length === 1 ? selected[0] : null;
  const onlyTrigger = nodes.length <= 1;

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [notice]);

  const select = useCallback((id: string | null) => setNodes(ns => ns.map(n => ({ ...n, selected: n.id === id }))), [setNodes]);

  // One edge per output handle: a new connection from a handle replaces the old one.
  const onConnect = useCallback((c: Connection) => {
    const handle = c.sourceHandle ?? OUT;
    setEdges(es => addEdge({ ...c, sourceHandle: handle, id: uid("e") }, es.filter(e => !(e.source === c.source && (e.sourceHandle ?? OUT) === handle))));
  }, [setEdges]);

  const isValidConnection: IsValidConnection<FlowEdge> = useCallback(c => {
    if (c.source === c.target) return false;
    return nodes.find(n => n.id === c.target)?.data.type !== "trigger";
  }, [nodes]);

  const addBlock = useCallback((key: string, at?: { x: number; y: number }) => {
    const block = BLOCKS.find(b => b.key === key);
    if (!block) return;
    const anchor = current ?? [...nodes].sort((a, b) => b.position.y - a.position.y)[0];
    const position = at ?? (anchor ? { x: anchor.position.x, y: anchor.position.y + GAP_Y } : { x: 0, y: 0 });
    const node: FlowNode = { id: uid(), type: "flow", position, data: block.make(), selected: true };
    setNodes(ns => [...ns.map(n => ({ ...n, selected: false })), node]);
    // Tapping a block under a selected single-output block that has no next step connects them.
    if (!at && current && outputsOf(current.data).some(o => o.id === OUT) && !edges.some(e => e.source === current.id)) {
      setEdges(es => [...es, { id: uid("e"), source: current.id, target: node.id, sourceHandle: OUT }]);
    }
    setPaletteOpen(false);
    if (!at) requestAnimationFrame(() => fitView({ nodes: [{ id: node.id }], duration: 250, maxZoom: 1 }));
  }, [current, nodes, edges, setNodes, setEdges, fitView]);

  const onDrop = useCallback((e: DragEvent) => {
    const key = e.dataTransfer.getData(DRAG_BLOCK);
    if (!key) return;
    e.preventDefault();
    addBlock(key, screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  }, [addBlock, screenToFlowPosition]);

  const updateData = useCallback((id: string, patch: Partial<NodeData>) => {
    const next = nodes.map(n => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n));
    setNodes(next);
    setEdges(es => pruneEdges(next, es));
  }, [nodes, setNodes, setEdges]);

  const deleteSelected = () => {
    void deleteElements({ nodes: selected.filter(n => n.data.type !== "trigger").map(n => ({ id: n.id })), edges: edges.filter(e => e.selected).map(e => ({ id: e.id })) });
  };

  const applyTemplate = (key: string) => {
    const t = FLOW_TEMPLATES.find(x => x.key === key);
    if (!t) return;
    const built = t.build();
    const next = fromStored(built.nodes, built.edges);
    setNodes(next.nodes);
    setEdges(next.edges);
    if (!name.trim() || name === "New flow") setName(t.title);
    setProblems([]);
    requestAnimationFrame(() => fitView({ duration: 250, padding: 0.2 }));
  };

  const save = async () => {
    const found = validateFlow(stored.nodes, stored.edges);
    if (!name.trim()) found.unshift({ message: "Give the flow a name." });
    setProblems(found);
    if (found.length) return;
    setSaving(true);
    try {
      const trig = stored.nodes.find(n => n.type === "trigger");
      const body = { name: name.trim(), description: flow.description, nodes: stored.nodes, edges: stored.edges, trigger: trig ? triggerOf(trig) || null : null };
      const res = flowId ? await api.put(`/messaging/flows/${flowId}`, body) : await api.post("/messaging/flows", body);
      setFlowId(res.data.id);
      setSavedSnap(snapshot(stored, name));
      setNotice({ type: "success", msg: "Flow saved." });
      onSaved(res.data);
    } catch (err) {
      setNotice({ type: "error", msg: errorText(err) });
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async () => {
    if (!flowId) return;
    setToggling(true);
    try {
      const res = await api.patch(`/messaging/flows/${flowId}/activate`);
      setActive(!!res.data.is_active);
      setNotice({ type: "success", msg: res.data.is_active ? "Flow is live." : "Flow paused." });
    } catch (err) {
      setNotice({ type: "error", msg: errorText(err) });
    } finally {
      setToggling(false);
    }
  };

  const back = () => { if (!dirty || confirm("Leave without saving your changes?")) onBack(); };

  const settings = current && <NodeFields key={current.id} data={current.data} onChange={patch => updateData(current.id, patch)} />;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex flex-shrink-0 flex-wrap items-center gap-2 border-b border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 sm:px-4">
        <button type="button" onClick={back} aria-label="Back to flows" className={cn(ghost, "px-2")}><ChevronLeft size={16} /><span className="hidden sm:inline">Flows</span></button>
        <input value={name} onChange={e => setName(e.target.value)} aria-label="Flow name" placeholder="Flow name"
          className="min-h-11 min-w-0 flex-1 basis-40 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base font-semibold text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary/30 sm:text-sm" />
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" role="switch" aria-checked={active} onClick={toggleActive} disabled={!flowId || toggling}
            title={flowId ? undefined : "Save the flow first"}
            className={cn(btn, "border", active ? "border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)] text-[var(--haip-fg-muted)]")}>
            <span className={cn("relative h-5 w-9 rounded-full transition-colors", active ? "bg-primary" : "bg-[var(--haip-border-strong)]")}>
              <span className={cn("absolute top-0.5 size-4 rounded-full bg-[var(--haip-card)] transition-transform", active ? "translate-x-[18px]" : "translate-x-0.5")} />
            </span>
            {active ? "Active" : "Paused"}
          </button>
          <button type="button" onClick={() => setPreviewOpen(true)} aria-label="Preview" className={ghost}><Eye size={15} /><span className="hidden sm:inline">Preview</span></button>
          <button type="button" onClick={() => fitView({ duration: 250, padding: 0.2 })} aria-label="Fit to screen" className={ghost}><Target size={15} /></button>
          <button type="button" onClick={deleteSelected} aria-label="Delete selected" disabled={!selected.some(n => n.data.type !== "trigger") && !edges.some(e => e.selected)}
            className={cn(ghost, "hover:text-[var(--haip-status-danger-fg)]")}><Trash2 size={15} /></button>
          <button type="button" onClick={save} disabled={saving} className={cn(btn, "bg-primary text-primary-foreground")}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} {flowId && !dirty ? "Saved" : "Save"}
          </button>
        </div>
      </div>

      {problems.length > 0 && (
        <div role="alert" className="flex-shrink-0 border-b border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] px-4 py-2 text-[13px] text-[var(--haip-status-danger-fg)]">
          <div className="flex items-start gap-2">
            <AlertCircle size={15} className="mt-0.5 shrink-0" />
            <ul className="min-w-0 flex-1 space-y-0.5">
              {problems.slice(0, 5).map((p, i) => (
                <li key={i}>
                  {p.nodeId ? <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => { select(p.nodeId!); fitView({ nodes: [{ id: p.nodeId! }], duration: 250, maxZoom: 1 }); }}>
                    {blockTitle(nodes.find(n => n.id === p.nodeId)?.data ?? { type: "message" })}: {p.message}</button> : p.message}
                </li>
              ))}
              {problems.length > 5 && <li>and {problems.length - 5} more.</li>}
            </ul>
            <button type="button" aria-label="Dismiss" onClick={() => setProblems([])} className="-m-2 flex size-11 items-center justify-center"><X size={14} /></button>
          </div>
        </div>
      )}

      <div className="relative flex min-h-0 flex-1">
        <aside className="hidden w-60 flex-shrink-0 overflow-y-auto border-r border-[var(--haip-border)] bg-[var(--haip-card)] p-3 md:block">
          <BlockPalette onAdd={key => addBlock(key)} />
        </aside>

        <div ref={wrapper} className="relative min-w-0 flex-1" onDragOver={e => { if (e.dataTransfer.types.includes(DRAG_BLOCK)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } }} onDrop={onDrop}>
          <ReactFlow<FlowNode, FlowEdge>
            nodes={nodes} edges={edges} nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} isValidConnection={isValidConnection}
            onPaneClick={() => select(null)} selectNodesOnDrag={false} fitView fitViewOptions={{ padding: 0.2, maxZoom: 1 }} minZoom={0.2}
            deleteKeyCode={["Backspace", "Delete"]} defaultEdgeOptions={{ type: "smoothstep" }} proOptions={{ hideAttribution: true }}
            className="bg-[var(--haip-surface)] [--xy-edge-stroke:var(--haip-border-strong)] [--xy-edge-stroke-selected:var(--primary)] [--xy-connectionline-stroke:var(--primary)] [--xy-background-pattern-dots-color:var(--haip-border)] [--xy-controls-button-background-color:var(--haip-card)] [--xy-controls-button-color:var(--haip-fg-2)] [--xy-controls-button-border-color:var(--haip-border)]">
            <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} />
            <Controls showInteractive={false} position="bottom-left" />
          </ReactFlow>

          {onlyTrigger && (
            <div className="pointer-events-none absolute inset-x-0 bottom-20 flex justify-center px-4 md:bottom-6">
              <div className="pointer-events-auto w-full max-w-xl rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-3 shadow-[var(--haip-shadow-lg)]">
                <p className="mb-2 text-[13px] font-semibold text-[var(--haip-fg)]">Start from a template, or add blocks yourself</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {FLOW_TEMPLATES.map(t => (
                    <button key={t.key} type="button" onClick={() => applyTemplate(t.key)}
                      className="flex min-h-11 flex-col items-start rounded-xl border border-[var(--haip-border)] px-3 py-2 text-left hover:border-primary hover:bg-[var(--haip-primary-tint)]">
                      <span className="text-[13px] font-semibold text-[var(--haip-fg)]">{t.title}</span>
                      <span className="text-[12px] text-[var(--haip-fg-subtle)]">{t.hint}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          <button type="button" onClick={() => setPaletteOpen(true)}
            className={cn(btn, "absolute bottom-4 right-4 z-10 bg-primary text-primary-foreground shadow-[var(--haip-shadow-lg)] md:hidden")}>
            <Layers size={16} /> Add block
          </button>
        </div>

        {!phone && current && (
          <aside className="flex w-80 flex-shrink-0 flex-col border-l border-[var(--haip-border)] bg-[var(--haip-card)]">
            <div className="flex items-center justify-between border-b border-[var(--haip-border)] px-4 py-2">
              <span className="text-sm font-bold text-[var(--haip-fg)]">{blockTitle(current.data)}</span>
              <button type="button" aria-label="Close settings" onClick={() => select(null)} className="-mr-2 flex size-11 items-center justify-center text-[var(--haip-fg-subtle)]"><X size={16} /></button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">{settings}</div>
          </aside>
        )}
      </div>

      {phone && <Drawer open={!!current} onOpenChange={o => { if (!o) select(null); }} title={current ? blockTitle(current.data) : ""}>{settings}</Drawer>}
      <BottomSheet open={paletteOpen} onOpenChange={setPaletteOpen} title="Add a block" description="Tap a block to add it under the selected one.">
        <BlockPalette onAdd={key => addBlock(key)} />
      </BottomSheet>
      <FlowPreview open={previewOpen} onOpenChange={setPreviewOpen} nodes={stored.nodes} edges={stored.edges} />

      {notice && (
        <div role="status" className={cn("fixed bottom-24 left-4 right-4 z-50 flex items-center gap-2 rounded-xl border px-4 py-3 text-sm font-medium shadow-lg sm:left-auto sm:max-w-sm md:bottom-6",
          notice.type === "success" ? "border-[var(--haip-status-success-border)] bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]" : "border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]")}>
          {notice.type === "success" ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
          <span className="flex-1">{notice.msg}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)} className="-m-2 flex size-11 items-center justify-center"><X size={13} /></button>
        </div>
      )}
    </div>
  );
}
