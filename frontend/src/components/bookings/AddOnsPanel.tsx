"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus, Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { PRICE_TYPE_LABEL, errorMessage, type BookingDetail } from "@/lib/bookings";

const input = "w-full text-sm border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500";

/** Extras sold with the stay: pick from the property's add-on list, or add a one-off item. */
export function AddOnsPanel({ booking, onChange }: { booking: BookingDetail; onChange: (b: BookingDetail) => void }) {
  const { toast } = useToast();
  const base = `/bookings/${booking.id}/addons`;
  const [picker, setPicker] = useState(false);
  const [custom, setCustom] = useState({ name: "", price: "", qty: "1" });

  const run = useMutation({
    mutationFn: (req: () => Promise<{ data: BookingDetail }>) => req(),
    onSuccess: res => onChange(res.data),
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not update add-ons") }),
  });

  const addCatalog = (id: string) => run.mutate(() => api.post(base, { addon_id: id }), { onSuccess: () => setPicker(false) });
  const addCustom = () => {
    const price = Number(custom.price);
    if (!custom.name.trim() || !(price >= 0) || custom.price === "") {
      toast({ variant: "error", title: "Enter a name and a price" });
      return;
    }
    run.mutate(() => api.post(base, { name: custom.name.trim(), unit_price: price, quantity: Math.max(1, Number(custom.qty) || 1) }), {
      onSuccess: () => setCustom({ name: "", price: "", qty: "1" }),
    });
  };

  return (
    <section className="haip-card">
      <div className="haip-card-head">
        <h2 className="haip-card-title">Add-ons</h2>
        <span className="ml-auto text-xs text-gray-400 tabular-nums">{formatINR(booking.financials.addons_total)}</span>
      </div>
      <div className="p-4 space-y-3">
        {booking.addons.length === 0 && <p className="text-sm text-gray-400">No add-ons on this booking yet.</p>}
        {booking.addons.map(a => (
          <div key={a.id} className="flex items-center gap-2 text-sm">
            <div className="min-w-0 flex-1">
              <p className="font-medium text-gray-900 truncate">{a.name}</p>
              <p className="text-xs text-gray-400">{formatINR(a.unit_price)} each</p>
            </div>
            <input
              type="number" min={1} defaultValue={a.quantity} aria-label={`Quantity for ${a.name}`}
              className="w-16 text-sm text-center border border-gray-200 rounded-lg py-1 focus:outline-none focus:ring-2 focus:ring-teal-500"
              onBlur={e => {
                const q = Math.max(1, Number(e.target.value) || 1);
                if (q !== a.quantity) run.mutate(() => api.patch(`${base}/${a.id}`, { quantity: q }));
              }}
            />
            <span className="w-20 text-right tabular-nums font-medium">{formatINR(a.line_total)}</span>
            <button
              aria-label={`Remove ${a.name}`}
              onClick={() => run.mutate(() => api.delete(`${base}/${a.id}`))}
              className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50"
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}

        <div className="pt-2 border-t border-gray-100 space-y-3">
          <div>
            <button onClick={() => setPicker(p => !p)} className="flex items-center gap-1.5 text-xs font-semibold text-teal-700 hover:text-teal-800">
              <Plus size={13} /> Add from {booking.property?.name ?? "property"} list
            </button>
            {picker && (
              <div className="mt-2 grid gap-1.5">
                {booking.available_addons.length === 0 && (
                  <p className="text-xs text-gray-400">This property has no add-ons set up. Add a one-off item below.</p>
                )}
                {booking.available_addons.map(c => (
                  <button
                    key={c.id}
                    onClick={() => addCatalog(c.id)}
                    disabled={run.isPending}
                    className="flex items-center gap-2 text-left text-sm border border-gray-200 rounded-lg px-3 py-2 hover:border-teal-400 hover:bg-teal-50/40 disabled:opacity-50"
                  >
                    <span className="flex-1 min-w-0 truncate">{c.name}</span>
                    <span className="text-xs text-gray-500 tabular-nums">
                      {formatINR(c.price)} {PRICE_TYPE_LABEL[c.price_type] ?? ""}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            <p className="text-xs font-semibold text-gray-500 mb-1.5">One-off item</p>
            <div className="grid grid-cols-[1fr_5.5rem_3.5rem_auto] gap-2 items-center">
              <input className={input} placeholder="e.g. Birthday cake" value={custom.name} onChange={e => setCustom(c => ({ ...c, name: e.target.value }))} aria-label="Item name" />
              <input className={input} placeholder="Price" inputMode="decimal" value={custom.price} onChange={e => setCustom(c => ({ ...c, price: e.target.value.replace(/[^0-9.]/g, "") }))} aria-label="Price" />
              <input className={input} placeholder="Qty" inputMode="numeric" value={custom.qty} onChange={e => setCustom(c => ({ ...c, qty: e.target.value.replace(/\D/g, "") }))} aria-label="Quantity" />
              <button onClick={addCustom} disabled={run.isPending} className="text-xs font-semibold bg-gray-900 text-white px-3 py-2 rounded-lg hover:bg-gray-700 disabled:opacity-50">Add</button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
