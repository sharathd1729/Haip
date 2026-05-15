"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Home, Plus, X, Edit2, Building2, Loader2, ChevronRight } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

interface Property {
  id: string;
  name: string;
  city?: string;
  property_type?: string;
  is_active?: boolean;
  created_at: string;
}

const PROPERTY_TYPES = ["villa", "resort", "hotel", "apartment", "hostel", "camp", "other"];

export default function PropertiesPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Property | null>(null);
  const [form, setForm] = useState({ name: "", city: "", property_type: "villa" });

  const { data: properties = [], isLoading } = useQuery<Property[]>({
    queryKey: ["properties"],
    queryFn: () => api.get("/properties").then(r => r.data),
    staleTime: 60_000,
  });

  const createMutation = useMutation({
    mutationFn: () => api.post("/properties", form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["properties"] });
      toast({ variant: "success", title: "Property created" });
      setShowForm(false);
      setForm({ name: "", city: "", property_type: "villa" });
    },
    onError: () => toast({ variant: "error", title: "Create failed" }),
  });

  const updateMutation = useMutation({
    mutationFn: () => api.patch(`/properties/${editing!.id}`, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["properties"] });
      toast({ variant: "success", title: "Property updated" });
      setEditing(null);
    },
    onError: () => toast({ variant: "error", title: "Update failed" }),
  });

  const openEdit = (p: Property) => {
    setEditing(p);
    setForm({ name: p.name, city: p.city ?? "", property_type: p.property_type ?? "villa" });
    setShowForm(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editing) updateMutation.mutate();
    else createMutation.mutate();
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="h-full flex flex-col bg-white">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Properties</h1>
          <p className="text-xs text-gray-400 mt-0.5">{properties.length} properties</p>
        </div>
        <button
          onClick={() => { setEditing(null); setForm({ name: "", city: "", property_type: "villa" }); setShowForm(true); }}
          className="flex items-center gap-1.5 text-xs bg-teal-500 text-white px-3 py-1.5 rounded-lg font-medium hover:bg-teal-600 transition-colors"
        >
          <Plus size={13} /> Add property
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-32 rounded-2xl" />)}
          </div>
        ) : properties.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
              <Building2 size={28} className="text-gray-400" />
            </div>
            <p className="text-gray-600 font-medium">No properties yet</p>
            <p className="text-gray-400 text-sm mt-1 mb-4">Add your first property to get started</p>
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 text-sm bg-teal-500 text-white px-4 py-2 rounded-xl font-medium hover:bg-teal-600 transition-colors"
            >
              <Plus size={15} /> Add property
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {properties.map(p => (
              <div
                key={p.id}
                className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm hover:shadow-md transition-shadow group"
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="w-10 h-10 rounded-xl bg-purple-100 flex items-center justify-center flex-shrink-0">
                    <Home size={18} className="text-purple-600" />
                  </div>
                  <button
                    onClick={() => openEdit(p)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-gray-600"
                  >
                    <Edit2 size={14} />
                  </button>
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{p.name}</h3>
                <div className="flex items-center gap-2 flex-wrap">
                  {p.city && <span className="text-xs text-gray-500">{p.city}</span>}
                  {p.property_type && (
                    <Badge variant="ghost" className="capitalize text-xs">{p.property_type}</Badge>
                  )}
                  {p.is_active === false && (
                    <Badge variant="secondary" className="text-xs">Inactive</Badge>
                  )}
                </div>
                <p className="text-[11px] text-gray-400 mt-3">
                  Added {new Date(p.created_at).toLocaleDateString("en-IN")}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create/Edit modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-gray-900">{editing ? "Edit property" : "Add property"}</h3>
              <button onClick={() => setShowForm(false)}><X size={16} className="text-gray-400" /></button>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Property name *</label>
                <input
                  required
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="Jade Beach Villa"
                  className="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">City *</label>
                <input
                  required
                  value={form.city}
                  onChange={e => setForm(f => ({ ...f, city: e.target.value }))}
                  placeholder="Goa"
                  className="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Type</label>
                <select
                  value={form.property_type}
                  onChange={e => setForm(f => ({ ...f, property_type: e.target.value }))}
                  className="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white"
                >
                  {PROPERTY_TYPES.map(t => (
                    <option key={t} value={t} className="capitalize">{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isPending}
                  className="flex-1 py-2.5 bg-teal-500 hover:bg-teal-600 disabled:opacity-50 text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2"
                >
                  {isPending && <Loader2 size={14} className="animate-spin" />}
                  {editing ? "Save changes" : "Create property"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
