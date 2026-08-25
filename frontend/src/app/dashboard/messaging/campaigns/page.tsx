"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Megaphone, Plus, Play, Pause, Clock, CheckCircle2, Users, TrendingUp, X, Loader2, AlertCircle, Calendar, Send, Eye, Trash2, Tag, Filter } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface Campaign {
  id: string;
  name: string;
  template_id: string | null;
  status: "draft" | "scheduled" | "running" | "completed" | "paused";
  audience_filter: Record<string, any>;
  scheduled_at: string | null;
  sent_count: string;
  delivered_count: string;
  read_count: string;
  failed_count: string;
  created_at: string | null;
}

interface Template {
  id: string;
  name: string;
  status: string;
  category: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const STATUS_CFG = {
  draft:     { label: "Draft",     cls: "bg-gray-50 text-gray-600 border-gray-200",    icon: <Eye size={10} /> },
  scheduled: { label: "Scheduled", cls: "bg-blue-50 text-blue-700 border-blue-200",    icon: <Clock size={10} /> },
  running:   { label: "Running",   cls: "bg-teal-50 text-teal-700 border-teal-200",    icon: <Play size={10} /> },
  completed: { label: "Completed", cls: "bg-green-50 text-green-700 border-green-200", icon: <CheckCircle2 size={10} /> },
  paused:    { label: "Paused",    cls: "bg-amber-50 text-amber-700 border-amber-200", icon: <Pause size={10} /> },
};

function rate(num: string, den: string): string {
  const n = parseInt(num) || 0;
  const d = parseInt(den) || 0;
  if (d === 0) return "—";
  return `${Math.round((n / d) * 100)}%`;
}

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

// ─── Audience Filter Builder ──────────────────────────────────────────────────

const SOURCES = ["web_widget", "import", "inbound", "manual"] as const;

function AudienceFilterBuilder({
  filter,
  onChange,
  allTags,
  subscriberCount,
}: {
  filter: { tags: string[]; source: string[] };
  onChange: (f: { tags: string[]; source: string[] }) => void;
  allTags: string[];
  subscriberCount: number | null;
}) {
  const [tagInput, setTagInput] = useState("");

  const toggleTag = (t: string) => {
    const next = filter.tags.includes(t)
      ? filter.tags.filter(x => x !== t)
      : [...filter.tags, t];
    onChange({ ...filter, tags: next });
  };

  const toggleSource = (s: string) => {
    const next = filter.source.includes(s)
      ? filter.source.filter(x => x !== s)
      : [...filter.source, s];
    onChange({ ...filter, source: next });
  };

  const addTag = () => {
    const t = tagInput.trim().toLowerCase();
    if (t && !filter.tags.includes(t)) onChange({ ...filter, tags: [...filter.tags, t] });
    setTagInput("");
  };

  const isEmpty = filter.tags.length === 0 && filter.source.length === 0;

  return (
    <div className="space-y-3">
      {/* Tag filter */}
      <div>
        <p className="text-xs font-semibold text-gray-700 mb-1.5 flex items-center gap-1">
          <Tag size={11} /> Filter by tags
        </p>
        {allTags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {allTags.map(t => (
              <button key={t} onClick={() => toggleTag(t)}
                className={cn("text-[11px] px-2.5 py-1 rounded-full border font-medium transition-colors",
                  filter.tags.includes(t)
                    ? "bg-teal-500 text-white border-teal-500"
                    : "bg-gray-50 text-gray-600 border-gray-200 hover:border-teal-300")}>
                {t}
              </button>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <input value={tagInput} onChange={e => setTagInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
            placeholder="Type a tag and press Enter…"
            className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
          <button onClick={addTag}
            className="px-3 py-2 bg-gray-100 text-gray-600 rounded-xl text-xs font-medium hover:bg-gray-200 transition-colors">
            Add
          </button>
        </div>
      </div>

      {/* Source filter */}
      <div>
        <p className="text-xs font-semibold text-gray-700 mb-1.5 flex items-center gap-1">
          <Filter size={11} /> Filter by source
        </p>
        <div className="flex flex-wrap gap-1.5">
          {SOURCES.map(s => (
            <button key={s} onClick={() => toggleSource(s)}
              className={cn("text-[11px] px-2.5 py-1 rounded-full border font-medium transition-colors",
                filter.source.includes(s)
                  ? "bg-blue-500 text-white border-blue-500"
                  : "bg-gray-50 text-gray-600 border-gray-200 hover:border-blue-300")}>
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {/* Estimated reach */}
      <div className={cn("rounded-xl px-3 py-2.5 flex items-center gap-2 text-xs",
        isEmpty ? "bg-teal-50 border border-teal-100" : "bg-blue-50 border border-blue-100")}>
        <Users size={13} className={isEmpty ? "text-teal-600" : "text-blue-600"} />
        <span className={isEmpty ? "text-teal-700" : "text-blue-700"}>
          {subscriberCount === null ? (
            <span className="flex items-center gap-1"><Loader2 size={11} className="animate-spin" /> Calculating…</span>
          ) : isEmpty ? (
            <><strong>{subscriberCount.toLocaleString()}</strong> opted-in subscribers will receive this</>
          ) : (
            <><strong>~{subscriberCount.toLocaleString()}</strong> subscribers match these filters</>
          )}
        </span>
      </div>
    </div>
  );
}

// ─── Create Campaign Modal ────────────────────────────────────────────────────

function CreateCampaignModal({ templates, onClose, onCreated }: {
  templates: Template[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({ name: "", template_id: "", scheduled_at: "" });
  const [audienceFilter, setAudienceFilter] = useState<{ tags: string[]; source: string[] }>({ tags: [], source: [] });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Fetch all subscriber tags for the tag picker
  const { data: subscribers = [] } = useQuery<{ tags: string[] }[]>({
    queryKey: ["wa-subscribers-all"],
    queryFn: () => api.get("/messaging/subscribers", { params: { limit: 500 } }).then(r => r.data).catch(() => []),
    staleTime: 60_000,
  });

  // Derive unique tags across all subscribers
  const allTags = [...new Set((subscribers as any[]).flatMap((s: any) => s.tags || []))].sort();

  // Live audience count — recomputed when filter changes
  const { data: audienceCount } = useQuery<number>({
    queryKey: ["wa-audience-count", audienceFilter],
    queryFn: async () => {
      const all: any[] = await api.get("/messaging/subscribers", { params: { opted_in: true, limit: 500 } }).then(r => r.data);
      let list = all;
      if (audienceFilter.tags.length > 0) {
        list = list.filter((s: any) => audienceFilter.tags.some(t => (s.tags || []).includes(t)));
      }
      if (audienceFilter.source.length > 0) {
        list = list.filter((s: any) => audienceFilter.source.includes(s.source));
      }
      return list.length;
    },
    staleTime: 0,
  });

  const handleCreate = async () => {
    if (!form.name.trim()) { setError("Campaign name is required."); return; }
    if (!form.template_id) { setError("Please select a message template."); return; }
    setError("");
    setSubmitting(true);
    try {
      const af: Record<string, any> = {};
      if (audienceFilter.tags.length > 0) af.tags = audienceFilter.tags;
      if (audienceFilter.source.length > 0) af.source = audienceFilter.source;

      await api.post("/messaging/campaigns", {
        name: form.name,
        template_id: form.template_id,
        scheduled_at: form.scheduled_at || null,
        audience_filter: af,
      });
      onCreated();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to create campaign.");
    } finally {
      setSubmitting(false);
    }
  };

  const approvedTemplates = templates.filter(t => t.status === "approved");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden max-h-[90vh] flex flex-col">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-base font-bold text-gray-900">New campaign</h2>
            <p className="text-xs text-gray-400 mt-0.5">Send a template to your opted-in subscribers.</p>
          </div>
          <button onClick={onClose}><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>

        <div className="px-6 py-5 space-y-5 overflow-y-auto flex-1">
          {/* Name */}
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Campaign name <span className="text-red-500">*</span></label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="Diwali 2025 Offer"
              className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
          </div>

          {/* Template */}
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Message template <span className="text-red-500">*</span></label>
            {approvedTemplates.length === 0 ? (
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-700">
                No approved templates yet. <a href="/dashboard/messaging/templates" className="underline font-medium">Create and submit a template</a> first.
              </div>
            ) : (
              <select value={form.template_id} onChange={e => setForm(f => ({ ...f, template_id: e.target.value }))}
                className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30">
                <option value="">Select a template…</option>
                {approvedTemplates.map(t => (
                  <option key={t.id} value={t.id}>{t.name} ({t.category.toLowerCase()})</option>
                ))}
              </select>
            )}
          </div>

          {/* Audience filter */}
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-2">
              Audience <span className="text-gray-400 font-normal">(optional — leave all blank for all subscribers)</span>
            </label>
            <div className="border border-gray-200 rounded-xl p-4">
              <AudienceFilterBuilder
                filter={audienceFilter}
                onChange={setAudienceFilter}
                allTags={allTags}
                subscriberCount={audienceCount ?? null}
              />
            </div>
          </div>

          {/* Schedule */}
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Schedule for later <span className="text-gray-400 font-normal">(optional)</span></label>
            <input type="datetime-local" value={form.scheduled_at} onChange={e => setForm(f => ({ ...f, scheduled_at: e.target.value }))}
              className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
            <p className="text-[10px] text-gray-400 mt-1">Leave blank to save as draft and launch manually.</p>
          </div>

          {error && (
            <div className="flex items-center gap-2 text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2">
              <AlertCircle size={13} /> {error}
            </div>
          )}
        </div>

        <div className="px-6 pb-5 flex gap-3 flex-shrink-0 border-t border-gray-100 pt-4">
          <button onClick={onClose} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors">Cancel</button>
          <button onClick={handleCreate} disabled={submitting}
            className="flex-1 py-2.5 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Megaphone size={14} />}
            Create campaign
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Campaign Card ────────────────────────────────────────────────────────────

function CampaignCard({ campaign, onLaunch, onDelete }: {
  campaign: Campaign;
  onLaunch: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const sc = STATUS_CFG[campaign.status] ?? STATUS_CFG.draft;
  const sent = parseInt(campaign.sent_count) || 0;
  const delivered = parseInt(campaign.delivered_count) || 0;
  const read = parseInt(campaign.read_count) || 0;

  return (
    <div className="haip-card p-5 hover:shadow-sm transition-shadow">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-bold text-gray-900 truncate">{campaign.name}</h3>
            <span className={cn("inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border flex-shrink-0", sc.cls)}>
              {sc.icon} {sc.label}
            </span>
          </div>
          {campaign.scheduled_at && (
            <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
              <Calendar size={10} />
              <span>Scheduled: {new Date(campaign.scheduled_at).toLocaleString()}</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {(campaign.status === "draft" || campaign.status === "paused") && (
            <button onClick={() => onLaunch(campaign.id)}
              className="flex items-center gap-1.5 text-xs bg-teal-500 text-white px-3 py-1.5 rounded-lg font-medium hover:bg-teal-600 transition-colors">
              <Play size={11} /> Launch
            </button>
          )}
          <button onClick={() => { if (confirm("Delete this campaign?")) onDelete(campaign.id); }}
            className="text-gray-400 hover:text-red-500 transition-colors p-1.5 rounded-lg hover:bg-red-50">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Stats */}
      {sent > 0 && (
        <div className="grid grid-cols-4 gap-3 pt-3 border-t border-gray-100">
          {[
            { label: "Sent", value: sent, icon: <Send size={12} className="text-gray-400" /> },
            { label: "Delivered", value: delivered, sub: rate(campaign.delivered_count, campaign.sent_count), icon: <CheckCircle2 size={12} className="text-blue-400" /> },
            { label: "Read", value: read, sub: rate(campaign.read_count, campaign.sent_count), icon: <Eye size={12} className="text-teal-500" /> },
            { label: "Failed", value: parseInt(campaign.failed_count) || 0, icon: <AlertCircle size={12} className="text-red-400" /> },
          ].map(stat => (
            <div key={stat.label} className="text-center">
              <div className="flex items-center justify-center gap-1 mb-0.5">{stat.icon}</div>
              <p className="text-base font-bold text-gray-900">{stat.value.toLocaleString()}</p>
              {stat.sub && <p className="text-[10px] text-gray-400">{stat.sub}</p>}
              <p className="text-[10px] text-gray-400">{stat.label}</p>
            </div>
          ))}
        </div>
      )}
      {sent === 0 && campaign.status === "draft" && (
        <p className="text-[11px] text-gray-400 pt-2 border-t border-gray-100">
          Launch this campaign to start sending messages to your opted-in subscribers.
        </p>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CampaignsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: campaigns = [], isLoading, isError, refetch, isFetching } = useQuery<Campaign[]>({
    queryKey: ["wa-campaigns"],
    queryFn: () => api.get("/messaging/campaigns").then(r => r.data),
    staleTime: 30_000,
  });

  const { data: templates = [] } = useQuery<Template[]>({
    queryKey: ["wa-templates"],
    queryFn: () => api.get("/messaging/templates").then(r => r.data).catch(() => []),
    staleTime: 60_000,
  });

  const launchMutation = useMutation({
    mutationFn: (id: string) => api.post(`/messaging/campaigns/${id}/launch`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-campaigns"] }); showToast("Campaign launched!", "success"); },
    onError: () => showToast("Launch failed.", "error"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/messaging/campaigns/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-campaigns"] }); showToast("Campaign deleted.", "success"); },
    onError: () => showToast("Delete failed.", "error"),
  });

  const totalSent = campaigns.reduce((s, c) => s + (parseInt(c.sent_count) || 0), 0);
  const totalRead = campaigns.reduce((s, c) => s + (parseInt(c.read_count) || 0), 0);

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="haip-page-title">Campaigns</h1>
            <p className="text-sm text-gray-400 mt-0.5">Broadcast WhatsApp messages to opted-in guests using approved templates.</p>
          </div>
          <button onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 bg-teal-500 text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors shadow-sm shadow-teal-200">
            <Plus size={15} /> New campaign
          </button>
        </div>

        {/* Summary stats */}
        {totalSent > 0 && (
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: "Total sent", value: totalSent.toLocaleString(), icon: <Send size={14} className="text-gray-500" /> },
              { label: "Total read", value: totalRead.toLocaleString(), icon: <Eye size={14} className="text-teal-500" /> },
              { label: "Read rate", value: rate(totalRead.toString(), totalSent.toString()), icon: <TrendingUp size={14} className="text-blue-500" /> },
            ].map(s => (
              <div key={s.label} className="bg-gray-50 rounded-xl p-3 flex items-center gap-3">
                {s.icon}
                <div>
                  <p className="text-lg font-bold text-gray-900">{s.value}</p>
                  <p className="text-[10px] text-gray-500">{s.label}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {isError ? (
          <div className="py-20 text-center">
            <AlertCircle size={32} className="text-red-300 mx-auto mb-3" />
            <p className="text-sm text-gray-700 font-medium">Couldn't load campaigns</p>
            <p className="text-xs text-gray-400 mt-1">The server didn't respond — this isn't your saved campaign history.</p>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="mt-4 text-xs font-semibold text-teal-600 border border-teal-200 bg-teal-50 hover:bg-teal-100 px-3 py-1.5 rounded-lg transition-colors"
            >
              {isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        ) : isLoading ? (
          <div className="space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div>
        ) : campaigns.length === 0 ? (
          <div className="py-20 text-center">
            <Megaphone size={40} className="text-gray-200 mx-auto mb-3" />
            <p className="text-sm text-gray-500 font-medium">No campaigns yet</p>
            <p className="text-xs text-gray-400 mt-1">Create your first campaign to reach guests at scale via WhatsApp.</p>
            <button onClick={() => setShowCreate(true)}
              className="mt-4 flex items-center gap-2 bg-teal-500 text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-teal-600 transition-colors mx-auto">
              <Plus size={14} /> Create campaign
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {campaigns.map(c => (
              <CampaignCard
                key={c.id}
                campaign={c}
                onLaunch={(id) => launchMutation.mutate(id)}
                onDelete={(id) => deleteMutation.mutate(id)}
              />
            ))}
          </div>
        )}
      </div>

      {showCreate && (
        <CreateCampaignModal
          templates={templates as Template[]}
          onClose={() => setShowCreate(false)}
          onCreated={() => { queryClient.invalidateQueries({ queryKey: ["wa-campaigns"] }); showToast("Campaign created!", "success"); }}
        />
      )}
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}
