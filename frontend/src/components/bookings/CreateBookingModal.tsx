"use client";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Search, Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { formatPhone } from "@/lib/utils";
import type { RWBooking } from "@/lib/rentalwise";

interface GuestSearchResult {
  id: string;
  name: string | null;
  phone: string;
}

interface RatePlan {
  id: string;
  name: string;
  base_price_per_night: number | null;
  min_nights: number;
  max_nights: number | null;
  inclusions: string[];
}

interface BookableProperty {
  id: string;
  name: string;
  type: string;
  price_per_day: number | null;
  rate_plans: RatePlan[];
}

const inputCls = "w-full px-4 py-2.5 rounded-xl text-sm focus:outline-none transition-colors";
const inputStyle = {
  border: "1px solid var(--haip-border)",
  background: "var(--haip-surface)",
  color: "var(--haip-fg)",
};
const focusHandlers = {
  onFocus: (e: React.FocusEvent<HTMLElement>) => {
    e.currentTarget.style.borderColor = "#14B8A6";
    e.currentTarget.style.boxShadow = "0 0 0 2px rgba(20,184,166,0.15)";
  },
  onBlur: (e: React.FocusEvent<HTMLElement>) => {
    e.currentTarget.style.borderColor = "var(--haip-border)";
    e.currentTarget.style.boxShadow = "";
  },
};

