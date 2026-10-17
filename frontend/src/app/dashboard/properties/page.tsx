"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus, X, Edit2, Loader2, MapPin, Users, Wifi, TrendingUp, CheckCircle2, AlertCircle } from "@/lib/icons";
import { BedDouble, Bath } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";

interface Property {
  id: string;
  name: string;
  city?: string;
  address?: string;
  type?: string;
  property_type?: string;
  is_active?: boolean;
  bedrooms?: number;
  bathrooms?: number;
  max_adults?: number;
  channel_source?: string;
  created_at?: string;
}

const PROPERTY_TYPES = ["villa", "resort", "hotel", "apartment", "hostel", "camp", "other"];

const TYPE_ICON: Record<string, string> = {
  villa: "🏡",
  resort: "🌴",
  hotel: "🏨",
  apartment: "🏢",
  hostel: "🛏",
  camp: "⛺",
  other: "🏠",
};

const SOURCE_COLOR: Record<string, { bg: string; text: string }> = {
  rentalwise: { bg: "var(--haip-primary-tint)", text: "var(--primary)" },
  airbnb:     { bg: "rgba(255,90,95,0.12)",  text: "#e11d48" },
  booking:    { bg: "rgba(0,99,191,0.12)",   text: "#0057a8" },
  manual:     { bg: "rgba(148,163,184,0.12)", text: "#64748b" },
};

function sourceStyle(s?: string) {
  if (!s) return SOURCE_COLOR.manual;
  return SOURCE_COLOR[s.toLowerCase()] ?? SOURCE_COLOR.manual;
}

function PropertySkeleton() {
  return (
    <div className="haip-card p-5 rounded-2xl animate-pulse">
      <div className="flex items-start justify-between mb-4">
        <div className="w-11 h-11 rounded-xl bg-[var(--haip-status-neutral-bg)]" />
        <div className="w-16 h-5 rounded-full bg-[var(--haip-status-neutral-bg)]" />
      </div>
      <div className="h-4 bg-[var(--haip-status-neutral-bg)] rounded w-3/4 mb-2" />
      <div className="h-3 bg-[var(--haip-status-neutral-bg)] rounded w-1/2 mb-4" />
      <div className="flex gap-2">
        <div className="h-3 bg-[var(--haip-status-neutral-bg)] rounded w-12" />
        <div className="h-3 bg-[var(--haip-status-neutral-bg)] rounded w-12" />
        <div className="h-3 bg-[var(--haip-status-neutral-bg)] rounded w-12" />
      </div>
    </div>
  );
}

