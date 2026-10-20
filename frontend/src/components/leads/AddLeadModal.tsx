"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Loader2 } from "@/lib/icons";
import api from "@/lib/api";

interface BookableProperty {
  id: string;
  name: string;
}

const SOURCE_OPTIONS = [
  { value: "walk_in",     label: "Walk-in" },
  { value: "phone",       label: "Phone" },
  { value: "referral",    label: "Referral" },
  { value: "travel_agent",label: "Travel agent" },
  { value: "website",     label: "Website" },
  { value: "google",      label: "Google" },
];

const inputCls = "w-full px-4 py-2.5 rounded-xl text-sm focus:outline-none transition-colors";
const inputStyle = {
  border: "1px solid var(--haip-border)",
  background: "var(--haip-surface)",
  color: "var(--haip-fg)",
};
const focusHandlers = {
  onFocus: (e: React.FocusEvent<HTMLElement>) => {
    e.currentTarget.style.borderColor = "var(--primary)";
    e.currentTarget.style.boxShadow = "0 0 0 2px var(--haip-primary-tint)";
  },
  onBlur: (e: React.FocusEvent<HTMLElement>) => {
    e.currentTarget.style.borderColor = "var(--haip-border)";
    e.currentTarget.style.boxShadow = "";
  },
};

export function AddLeadModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const queryClient = useQueryClient();

  const [guestName, setGuestName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [source, setSource] = useState("walk_in");
  const [propertyId, setPropertyId] = useState("");
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [adults, setAdults] = useState<string>("");
  const [children, setChildren] = useState<string>("");
  const [occasion, setOccasion] = useState("");
  const [budget, setBudget] = useState("");

  const { data: properties = [] } = useQuery<BookableProperty[]>({
    queryKey: ["bookable-properties"],
    queryFn: () => api.get("/bookings/properties").then(r => r.data),
  });

  const mutation = useMutation({
    mutationFn: () =>
      api.post("/leads", {
        guest_name: guestName.trim(),
        phone: phone.trim() || undefined,
        email: email.trim() || undefined,
        source,
        property_id: propertyId || undefined,
        check_in: checkIn || undefined,
        check_out: checkOut || undefined,
        adults: adults ? Number(adults) : undefined,
        children: children ? Number(children) : undefined,
        occasion: occasion.trim() || undefined,
        budget: budget ? Number(budget) : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      onCreated();
    },
  });

  const canSubmit = guestName.trim().length > 0 && (phone.trim() || email.trim()) && !mutation.isPending;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      {/* maxHeight uses dvh (the height actually visible, URL bar and on-screen
          keyboard excluded) -- 90vh on a phone is taller than the visible
          screen, which pushed the Add Lead button below the fold with nothing
          left to scroll. Browsers without dvh drop the inline value and fall
          back to the 90vh class. Same fix as CreateBookingModal. */}
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden max-h-[90vh] flex flex-col"
        style={{ border: "1px solid var(--haip-border)", maxHeight: "calc(100dvh - 2rem)" }}
      >
        <div
          className="flex items-center justify-between px-6 py-4 flex-shrink-0"
          style={{ background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}
        >
          <h3 className="font-bold text-[15px]" style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}>
            Add Lead
          </h3>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-2)]">
            <X size={15} />
          </button>
        </div>

        <form
          onSubmit={e => { e.preventDefault(); mutation.mutate(); }}
          className="flex flex-col flex-1 min-h-0"
        >
          <div className="p-6 space-y-4 overflow-y-auto flex-1 min-h-0">
          <div>
            <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Guest name *</label>
            <input
              required
              value={guestName}
              onChange={e => setGuestName(e.target.value)}
              placeholder="Full name"
              className={inputCls} style={inputStyle} {...focusHandlers}
            />
          </div>

          <div>
            <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>
              Phone or email *
            </label>
            <div className="grid grid-cols-2 gap-2">
              <input
                value={phone}
                onChange={e => setPhone(e.target.value)}
                placeholder="+91XXXXXXXXXX"
                className={inputCls} style={inputStyle} {...focusHandlers}
              />
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="guest@email.com"
                className={inputCls} style={inputStyle} {...focusHandlers}
              />
            </div>
            <p className="text-[11px] mt-1" style={{ color: "var(--haip-fg-subtle)" }}>
              At least one — used to find or create the guest's profile.
            </p>
          </div>

          <div>
            <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Source</label>
            <select
              value={source}
              onChange={e => setSource(e.target.value)}
              className={inputCls + " appearance-none cursor-pointer"} style={inputStyle}
            >
              {SOURCE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Property (optional)</label>
            <select
              value={propertyId}
              onChange={e => setPropertyId(e.target.value)}
              className={inputCls + " appearance-none cursor-pointer"} style={inputStyle}
            >
              <option value="">No specific property yet</option>
              {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Check-in</label>
              <input type="date" value={checkIn} onChange={e => setCheckIn(e.target.value)} className={inputCls} style={inputStyle} {...focusHandlers} />
            </div>
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Check-out</label>
              <input type="date" value={checkOut} onChange={e => setCheckOut(e.target.value)} className={inputCls} style={inputStyle} {...focusHandlers} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Adults</label>
              <input type="number" min={0} value={adults} onChange={e => setAdults(e.target.value)} className={inputCls} style={inputStyle} {...focusHandlers} />
            </div>
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Children</label>
              <input type="number" min={0} value={children} onChange={e => setChildren(e.target.value)} className={inputCls} style={inputStyle} {...focusHandlers} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <input
              value={occasion}
              onChange={e => setOccasion(e.target.value)}
              placeholder="Occasion (optional)"
              className={inputCls} style={inputStyle} {...focusHandlers}
            />
            <input
              type="number" min={0}
              value={budget}
              onChange={e => setBudget(e.target.value)}
              placeholder="Budget ₹ (optional)"
              className={inputCls} style={inputStyle} {...focusHandlers}
            />
          </div>

          </div>

          {/* Pinned footer: Cancel / Add Lead stay on screen however long the
              form gets. The error sits here too, so a failed save is never
              scrolled out of view. */}
          <div className="px-6 py-4 flex-shrink-0 space-y-2" style={{ borderTop: "1px solid #E5E7EB", background: "#fff" }}>
          {mutation.isError && (
            <p className="text-xs text-red-600">
              {(mutation.error as any)?.response?.data?.detail || "Failed to add lead. Please check the fields and try again."}
            </p>
          )}
          <div className="flex gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2.5 rounded-xl text-sm font-medium transition-colors"
              style={{ border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white transition-colors disabled:opacity-40 flex items-center justify-center gap-2"
              style={{ background: "var(--primary)" }}
            >
              {mutation.isPending && <Loader2 size={14} className="animate-spin" />}
              Add Lead
            </button>
          </div>
          </div>
        </form>
      </div>
    </div>
  );
}