export function CreateBookingModal({
  onClose, onCreated, editBooking,
}: {
  onClose: () => void;
  onCreated: () => void;
  /** When set, the modal edits this existing booking instead of creating a new one. */
  editBooking?: RWBooking;
}) {
  const queryClient = useQueryClient();
  const isEditing = !!editBooking;

  // Guest -- either pick an existing one via search, or fill in a new one.
  // Not editable once a booking exists -- who booked it doesn't change.
  const [guestSearch, setGuestSearch] = useState("");
  const [debouncedGuestSearch, setDebouncedGuestSearch] = useState("");
  const [selectedGuest, setSelectedGuest] = useState<GuestSearchResult | null>(
    editBooking?.main_guest
      ? {
          id: String(editBooking.main_guest.id ?? ""),
          name: `${editBooking.main_guest.first_name} ${editBooking.main_guest.last_name}`.trim(),
          phone: editBooking.main_guest.phone || "",
        }
      : null
  );
  const [newGuestName, setNewGuestName] = useState("");
  const [newGuestPhone, setNewGuestPhone] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedGuestSearch(guestSearch), 350);
    return () => clearTimeout(t);
  }, [guestSearch]);

  const { data: guestResults = [], isFetching: searchingGuests } = useQuery<GuestSearchResult[]>({
    queryKey: ["guest-search", debouncedGuestSearch],
    queryFn: () => api.get("/guests", { params: { search: debouncedGuestSearch, limit: 8 } }).then(r => r.data),
    enabled: debouncedGuestSearch.length >= 2 && !selectedGuest,
  });

  const { data: properties = [], isLoading: loadingProperties } = useQuery<BookableProperty[]>({
    queryKey: ["bookable-properties"],
    queryFn: () => api.get("/bookings/properties").then(r => r.data),
  });

  const [propertyId, setPropertyId] = useState(editBooking?.property?.id ? String(editBooking.property.id) : "");
  const [ratePlanId, setRatePlanId] = useState("");
  const [checkIn, setCheckIn] = useState(editBooking?.checkin || "");
  const [checkOut, setCheckOut] = useState(editBooking?.checkout || "");
  const [adults, setAdults] = useState(editBooking?.adults || 2);
  const [children, setChildren] = useState(editBooking?.children || 0);
  const [totalAmount, setTotalAmount] = useState<string>(editBooking?.total ? String(editBooking.total) : "");
  // In edit mode the total already reflects the existing booking, not a
  // package default -- treat it as already "edited" so selecting a package
  // (e.g. while fixing which caravan this booking is on) doesn't silently
  // overwrite a real total with the package's flat price.
  const [totalEdited, setTotalEdited] = useState(isEditing);
  const [occasion, setOccasion] = useState(""); // RWBooking doesn't expose occasion -- edit mode leaves this blank rather than guessing
  const [specialRequests, setSpecialRequests] = useState("");
  const [status, setStatus] = useState<string>(editBooking?.status || "confirmed");

  const selectedProperty = properties.find(p => p.id === propertyId);
  const selectedRatePlan = selectedProperty?.rate_plans.find(rp => rp.id === ratePlanId);

  // Auto-fill total from the chosen rate plan, unless the user has already
  // manually edited the field -- never clobber a deliberate override.
  useEffect(() => {
    if (totalEdited) return;
    if (selectedRatePlan?.base_price_per_night) {
      setTotalAmount(String(selectedRatePlan.base_price_per_night));
    }
  }, [selectedRatePlan, totalEdited]);

  const mutation = useMutation({
    mutationFn: () =>
      isEditing
        ? api.patch(`/bookings/${editBooking!.id}`, {
            property_id: propertyId,
            check_in: checkIn,
            check_out: checkOut,
            adults,
            children,
            total_amount: totalAmount ? Number(totalAmount) : undefined,
            status,
            occasion: occasion || undefined,
            special_requests: specialRequests || undefined,
          })
        : api.post("/bookings", {
            guest_id: selectedGuest?.id || undefined,
            guest_name: selectedGuest ? undefined : (newGuestName || undefined),
            guest_phone: selectedGuest ? undefined : (newGuestPhone || undefined),
            property_id: propertyId,
            rate_plan_id: ratePlanId || undefined,
            check_in: checkIn,
            check_out: checkOut,
            adults,
            children,
            total_amount: totalAmount ? Number(totalAmount) : undefined,
            occasion: occasion || undefined,
            special_requests: specialRequests || undefined,
          }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["local-bookings"] });
      onCreated();
    },
  });

  const guestValid = isEditing || !!selectedGuest || (newGuestName.trim() && newGuestPhone.trim());
  const canSubmit = guestValid && propertyId && checkIn && checkOut && !mutation.isPending;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      {/* maxHeight uses dvh (the height actually visible, URL bar and on-screen
          keyboard excluded) -- 90vh on a phone is taller than the visible
          screen, which pushed the Create Booking button below the fold with
          nothing left to scroll. Browsers without dvh drop the inline value
          and fall back to the 90vh class. */}
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden max-h-[90vh] flex flex-col"
        style={{ border: "1px solid var(--haip-border)", maxHeight: "calc(100dvh - 2rem)" }}
      >
        <div
          className="flex items-center justify-between px-6 py-4 flex-shrink-0"
          style={{ background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}
        >
          <h3 className="font-bold text-[15px]" style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}>
            {isEditing ? `Edit Booking #${editBooking!.external_id ?? editBooking!.id}` : "Create Booking"}
          </h3>
          <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-700">
            <X size={15} />
          </button>
        </div>

        <form
          onSubmit={e => { e.preventDefault(); mutation.mutate(); }}
          className="flex flex-col flex-1 min-h-0"
        >
          <div className="p-6 space-y-4 overflow-y-auto flex-1 min-h-0">
          {/* Guest */}
          <div>
            <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Guest *</label>
            {selectedGuest ? (
              <div className="flex items-center justify-between px-4 py-2.5 rounded-xl text-sm" style={{ border: "1px solid var(--haip-border)", background: "var(--haip-surface)" }}>
                <span>{selectedGuest.name || "Unknown"} · {formatPhone(selectedGuest.phone)}</span>
                {!isEditing && (
                  <button type="button" onClick={() => setSelectedGuest(null)} className="text-xs text-teal-600 font-medium">Change</button>
                )}
              </div>
            ) : (
              <div className="space-y-2">
                <div className="relative">
                  <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    value={guestSearch}
                    onChange={e => setGuestSearch(e.target.value)}
                    placeholder="Search existing guest by name or phone…"
                    className={inputCls + " pl-9"}
                    style={inputStyle}
                    {...focusHandlers}
                  />
                </div>
                {debouncedGuestSearch.length >= 2 && (
                  <div className="rounded-xl overflow-hidden" style={{ border: "1px solid var(--haip-border)" }}>
                    {searchingGuests ? (
                      <div className="px-4 py-2.5 text-xs text-gray-400">Searching…</div>
                    ) : guestResults.length === 0 ? (
                      <div className="px-4 py-2.5 text-xs text-gray-400">No matches — fill in a new guest below</div>
                    ) : (
                      guestResults.map(g => (
                        <button
                          key={g.id}
                          type="button"
                          onClick={() => { setSelectedGuest(g); setGuestSearch(""); }}
                          className="w-full text-left px-4 py-2.5 text-sm hover:bg-gray-50 border-b last:border-b-0"
                          style={{ borderColor: "#F3F4F6" }}
                        >
                          {g.name || "Unknown"} · {formatPhone(g.phone)}
                        </button>
                      ))
                    )}
                  </div>
                )}
                <p className="text-[11px] text-gray-400">— or fill in a new guest —</p>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    value={newGuestName}
                    onChange={e => setNewGuestName(e.target.value)}
                    placeholder="Full name"
                    className={inputCls} style={inputStyle} {...focusHandlers}
                  />
                  <input
                    value={newGuestPhone}
                    onChange={e => setNewGuestPhone(e.target.value)}
                    placeholder="+91XXXXXXXXXX"
                    className={inputCls} style={inputStyle} {...focusHandlers}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Property */}
          <div>
            <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Caravan / Property *</label>
            <select
              required
              value={propertyId}
              onChange={e => { setPropertyId(e.target.value); setRatePlanId(""); setTotalEdited(false); }}
              className={inputCls + " appearance-none cursor-pointer"} style={inputStyle}
            >
              <option value="">{loadingProperties ? "Loading…" : "Select…"}</option>
              {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>

          {/* Rate plan / package */}
          {selectedProperty && selectedProperty.rate_plans.length > 0 && (
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Package</label>
              <select
                value={ratePlanId}
                onChange={e => { setRatePlanId(e.target.value); setTotalEdited(false); }}
                className={inputCls + " appearance-none cursor-pointer"} style={inputStyle}
              >
                <option value="">No specific package</option>
                {selectedProperty.rate_plans.map(rp => (
                  <option key={rp.id} value={rp.id}>
                    {rp.name}{rp.base_price_per_night ? ` — ₹${rp.base_price_per_night.toLocaleString("en-IN")}` : " — price on request"}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Check-in *</label>
              <input type="date" required value={checkIn} onChange={e => setCheckIn(e.target.value)} className={inputCls} style={inputStyle} {...focusHandlers} />
            </div>
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Check-out *</label>
              <input type="date" required value={checkOut} onChange={e => setCheckOut(e.target.value)} className={inputCls} style={inputStyle} {...focusHandlers} />
            </div>
          </div>

          {/* Pax */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Adults</label>
              <input type="number" min={1} value={adults} onChange={e => setAdults(Number(e.target.value))} className={inputCls} style={inputStyle} {...focusHandlers} />
            </div>
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Children</label>
              <input type="number" min={0} value={children} onChange={e => setChildren(Number(e.target.value))} className={inputCls} style={inputStyle} {...focusHandlers} />
            </div>
          </div>

          {/* Total */}
          <div>
            <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>
              Total amount (₹){selectedRatePlan?.base_price_per_night ? " — auto-filled from package, edit if needed" : ""}
            </label>
            <input
              type="number" min={0}
              value={totalAmount}
              onChange={e => { setTotalAmount(e.target.value); setTotalEdited(true); }}
              placeholder="0"
              className={inputCls} style={inputStyle} {...focusHandlers}
            />
          </div>

          {/* Occasion + notes */}
          <div className="grid grid-cols-2 gap-3">
            <input
              value={occasion}
              onChange={e => setOccasion(e.target.value)}
              placeholder="Occasion (optional)"
              className={inputCls} style={inputStyle} {...focusHandlers}
            />
            <input
              value={specialRequests}
              onChange={e => setSpecialRequests(e.target.value)}
              placeholder="Special requests (optional)"
              className={inputCls} style={inputStyle} {...focusHandlers}
            />
          </div>

          {/* Status -- only meaningful once a booking already exists */}
          {isEditing && (
            <div>
              <label className="block text-[12.5px] font-semibold mb-1.5" style={{ color: "var(--haip-fg)" }}>Status</label>
              <select
                value={status}
                onChange={e => setStatus(e.target.value)}
                className={inputCls + " appearance-none cursor-pointer"} style={inputStyle}
              >
                <option value="confirmed">Confirmed</option>
                <option value="checked_in">Checked In</option>
                <option value="checked_out">Checked Out</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>
          )}

          </div>

          {/* Pinned footer: Cancel / Create stay on screen however long the
              form gets, instead of living at the bottom of the scroll area.
              The error sits here too, so a failed save is never off-screen. */}
          <div className="px-6 py-4 flex-shrink-0 space-y-2" style={{ borderTop: "1px solid #E5E7EB", background: "#fff" }}>
          {mutation.isError && (
            <p className="text-xs text-red-600">
              {(mutation.error as any)?.response?.data?.detail || "Failed to save booking. Please check the fields and try again."}
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
              style={{ background: "#0F766E" }}
            >
              {mutation.isPending && <Loader2 size={14} className="animate-spin" />}
              {isEditing ? "Save Changes" : "Create Booking"}
            </button>
          </div>
          </div>
        </form>
      </div>
    </div>
  );
}
