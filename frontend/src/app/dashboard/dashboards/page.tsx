"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { Plus, LayoutDashboard, Pin, Star, Trash2, Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MoreHorizontal } from "lucide-react";

interface Dashboard {
  id: string;
  name: string;
  description?: string;
  visibility: "private" | "shared" | "workspace";
  is_pinned: boolean;
  is_default: boolean;
  owner_id: string;
  from_template_key?: string;
  created_at: string;
  updated_at: string;
}

interface Template {
  template_key: string;
  name: string;
  description?: string;
  available: boolean;
  missing_modules: string[];
}

export default function DashboardsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", visibility: "private", template_key: "" });

  const { data, isLoading } = useQuery({
    queryKey: ["dashboards"],
    queryFn: () => api.get("/dashboards").then((r) => r.data as { dashboards: Dashboard[] }),
  });

  const { data: tplData } = useQuery({
    queryKey: ["dashboard-templates"],
    queryFn: () => api.get("/dashboards/templates/list").then((r) => r.data as { templates: Template[] }),
  });

  const createMutation = useMutation({
    mutationFn: (body: object) => api.post("/dashboards", body),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["dashboards"] });
      setCreateOpen(false);
      router.push(`/dashboard/dashboards/${res.data.id}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/dashboards/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboards"] }),
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) => api.patch(`/dashboards/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboards"] }),
  });

  const dashboards = data?.dashboards ?? [];
  const pinned = dashboards.filter((d) => d.is_pinned);
  const rest = dashboards.filter((d) => !d.is_pinned);

  function handleCreate() {
    createMutation.mutate({
      name: form.name,
      description: form.description || undefined,
      visibility: form.visibility,
      from_template_key: form.template_key || undefined,
    });
  }

  const visibilityColor: Record<string, string> = {
    private: "bg-gray-100 text-gray-700",
    shared: "bg-blue-100 text-blue-700",
    workspace: "bg-green-100 text-green-700",
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">My Dashboards</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Create unlimited custom dashboards with drag-drop widgets
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="w-4 h-4" />
          New Dashboard
        </Button>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-36 rounded-xl bg-muted animate-pulse" />
          ))}
        </div>
      )}

      {/* Pinned */}
      {pinned.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            Pinned
          </h2>
          <DashboardGrid
            dashboards={pinned}
            onOpen={(id) => router.push(`/dashboard/dashboards/${id}`)}
            onDelete={(id) => deleteMutation.mutate(id)}
            onPatch={(id, body) => patchMutation.mutate({ id, body })}
            visibilityColor={visibilityColor}
          />
        </section>
      )}

      {/* All */}
      <section>
        {pinned.length > 0 && (
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            All Dashboards
          </h2>
        )}
        {rest.length === 0 && !isLoading && (
          <div className="text-center py-16 border-2 border-dashed rounded-xl">
            <LayoutDashboard className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
            <p className="font-medium">No dashboards yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Create one from scratch or pick a template
            </p>
            <Button className="mt-4 gap-2" onClick={() => setCreateOpen(true)}>
              <Plus className="w-4 h-4" />
              Create Dashboard
            </Button>
          </div>
        )}
        <DashboardGrid
          dashboards={rest}
          onOpen={(id) => router.push(`/dashboard/dashboards/${id}`)}
          onDelete={(id) => deleteMutation.mutate(id)}
          onPatch={(id, body) => patchMutation.mutate({ id, body })}
          visibilityColor={visibilityColor}
        />
      </section>

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>New Dashboard</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="text-sm font-medium">Name</label>
              <Input
                className="mt-1"
                placeholder="e.g. Weekly Sales Overview"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div>
              <label className="text-sm font-medium">Description (optional)</label>
              <Textarea
                className="mt-1"
                rows={2}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium">Visibility</label>
                <Select value={form.visibility} onValueChange={(v) => setForm({ ...form, visibility: v ?? "private" })}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="private">Private</SelectItem>
                    <SelectItem value="shared">Shared</SelectItem>
                    <SelectItem value="workspace">Workspace</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium">Start from template</label>
                <Select value={form.template_key} onValueChange={(v) => setForm({ ...form, template_key: v ?? "" })}>
                  <SelectTrigger className="mt-1">
                    <SelectValue placeholder="Blank" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">Blank</SelectItem>
                    {(tplData?.templates ?? [])
                      .filter((t) => t.available)
                      .map((t) => (
                        <SelectItem key={t.template_key} value={t.template_key}>
                          {t.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button
              onClick={handleCreate}
              disabled={!form.name.trim() || createMutation.isPending}
            >
              {createMutation.isPending ? "Creating…" : "Create Dashboard"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DashboardGrid({
  dashboards,
  onOpen,
  onDelete,
  onPatch,
  visibilityColor,
}: {
  dashboards: Dashboard[];
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onPatch: (id: string, body: object) => void;
  visibilityColor: Record<string, string>;
}) {
  if (!dashboards.length) return null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {dashboards.map((d) => (
        <div
          key={d.id}
          className="group relative border rounded-xl p-5 cursor-pointer hover:border-primary/50 hover:shadow-sm transition-all"
          onClick={() => onOpen(d.id)}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                {d.is_default && <Star className="w-3.5 h-3.5 text-amber-500 fill-amber-400 flex-shrink-0" />}
                {d.is_pinned && <Pin className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />}
                <span className="font-medium truncate">{d.name}</span>
              </div>
              {d.description && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{d.description}</p>
              )}
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger
                className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-muted transition-opacity"
                onClick={(e: React.MouseEvent) => e.stopPropagation()}
              >
                <MoreHorizontal className="w-4 h-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent
                sideOffset={4}
                onClick={(e: React.MouseEvent) => e.stopPropagation()}
              >
                <DropdownMenuItem onClick={() => onPatch(d.id, { is_pinned: !d.is_pinned })}>
                  <Pin className="w-3.5 h-3.5 mr-2" />
                  {d.is_pinned ? "Unpin" : "Pin"}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onPatch(d.id, { is_default: true })}>
                  <Star className="w-3.5 h-3.5 mr-2" />
                  Set as default
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onPatch(d.id, { visibility: "shared" })}>
                  <Share2 className="w-3.5 h-3.5 mr-2" />
                  Share
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-destructive"
                  onClick={() => { if (confirm(`Delete "${d.name}"?`)) onDelete(d.id); }}
                >
                  <Trash2 className="w-3.5 h-3.5 mr-2" />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <div className="mt-4 flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${visibilityColor[d.visibility]}`}>
              {d.visibility}
            </span>
            {d.from_template_key && (
              <span className="text-xs text-muted-foreground">from {d.from_template_key}</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            {d.updated_at ? new Date(d.updated_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : ""}
          </p>
        </div>
      ))}
    </div>
  );
}
