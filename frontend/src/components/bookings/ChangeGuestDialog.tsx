"use client";
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { X } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatPhone } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { errorMessage, type BookingDetail } from "@/lib/bookings";

type Mode = "existing" | "new" | "fix";
const input = "w-full text-sm border border-[var(--haip-border)] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary";

interface GuestHit { id: string; name: string | null; phone: string }

/** Move a booking to another guest, or correct the current guest's name and email. */
export function ChangeGuestDialog({ booking, onClose, onChange }: {
  booking: BookingDetail; onClose: () => void; onChange: (b: BookingDetail) => void;
}) {
  const { toast } = useToast();
  const [mode, setMode] = useState<Mode>("existing");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [picked, setPicked] = useState<GuestHit | null>(null);
  const [phone, setPhone] = useState("");
  const [name, setName] = useState(booking.guest?.name ?? "");
  const [email, setEmail] = useState(booking.guest?.email ?? "");

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data: hits = [] } = useQuery<GuestHit[]>({
    queryKey: ["guest-search", debounced],
    queryFn: () => api.get("/guests", { params: { search: debounced, limit: 8 } }).then(r => r.data),
    enabled: mode === "existing" && debounced.length >= 2,
  });

  const save = useMutation({
    mutationFn: () => {
      if (mode === "existing") return api.patch(`/bookings/${booking.id}/guest`, { guest_id: picked!.id });
      if (mode === "new") return api.patch(`/bookings/${booking.id}/guest`, { phone: phone.trim(), name: name.trim() || undefined });
      return api.patch(`/bookings/${booking.id}/guest`, { name: name.trim(), email: email.trim() });
    },
    onSuccess: res => { onChange(res.data); onClose(); toast({ variant: "success", title: "Guest updated" }); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not update the guest") }),
  });

  const ready = mode === "existing" ? !!picked : mode === "new" ? phone.replace(/\D/g, "").length >= 8 : !!name.trim();
  const tabs: { id: Mode; label: string }[] = [
    { id: "existing", label: "Another guest" }, { id: "new", label: "New by phone" }, { id: "fix", label: "Fix details" },
  ];

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true" aria-label="Change guest">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md max-h-[calc(100dvh-2rem)] overflow-y-auto p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-[var(--haip-fg)]">Change guest</h3>
          <button onClick={onClose} aria-label="Close"><X size={16} className="text-[var(--haip-fg-subtle)]" /></button>
        </div>

        <div className="flex gap-1 p-0.5 bg-[var(--haip-status-neutral-bg)] rounded-lg">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setMode(t.id)}
              className={cn("flex-1 px-2 py-1.5 rounded-md text-xs font-semibold", mode === t.id ? "bg-white shadow-sm text-[var(--haip-fg)]" : "text-[var(--haip-fg-subtle)]")}>{t.label}</button>
          ))}
        </div>

        {mode === "existing" && (
          <div className="space-y-2">
            <input className={input} placeholder="Search name or phone" value={search} onChange={e => { setSearch(e.target.value); setPicked(null); }} autoFocus />
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {debounced.length >= 2 && hits.length === 0 && <p className="text-xs text-[var(--haip-fg-subtle)] px-1">No guests found. Use &ldquo;New by phone&rdquo;.</p>}
              {hits.map(h => (
                <button key={h.id} onClick={() => setPicked(h)}
                  className={cn("w-full text-left text-sm rounded-lg border px-3 py-2", picked?.id === h.id ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)] hover:bg-[var(--haip-surface)]")}>
                  <span className="font-medium">{h.name || "Unnamed"}</span> <span className="text-[var(--haip-fg-subtle)]">{formatPhone(h.phone)}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {mode === "new" && (
          <div className="space-y-2">
            <input className={input} placeholder="Phone, e.g. +91 98765 43210" inputMode="tel" value={phone} onChange={e => setPhone(e.target.value)} autoFocus />
            <input className={input} placeholder="Name" value={name} onChange={e => setName(e.target.value)} />
            <p className="text-xs text-[var(--haip-fg-subtle)]">If a guest with this phone already exists, the booking moves to them instead of creating a duplicate.</p>
          </div>
        )}

        {mode === "fix" && (
          <div className="space-y-2">
            <input className={input} placeholder="Name" value={name} onChange={e => setName(e.target.value)} autoFocus />
            <input className={input} placeholder="Email" type="email" value={email} onChange={e => setEmail(e.target.value)} />
            <p className="text-xs text-[var(--haip-fg-subtle)]">To change the phone number, move the booking to the right guest instead.</p>
          </div>
        )}

        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]">Cancel</button>
          <button onClick={() => save.mutate()} disabled={!ready || save.isPending}
            className="flex-1 py-2.5 bg-primary hover:bg-primary disabled:opacity-40 text-white font-semibold rounded-xl text-sm">
            {save.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
