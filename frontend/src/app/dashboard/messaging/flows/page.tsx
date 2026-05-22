"use client";
import { useState, useCallback, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  GitBranch, Plus, Save, Play, Pause, Trash2,
  X, CheckCircle2, AlertCircle, Loader2, MessageSquare,
  Zap, ArrowRight, ChevronRight, Settings, Move,
  ToggleLeft, Clock, Users, Send, Hash,
} from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface FlowNode {
  id: string;
  type: "trigger" | "message" | "condition" | "delay" | "action" | "end";
  label: string;
  content?: string;
  condition?: string;
  delay_minutes?: number;
  x: number;
  y: number;
}

interface FlowEdge {
  id: string;
  from: string;
  to: string;
  label?: string;
}

interface Flow {
  id: string;
  name: string;
  description: string | null;
  nodes: FlowNode[];
  edges: FlowEdge[];
  is_active: boolean;
  trigger: string | null;
  created_at: string | null;
}

// ─── Node type definitions ────────────────────────────────────────────────────

const NODE_TYPES = {
  trigger: { label: "Trigger", icon: <Zap size={14} />, color: "bg-amber-50 border-amber-300 text-amber-700", dot: "bg-amber-400" },
  message: { label: "Send Message", icon: <MessageSquare size={14} />, color: "bg-indigo-50 border-indigo-300 text-indigo-700", dot: "bg-indigo-400" },
  condition: { label: "Condition", icon: <GitBranch size={14} />, color: "bg-blue-50 border-blue-300 text-blue-700", dot: "bg-blue-400" },
  delay: { label: "Wait / Delay", icon: <Clock size={14} />, color: "bg-purple-50 border-purple-300 text-purple-700", dot: "bg-purple-400" },
  action: { label: "Action", icon: <Zap size={14} />, color: "bg-pink-50 border-pink-300 text-pink-700", dot: "bg-pink-400" },
  end: { label: "End", icon: <Hash size={14} />, color: "bg-gray-50 border-gray-300 text-gray-500", dot: "bg-gray-400" },
};

const TRIGGER_OPTIONS = [
  { value: "opt_in", label: "Contact opts in" },
  { value: "keyword", label: "Keyword reply" },
  { value: "campaign_reply", label: "Campaign reply" },
  { value: "new_inquiry", label: "New inquiry created" },
  { value: "check_in", label: "Guest check-in (D-1)" },
  { value: "check_out", label: "Guest check-out (D+1)" },
];

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn("fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-green-50 text-green-800 border-green-200" : "bg-red-50 text-red-800 border-red-200")}>
      {type === "success" ? <CheckCircle2 size={15} className="text-green-600" /> : <AlertCircle size={15} className="text-red-600" />}
      <span className="flex-1">{msg}</span>
      <button onClick={onClose}><X size={13} className="opacity-60" /></button>
    </div>
  );
}

// ─── Flow Canvas (simplified visual builder) ──────────────────────────────────

