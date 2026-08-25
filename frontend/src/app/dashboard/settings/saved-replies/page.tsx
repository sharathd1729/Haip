"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Globe, User, X, MessageSquare } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

interface SavedReply {
  id: string;
  title: string;
  body: string;
  language: string;
  usage_count: number;
  user_id?: string;
  created_by: string;
}

const SEED_REPLIES = [
  { title: "Welcome back", body: "Welcome back, {{guest.name}}! How can we help you today?" },
  { title: "Sending rate quote", body: "Hi {{guest.name}}, here's the rate for {{property.name}}: ₹{{rate}} per night for {{check_in}} – {{check_out}}." },
  { title: "Check-in tomorrow", body: "Hi {{guest.name}}, just a reminder — your check-in at {{property.name}} is tomorrow. Looking forward to welcoming you!" },
  { title: "Following up", body: "Hi {{guest.name}}, following up on your inquiry. Would you like to proceed with a booking for {{check_in}}?" },
  { title: "Available! Confirm dates?", body: "Great news, {{property.name}} is available for your dates! Would you like to confirm {{check_in}} – {{check_out}}?" },
  { title: "Apology — checking", body: "I'm so sorry for the inconvenience, {{guest.name}}. Let me check on this right away and get back to you shortly." },
];

export default function SavedRepliesPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [form, setForm] = useState<{ id?: string; title: string; body: string; language: string } | null>(null);

  const { data: replies = [], isLoading } = useQuery<SavedReply[]>({
    queryKey: ["saved-replies"],
    queryFn: () => api.get("/saved-replies").then(r => r.data),
  });

  const saveMutation = useMutation({
    mutationFn: (data: { id?: string; title: string; body: string; language: string }) =>
      data.id
        ? api.patch(`/saved-replies/${data.id}`, { title: data.title, body: data.body, language: data.language })
        : api.post("/saved-replies", { title: data.title, body: data.body, language: data.language }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-replies"] });
      setForm(null);
      toast({ variant: "success", title: "Saved reply saved" });
    },
    onError: () => toast({ variant: "error", title: "Failed to save" }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/saved-replies/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-replies"] });
      toast({ variant: "success", title: "Deleted" });
    },
  });

  const seedMutation = useMutation({
    mutationFn: () =>
      Promise.all(SEED_REPLIES.map(r => api.post("/saved-replies", { ...r, language: "en" }))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-replies"] });
      toast({ variant: "success", title: `Seeded ${SEED_REPLIES.length} replies` });
    },
  });

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-teal-100 flex items-center justify-center">
          <MessageSquare size={18} className="text-teal-600" />
        </div>
        <div>
          <h1 className="haip-page-title">Saved replies</h1>
          <p className="text-xs text-gray-400">Canned responses · trigger with / in composer</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {replies.length === 0 && (
            <button
              onClick={() => seedMutation.mutate()}
              disabled={seedMutation.isPending}
              className="text-xs text-gray-500 border border-gray-200 hover:bg-gray-50 px-3 py-1.5 rounded-lg transition-colors"
            >
              Seed defaults
            </button>
          )}
          <button
            onClick={() => setForm({ title: "", body: "", language: "en" })}
            className="flex items-center gap-1.5 text-xs bg-teal-500 text-white px-3 py-1.5 rounded-lg font-medium hover:bg-teal-600 transition-colors"
          >
            <Plus size={13} /> New reply
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
        </div>
      ) : replies.length === 0 ? (
        <div className="text-center py-16 text-gray-400 text-sm">
          No saved replies yet. Click "New reply" or "Seed defaults".
        </div>
      ) : (
        <div className="space-y-2">
          {replies.map(r => (
            <div key={r.id} className="flex items-start gap-3 bg-white border border-gray-100 rounded-xl p-4 hover:border-gray-200 transition-colors">
              {r.user_id
                ? <User size={14} className="text-gray-400 mt-0.5 flex-shrink-0" />
                : <Globe size={14} className="text-teal-500 mt-0.5 flex-shrink-0" />}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <p className="text-sm font-semibold text-gray-900">{r.title}</p>
                  {r.language && r.language !== "en" && (
                    <Badge variant="ghost" className="text-[10px] capitalize">{r.language}</Badge>
                  )}
                  <span className="text-[10px] text-gray-400 ml-auto">{r.usage_count} uses</span>
                </div>
                <p className="text-xs text-gray-500 truncate">{r.body}</p>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={() => setForm({ id: r.id, title: r.title, body: r.body, language: r.language })}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                >
                  <Pencil size={13} />
                </button>
                <button
                  onClick={() => deleteMutation.mutate(r.id)}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Form modal */}
      {form && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-gray-900">{form.id ? "Edit" : "New"} saved reply</h3>
              <button onClick={() => setForm(null)}><X size={16} className="text-gray-400" /></button>
            </div>
            <div className="space-y-3 mb-5">
              <div>
                <label className="block text-xs font-semibold text-gray-500 mb-1">Title</label>
                <input
                  value={form.title}
                  onChange={e => setForm(f => f ? { ...f, title: e.target.value } : f)}
                  placeholder="e.g. Welcome back"
                  className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 mb-1">Body</label>
                <textarea
                  value={form.body}
                  onChange={e => setForm(f => f ? { ...f, body: e.target.value } : f)}
                  rows={4}
                  placeholder="Use {{guest.name}}, {{property.name}}, {{check_in}}, {{check_out}}"
                  className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  Merge fields: {"{{guest.name}} {{property.name}} {{check_in}} {{check_out}} {{owner.name}}"}
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setForm(null)} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
              <button
                onClick={() => { if (form) saveMutation.mutate(form); }}
                disabled={!form.title.trim() || !form.body.trim() || saveMutation.isPending}
                className="flex-1 py-2.5 bg-teal-500 hover:bg-teal-600 disabled:opacity-40 text-white font-semibold rounded-xl text-sm"
              >
                {form.id ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