function PropertyCard({ p, onEdit, noun }: { p: Property; onEdit: (p: Property) => void; noun: string }) {
  const typeKey = (p.type ?? p.property_type ?? "other").toLowerCase();
  const emoji = TYPE_ICON[typeKey] ?? "🏠";
  const sc = sourceStyle(p.channel_source);
  const active = p.is_active !== false;

  return (
    <div
      className="haip-card rounded-2xl p-5 flex flex-col gap-4 group relative overflow-hidden transition-all duration-200"
      style={{ border: "1px solid var(--haip-border)" }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--primary)";
        (e.currentTarget as HTMLElement).style.boxShadow = "0 0 0 1px var(--primary), 0 4px 20px var(--haip-primary-tint)";
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--haip-border)";
        (e.currentTarget as HTMLElement).style.boxShadow = "";
      }}
    >
      {/* header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center text-xl flex-shrink-0"
            style={{ background: "var(--haip-primary-tint)" }}
          >
            {emoji}
          </div>
          <div className="min-w-0">
            <h3
              className="font-semibold text-[14.5px] leading-snug line-clamp-2"
              style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}
            >
              {p.name || <span className="text-[var(--haip-fg-subtle)] italic text-sm">Unnamed {noun}</span>}
            </h3>
            {(p.city || p.address) && (
              <div className="flex items-center gap-1 mt-0.5">
                <MapPin size={10} style={{ color: "var(--haip-fg-muted)" }} />
                <span className="text-[11px] truncate max-w-[140px]" style={{ color: "var(--haip-fg-muted)" }}>
                  {p.city || p.address}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* edit button */}
        <button
          onClick={() => onEdit(p)}
          className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg"
          style={{ color: "var(--haip-fg-muted)" }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "rgba(0,0,0,0.05)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = ""; }}
          title={`Edit ${noun}`}
        >
          <Edit2 size={13} />
        </button>
      </div>

      {/* badges row */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* type badge */}
        <span
          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium capitalize"
          style={{ background: "var(--haip-primary-tint)", color: "var(--primary)" }}
        >
          {typeKey}
        </span>

        {/* source badge */}
        {p.channel_source && (
          <span
            className="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium capitalize"
            style={{ background: sc.bg, color: sc.text }}
          >
            {p.channel_source}
          </span>
        )}

        {/* active/inactive */}
        {active ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
            style={{ background: "var(--haip-primary-tint)", color: "var(--primary)" }}>
            <CheckCircle2 size={9} /> Active
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
            style={{ background: "rgba(248,113,113,0.10)", color: "#dc2626" }}>
            <AlertCircle size={9} /> Inactive
          </span>
        )}
      </div>

      {/* capacity row */}
      {(p.bedrooms != null || p.bathrooms != null || p.max_adults != null) && (
        <div
          className="flex items-center gap-4 pt-3"
          style={{ borderTop: "1px solid var(--haip-border)" }}
        >
          {p.bedrooms != null && (
            <div className="flex items-center gap-1.5">
              <BedDouble size={12} style={{ color: "var(--haip-fg-muted)" }} />
              <span className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>
                {p.bedrooms} bed{p.bedrooms !== 1 ? "s" : ""}
              </span>
            </div>
          )}
          {p.bathrooms != null && (
            <div className="flex items-center gap-1.5">
              <Bath size={12} style={{ color: "var(--haip-fg-muted)" }} />
              <span className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>
                {p.bathrooms} bath{p.bathrooms !== 1 ? "s" : ""}
              </span>
            </div>
          )}
          {p.max_adults != null && (
            <div className="flex items-center gap-1.5">
              <Users size={12} style={{ color: "var(--haip-fg-muted)" }} />
              <span className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>
                {p.max_adults} guests
              </span>
            </div>
          )}
        </div>
      )}

      {/* added date */}
      {p.created_at && (
        <p className="text-[10.5px] -mt-1" style={{ color: "rgba(100,116,139,0.6)" }}>
          Added {new Date(p.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
        </p>
      )}
    </div>
  );
}

