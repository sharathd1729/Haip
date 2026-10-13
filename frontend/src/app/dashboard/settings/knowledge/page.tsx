"use client";
import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, X, History, AlertCircle, Loader2, RefreshCw, CheckCircle2, BookOpen, Upload, Globe } from "@/lib/icons";
import api from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { Tabs } from "@/components/ui/kit";
import { KnowledgeTestBox } from "@/components/knowledge/KnowledgeTestBox";
import { StructuredDataTab } from "@/components/knowledge/StructuredDataTab";
import { KnowledgeHistoryDrawer } from "@/components/knowledge/KnowledgeHistoryDrawer";

interface KnowledgeEntry {
  id: string;
  category: string;
  question?: string | null;
  content: string;
  source: string;
  source_url?: string | null;
  alt_phrasings?: string[] | null;
  priority: number;
  is_active: boolean;
  review_status: string;
  embedding_status: string;
  embedding_error?: string | null;
  embedding_attempts?: number;
  embedded_at?: string | null;
  stale_since?: string | null;
  property_id?: string | null;
  updated_at: string;
}

interface KnowledgeStats {
  total: number;
  active: number;
  pending_review: number;
  embedding_pending: number;
  embedding_failed: number;
  retrievable: number;
  stale?: number;
  last_indexed_at?: string | null;
  last_error?: string | null;
  search_available?: boolean;
}

interface PropertyLite {
  id: string;
  name: string;
}

const CATEGORIES = [
  { key: "faq", label: "FAQ", hint: "Common guest questions and their answers" },
  { key: "pricing", label: "Pricing", hint: "Rates, packages, seasonal pricing notes" },
  { key: "amenities", label: "Amenities", hint: "What's included — WiFi, AC, kitchen, bedding" },
  { key: "addons", label: "Add-ons", hint: "Extras guests can book — BBQ, bonfire, chef" },
  { key: "location", label: "Location", hint: "Where you are, landmarks, how to find you" },
  { key: "routes", label: "Routes", hint: "Distances and travel times to destinations" },
  { key: "policy", label: "Policies", hint: "Cancellation, check-in times, house rules" },
  { key: "availability", label: "Availability", hint: "Seasonal closures, minimum stays" },
  { key: "other", label: "Other", hint: "Anything else the AI should know" },
];

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((c) => [c.key, c.label]),
);

type FormState = {
  id?: string;
  category: string;
  question: string;
  content: string;
  priority: number;
  property_id: string;   // "" = applies to every property
};

const EMPTY_FORM: FormState = { category: "faq", question: "", content: "", priority: 0, property_id: "" };

