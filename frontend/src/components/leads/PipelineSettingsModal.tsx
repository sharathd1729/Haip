"use client";

import { useState, useRef } from "react";
import { GripVertical, X, Plus, Trash2, Check, Award, Ban } from "lucide-react";
import {
  PipelineStageRow,
  useInvalidatePipelineStages,
  createPipelineStage,
  updatePipelineStage,
  reorderPipelineStages,
  deletePipelineStage,
} from "@/hooks/usePipelineStages";

const PALETTE = [
  "#6366f1", "#f59e0b", "#8b5cf6", "#06b6d4",
  "#10b981", "#22c55e", "#6b7280", "#ef4444",
];

interface Props {
  stages: PipelineStageRow[];
  onClose: () => void;
}

export function PipelineSettingsModal({ stages: initialStages, onClose }: Props) {
  const [rows, setRows] = useState<PipelineStageRow[]>(
    [...initialStages].sort((a, b) => a.order - b.order)
  );
  const [editingId, setEditingId] = useState<string | null>(null);
  const [colorPickerId, setColorPickerId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [reassignTargetId, setReassignTargetId] = useState<string>("");
  const [addingLabel, setAddingLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dragIdx = useRef<number | null>(null);
  const invalidate = useInvalidatePipelineStages();

  function slugify(label: string): string {
    return label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "stage";
  }

  async function withBusy<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Action failed";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function handleAddStage() {
    const label = addingLabel.trim();
    if (!label) return;
    const key = slugify(label) + "_" + Math.random().toString(36).slice(2, 6);
    const created = await withBusy(() =>
      createPipelineStage({ key, label, color: PALETTE[rows.length % PALETTE.length] })
    );
    if (created) {
      setRows(prev => [...prev, created]);
      setAddingLabel("");
      invalidate();
    }
  }

  async function handleLabelBlur(row: PipelineStageRow, newLabel: string) {
    setEditingId(null);
    if (newLabel.trim() === row.label || !newLabel.trim()) return;
    const updated = await withBusy(() => updatePipelineStage(row.id, { label: newLabel.trim() }));
    if (updated) {
      setRows(prev => prev.map(r => (r.id === row.id ? updated : r)));
      invalidate();
    }
  }

  async function handleColorChange(row: PipelineStageRow, color: string) {
    setColorPickerId(null);
    const updated = await withBusy(() => updatePipelineStage(row.id, { color }));
    if (updated) {
      setRows(prev => prev.map(r => (r.id === row.id ? updated : r)));
      invalidate();
    }
  }

  async function handleSetDefaultEntry(row: PipelineStageRow) {
    const updated = await withBusy(() => updatePipelineStage(row.id, { is_default_entry: true }));
    if (updated) {
      setRows(prev => prev.map(r => (r.id === row.id ? updated : { ...r, is_default_entry: false })));
      invalidate();
    }
  }

  async function handleToggleClosedFlag(row: PipelineStageRow, flag: "is_closed_won" | "is_closed_lost") {
    const updated = await withBusy(() => updatePipelineStage(row.id, { [flag]: !row[flag] }));
    if (updated) {
      setRows(prev => prev.map(r => (r.id === row.id ? updated : r)));
      invalidate();
    }
  }

  function requestDelete(row: PipelineStageRow) {
    setPendingDeleteId(row.id);
    setReassignTargetId(rows.find(r => r.id !== row.id)?.id ?? "");
    setError(null);
  }

  async function confirmDelete() {
    if (!pendingDeleteId) return;
    const target = rows.find(r => r.id === pendingDeleteId);
    const ok = await withBusy(() =>
      deletePipelineStage(pendingDeleteId, target && target.lead_count > 0 ? reassignTargetId : undefined)
    );
    if (ok !== undefined || !error) {
      setRows(prev => prev.filter(r => r.id !== pendingDeleteId));
      setPendingDeleteId(null);
      invalidate();
    }
  }

  // ── HTML5 drag-to-reorder ──────────────────────────────────────────────────
  function onDragStart(idx: number) {
    dragIdx.current = idx;
  }

  function onDragOver(e: React.DragEvent, idx: number) {
    e.preventDefault();
    if (dragIdx.current === null || dragIdx.current === idx) return;
    const next = [...rows];
    const [moved] = next.splice(dragIdx.current, 1);
    next.splice(idx, 0, moved);
    dragIdx.current = idx;
    setRows(next);
  }

  async function onDragEnd() {
    dragIdx.current = null;
    const reordered = await withBusy(() => reorderPipelineStages(rows.map(r => r.id)));
    if (reordered) {
      setRows(reordered);
      invalidate();
    }
  }

  const pendingDeleteRow = rows.find(r => r.id === pendingDeleteId);
  const reassignOptions = rows.filter(r => r.id !== pendingDeleteId);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />

      <div
        className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md rounded-2xl shadow-xl overflow-hidden"
        style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)" }}
      >
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: "1px solid var(--haip-border)" }}>
          <div>
            <h2 className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>Pipeline Stages</h2>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              Drag to reorder · click label to rename · add/remove stages freely
            </p>
          </div>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center rounded-lg" style={{ color: "var(--haip-fg-subtle)" }}>
            <X size={14} />
          </button>
        </div>

        {/* Delete confirmation / reassignment panel */}
        {pendingDeleteRow && (
          <div className="px-5 py-3 text-xs" style={{ background: "var(--haip-bg-subtle, rgba(0,0,0,0.03))", borderBottom: "1px solid var(--haip-border)" }}>
            <p className="mb-2" style={{ color: "var(--haip-fg)" }}>
              Delete <strong>{pendingDeleteRow.label}</strong>?
              {pendingDeleteRow.lead_count > 0 && (
                <> {pendingDeleteRow.lead_count} lead(s) will move to:</>
              )}
            </p>
            {pendingDeleteRow.lead_count > 0 && (
              <select
                className="w-full text-xs rounded-lg px-2 py-1.5 mb-2"
                style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
                value={reassignTargetId}
                onChange={e => setReassignTargetId(e.target.value)}
              >
                {reassignOptions.map(r => (
                  <option key={r.id} value={r.id}>{r.label}</option>
                ))}
              </select>
            )}
            <div className="flex gap-2 justify-end">
              <button onClick={() => setPendingDeleteId(null)} className="text-xs px-3 py-1 rounded-lg border" style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}>
                Cancel
              </button>
              <button onClick={confirmDelete} disabled={busy} className="text-xs px-3 py-1 rounded-lg font-semibold text-white" style={{ background: "var(--haip-red, #ef4444)" }}>
                Delete
              </button>
            </div>
          </div>
        )}

        <div className="py-2 max-h-[360px] overflow-y-auto haip-scrollbar">
          {rows.map((row, idx) => (
            <div
              key={row.id}
              draggable
              onDragStart={() => onDragStart(idx)}
              onDragOver={e => onDragOver(e, idx)}
              onDragEnd={onDragEnd}
              className="flex items-center gap-2 px-4 py-2.5 cursor-default select-none group"
              style={{ borderBottom: "1px solid var(--haip-border)" }}
            >
              <GripVertical size={14} className="flex-shrink-0 cursor-grab active:cursor-grabbing" style={{ color: "var(--haip-fg-subtle)" }} />

              <div className="relative flex-shrink-0">
                <button
                  className="w-4 h-4 rounded-full border-2 border-white/20"
                  style={{ background: row.color }}
                  onClick={() => setColorPickerId(colorPickerId === row.id ? null : row.id)}
                  title="Change color"
                />
                {colorPickerId === row.id && (
                  <div className="absolute left-0 top-6 z-10 flex gap-1.5 p-2 rounded-xl shadow-lg" style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)" }}>
                    {PALETTE.map(c => (
                      <button
                        key={c}
                        className="w-5 h-5 rounded-full border-2"
                        style={{ background: c, borderColor: row.color === c ? "white" : "transparent" }}
                        onClick={() => handleColorChange(row, c)}
                      />
                    ))}
                  </div>
                )}
              </div>

              {editingId === row.id ? (
                <input
                  autoFocus
                  className="flex-1 text-xs bg-transparent border-b outline-none min-w-0"
                  style={{ color: "var(--haip-fg)", borderColor: "var(--primary)" }}
                  defaultValue={row.label}
                  maxLength={80}
                  onBlur={e => handleLabelBlur(row, e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEditingId(null); }}
                />
              ) : (
                <button className="flex-1 text-left text-xs truncate" style={{ color: "var(--haip-fg)" }} onClick={() => setEditingId(row.id)}>
                  {row.label}
                  {row.lead_count > 0 && (
                    <span className="ml-1.5 text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>({row.lead_count})</span>
                  )}
                </button>
              )}

              <button
                onClick={() => handleSetDefaultEntry(row)}
                title={row.is_default_entry ? "Default entry stage" : "Set as default entry stage"}
                className="flex-shrink-0"
                style={{ color: row.is_default_entry ? "var(--primary)" : "var(--haip-fg-subtle)", opacity: row.is_default_entry ? 1 : 0.3 }}
              >
                <Check size={13} />
              </button>
              <button
                onClick={() => handleToggleClosedFlag(row, "is_closed_won")}
                title={row.is_closed_won ? "Marked as Won" : "Mark as Won stage"}
                className="flex-shrink-0"
                style={{ color: row.is_closed_won ? "#22c55e" : "var(--haip-fg-subtle)", opacity: row.is_closed_won ? 1 : 0.3 }}
              >
                <Award size={13} />
              </button>
              <button
                onClick={() => handleToggleClosedFlag(row, "is_closed_lost")}
                title={row.is_closed_lost ? "Marked as Lost" : "Mark as Lost stage"}
                className="flex-shrink-0"
                style={{ color: row.is_closed_lost ? "#ef4444" : "var(--haip-fg-subtle)", opacity: row.is_closed_lost ? 1 : 0.3 }}
              >
                <Ban size={13} />
              </button>
              <button
                onClick={() => requestDelete(row)}
                title="Delete stage"
                className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ color: "var(--haip-red, #ef4444)" }}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>

        {/* Add stage */}
        <div className="flex items-center gap-2 px-5 py-3" style={{ borderTop: "1px solid var(--haip-border)" }}>
          <input
            className="flex-1 text-xs rounded-lg px-2.5 py-1.5"
            style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
            placeholder="New stage name…"
            value={addingLabel}
            onChange={e => setAddingLabel(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") handleAddStage(); }}
          />
          <button
            onClick={handleAddStage}
            disabled={busy || !addingLabel.trim()}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg font-semibold"
            style={{ background: "var(--primary)", color: "var(--primary-foreground)", opacity: busy || !addingLabel.trim() ? 0.5 : 1 }}
          >
            <Plus size={12} /> Add
          </button>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 gap-3" style={{ borderTop: "1px solid var(--haip-border)" }}>
          {error && <p className="text-[11px] flex-1 truncate" style={{ color: "var(--haip-red)" }}>{error}</p>}
          <button onClick={onClose} className="text-xs px-4 py-1.5 rounded-lg font-semibold ml-auto" style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}>
            Done
          </button>
        </div>
      </div>
    </>
  );
}