export default function PropertiesPage() {
  const queryClient = useQueryClient();
  const businessType = useBusinessType();
  const isCaravan = businessType === "caravan";
  const noun = isCaravan ? "package" : "property";
  const nounPlural = isCaravan ? "packages" : "properties";
  const Noun = isCaravan ? "Package" : "Property";
  const NounPlural = isCaravan ? "Packages" : "Portfolio";
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Property | null>(null);
  const [form, setForm] = useState({ name: "", city: "", property_type: "villa" });
  const [toastMsg, setToastMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

  function showToast(type: "success" | "error", text: string) {
    setToastMsg({ type, text });
    setTimeout(() => setToastMsg(null), 3500);
  }

  const { data: properties = [], isLoading } = useQuery<Property[]>({
    queryKey: ["properties"],
    queryFn: () => api.get("/properties").then(r => r.data),
    staleTime: 60_000,
  });

  const createMutation = useMutation({
    mutationFn: () => api.post("/properties", form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["properties"] });
      showToast("success", `${Noun} created`);
      setShowForm(false);
      setForm({ name: "", city: "", property_type: "villa" });
    },
    onError: () => showToast("error", "Create failed"),
  });

  const updateMutation = useMutation({
    mutationFn: () => api.patch(`/properties/${editing!.id}`, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["properties"] });
      showToast("success", `${Noun} updated`);
      setEditing(null);
      setShowForm(false);
    },
    onError: () => showToast("error", "Update failed"),
  });

  const openEdit = (p: Property) => {
    setEditing(p);
    setForm({ name: p.name, city: p.city ?? "", property_type: p.type ?? p.property_type ?? "villa" });
    setShowForm(true);
  };

  const openCreate = () => {
    setEditing(null);
    setForm({ name: "", city: "", property_type: "villa" });
    setShowForm(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editing) updateMutation.mutate();
    else createMutation.mutate();
  };

  const isPending = createMutation.isPending || updateMutation.isPending;
  const activeCount = properties.filter(p => p.is_active !== false).length;
  const inactiveCount = properties.length - activeCount;

  return (
    <div className="h-full flex flex-col" style={{ background: "var(--haip-surface)" }}>

      {/* ── Page header ─────────────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 px-6 py-5"
        style={{
          background: "#FFFFFF",
          borderBottom: "1px solid #E5E7EB",
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1
              className="text-[22px] font-bold leading-tight"
              style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
            >
              {NounPlural}
            </h1>
            <p className="text-[13px] mt-0.5" style={{ color: "#6B7280" }}>
              {isLoading ? "Loading…" : `${properties.length} ${properties.length === 1 ? noun : nounPlural}`}
              {!isLoading && inactiveCount > 0 && (
                <span style={{ color: "#EF4444" }}> · {inactiveCount} inactive</span>
              )}
            </p>
          </div>

          <button
            onClick={openCreate}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-[13px] font-semibold transition-all text-white"
            style={{ background: "var(--primary)" }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--haip-primary-hover)"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "var(--primary)"; }}
          >
            <Plus size={14} />
            Add {noun}
          </button>
        </div>

        {/* KPI strip */}
        {!isLoading && properties.length > 0 && (
          <div className="flex items-center gap-6 mt-4">
            <div>
              <p className="text-[11px]" style={{ color: "#9CA3AF" }}>Total</p>
              <p className="text-[22px] font-bold leading-none mt-0.5"
                style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}>
                {properties.length}
              </p>
            </div>
            <div className="w-px h-8" style={{ background: "#E5E7EB" }} />
            <div>
              <p className="text-[11px]" style={{ color: "#9CA3AF" }}>Active</p>
              <p className="text-[22px] font-bold leading-none mt-0.5"
                style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--primary)" }}>
                {activeCount}
              </p>
            </div>
            {inactiveCount > 0 && (
              <>
                <div className="w-px h-8" style={{ background: "#E5E7EB" }} />
                <div>
                  <p className="text-[11px]" style={{ color: "#9CA3AF" }}>Inactive</p>
                  <p className="text-[22px] font-bold leading-none mt-0.5"
                    style={{ fontFamily: "var(--font-display), sans-serif", color: "#EF4444" }}>
                    {inactiveCount}
                  </p>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Content area ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-6 haip-scrollbar">
        {isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {Array.from({ length: 6 }).map((_, i) => <PropertySkeleton key={i} />)}
          </div>
        ) : properties.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
              style={{ background: "var(--haip-primary-tint)" }}
            >
              <Building2 size={28} style={{ color: "var(--primary)" }} />
            </div>
            <p className="font-semibold" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}>
              No {nounPlural} yet
            </p>
            <p className="text-sm mt-1 mb-5" style={{ color: "var(--haip-fg-muted)" }}>
              Add your first {noun} to start tracking inquiries and revenue
            </p>
            <button
              onClick={openCreate}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all"
              style={{ background: "var(--primary)", color: "#fff" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--primary)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "var(--primary)"; }}
            >
              <Plus size={15} /> Add {noun}
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {properties.map(p => (
              <PropertyCard key={p.id} p={p} onEdit={openEdit} noun={noun} />
            ))}
          </div>
        )}
      </div>

      {/* ── Create / Edit modal ─────────────────────────────────────────────── */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div
            className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden"
            style={{ border: "1px solid var(--haip-border)" }}
          >
            {/* modal header */}
            <div
              className="flex items-center justify-between px-6 py-4"
              style={{ background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}
            >
              <h3
                className="font-bold text-[15px]"
                style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
              >
                {editing ? `Edit ${noun}` : `Add ${noun}`}
              </h3>
              <button
                onClick={() => { setShowForm(false); setEditing(null); }}
                className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors"
                style={{ color: "#9CA3AF" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#374151"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#9CA3AF"; }}
              >
                <X size={15} />
              </button>
            </div>

            {/* form */}
            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              <div>
                <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>
                  {Noun} name *
                </label>
                <input
                  required
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  placeholder={isCaravan ? "Backwaters Explorer" : "Jade Beach Villa"}
                  className="w-full px-4 py-2.5 rounded-xl text-sm focus:outline-none transition-colors"
                  style={{
                    border: "1px solid var(--haip-border)",
                    background: "var(--haip-surface)",
                    color: "var(--haip-fg)",
                  }}
                  onFocus={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--primary)"; (e.currentTarget as HTMLElement).style.boxShadow = "0 0 0 2px var(--haip-primary-tint)"; }}
                  onBlur={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--haip-border)"; (e.currentTarget as HTMLElement).style.boxShadow = ""; }}
                />
              </div>
              <div>
                <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>
                  City *
                </label>
                <input
                  required
                  value={form.city}
                  onChange={e => setForm(f => ({ ...f, city: e.target.value }))}
                  placeholder="Goa"
                  className="w-full px-4 py-2.5 rounded-xl text-sm focus:outline-none transition-colors"
                  style={{
                    border: "1px solid var(--haip-border)",
                    background: "var(--haip-surface)",
                    color: "var(--haip-fg)",
                  }}
                  onFocus={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--primary)"; (e.currentTarget as HTMLElement).style.boxShadow = "0 0 0 2px var(--haip-primary-tint)"; }}
                  onBlur={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--haip-border)"; (e.currentTarget as HTMLElement).style.boxShadow = ""; }}
                />
              </div>
              <div>
                <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>
                  Type
                </label>
                <select
                  value={form.property_type}
                  onChange={e => setForm(f => ({ ...f, property_type: e.target.value }))}
                  className="w-full px-4 py-2.5 rounded-xl text-sm focus:outline-none transition-colors appearance-none cursor-pointer"
                  style={{
                    border: "1px solid var(--haip-border)",
                    background: "var(--haip-surface)",
                    color: "var(--haip-fg)",
                  }}
                >
                  {PROPERTY_TYPES.map(t => (
                    <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                  ))}
                </select>
              </div>

              <div className="flex gap-2.5 pt-1">
                <button
                  type="button"
                  onClick={() => { setShowForm(false); setEditing(null); }}
                  className="flex-1 py-2.5 rounded-xl text-sm font-medium transition-colors"
                  style={{ border: "1px solid var(--haip-border)", color: "var(--haip-fg-muted)", background: "transparent" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "rgba(0,0,0,0.04)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isPending}
                  className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 transition-all disabled:opacity-50"
                  style={{ background: "var(--primary)" }}
                  onMouseEnter={e => { if (!isPending) (e.currentTarget as HTMLElement).style.background = "var(--primary)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "var(--primary)"; }}
                >
                  {isPending && <Loader2 size={14} className="animate-spin" />}
                  {editing ? "Save changes" : `Create ${noun}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Toast ──────────────────────────────────────────────────────────── */}
      {toastMsg && (
        <div
          className="fixed bottom-5 right-5 z-50 px-4 py-3 rounded-xl text-sm font-medium shadow-lg transition-all"
          style={{
            background: toastMsg.type === "success" ? "var(--primary)" : "#dc2626",
            color: "#fff",
          }}
        >
          {toastMsg.text}
        </div>
      )}
    </div>
  );
}