function KnowledgeAndTrainingTab() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [form, setForm] = useState<FormState | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const [crawlOpen, setCrawlOpen] = useState(false);
  const [crawlUrls, setCrawlUrls] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: stats } = useQuery<KnowledgeStats>({
    queryKey: ["knowledge-stats"],
    queryFn: () => api.get("/knowledge/stats").then((r) => r.data),
    retry: 1,
    // While anything is waiting to be indexed, keep checking: the owner should see it become usable, not guess.
    refetchInterval: (q) => ((q.state.data?.embedding_pending ?? 0) > 0 ? 5000 : false),
  });
  const indexing = (stats?.embedding_pending ?? 0) > 0;

  const { data, isLoading, isError, refetch } = useQuery<{ items: KnowledgeEntry[]; total: number }>({
    queryKey: ["knowledge", categoryFilter],
    queryFn: () =>
      api
        .get("/knowledge", { params: { include_inactive: true, ...(categoryFilter ? { category: categoryFilter } : {}) } })
        .then((r) => r.data),
    retry: 1,
    refetchInterval: indexing ? 5000 : false,
  });

  const { data: properties = [] } = useQuery<PropertyLite[]>({
    queryKey: ["properties-lite"],
    queryFn: () => api.get("/properties").then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const propertyName = (id?: string | null) => properties.find((p) => p.id === id)?.name ?? "one property";

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    queryClient.invalidateQueries({ queryKey: ["knowledge-stats"] });
  };

  const saveMutation = useMutation({
    mutationFn: (d: FormState) => {
      const payload = {
        category: d.category,
        question: d.question.trim() || null,
        content: d.content.trim(),
        priority: d.priority,
        // null on edit = "applies to every property"; the server reads an explicit null as clearing the scope.
        property_id: d.property_id || null,
      };
      return d.id ? api.patch(`/knowledge/${d.id}`, payload) : api.post("/knowledge", payload);
    },
    onSuccess: () => {
      invalidate();
      setForm(null);
      toast({
        variant: "success",
        title: "Saved",
        description: "The AI starts using the new wording once it has been indexed. Watch the status on the entry.",
      });
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: unknown } } };
      const detail = err?.response?.data?.detail;
      toast({
        variant: "error",
        title: "Couldn't save",
        description: typeof detail === "string" ? detail : "Check the fields and try again.",
      });
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api.post("/knowledge/upload", body, {
        headers: { "Content-Type": "multipart/form-data" },
      }).then((r) => r.data as { entries_created: number; message: string });
    },
    onSuccess: (d) => {
      invalidate();
      toast({ variant: "success", title: "Uploaded", description: d.message });
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: unknown } } };
      const detail = err?.response?.data?.detail;
      toast({
        variant: "error",
        title: "Upload failed",
        description: typeof detail === "string" ? detail : "Try a PDF, Word doc, or plain text file under 15 MB.",
      });
    },
  });

  const crawlMutation = useMutation({
    mutationFn: (urls: string[]) =>
      api.post("/knowledge/crawl", { urls }).then((r) => r.data as { entries_created: number; message: string }),
    onSuccess: (d) => {
      invalidate();
      setCrawlOpen(false);
      setCrawlUrls("");
      toast({ variant: "success", title: "Added from website", description: d.message });
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: unknown } } };
      const detail = err?.response?.data?.detail;
      toast({
        variant: "error",
        title: "Couldn't fetch that page",
        description: typeof detail === "string" ? detail : "Check the URL and try again.",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/knowledge/${id}`),
    onSuccess: () => {
      invalidate();
      toast({ variant: "success", title: "Deleted" });
    },
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.patch(`/knowledge/${id}`, { is_active }),
    onSuccess: invalidate,
  });

  const removePhrasing = useMutation({
    mutationFn: ({ id, phrasings }: { id: string; phrasings: string[] }) =>
      api.patch(`/knowledge/${id}`, { alt_phrasings: phrasings }),
    onSuccess: () => {
      invalidate();
      toast({ variant: "success", title: "Removed", description: "Re-indexing this entry." });
    },
  });

  const review = useMutation({
    mutationFn: ({ id, review_status }: { id: string; review_status: "approved" | "rejected" }) =>
      api.patch(`/knowledge/${id}`, { review_status }),
    onSuccess: (_d, v) => {
      invalidate();
      toast({
        variant: "success",
        title: v.review_status === "approved" ? "Approved" : "Rejected",
        description: v.review_status === "approved" ? "The AI can use it once indexing shows as done." : undefined,
      });
    },
    onError: () => toast({ variant: "error", title: "Couldn't update that entry" }),
  });

  const keepOutOfDate = useMutation({
    mutationFn: (id: string) => api.patch(`/knowledge/${id}`, { keep_out_of_date: true }),
    onSuccess: () => {
      invalidate();
      toast({ variant: "success", title: "Kept", description: "The AI can use this again." });
    },
  });

  const reindexAll = useMutation({
    mutationFn: () => api.post("/knowledge/reindex").then((r) => r.data as { queued: number }),
    onSuccess: (d) => {
      invalidate();
      toast({
        variant: "success",
        title: d.queued ? `Re-indexing ${d.queued} entr${d.queued === 1 ? "y" : "ies"}` : "Nothing to re-index",
      });
    },
    onError: () => toast({ variant: "error", title: "Couldn't start indexing", description: "Try again in a minute." }),
  });

  const reembed = useMutation({
    mutationFn: (id: string) => api.post(`/knowledge/${id}/reembed`),
    onSuccess: () => {
      invalidate();
      toast({ variant: "success", title: "Re-indexing…" });
    },
  });

  const entries = data?.items ?? [];

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="haip-page-title">AI Knowledge Base</h1>
            <p className="text-sm text-gray-400 mt-0.5 max-w-2xl">
              What your AI concierge knows about your properties. Live availability and rates come from your
              calendar and rate card — everything else (amenities, add-ons, routes, policies) it learns here.
              Edits are used only after the entry shows as indexed.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) uploadMutation.mutate(file);
                e.target.value = "";
              }}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMutation.isPending}
              title="Upload a PDF, Word doc, or text file -- added as pending entries for you to review"
              className="flex items-center gap-1.5 px-3.5 py-2 bg-white border border-gray-200 text-gray-700 rounded-xl text-sm font-semibold hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              {uploadMutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
              Upload document
            </button>
            <button
              onClick={() => setCrawlOpen(true)}
              title="Pull content from your website (e.g. your FAQ or amenities page) -- added as pending entries for you to review"
              className="flex items-center gap-1.5 px-3.5 py-2 bg-white border border-gray-200 text-gray-700 rounded-xl text-sm font-semibold hover:bg-gray-50 transition-colors"
            >
              <Globe size={15} /> Add from website
            </button>
            <button
              onClick={() => setForm({ ...EMPTY_FORM })}
              className="flex items-center gap-1.5 px-4 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors"
            >
              <Plus size={15} /> Add knowledge
            </button>
          </div>
        </div>

        {stats && (
          <div className="flex flex-wrap items-center gap-4 mt-4 text-xs">
            <span className="inline-flex items-center gap-1.5 text-teal-700 font-medium">
              <CheckCircle2 size={13} /> {stats.retrievable} answers the AI can use
            </span>
            {stats.last_indexed_at && (
              <span className="text-gray-400">last indexed {timeAgo(stats.last_indexed_at)}</span>
            )}
            {stats.embedding_pending > 0 && (
              <span className="inline-flex items-center gap-1.5 text-gray-500">
                <Loader2 size={12} className="animate-spin" /> {stats.embedding_pending} indexing — not usable yet
              </span>
            )}
            {stats.embedding_failed > 0 && (
              <span className="inline-flex items-center gap-1.5 text-red-600" title={stats.last_error ?? undefined}>
                <AlertCircle size={12} /> {stats.embedding_failed} failed to index — the AI cannot use{" "}
                {stats.embedding_failed === 1 ? "it" : "them"}
              </span>
            )}
            {!!stats.stale && (
              <span className="inline-flex items-center gap-1.5 text-amber-600">
                <AlertCircle size={12} /> {stats.stale} out of date — not used
              </span>
            )}
            {(stats.embedding_failed > 0 || stats.embedding_pending > 0) && (
              <button
                onClick={() => reindexAll.mutate()}
                disabled={reindexAll.isPending}
                className="inline-flex items-center gap-1 text-teal-700 font-semibold hover:underline disabled:opacity-50"
              >
                <RefreshCw size={11} className={reindexAll.isPending ? "animate-spin" : undefined} /> Retry indexing
              </button>
            )}
            {stats.pending_review > 0 && (
              <span className="inline-flex items-center gap-1.5 text-amber-600">
                <AlertCircle size={12} /> {stats.pending_review} awaiting review
              </span>
            )}
          </div>
        )}
        {stats && stats.search_available === false && (
          <p className="mt-3 text-xs text-red-600">
            Knowledge search is not available on this deployment, so the AI is answering without your knowledge base.
          </p>
        )}
        {stats && stats.embedding_failed > 0 && stats.last_error && (
          <p className="mt-2 text-[11px] text-red-500 break-words">Last indexing error: {stats.last_error}</p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl space-y-5">
          <KnowledgeTestBox properties={properties} />

          {/* Category filter */}
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => setCategoryFilter("")}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
                !categoryFilter
                  ? "bg-teal-50 border-teal-300 text-teal-800"
                  : "bg-white border-gray-200 text-gray-600 hover:border-gray-300",
              )}
            >
              All
            </button>
            {CATEGORIES.map((c) => (
              <button
                key={c.key}
                onClick={() => setCategoryFilter(c.key)}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
                  categoryFilter === c.key
                    ? "bg-teal-50 border-teal-300 text-teal-800"
                    : "bg-white border-gray-200 text-gray-600 hover:border-gray-300",
                )}
              >
                {c.label}
              </button>
            ))}
          </div>

          {/* List */}
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 rounded-2xl" />
              ))}
            </div>
          ) : isError ? (
            <div className="flex items-start gap-3 px-4 py-3.5 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
              <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="font-medium">Couldn&apos;t load the knowledge base.</p>
              </div>
              <button
                onClick={() => refetch()}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-red-300 text-red-700 rounded-lg text-xs font-semibold hover:bg-red-100 transition-colors flex-shrink-0"
              >
                <RefreshCw size={12} /> Retry
              </button>
            </div>
          ) : entries.length === 0 ? (
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-10 text-center">
              <div className="w-10 h-10 rounded-full bg-teal-50 flex items-center justify-center mx-auto mb-3">
                <BookOpen size={18} className="text-teal-500" />
              </div>
              <p className="text-sm font-semibold text-gray-700">Nothing here yet</p>
              <p className="text-xs text-gray-400 mt-1 max-w-sm mx-auto">
                Until you add something, the AI can only answer availability and pricing questions. Start with
                your most-asked questions — pets, check-in time, what&apos;s included.
              </p>
              <button
                onClick={() => setForm({ ...EMPTY_FORM })}
                className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors"
              >
                <Plus size={14} /> Add the first one
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {entries.map((e) => (
                <div
                  key={e.id}
                  className={cn(
                    "bg-white rounded-2xl border shadow-sm p-4 transition-all",
                    e.is_active ? "border-gray-100" : "border-gray-100 opacity-60",
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-teal-700 bg-teal-50 px-1.5 py-0.5 rounded">
                          {CATEGORY_LABEL[e.category] ?? e.category}
                        </span>
                        {e.source !== "manual" && (
                          <span className="text-[10px] text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded capitalize">
                            from {e.source}
                          </span>
                        )}
                        {e.property_id && (
                          <span className="text-[10px] text-sky-700 bg-sky-50 px-1.5 py-0.5 rounded">
                            only {propertyName(e.property_id)}
                          </span>
                        )}
                        {e.review_status === "pending" && (
                          <span className="text-[10px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
                            needs review — not used yet
                          </span>
                        )}
                        {e.review_status === "rejected" && (
                          <span className="text-[10px] text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">rejected</span>
                        )}
                        {e.stale_since && (
                          <span className="text-[10px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
                            no longer on the source — not used
                          </span>
                        )}
                        {e.embedding_status === "pending" && (
                          <span className="inline-flex items-center gap-1 text-[10px] text-gray-500">
                            <Loader2 size={9} className="animate-spin" /> indexing — not usable until done
                          </span>
                        )}
                        {e.embedding_status === "failed" && (
                          <span
                            className="text-[10px] text-red-600 bg-red-50 px-1.5 py-0.5 rounded"
                            title={e.embedding_error ?? undefined}
                          >
                            indexing failed — not used
                          </span>
                        )}
                        {e.embedding_status === "done" && e.embedded_at && (
                          <span className="text-[10px] text-gray-400">indexed {timeAgo(e.embedded_at)}</span>
                        )}
                        {!e.is_active && (
                          <span className="text-[10px] text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">off</span>
                        )}
                      </div>
                      {e.embedding_status === "failed" && e.embedding_error && (
                        <p className="text-[11px] text-red-500 mb-1 break-words">{e.embedding_error}</p>
                      )}
                      {e.question && <p className="text-sm font-semibold text-gray-900">{e.question}</p>}
                      <p className="text-xs text-gray-600 leading-relaxed mt-0.5 whitespace-pre-wrap">{e.content}</p>

                      {/* Generated automatically -- shown so the owner can
                          see what the AI will recognise, and remove any that
                          miss the point. */}
                      {!!e.alt_phrasings?.length && (
                        <div className="mt-2">
                          <p className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">
                            Also recognises
                          </p>
                          <div className="flex flex-wrap gap-1">
                            {e.alt_phrasings.map(p => (
                              <span
                                key={p}
                                className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-gray-50 border border-gray-200 rounded text-[10px] text-gray-600"
                              >
                                {p}
                                <button
                                  onClick={() =>
                                    removePhrasing.mutate({
                                      id: e.id,
                                      phrasings: (e.alt_phrasings ?? []).filter(x => x !== p),
                                    })
                                  }
                                  className="text-gray-300 hover:text-red-500"
                                  title="Remove this phrasing"
                                >
                                  ×
                                </button>
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-1 flex-shrink-0">
                      {e.review_status === "pending" && (
                        <>
                          <button
                            onClick={() => review.mutate({ id: e.id, review_status: "approved" })}
                            disabled={review.isPending}
                            title="Let the AI use this"
                            className="px-2 py-1.5 text-teal-700 hover:text-teal-900 text-[11px] font-semibold whitespace-nowrap"
                          >
                            Approve
                          </button>
                          <button
                            onClick={() => review.mutate({ id: e.id, review_status: "rejected" })}
                            disabled={review.isPending}
                            title="Never use this"
                            className="px-2 py-1.5 text-gray-500 hover:text-red-600 text-[11px] font-medium whitespace-nowrap"
                          >
                            Reject
                          </button>
                        </>
                      )}
                      {e.stale_since && (
                        <button
                          onClick={() => keepOutOfDate.mutate(e.id)}
                          title="The source no longer has this, but it is still true — let the AI use it"
                          className="px-2 py-1.5 text-teal-700 hover:text-teal-900 text-[11px] font-semibold whitespace-nowrap"
                        >
                          Keep
                        </button>
                      )}
                      {e.embedding_status === "failed" && (
                        <button
                          onClick={() => reembed.mutate(e.id)}
                          title="Retry indexing"
                          className="p-1.5 text-gray-400 hover:text-teal-600 transition-colors"
                        >
                          <RefreshCw size={14} />
                        </button>
                      )}
                      {/* Label is the action, not the state -- a bare "Off"
                          next to an active entry reads as its status and
                          inverts the meaning for the user. */}
                      <button
                        onClick={() => toggleActive.mutate({ id: e.id, is_active: !e.is_active })}
                        title={e.is_active ? "Stop the AI using this" : "Let the AI use this"}
                        className="px-2 py-1.5 text-gray-500 hover:text-gray-800 transition-colors text-[11px] font-medium whitespace-nowrap"
                      >
                        {e.is_active ? "Turn off" : "Turn on"}
                      </button>
                      <button
                        onClick={() =>
                          setForm({
                            id: e.id,
                            category: e.category,
                            question: e.question ?? "",
                            content: e.content,
                            priority: e.priority,
                            property_id: e.property_id ?? "",
                          })
                        }
                        title="Edit"
                        className="p-1.5 text-gray-400 hover:text-teal-600 transition-colors"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        onClick={() => setHistoryFor(e.id)}
                        title="History — who changed this and what it said before"
                        aria-label="History"
                        className="p-1.5 text-gray-400 hover:text-teal-600 transition-colors"
                      >
                        <History size={14} />
                      </button>
                      <button
                        onClick={() => {
                          if (confirm("Delete this entry? The AI will stop using it immediately.")) {
                            deleteMutation.mutate(e.id);
                          }
                        }}
                        title="Delete"
                        className="p-1.5 text-gray-400 hover:text-red-600 transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <KnowledgeHistoryDrawer entryId={historyFor} onClose={() => setHistoryFor(null)} />

      {/* Editor modal */}
      {form && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto" style={{ maxHeight: "calc(100dvh - 2rem)" }}>
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white">
              <p className="text-sm font-semibold text-gray-800">
                {form.id ? "Edit knowledge" : "Add knowledge"}
              </p>
              <button onClick={() => setForm(null)} className="text-gray-400 hover:text-gray-600">
                <X size={16} />
              </button>
            </div>

            <div className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">Category</label>
                <select
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                >
                  {CATEGORIES.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-gray-400 mt-1">
                  {CATEGORIES.find((c) => c.key === form.category)?.hint}
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  Guest question{" "}
                  {form.category === "faq" ? (
                    <span className="text-red-500">*</span>
                  ) : (
                    <span className="text-gray-400 font-normal">(optional)</span>
                  )}
                </label>
                <input
                  value={form.question}
                  onChange={(e) => setForm({ ...form, question: e.target.value })}
                  placeholder="Do you allow pets?"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  Write it the way a guest would ask — that&apos;s what the AI matches against.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  What the AI should know <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={form.content}
                  onChange={(e) => setForm({ ...form, content: e.target.value })}
                  rows={5}
                  placeholder="Pets are welcome in our garden caravans at no extra charge…"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30 resize-y"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  Be specific and factual. The AI will paraphrase this in your brand voice — it won&apos;t quote
                  it word for word.
                </p>
              </div>

              {properties.length > 1 && (
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1.5">Applies to</label>
                  <select
                    value={form.property_id}
                    onChange={(e) => setForm({ ...form, property_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                  >
                    <option value="">Every property</option>
                    {properties.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} only
                      </option>
                    ))}
                  </select>
                  <p className="text-[11px] text-gray-400 mt-1">
                    A property-only entry is never offered to guests asking about another property.
                  </p>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  Priority <span className="text-gray-400 font-normal">(0–100)</span>
                </label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={form.priority}
                  onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
                  className="w-32 px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  Breaks ties when two entries match a question equally well. Leave at 0 unless something must win.
                </p>
              </div>
            </div>

            <div className="px-5 py-4 border-t border-gray-100 flex items-center justify-end gap-2 sticky bottom-0 bg-white">
              <button
                onClick={() => setForm(null)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => saveMutation.mutate(form)}
                disabled={
                  saveMutation.isPending ||
                  !form.content.trim() ||
                  (form.category === "faq" && !form.question.trim())
                }
                className="flex items-center gap-1.5 px-5 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50"
              >
                {saveMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add from website modal */}
      {crawlOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto" style={{ maxHeight: "calc(100dvh - 2rem)" }}>
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white">
              <p className="text-sm font-semibold text-gray-800">Add from website</p>
              <button onClick={() => setCrawlOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X size={16} />
              </button>
            </div>

            <div className="p-5 space-y-3">
              <label className="block text-xs font-medium text-gray-600 mb-1.5">
                Page URLs <span className="text-red-500">*</span>
              </label>
              <textarea
                value={crawlUrls}
                onChange={(e) => setCrawlUrls(e.target.value)}
                rows={5}
                placeholder={"https://yourproperty.com/faq\nhttps://yourproperty.com/amenities"}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30 resize-y font-mono"
              />
              <p className="text-[11px] text-gray-400">
                One URL per line, up to 5 pages at a time. Point it at specific pages that actually matter — your
                FAQ, amenities, or policies page — not your homepage. Content lands as pending entries for you to
                review before the AI can use it.
              </p>
            </div>

            <div className="px-5 py-4 border-t border-gray-100 flex items-center justify-end gap-2 sticky bottom-0 bg-white">
              <button
                onClick={() => setCrawlOpen(false)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  const urls = crawlUrls.split("\n").map((u) => u.trim()).filter(Boolean).slice(0, 5);
                  if (urls.length) crawlMutation.mutate(urls);
                }}
                disabled={crawlMutation.isPending || !crawlUrls.trim()}
                className="flex items-center gap-1.5 px-5 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50"
              >
                {crawlMutation.isPending && <Loader2 size={13} className="animate-spin" />}
                Fetch &amp; add
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

type Tab = "knowledge" | "structured";

export default function KnowledgePage() {
  const [tab, setTab] = useState<Tab>("knowledge");
  return (
    <div className="flex h-full flex-col">
      <div className="flex-shrink-0 border-b border-[var(--haip-border)] bg-[var(--haip-card)] px-4 pt-3 sm:px-6">
        <Tabs
          label="Knowledge base sections" value={tab} onChange={(v) => setTab(v as Tab)} className="max-w-md"
          items={[{ value: "knowledge", label: "Knowledge & Training" }, { value: "structured", label: "Structured Business Data" }]}
        />
      </div>
      <div className="min-h-0 flex-1">{tab === "knowledge" ? <KnowledgeAndTrainingTab /> : <StructuredDataPane />}</div>
    </div>
  );
}

function StructuredDataPane() {
  const { data: properties = [] } = useQuery<PropertyLite[]>({
    queryKey: ["properties-lite"],
    queryFn: () => api.get("/properties").then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <StructuredDataTab />
      <div className="mx-auto w-full max-w-4xl px-4 pb-8 sm:px-6">
        <KnowledgeTestBox properties={properties} />
      </div>
    </div>
  );
}
