"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Send, Loader2, LayoutTemplate } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

interface TemplateComponent {
  type: string;
  text?: string;
}

interface Template {
  id: string;
  name: string;
  language: string;
  status: string;
  components: TemplateComponent[];
}

function countPlaceholders(text: string): number {
  const matches = text.match(/\{\{\d+\}\}/g);
  if (!matches) return 0;
  return new Set(matches).size;
}

export function TemplatePickerModal({
  conversationId, onClose, onSent,
}: {
  conversationId: string;
  onClose: () => void;
  onSent: () => void;
}) {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [variables, setVariables] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const { data: templates = [], isLoading } = useQuery<Template[]>({
    queryKey: ["wa-templates"],
    queryFn: () => api.get("/messaging/templates").then(r => r.data),
    staleTime: 30_000,
  });

  const approved = templates.filter(t => t.status === "approved");
  const selected = approved.find(t => t.id === selectedId) ?? null;
  const bodyComponent = selected?.components.find(c => c.type === "BODY");
  const placeholderCount = bodyComponent ? countPlaceholders(bodyComponent.text ?? "") : 0;

  function selectTemplate(t: Template) {
    setSelectedId(t.id);
    const body = t.components.find(c => c.type === "BODY");
    const count = body ? countPlaceholders(body.text ?? "") : 0;
    setVariables(Array.from({ length: count }, () => ""));
    setError(null);
  }

  function preview(): string {
    if (!bodyComponent?.text) return "";
    let text = bodyComponent.text;
    variables.forEach((v, i) => {
      text = text.replace(`{{${i + 1}}}`, v || `{{${i + 1}}}`);
    });
    return text;
  }

  const sendMutation = useMutation({
    mutationFn: () =>
      api.post(`/conversations/${conversationId}/send-template`, {
        template_id: selectedId,
        variables,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["conversation", conversationId] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      onSent();
      onClose();
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to send template";
      setError(typeof msg === "string" ? msg : "Failed to send template");
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md max-h-[80vh] flex flex-col" style={{ maxHeight: "calc(100dvh - 2rem)" }}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--haip-border)]">
          <div className="flex items-center gap-2">
            <LayoutTemplate size={16} className="text-amber-600" />
            <h2 className="text-sm font-bold text-[var(--haip-fg)]">Send WhatsApp Template</h2>
          </div>
          <button onClick={onClose} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]"><X size={16} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {isLoading ? (
            <p className="text-xs text-[var(--haip-fg-subtle)] text-center py-6">Loading templates…</p>
          ) : approved.length === 0 ? (
            <p className="text-xs text-[var(--haip-fg-subtle)] text-center py-6">No approved templates yet. Create and submit one for Meta review first.</p>
          ) : !selectedId ? (
            <div className="space-y-1.5">
              {approved.map(t => (
                <button
                  key={t.id}
                  onClick={() => selectTemplate(t)}
                  className="w-full text-left px-3 py-2.5 rounded-lg border border-[var(--haip-border)] hover:border-[color-mix(in_srgb,var(--primary)_25%,transparent)] hover:bg-[var(--haip-primary-tint)] transition-colors"
                >
                  <p className="text-sm font-medium text-[var(--haip-fg)]">{t.name}</p>
                  <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5 line-clamp-2">
                    {t.components.find(c => c.type === "BODY")?.text ?? ""}
                  </p>
                </button>
              ))}
            </div>
          ) : (
            <div className="space-y-3">
              <button onClick={() => setSelectedId(null)} className="text-xs text-primary font-medium">← Choose a different template</button>

              {placeholderCount > 0 && (
                <div className="space-y-2">
                  {variables.map((v, i) => (
                    <div key={i}>
                      <label className="text-[11px] font-semibold text-[var(--haip-fg-muted)] block mb-1">Variable {`{{${i + 1}}}`}</label>
                      <input
                        value={v}
                        onChange={e => setVariables(prev => prev.map((p, idx) => idx === i ? e.target.value : p))}
                        className="w-full text-sm px-2.5 py-1.5 border border-[var(--haip-border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/30"
                        placeholder={`Value for {{${i + 1}}}`}
                      />
                    </div>
                  ))}
                </div>
              )}

              <div className="bg-[var(--haip-surface)] rounded-lg p-3 text-sm text-[var(--haip-fg-2)] whitespace-pre-wrap">
                {preview() || "…"}
              </div>

              {error && <p className="text-xs text-red-500">{error}</p>}
            </div>
          )}
        </div>

        {selectedId && (
          <div className="px-5 py-3.5 border-t border-[var(--haip-border)] flex justify-end gap-2">
            <button onClick={onClose} className="text-xs px-3 py-1.5 rounded-lg border border-[var(--haip-border)] text-[var(--haip-fg-muted)]">Cancel</button>
            <button
              onClick={() => sendMutation.mutate()}
              disabled={sendMutation.isPending || variables.some(v => !v.trim())}
              className={cn(
                "flex items-center gap-1.5 text-xs font-semibold text-white px-3.5 py-1.5 rounded-lg transition-colors",
                sendMutation.isPending || variables.some(v => !v.trim()) ? "bg-amber-300" : "bg-amber-600 hover:bg-amber-700"
              )}
            >
              {sendMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
              Send
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