function FlowCanvas({
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
  onAddNode,
  onDeleteNode,
}: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  onAddNode: (type: FlowNode["type"], afterId?: string) => void;
  onDeleteNode: (id: string) => void;
}) {
  return (
    <div className="relative w-full overflow-auto bg-[#f8fafc]" style={{ minHeight: "500px", backgroundImage: "radial-gradient(circle, #e2e8f0 1px, transparent 1px)", backgroundSize: "24px 24px" }}>
      <div className="p-8 flex flex-col items-start gap-0 min-w-[600px]">
        {nodes.map((node, idx) => {
          const cfg = NODE_TYPES[node.type] ?? NODE_TYPES.message;
          const isSelected = selectedNodeId === node.id;
          const nextNode = nodes[idx + 1];
          const edge = edges.find(e => e.from === node.id);

          return (
            <div key={node.id} className="flex flex-col items-center">
              {/* Node */}
              <div
                onClick={() => onSelectNode(isSelected ? null : node.id)}
                className={cn(
                  "w-72 rounded-2xl border-2 p-4 cursor-pointer transition-all shadow-sm hover:shadow-md group relative",
                  cfg.color,
                  isSelected && "ring-2 ring-offset-2 ring-indigo-500 shadow-md"
                )}
              >
                <div className="flex items-start gap-3">
                  <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0", cfg.dot.replace("bg-", "bg-").replace("400", "100"))}>
                    <span className={cn(cfg.dot.replace("bg-", "text-"))}>{cfg.icon}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold uppercase tracking-wide opacity-60">{cfg.label}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); onDeleteNode(node.id); }}
                        className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 transition-all"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                    <p className="text-sm font-semibold mt-0.5 truncate">{node.label}</p>
                    {node.content && <p className="text-[11px] opacity-60 mt-0.5 truncate">{node.content}</p>}
                    {node.delay_minutes && <p className="text-[11px] opacity-60 mt-0.5">Wait {node.delay_minutes} min</p>}
                  </div>
                </div>
              </div>

              {/* Connector + add button */}
              {node.type !== "end" && (
                <div className="flex flex-col items-center py-1">
                  <div className="w-0.5 h-4 bg-gray-300" />
                  {edge?.label && (
                    <span className="text-[9px] bg-white border border-gray-200 rounded px-1.5 py-0.5 text-gray-500 font-medium">{edge.label}</span>
                  )}
                  <button
                    onClick={() => onAddNode("message", node.id)}
                    className="w-6 h-6 rounded-full bg-white border-2 border-gray-300 flex items-center justify-center text-gray-400 hover:border-indigo-500 hover:text-indigo-500 hover:bg-indigo-50 transition-all"
                    title="Add step"
                  >
                    <Plus size={12} />
                  </button>
                  <div className="w-0.5 h-4 bg-gray-300" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Node Editor Panel ────────────────────────────────────────────────────────

function NodeEditorPanel({
  node,
  onUpdate,
  onClose,
}: {
  node: FlowNode;
  onUpdate: (id: string, changes: Partial<FlowNode>) => void;
  onClose: () => void;
}) {
  const [local, setLocal] = useState({ ...node });

  return (
    <div className="w-72 bg-white border-l border-gray-100 flex flex-col h-full shadow-xl">
      <div className="px-4 py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-gray-900">Edit step</span>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div>
          <label className="text-xs font-semibold text-gray-700 block mb-1.5">Step type</label>
          <select value={local.type}
            onChange={e => setLocal(l => ({ ...l, type: e.target.value as FlowNode["type"] }))}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30">
            {Object.entries(NODE_TYPES).map(([t, cfg]) => (
              <option key={t} value={t}>{cfg.label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs font-semibold text-gray-700 block mb-1.5">Step label</label>
          <input value={local.label} onChange={e => setLocal(l => ({ ...l, label: e.target.value }))}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30" />
        </div>

        {local.type === "trigger" && (
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Trigger event</label>
            <select value={local.content ?? ""} onChange={e => setLocal(l => ({ ...l, content: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30">
              <option value="">Select trigger…</option>
              {TRIGGER_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
        )}

        {local.type === "message" && (
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Message content</label>
            <textarea value={local.content ?? ""} onChange={e => setLocal(l => ({ ...l, content: e.target.value }))} rows={4}
              placeholder={"Hi {{name}}, welcome to our villa!\n\nYour booking is confirmed."}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500/30" />
            <p className="text-[10px] text-gray-400 mt-1">Use {`{{name}}`}, {`{{property}}`} etc. for personalization.</p>
          </div>
        )}

        {local.type === "condition" && (
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Condition</label>
            <select value={local.condition ?? ""} onChange={e => setLocal(l => ({ ...l, condition: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30">
              <option value="">Select condition…</option>
              <option value="message_read">Message was read</option>
              <option value="replied">Contact replied</option>
              <option value="is_vip">Contact is VIP tag</option>
              <option value="has_booking">Has active booking</option>
            </select>
          </div>
        )}

        {local.type === "delay" && (
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Wait duration (minutes)</label>
            <input type="number" min={1} value={local.delay_minutes ?? 60}
              onChange={e => setLocal(l => ({ ...l, delay_minutes: parseInt(e.target.value) || 60 }))}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30" />
          </div>
        )}

        {local.type === "action" && (
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Action</label>
            <select value={local.content ?? ""} onChange={e => setLocal(l => ({ ...l, content: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30">
              <option value="">Select action…</option>
              <option value="tag_vip">Add tag: VIP</option>
              <option value="create_inquiry">Create inquiry</option>
              <option value="notify_agent">Notify agent in inbox</option>
              <option value="opt_out">Opt out contact</option>
            </select>
          </div>
        )}
      </div>
      <div className="px-4 pb-4 pt-2 border-t border-gray-100">
        <button
          onClick={() => { onUpdate(node.id, local); onClose(); }}
          className="w-full py-2.5 bg-indigo-500 text-white rounded-xl text-sm font-semibold hover:bg-indigo-600 transition-colors"
        >
          Apply changes
        </button>
      </div>
    </div>
  );
}

// ─── Default flow template ────────────────────────────────────────────────────

function makeDefaultFlow(name: string): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const trigger: FlowNode = { id: "n1", type: "trigger", label: "Contact opts in", content: "opt_in", x: 0, y: 0 };
  const welcome: FlowNode = { id: "n2", type: "message", label: "Welcome message", content: "Hi {{name}}! Welcome. Reply YES to confirm you'd like to receive updates.", x: 0, y: 120 };
  const delay: FlowNode = { id: "n3", type: "delay", label: "Wait 1 day", delay_minutes: 1440, x: 0, y: 240 };
  const followup: FlowNode = { id: "n4", type: "message", label: "Follow-up offer", content: "We have a special offer for you! Reply OFFER to learn more.", x: 0, y: 360 };
  const end: FlowNode = { id: "n5", type: "end", label: "End of flow", x: 0, y: 480 };
  return {
    nodes: [trigger, welcome, delay, followup, end],
    edges: [
      { id: "e1", from: "n1", to: "n2" },
      { id: "e2", from: "n2", to: "n3" },
      { id: "e3", from: "n3", to: "n4" },
      { id: "e4", from: "n4", to: "n5" },
    ],
  };
}

// ─── Create Flow Modal ────────────────────────────────────────────────────────

function CreateFlowModal({ onClose, onCreated }: { onClose: () => void; onCreated: (flow: Flow) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleCreate = async () => {
    if (!name.trim()) { setError("Flow name is required."); return; }
    setError("");
    setSubmitting(true);
    try {
      const { nodes, edges } = makeDefaultFlow(name);
      const res = await api.post("/messaging/flows", { name, description, nodes, edges });
      onCreated(res.data);
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to create flow.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-base font-bold text-gray-900">New flow</h2>
          <button onClick={onClose}><X size={18} className="text-gray-400" /></button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Flow name <span className="text-red-500">*</span></label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Welcome series"
              className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30" />
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Description <span className="text-gray-400 font-normal">(optional)</span></label>
            <input value={description} onChange={e => setDescription(e.target.value)} placeholder="Sent to new opt-ins"
              className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30" />
          </div>
          {error && <div className="flex items-center gap-2 text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2"><AlertCircle size={13} /> {error}</div>}
        </div>
        <div className="px-6 pb-5 flex gap-3">
          <button onClick={onClose} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors">Cancel</button>
          <button onClick={handleCreate} disabled={submitting}
            className="flex-1 py-2.5 bg-indigo-500 text-white rounded-xl text-sm font-semibold hover:bg-indigo-600 disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <GitBranch size={14} />}
            Create flow
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Flow Editor (full-page canvas view) ─────────────────────────────────────

function FlowEditor({ flow: initialFlow, onBack, onSaved }: {
  flow: Flow;
  onBack: () => void;
  onSaved: () => void;
}) {
  const [flow, setFlow] = useState(initialFlow);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  };

  const addNode = useCallback((type: FlowNode["type"], afterId?: string) => {
    const newNode: FlowNode = {
      id: `n${Date.now()}`,
      type,
      label: NODE_TYPES[type].label,
      x: 0,
      y: 0,
    };
    setFlow(f => {
      const nodes = [...f.nodes];
      const edges = [...f.edges];
      if (afterId) {
        const afterIdx = nodes.findIndex(n => n.id === afterId);
        const nextNode = nodes[afterIdx + 1];
        // Remove edge from afterId to nextNode
        const existingEdgeIdx = edges.findIndex(e => e.from === afterId);
        if (existingEdgeIdx >= 0 && nextNode) {
          edges.splice(existingEdgeIdx, 1, { id: `e${Date.now()}`, from: afterId, to: newNode.id });
          edges.push({ id: `e${Date.now() + 1}`, from: newNode.id, to: nextNode.id });
        } else {
          edges.push({ id: `e${Date.now()}`, from: afterId, to: newNode.id });
        }
        nodes.splice(afterIdx + 1, 0, newNode);
      } else {
        nodes.push(newNode);
      }
      return { ...f, nodes, edges };
    });
    setSelectedNodeId(newNode.id);
  }, []);

  const updateNode = useCallback((id: string, changes: Partial<FlowNode>) => {
    setFlow(f => ({
      ...f,
      nodes: f.nodes.map(n => n.id === id ? { ...n, ...changes } : n),
    }));
  }, []);

  const deleteNode = useCallback((id: string) => {
    setFlow(f => {
      const nodes = f.nodes.filter(n => n.id !== id);
      // Re-wire edges
      const inEdge = f.edges.find(e => e.to === id);
      const outEdge = f.edges.find(e => e.from === id);
      let edges = f.edges.filter(e => e.from !== id && e.to !== id);
      if (inEdge && outEdge) {
        edges.push({ id: `e${Date.now()}`, from: inEdge.from, to: outEdge.to });
      }
      return { ...f, nodes, edges };
    });
    if (selectedNodeId === id) setSelectedNodeId(null);
  }, [selectedNodeId]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.put(`/messaging/flows/${flow.id}`, {
        name: flow.name,
        description: flow.description,
        nodes: flow.nodes,
        edges: flow.edges,
        trigger: flow.nodes.find(n => n.type === "trigger")?.content ?? null,
      });
      showToast("Flow saved!", "success");
      onSaved();
    } catch {
      showToast("Save failed.", "error");
    } finally {
      setSaving(false);
    }
  };

  const selectedNode = flow.nodes.find(n => n.id === selectedNodeId) ?? null;

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Toolbar */}
      <div className="px-4 py-3 bg-white border-b border-gray-100 flex items-center gap-3 flex-shrink-0">
        <button onClick={onBack} className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 transition-colors">
          <ChevronRight size={14} className="rotate-180" /> Flows
        </button>
        <span className="text-gray-300">/</span>
        <span className="text-sm font-semibold text-gray-900 flex-1">{flow.name}</span>

        <div className="flex items-center gap-2">
          {/* Add node buttons */}
          {(["message", "condition", "delay", "action"] as const).map(t => (
            <button key={t} onClick={() => addNode(t)}
              className="flex items-center gap-1.5 text-xs border border-gray-200 text-gray-600 px-2.5 py-1.5 rounded-lg hover:bg-gray-50 transition-colors font-medium">
              <Plus size={11} />
              {NODE_TYPES[t].label}
            </button>
          ))}
          <div className="w-px h-5 bg-gray-200" />
          <button onClick={handleSave} disabled={saving}
            className="flex items-center gap-1.5 text-xs bg-indigo-500 text-white px-3 py-1.5 rounded-lg font-medium hover:bg-indigo-600 transition-colors disabled:opacity-50">
            {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
            Save
          </button>
        </div>
      </div>

      {/* Canvas + panel */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-auto">
          <FlowCanvas
            nodes={flow.nodes}
            edges={flow.edges}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onAddNode={addNode}
            onDeleteNode={deleteNode}
          />
        </div>
        {selectedNode && (
          <NodeEditorPanel
            node={selectedNode}
            onUpdate={updateNode}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}

// ─── Main page (flow list) ────────────────────────────────────────────────────

export default function FlowsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editingFlow, setEditingFlow] = useState<Flow | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: flows = [], isLoading } = useQuery<Flow[]>({
    queryKey: ["wa-flows"],
    queryFn: () => api.get("/messaging/flows").then(r => r.data).catch(() => DEMO_FLOWS),
    staleTime: 30_000,
  });

  const toggleMutation = useMutation({
    mutationFn: (id: string) => api.patch(`/messaging/flows/${id}/activate`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-flows"] }); showToast("Flow updated.", "success"); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/messaging/flows/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-flows"] }); showToast("Flow deleted.", "success"); },
  });

  // If editing a flow, show the editor full-page
  if (editingFlow) {
    return (
      <FlowEditor
        flow={editingFlow}
        onBack={() => setEditingFlow(null)}
        onSaved={() => { queryClient.invalidateQueries({ queryKey: ["wa-flows"] }); }}
      />
    );
  }

  return (
    <div className="h-full flex flex-col bg-gray-50">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Flow Builder</h1>
            <p className="text-sm text-gray-400 mt-0.5">Automate multi-step WhatsApp conversations triggered by guest actions.</p>
          </div>
          <button onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 bg-indigo-500 text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-indigo-600 transition-colors shadow-sm shadow-indigo-200">
            <Plus size={15} /> New flow
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}</div>
        ) : flows.length === 0 ? (
          <div className="py-20 text-center">
            <GitBranch size={40} className="text-gray-200 mx-auto mb-3" />
            <p className="text-sm text-gray-500 font-medium">No flows yet</p>
            <p className="text-xs text-gray-400 mt-1">Build automated message sequences triggered by guest actions.</p>
            <button onClick={() => setShowCreate(true)}
              className="mt-4 flex items-center gap-2 bg-indigo-500 text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-indigo-600 transition-colors mx-auto">
              <Plus size={14} /> Create flow
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {flows.map(flow => {
              const stepCount = flow.nodes.length;
              const triggerNode = flow.nodes.find(n => n.type === "trigger");
              const triggerLabel = TRIGGER_OPTIONS.find(t => t.value === triggerNode?.content)?.label ?? triggerNode?.content ?? "No trigger";

              return (
                <div key={flow.id} className="bg-white border border-gray-100 rounded-2xl p-5 hover:shadow-sm transition-shadow">
                  <div className="flex items-start gap-4">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
                      flow.is_active ? "bg-indigo-50" : "bg-gray-100")}>
                      <GitBranch size={18} className={flow.is_active ? "text-indigo-600" : "text-gray-400"} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="text-sm font-bold text-gray-900">{flow.name}</h3>
                        <span className={cn("inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border",
                          flow.is_active ? "bg-indigo-50 text-indigo-700 border-indigo-200" : "bg-gray-50 text-gray-500 border-gray-200")}>
                          {flow.is_active ? <><Play size={8} /> Active</> : <><Pause size={8} /> Inactive</>}
                        </span>
                      </div>
                      {flow.description && <p className="text-xs text-gray-500 mb-1">{flow.description}</p>}
                      <div className="flex items-center gap-3 text-[11px] text-gray-400 flex-wrap">
                        <span className="flex items-center gap-1"><Zap size={10} /> Trigger: {triggerLabel}</span>
                        <span className="flex items-center gap-1"><GitBranch size={10} /> {stepCount} steps</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button onClick={() => setEditingFlow(flow)}
                        className="flex items-center gap-1.5 text-xs border border-gray-200 text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors font-medium">
                        <Settings size={12} /> Edit
                      </button>
                      <button onClick={() => toggleMutation.mutate(flow.id)}
                        className={cn("text-xs px-3 py-1.5 rounded-lg font-medium transition-colors border",
                          flow.is_active ? "text-amber-600 border-amber-200 hover:bg-amber-50" : "text-indigo-600 border-indigo-200 hover:bg-indigo-50")}>
                        {flow.is_active ? "Pause" : "Activate"}
                      </button>
                      <button onClick={() => { if (confirm("Delete this flow?")) deleteMutation.mutate(flow.id); }}
                        className="text-gray-400 hover:text-red-500 transition-colors p-1.5 rounded-lg hover:bg-red-50">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* How it works */}
        <div className="mt-8 bg-white border border-gray-100 rounded-2xl p-5">
          <p className="text-sm font-bold text-gray-800 mb-3">How Flow Builder works</p>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            {[
              { step: "1", title: "Set a trigger", desc: "Choose what event starts the flow (opt-in, keyword, check-in…)" },
              { step: "2", title: "Add steps", desc: "Mix messages, delays, conditions, and actions in any order" },
              { step: "3", title: "Activate", desc: "Turn on the flow — it runs automatically for new contacts" },
              { step: "4", title: "Measure", desc: "Track delivery, read rates, and drop-off per step" },
            ].map(s => (
              <div key={s.step} className="flex gap-3">
                <div className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-[11px] font-bold flex-shrink-0 mt-0.5">{s.step}</div>
                <div>
                  <p className="text-xs font-semibold text-gray-800">{s.title}</p>
                  <p className="text-[10px] text-gray-400 leading-relaxed mt-0.5">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {showCreate && (
        <CreateFlowModal
          onClose={() => setShowCreate(false)}
          onCreated={(flow) => {
            queryClient.invalidateQueries({ queryKey: ["wa-flows"] });
            setShowCreate(false);
            setEditingFlow(flow);
          }}
        />
      )}
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}

// ─── Demo data ────────────────────────────────────────────────────────────────

const DEMO_FLOWS: Flow[] = [
  {
    id: "1", name: "New Opt-in Welcome", description: "Greet new subscribers and warm them up",
    is_active: true, trigger: "opt_in",
    nodes: [
      { id: "n1", type: "trigger", label: "Contact opts in", content: "opt_in", x: 0, y: 0 },
      { id: "n2", type: "message", label: "Welcome message", content: "Hi! Welcome to Casa Aurora updates. Reply YES to confirm.", x: 0, y: 120 },
      { id: "n3", type: "delay", label: "Wait 1 day", delay_minutes: 1440, x: 0, y: 240 },
      { id: "n4", type: "message", label: "Offer follow-up", content: "Here's our latest availability for you…", x: 0, y: 360 },
      { id: "n5", type: "end", label: "End", x: 0, y: 480 },
    ],
    edges: [
      { id: "e1", from: "n1", to: "n2" },
      { id: "e2", from: "n2", to: "n3" },
      { id: "e3", from: "n3", to: "n4" },
      { id: "e4", from: "n4", to: "n5" },
    ],
    created_at: "2025-05-01T10:00:00Z",
  },
  {
    id: "2", name: "Pre-Arrival Sequence", description: "D-1 reminder + check-in details",
    is_active: false, trigger: "check_in",
    nodes: [
      { id: "n1", type: "trigger", label: "Check-in D-1", content: "check_in", x: 0, y: 0 },
      { id: "n2", type: "message", label: "Arrival reminder", content: "Your stay at Casa Aurora starts tomorrow! Here are your check-in details…", x: 0, y: 120 },
      { id: "n3", type: "end", label: "End", x: 0, y: 240 },
    ],
    edges: [{ id: "e1", from: "n1", to: "n2" }, { id: "e2", from: "n2", to: "n3" }],
    created_at: "2025-05-10T08:00:00Z",
  },
];
