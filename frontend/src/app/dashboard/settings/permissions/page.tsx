"use client";
import { Fragment, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Lock, Loader2, AlertCircle, CheckCircle2, X, Save } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface CapabilityOut {
  key: string;
  label: string;
  category: string;
  is_write: boolean;
  risk: string;
}

interface RoleCapabilityEntry {
  role: string;
  capability_key: string;
  allowed: boolean;
}

const ROLES = [
  "owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only",
] as const;

const ROLE_LABELS: Record<string, string> = {
  owner: "Owner", manager: "Manager", reservations: "Reservations", concierge: "Concierge",
  foh: "Front of House", marketing: "Marketing", compliance: "Compliance", read_only: "Read Only",
};

function Toast({ msg, type, onDismiss }: { msg: string; type: "success" | "error"; onDismiss: () => void }) {
  return (
    <div className={cn(
      "fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg text-sm font-medium",
      type === "success" ? "bg-teal-600 text-white" : "bg-red-600 text-white"
    )}>
      {type === "success" ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
      {msg}
      <button onClick={onDismiss}><X size={13} className="opacity-60 hover:opacity-100" /></button>
    </div>
  );
}

export default function PermissionsPage() {
  const { data: session } = useSession();
  const queryClient = useQueryClient();
  const isOwner = session?.user?.role === "owner";

  const [pending, setPending] = useState<Map<string, boolean>>(new Map());
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: catalogue = [], isLoading: catalogueLoading } = useQuery<CapabilityOut[]>({
    queryKey: ["capabilities-catalogue"],
    queryFn: () => api.get("/capabilities").then(r => r.data),
    enabled: isOwner,
    staleTime: 300_000,
  });

  const { data: matrix, isLoading: matrixLoading, error: matrixError } = useQuery<{ entries: RoleCapabilityEntry[] }>({
    queryKey: ["capabilities-matrix"],
    queryFn: () => api.get("/capabilities/matrix").then(r => r.data),
    enabled: isOwner,
    staleTime: 30_000,
  });

  const allowedMap = useMemo(() => {
    const m = new Map<string, boolean>();
    for (const e of matrix?.entries ?? []) m.set(`${e.role}:${e.capability_key}`, e.allowed);
    return m;
  }, [matrix]);

  const byCategory = useMemo(() => {
    const groups = new Map<string, CapabilityOut[]>();
    for (const cap of catalogue) {
      if (!groups.has(cap.category)) groups.set(cap.category, []);
      groups.get(cap.category)!.push(cap);
    }
    return groups;
  }, [catalogue]);

  const isChecked = (role: string, key: string): boolean => {
    const cellKey = `${role}:${key}`;
    return pending.has(cellKey) ? pending.get(cellKey)! : (allowedMap.get(cellKey) ?? false);
  };

  const toggle = (role: string, key: string) => {
    // Owner's own leads.read/write etc. are still editable in principle, but
    // MCP access itself (Phase 0) and every REST endpoint assume owner has
    // full access -- don't let this UI create a state where the owner locks
    // themselves out.
    if (role === "owner") return;
    const cellKey = `${role}:${key}`;
    setPending(prev => {
      const next = new Map(prev);
      const current = isChecked(role, key);
      next.set(cellKey, !current);
      return next;
    });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const edits = Array.from(pending.entries()).map(([cellKey, allowed]) => {
        const [role, capability_key] = cellKey.split(":");
        return { role, capability_key, allowed };
      });
      return api.put("/capabilities/matrix", { edits });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["capabilities-matrix"] });
      setPending(new Map());
      showToast("Permissions updated.", "success");
    },
    onError: () => showToast("Failed to save changes.", "error"),
  });

  if (!isOwner) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <Lock size={28} className="text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-500">Only the workspace owner can view Roles &amp; Permissions.</p>
        </div>
      </div>
    );
  }

  const loading = catalogueLoading || matrixLoading;

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-50 flex items-center justify-center">
              <Lock size={18} className="text-teal-600" />
            </div>
            <div>
              <h1 className="haip-page-title">Roles &amp; Permissions</h1>
              <p className="text-sm text-gray-400 mt-0.5">
                What each role can read or change -- also gates what MCP tokens for that role can do.
              </p>
            </div>
          </div>
          {pending.size > 0 && (
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="flex items-center gap-2 px-4 py-2.5 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Save {pending.size} change{pending.size === 1 ? "" : "s"}
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto px-6 py-6">
        {loading ? (
          <p className="text-sm text-gray-400">Loading...</p>
        ) : matrixError ? (
          <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 rounded-lg px-4 py-3 max-w-lg">
            <AlertCircle size={15} /> Couldn't load the permission matrix. It may not be provisioned for this workspace yet -- contact support.
          </div>
        ) : (
          <table className="min-w-full border-separate border-spacing-0">
            <thead>
              <tr>
                <th className="text-left text-xs font-semibold text-gray-500 sticky left-0 bg-[var(--haip-bg,white)] pb-2 pr-4 min-w-[220px]">
                  Capability
                </th>
                {ROLES.map(role => (
                  <th key={role} className="text-center text-xs font-semibold text-gray-500 pb-2 px-3 min-w-[92px]">
                    {ROLE_LABELS[role]}
                    {role === "owner" && <span className="block text-[9px] font-normal text-gray-300">always full</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from(byCategory.entries()).map(([category, caps]) => (
                <Fragment key={category}>
                  <tr>
                    <td colSpan={ROLES.length + 1} className="pt-4 pb-1.5 text-[10px] font-bold uppercase tracking-wide text-gray-400">
                      {category}
                    </td>
                  </tr>
                  {caps.map(cap => (
                    <tr key={cap.key} className="group">
                      <td className="text-sm text-gray-700 py-2 pr-4 sticky left-0 bg-[var(--haip-bg,white)]">
                        <div className="flex items-center gap-1.5">
                          {cap.label}
                          {cap.is_write && (
                            <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700">write</span>
                          )}
                          {cap.risk === "high" && (
                            <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-red-50 text-red-700">sensitive</span>
                          )}
                        </div>
                      </td>
                      {ROLES.map(role => {
                        const checked = isChecked(role, cap.key);
                        const isDirty = pending.has(`${role}:${cap.key}`);
                        const disabled = role === "owner";
                        return (
                          <td key={role} className="text-center py-2 px-3">
                            <input
                              type="checkbox"
                              checked={role === "owner" ? true : checked}
                              disabled={disabled}
                              onChange={() => toggle(role, cap.key)}
                              className={cn(
                                "w-4 h-4 rounded accent-teal-500 cursor-pointer",
                                disabled && "opacity-40 cursor-not-allowed",
                                isDirty && "ring-2 ring-amber-400 ring-offset-1"
                              )}
                            />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {toast && <Toast msg={toast.msg} type={toast.type} onDismiss={() => setToast(null)} />}
    </div>
  );
}
