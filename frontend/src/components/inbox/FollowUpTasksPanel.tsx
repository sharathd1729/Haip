"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, ClipboardList, CalendarClock } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

/** HAIP Inbox prototype-wiring plan, ticket 5. Backed by the real Task
 * model (ticket 1) -- POST/GET/PATCH /tasks scoped to this conversation. */

interface TaskItem {
  id: string;
  title: string;
  due_date?: string | null;
  priority: string;
  is_done: boolean;
}

export function FollowUpTasksPanel({ conversationId }: { conversationId: string }) {
  const qc = useQueryClient();
  const [newTitle, setNewTitle] = useState("");

  const { data: tasks = [] } = useQuery<TaskItem[]>({
    queryKey: ["tasks", conversationId],
    queryFn: () => api.get(`/tasks?conversation_id=${conversationId}`).then(r => r.data),
    staleTime: 15_000,
  });

  const addTask = useMutation({
    mutationFn: (title: string) =>
      api.post("/tasks", { title, conversation_id: conversationId, priority: "medium" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", conversationId] });
      setNewTitle("");
    },
  });

  const toggleTask = useMutation({
    mutationFn: (taskId: string) => api.patch(`/tasks/${taskId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", conversationId] }),
  });

  const doneCount = tasks.filter(t => t.is_done).length;

  const PRIORITY_COLOR: Record<string, string> = {
    high: "#ef4444",
    medium: "#f59e0b",
    low: "#6b7280",
  };

  return (
    <div
      className="p-3.5 rounded-xl border space-y-2.5"
      style={{ borderColor: "var(--haip-border)", background: "var(--card)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5" style={{ color: "var(--haip-fg-subtle)" }}>
          <ClipboardList size={12} />
          Follow-up tasks
        </span>
        {tasks.length > 0 && (
          <span className="text-[10px] font-bold" style={{ color: "var(--primary)" }}>
            {doneCount}/{tasks.length} done
          </span>
        )}
      </div>

      {tasks.length > 0 && (
        <div className="space-y-1.5">
          {tasks.map(t => (
            <button
              key={t.id}
              type="button"
              onClick={() => toggleTask.mutate(t.id)}
              className="w-full flex items-center justify-between gap-2 p-2 rounded-lg border text-left text-xs transition-colors"
              style={{ borderColor: "var(--haip-border)" }}
            >
              <span className="flex items-center gap-2 min-w-0">
                <span
                  className={cn(
                    "w-4 h-4 rounded flex items-center justify-center border flex-shrink-0",
                    t.is_done ? "bg-emerald-500 border-emerald-500 text-white" : "border-gray-300"
                  )}
                >
                  {t.is_done && <Check size={11} />}
                </span>
                <span
                  title={`Priority: ${t.priority}`}
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ background: PRIORITY_COLOR[t.priority] ?? PRIORITY_COLOR.medium }}
                />
                <span className={cn("truncate", t.is_done && "line-through opacity-50")}>{t.title}</span>
              </span>
              {t.due_date && (
                <span className="flex items-center gap-1 text-[10px] flex-shrink-0" style={{ color: "var(--haip-fg-subtle)" }}>
                  <CalendarClock size={10} />
                  {new Date(t.due_date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={e => { e.preventDefault(); if (newTitle.trim()) addTask.mutate(newTitle.trim()); }}
        className="flex gap-1.5"
      >
        <input
          type="text"
          value={newTitle}
          onChange={e => setNewTitle(e.target.value)}
          placeholder="Add follow-up task…"
          className="flex-1 px-2 py-1 rounded-lg text-xs border outline-none"
          style={{ borderColor: "var(--haip-border)" }}
        />
        <button
          type="submit"
          disabled={addTask.isPending || !newTitle.trim()}
          className="p-1.5 rounded-lg text-white disabled:opacity-60"
          style={{ background: "var(--primary)" }}
        >
          <Plus size={13} />
        </button>
      </form>
    </div>
  );
}
