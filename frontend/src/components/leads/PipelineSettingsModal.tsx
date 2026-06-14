"use client";

import { useState, useRef } from "react";
import { Eye, EyeOff, GripVertical, X, RotateCcw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  PipelineStage,
  DEFAULT_PIPELINE_STAGES,
} from "@/hooks/usePipelineConfig";

const PALETTE = [
  "#6366f1", "#f59e0b", "#8b5cf6", "#06b6d4",
  "#10b981", "#22c55e", "#6b7280", "#ef4444",
];

interface Props {
  stages: PipelineStage[];
  onClose: () => void;
}

export function PipelineSettingsModal({ stages: initialStages, onClose }: Props) {
  const [rows, setRows] = useState<PipelineStage[]>(
    [...initialStages].sort((a, b) => a.order - b.order)
  );
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [colorPickerKey, setColorPickerKey] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dragIdx = useRef<number | null>(null);
  const qc = useQueryClient();

  function updateRow(key: string, patch: Partial<PipelineStage>) {
    setRows(prev => prev.map(r => r.key === key ? { ...r, ...patch } : r));
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
    setRows(next.map((r, i) => ({ ...r, order: i })));
  }

  function onDragEnd() {
    dragIdx.current = null;
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const payload = rows.map((r, i) => ({ ...r, order: i }));
      await api.put("/tenants/me/pipeline-config", { stages: payload });
      await qc.invalidateQueries({ queryKey: ["pipeline-config"] });
      await qc.invalidateQueries({ queryKey: ["leads"] });
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? "Save failed";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setSaving(false);
    }
  }

  function handleReset() {
    setRows([...DEFAULT_PIPELINE_STAGES]);
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md rounded-2xl shadow-xl overflow-hidden"
        style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)" }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: "1px solid var(--haip-border)" }}
        >
          <div>
            <h2 className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>
              Pipeline Stages
            </h2>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              Drag to reorder · click label to rename
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-lg"
            style={{ color: "var(--haip-fg-subtle)" }}
          >
            <X size={14} />
          </button>
        </div>

        {/* Stage rows */}
        <div className="py-2 max-h-[360px] overflow-y-auto haip-scrollbar">
          {rows.map((row, idx) => (
            <div
              key={row.key}
              draggable
              onDragStart={() => onDragStart(idx)}
              onDragOver={e => onDragOver(e, idx)}
              onDragEnd={onDragEnd}
              className="flex items-center gap-3 px-4 py-2.5 cursor-default select-none"
              style={{
                opacity: row.visible ? 1 : 0.45,
                borderBottom: "1px solid var(--haip-border)",
              }}
            >
              {/* Drag handle */}
              <GripVertical
                size={14}
                className="flex-shrink-0 cursor-grab active:cursor-grabbing"
                style={{ color: "var(--haip-fg-subtle)" }}
              />

              {/* Color dot + picker */}
              <div className="relative flex-shrink-0">
                <button
                  className="w-4 h-4 rounded-full border-2 border-white/20"
                  style={{ background: row.color }}
                  onClick={() => setColorPickerKey(colorPickerKey === row.key ? null : row.key)}
                  title="Change color"
                />
                {colorPickerKey === row.key && (
                  <div
                    className="absolute left-0 top-6 z-10 flex gap-1.5 p-2 rounded-xl shadow-lg"
                    style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)" }}
                  >
                    {PALETTE.map(c => (
                      <button
                        key={c}
                        className="w-5 h-5 rounded-full border-2"
                        style={{
                          background: c,
                          borderColor: row.color === c ? "white" : "transparent",
                        }}
                        onClick={() => {
                          updateRow(row.key, { color: c });
                          setColorPickerKey(null);
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>

              {/* Label — click to edit */}
              {editingKey === row.key ? (
                <input
                  autoFocus
                  className="flex-1 text-xs bg-transparent border-b outline-none"
                  style={{
                    color: "var(--haip-fg)",
                    borderColor: "var(--primary)",
                  }}
                  value={row.label}
                  maxLength={40}
                  onChange={e => updateRow(row.key, { label: e.target.value })}
                  onBlur={() => setEditingKey(null)}
                  onKeyDown={e => { if (e.key === "Enter" || e.key === "Escape") setEditingKey(null); }}
                />
              ) : (
                <button
                  className="flex-1 text-left text-xs"
                  style={{ color: "var(--haip-fg)" }}
                  onClick={() => setEditingKey(row.key)}
                >
                  {row.label}
                </button>
              )}

              {/* Visibility toggle */}
              <button
                onClick={() => updateRow(row.key, { visible: !row.visible })}
                title={row.visible ? "Hide stage" : "Show stage"}
                className="flex-shrink-0"
                style={{ color: "var(--haip-fg-subtle)" }}
              >
                {row.visible ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-between px-5 py-3.5 gap-3"
          style={{ borderTop: "1px solid var(--haip-border)" }}
        >
          {error && (
            <p className="text-[11px] flex-1 truncate" style={{ color: "var(--haip-red)" }}>
              {error}
            </p>
          )}
          <button
            onClick={handleReset}
            className="flex items-center gap-1.5 text-xs"
            style={{ color: "var(--haip-fg-subtle)" }}
          >
            <RotateCcw size={11} />
            Reset
          </button>
          <div className="flex items-center gap-2 ml-auto">
            <button
              onClick={onClose}
              className="text-xs px-3 py-1.5 rounded-lg border"
              style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="text-xs px-4 py-1.5 rounded-lg font-semibold"
              style={{
                background: "var(--primary)",
                color: "var(--primary-foreground)",
                opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
