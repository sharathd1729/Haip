"use client";
import { useState } from "react";
import { X } from "@/lib/icons";
import { useWidgetLibrary } from "@/hooks/useDashboardWidgets";
import type { LibraryWidget } from "@/hooks/useDashboardWidgets";
import api from "@/lib/api";

interface Props {
  selected: string[];
  onClose: () => void;
  onSaved: (keys: string[]) => void;
}

const CATEGORY_ORDER = ["calls", "messaging", "revenue", "guests"];
const CATEGORY_LABELS: Record<string, string> = {
  calls: "Calls", messaging: "Messaging", revenue: "Revenue", guests: "Guests",
};

export function WidgetLibraryModal({ selected, onClose, onSaved }: Props) {
  const { data, isLoading } = useWidgetLibrary();
  const [current, setCurrent] = useState<string[]>(selected);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(key: string) {
    setCurrent((prev) => {
      if (prev.includes(key)) return prev.filter((k) => k !== key);
      if (prev.length >= 8) {
        setError("Maximum 8 widgets. Remove one first.");
        return prev;
      }
      setError(null);
      return [...prev, key];
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.put("/dashboard/config", { selected_widgets: current });
      onSaved(current);
      onClose();
    } catch (e: unknown) {
      setError("Save failed. Try again.");
    } finally {
      setSaving(false);
    }
  }

  const byCategory: Record<string, LibraryWidget[]> = {};
  for (const w of data?.library ?? []) {
    if (!byCategory[w.category]) byCategory[w.category] = [];
    byCategory[w.category].push(w);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.5)" }}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-2xl max-h-[80vh] flex flex-col rounded-2xl overflow-hidden"
        style={{ background: "var(--card)", boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4 flex-shrink-0"
          style={{ borderBottom: "1px solid var(--haip-border)" }}
        >
          <div>
            <h2 className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>
              Customize Dashboard
            </h2>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              Select up to 8 widgets · {current.length}/8 selected
            </p>
          </div>
          <button onClick={onClose} style={{ color: "var(--haip-fg-subtle)" }}>
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 haip-scrollbar">
          {isLoading ? (
            <p className="text-[12px] text-center py-8" style={{ color: "var(--haip-fg-subtle)" }}>Loading…</p>
          ) : (
            CATEGORY_ORDER.filter((c) => byCategory[c]).map((cat) => (
              <div key={cat} className="mb-5">
                <p
                  className="text-[10px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "var(--haip-fg-subtle)" }}
                >
                  {CATEGORY_LABELS[cat]}
                </p>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {byCategory[cat].map((w) => {
                    const isSelected = current.includes(w.key);
                    const isUnavailable = w.state === "unavailable";
                    return (
                      <button
                        key={w.key}
                        onClick={() => !isUnavailable && toggle(w.key)}
                        disabled={isUnavailable}
                        className="rounded-lg p-2.5 text-left border transition-colors duration-150"
                        style={{
                          borderColor: isSelected ? "var(--primary)" : "var(--haip-border)",
                          background: isSelected ? "color-mix(in srgb, var(--primary) 8%, transparent)" : "transparent",
                          opacity: isUnavailable ? 0.45 : 1,
                          cursor: isUnavailable ? "not-allowed" : "pointer",
                        }}
                        title={isUnavailable ? `Requires: ${w.missing_modules.join(", ")}` : undefined}
                      >
                        <p className="text-[11px] font-medium" style={{ color: "var(--haip-fg)" }}>{w.title}</p>
                        <p className="text-[10px] mt-0.5 line-clamp-2" style={{ color: "var(--haip-fg-subtle)" }}>
                          {isUnavailable ? `Requires ${w.missing_modules.join(", ")}` : w.description}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-between px-5 py-3 flex-shrink-0"
          style={{ borderTop: "1px solid var(--haip-border)" }}
        >
          {error ? (
            <p className="text-[11px]" style={{ color: "#ef4444" }}>{error}</p>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg text-[11px] border"
              style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="px-3 py-1.5 rounded-lg text-[11px] font-medium"
              style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
