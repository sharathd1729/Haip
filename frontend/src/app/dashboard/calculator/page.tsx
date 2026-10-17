"use client";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Calendar, Users, MapPin, Search, ChevronDown, ChevronUp, Send, Copy, Check, Home, Loader2, Plus, Minus, Zap, TrendingUp, TrendingDown, AlertTriangle, Info } from "@/lib/icons";
import { BedDouble, Bath } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AddOn {
  id: string;
  name: string;
  description?: string;
  category: string;
  price: number;
  price_type: string; // per_stay | per_night | per_person
}

interface PropertyResult {
  property_id: string;
  property_name: string;
  property_type: string;
  city: string;
  address: string;
  bedrooms: number;
  bathrooms: number;
  max_adults: number;
  photos: string[];
  available: boolean;
  nights: number;
  guests: number;
  price_per_night: number;
  subtotal_accommodation: number;
  currency: string;
  rate_source: string;
  rate_name: string;
  min_nights: number;
  addons: AddOn[];
  is_caravan: boolean;
  vehicle_name: string;
}

interface DynamicPriceResult {
  property_id: string;
  base_rate: number;
  final_rate: number;
  total_price: number;
  nights: number;
  aggregate_multiplier: number;
  factors: {
    lead_time: number;
    weekend: number;
    occupancy: number;
    duration: number;
  };
  insights: string[];
  suggested_floor: number;
  suggested_ceiling: number;
}

interface QuoteBreakdown {
  property: PropertyResult;
  selected_addons: Array<{ id: string; name: string; category: string; price: number; price_type: string; total: number }>;
  breakdown: {
    subtotal_accommodation: number;
    subtotal_addons: number;
    subtotal: number;
    gst: number;
    total: number;
    advance_percent: number;
    advance_amount: number;
    currency: string;
  };
  whatsapp_message: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

const addonTotal = (a: AddOn, nights: number, guests: number) => {
  if (a.price_type === "per_night") return a.price * nights;
  if (a.price_type === "per_person") return a.price * guests;
  return a.price;
};

const categoryEmoji: Record<string, string> = {
  meal: "🍽️", transfer: "🚗", experience: "✨", stay: "🛏️", other: "📦",
};

// ── Main Component ────────────────────────────────────────────────────────────

export default function CalculatorPage() {
  const { toast } = useToast();

  // Search form
  const [checkin, setCheckin] = useState("");
  const [checkout, setCheckout] = useState("");
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(0);
  const [city, setCity] = useState("");

  // Results
  const [results, setResults] = useState<PropertyResult[]>([]);
  const [selectedProperty, setSelectedProperty] = useState<PropertyResult | null>(null);
  const [selectedAddons, setSelectedAddons] = useState<Set<string>>(new Set());

  // Quote
  const [quote, setQuote] = useState<QuoteBreakdown | null>(null);
  const [guestPhone, setGuestPhone] = useState("");
  const [guestName, setGuestName] = useState("");

  // Dynamic pricing
  const [dynamicPrice, setDynamicPrice] = useState<DynamicPriceResult | null>(null);
  const [showDynamic, setShowDynamic] = useState(false);
  const [occupancyOverride, setOccupancyOverride] = useState(60);
  const [copied, setCopied] = useState(false);

  const nights = checkin && checkout
    ? Math.max(0, (new Date(checkout).getTime() - new Date(checkin).getTime()) / 86400000)
    : 0;

  // Search mutation
  const searchMutation = useMutation({
    mutationFn: () => api.post("/calculator/search", {
      checkin, checkout, adults, children, city: city || undefined,
    }).then(r => r.data),
    onSuccess: (data) => {
      setResults(data);
      setSelectedProperty(null);
      setSelectedAddons(new Set());
      setQuote(null);
      if (data.length === 0) toast({ variant: "default", title: "No properties available for these dates" });
    },
    onError: () => toast({ variant: "error", title: "Search failed" }),
  });

  // Quote mutation
  const quoteMutation = useMutation({
    mutationFn: (propId: string) => api.post("/calculator/quote", {
      property_id: propId,
      checkin, checkout, adults, children,
      selected_addon_ids: Array.from(selectedAddons),
    }).then(r => r.data),
    onSuccess: (data) => setQuote(data),
    onError: () => toast({ variant: "error", title: "Could not build quote" }),
  });

  // Dynamic price mutation
  const dynamicMutation = useMutation({
    mutationFn: () => api.post("/calculator/dynamic-price", {
      property_id: selectedProperty!.property_id,
      checkin, checkout,
      portfolio_occupancy_pct: occupancyOverride,
    }).then(r => r.data as DynamicPriceResult),
    onSuccess: (data) => { setDynamicPrice(data); setShowDynamic(true); },
    onError: () => toast({ variant: "error", title: "Dynamic pricing unavailable" }),
  });

  // Share mutation
  const shareMutation = useMutation({
    mutationFn: () => api.post("/calculator/share", {
      property_id: selectedProperty!.property_id,
      checkin, checkout, adults, children,
      selected_addon_ids: Array.from(selectedAddons),
      guest_phone: guestPhone,
      guest_name: guestName,
    }).then(r => r.data),
    onSuccess: (data) => {
      if (data.status === "sent") {
        toast({ variant: "success", title: "Quote sent on WhatsApp!" });
      } else {
        toast({ variant: "default", title: data.reason || "WhatsApp not connected" });
      }
    },
    onError: () => toast({ variant: "error", title: "Failed to send" }),
  });

  const handleSelectProperty = (p: PropertyResult) => {
    setSelectedProperty(p);
    setSelectedAddons(new Set());
    setQuote(null);
  };

  const toggleAddon = (id: string) => {
    setSelectedAddons(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
    setQuote(null);
  };

  const handleBuildQuote = () => {
    if (!selectedProperty) return;
    quoteMutation.mutate(selectedProperty.property_id);
  };

  const handleCopy = () => {
    if (!quote) return;
    navigator.clipboard.writeText(quote.whatsapp_message);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast({ variant: "success", title: "Quote copied!" });
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-5 py-4 bg-white border-b border-[var(--haip-border)] flex-shrink-0">
        <h1 className="haip-page-title">Rate Calculator</h1>
        <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">Calculate rates and share quotes instantly on WhatsApp</p>
      </div>

      <div className="flex-1 overflow-hidden flex gap-0">

        {/* LEFT — Search + Results */}
        <div className="w-[420px] flex-shrink-0 flex flex-col border-r border-[var(--haip-border)] bg-white overflow-y-auto">

          {/* Search Form */}
          <div className="p-4 border-b border-[var(--haip-border)] space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-medium text-[var(--haip-fg-subtle)] mb-1">Check-in</label>
                <input type="date" value={checkin} onChange={e => setCheckin(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-[var(--haip-border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" />
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--haip-fg-subtle)] mb-1">Check-out</label>
                <input type="date" value={checkout} onChange={e => setCheckout(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-[var(--haip-border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" />
              </div>
            </div>

            {nights > 0 && (
              <p className="text-xs text-primary font-medium">{nights} night{nights > 1 ? "s" : ""}</p>
            )}

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-medium text-[var(--haip-fg-subtle)] mb-1">Adults</label>
                <div className="flex items-center gap-2">
                  <button onClick={() => setAdults(Math.max(1, adults - 1))}
                    className="w-7 h-7 rounded-full border border-[var(--haip-border)] flex items-center justify-center hover:bg-[var(--haip-surface)]">
                    <Minus size={12} />
                  </button>
                  <span className="text-sm font-medium w-4 text-center">{adults}</span>
                  <button onClick={() => setAdults(adults + 1)}
                    className="w-7 h-7 rounded-full border border-[var(--haip-border)] flex items-center justify-center hover:bg-[var(--haip-surface)]">
                    <Plus size={12} />
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--haip-fg-subtle)] mb-1">Children</label>
                <div className="flex items-center gap-2">
                  <button onClick={() => setChildren(Math.max(0, children - 1))}
                    className="w-7 h-7 rounded-full border border-[var(--haip-border)] flex items-center justify-center hover:bg-[var(--haip-surface)]">
                    <Minus size={12} />
                  </button>
                  <span className="text-sm font-medium w-4 text-center">{children}</span>
                  <button onClick={() => setChildren(children + 1)}
                    className="w-7 h-7 rounded-full border border-[var(--haip-border)] flex items-center justify-center hover:bg-[var(--haip-surface)]">
                    <Plus size={12} />
                  </button>
                </div>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-[var(--haip-fg-subtle)] mb-1">Location (optional)</label>
              <input value={city} onChange={e => setCity(e.target.value)}
                placeholder="Goa, Coorg, Manali..."
                className="w-full px-3 py-2 text-sm border border-[var(--haip-border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" />
            </div>

            <button
              onClick={() => searchMutation.mutate()}
              disabled={!checkin || !checkout || searchMutation.isPending}
              className="w-full py-2.5 bg-primary hover:bg-primary disabled:opacity-50 text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2"
            >
              {searchMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
              Search Properties
            </button>
          </div>

          {/* Results */}
          {results.length > 0 && (
            <div className="flex-1 overflow-y-auto">
              <p className="px-4 py-2 text-xs text-[var(--haip-fg-subtle)] font-medium">{results.length} properties available</p>
              {results.map(p => (
                <button key={p.property_id} onClick={() => handleSelectProperty(p)}
                  className={cn(
                    "w-full text-left px-4 py-3 border-b border-[var(--haip-border)] hover:bg-[var(--haip-surface)] transition-colors",
                    selectedProperty?.property_id === p.property_id && "bg-[var(--haip-primary-tint)] border-l-2 border-l-teal-500"
                  )}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-[var(--haip-fg)] truncate">{p.property_name}</p>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-[var(--haip-fg-subtle)]">
                        {p.city && <span className="flex items-center gap-0.5"><MapPin size={10} />{p.city}</span>}
                        <span className="flex items-center gap-0.5"><BedDouble size={10} />{p.bedrooms}bd</span>
                        <span className="flex items-center gap-0.5"><Users size={10} />up to {p.max_adults}</span>
                      </div>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <p className="text-sm font-bold text-primary">{fmt(p.price_per_night)}</p>
                      <p className="text-xs text-[var(--haip-fg-subtle)]">/night</p>
                    </div>
                  </div>
                  <div className="mt-1.5 flex items-center justify-between">
                    <span className="text-xs text-[var(--haip-fg-subtle)]">{p.nights} nights = <span className="font-semibold text-[var(--haip-fg-2)]">{fmt(p.subtotal_accommodation)}</span></span>
                    {p.rate_name && <span className="text-[10px] bg-amber-50 text-amber-600 px-1.5 py-0.5 rounded font-medium">{p.rate_name}</span>}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* RIGHT — Add-ons + Quote */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {!selectedProperty ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-16 h-16 rounded-2xl bg-[var(--haip-primary-tint)] flex items-center justify-center mb-4">
                <Home size={28} className="text-primary" />
              </div>
              <p className="text-[var(--haip-fg-muted)] font-medium">Search and select a property</p>
              <p className="text-[var(--haip-fg-subtle)] text-sm mt-1">Enter dates and guests to see available rates</p>
            </div>
          ) : (
            <>
              {/* Property header */}
              <div className="bg-white rounded-2xl p-4 border border-[var(--haip-border)] shadow-sm">
                <div className="flex items-start justify-between">
                  <div>
                    <h2 className="font-bold text-[var(--haip-fg)]">{selectedProperty.property_name}</h2>
                    <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">{selectedProperty.address || selectedProperty.city}</p>
                    <div className="flex items-center gap-3 mt-2 text-xs text-[var(--haip-fg-subtle)]">
                      <span>{selectedProperty.bedrooms} bed · {selectedProperty.bathrooms} bath · up to {selectedProperty.max_adults} guests</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-bold text-primary">{fmt(selectedProperty.price_per_night)}</p>
                    <p className="text-xs text-[var(--haip-fg-subtle)]">per night</p>
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-[var(--haip-border)] flex items-center justify-between text-sm">
                  <span className="text-[var(--haip-fg-subtle)]">{nights} nights × {fmt(selectedProperty.price_per_night)}</span>
                  <span className="font-bold text-[var(--haip-fg)]">{fmt(selectedProperty.subtotal_accommodation)}</span>
                </div>
              </div>

              {/* Add-ons */}
              {selectedProperty.addons.length > 0 && (
                <div className="bg-white rounded-2xl border border-[var(--haip-border)] shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-[var(--haip-border)]">
                    <h3 className="text-sm font-semibold text-[var(--haip-fg)]">Add-ons & Experiences</h3>
                  </div>
                  <div className="divide-y divide-[var(--haip-border)]">
                    {selectedProperty.addons.map(addon => {
                      const total = addonTotal(addon, nights, adults + children);
                      const isSelected = selectedAddons.has(addon.id);
                      return (
                        <button key={addon.id} onClick={() => toggleAddon(addon.id)}
                          className={cn(
                            "w-full px-4 py-3 flex items-center justify-between hover:bg-[var(--haip-surface)] transition-colors text-left",
                            isSelected && "bg-[var(--haip-primary-tint)]"
                          )}>
                          <div className="flex items-center gap-3">
                            <div className={cn(
                              "w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors",
                              isSelected ? "bg-primary border-primary" : "border-[var(--haip-border-strong)]"
                            )}>
                              {isSelected && <Check size={11} className="text-white" />}
                            </div>
                            <div>
                              <p className="text-sm font-medium text-[var(--haip-fg)]">
                                {categoryEmoji[addon.category] || "•"} {addon.name}
                              </p>
                              {addon.description && (
                                <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">{addon.description}</p>
                              )}
                              <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5 capitalize">{addon.price_type.replace("_", " ")}</p>
                            </div>
                          </div>
                          <div className="text-right flex-shrink-0 ml-3">
                            <p className="text-sm font-semibold text-[var(--haip-fg)]">{fmt(total)}</p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Dynamic Pricing panel */}
              <div className="bg-gradient-to-br from-[var(--haip-primary-tint)] to-blue-50 rounded-2xl border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <Zap size={14} className="text-primary" />
                  <span className="text-sm font-semibold text-[var(--haip-fg)]">Dynamic Pricing</span>
                  <span className="text-[10px] bg-[var(--haip-primary-tint)] text-primary px-1.5 py-0.5 rounded-full font-medium ml-auto">AI-powered</span>
                </div>

                {/* Occupancy slider */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs text-[var(--haip-fg-subtle)]">Portfolio occupancy</label>
                    <span className="text-xs font-bold text-primary tabular-nums">{occupancyOverride}%</span>
                  </div>
                  <input
                    type="range" min={0} max={100} step={5}
                    value={occupancyOverride}
                    onChange={e => { setOccupancyOverride(+e.target.value); setDynamicPrice(null); }}
                    className="w-full accent-primary h-1.5"
                  />
                  <div className="flex justify-between text-[10px] text-[var(--haip-fg-subtle)]/70 mt-0.5">
                    <span>Low demand</span><span>High demand</span>
                  </div>
                </div>

                <button
                  onClick={() => dynamicMutation.mutate()}
                  disabled={!selectedProperty || !checkin || !checkout || dynamicMutation.isPending}
                  className="w-full py-2 bg-primary hover:bg-primary disabled:opacity-40 text-white font-semibold rounded-xl text-sm flex items-center justify-center gap-2 transition-colors"
                >
                  {dynamicMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <TrendingUp size={13} />}
                  Get Smart Rate
                </button>

                {/* Results */}
                {showDynamic && dynamicPrice && (
                  <div className="space-y-2 pt-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-[var(--haip-fg-subtle)]">Base rate / night</span>
                      <span className="text-xs text-[var(--haip-fg-2)] font-medium">{fmt(dynamicPrice.base_rate)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-[var(--haip-fg-subtle)]">Smart rate / night</span>
                      <div className="flex items-center gap-1">
                        {dynamicPrice.final_rate > dynamicPrice.base_rate
                          ? <TrendingUp size={11} className="text-green-500" />
                          : <TrendingDown size={11} className="text-rose-400" />
                        }
                        <span className={cn(
                          "text-sm font-bold",
                          dynamicPrice.final_rate > dynamicPrice.base_rate ? "text-green-600" : "text-rose-500"
                        )}>
                          {fmt(dynamicPrice.final_rate)}
                        </span>
                        <span className="text-[10px] text-[var(--haip-fg-subtle)]">
                          ({dynamicPrice.aggregate_multiplier >= 1 ? "+" : ""}{Math.round((dynamicPrice.aggregate_multiplier - 1) * 100)}%)
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center justify-between border-t border-[color-mix(in_srgb,var(--primary)_25%,transparent)] pt-2">
                      <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Total ({dynamicPrice.nights}n)</span>
                      <span className="text-base font-bold text-primary">{fmt(dynamicPrice.total_price)}</span>
                    </div>

                    {/* Factors breakdown */}
                    <div className="bg-white/70 rounded-xl p-2.5 space-y-1.5">
                      <p className="text-[10px] font-semibold text-[var(--haip-fg-subtle)] uppercase tracking-wider mb-1">Pricing factors</p>
                      {Object.entries(dynamicPrice.factors).map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between">
                          <span className="text-[11px] text-[var(--haip-fg-subtle)] capitalize">{k.replace("_", " ")}</span>
                          <span className={cn(
                            "text-[11px] font-semibold tabular-nums",
                            v > 1 ? "text-green-600" : v < 1 ? "text-rose-500" : "text-[var(--haip-fg-subtle)]"
                          )}>
                            {v > 1 ? "+" : ""}{Math.round((v - 1) * 100)}%
                          </span>
                        </div>
                      ))}
                    </div>

                    {/* Insights */}
                    <div className="space-y-1">
                      {dynamicPrice.insights.map((insight, i) => (
                        <div key={i} className="flex gap-1.5 items-start">
                          <Info size={10} className="text-primary flex-shrink-0 mt-0.5" />
                          <p className="text-[11px] text-[var(--haip-fg-muted)] leading-snug">{insight}</p>
                        </div>
                      ))}
                    </div>

                    {/* Floor / ceiling */}
                    <div className="flex gap-2 text-[10px] text-[var(--haip-fg-subtle)]">
                      <span>Floor: <span className="font-medium text-[var(--haip-fg-subtle)]">{fmt(dynamicPrice.suggested_floor)}</span></span>
                      <span>·</span>
                      <span>Ceiling: <span className="font-medium text-[var(--haip-fg-subtle)]">{fmt(dynamicPrice.suggested_ceiling)}</span></span>
                    </div>
                  </div>
                )}
              </div>

              {/* Build Quote button */}
              <button onClick={handleBuildQuote} disabled={quoteMutation.isPending}
                className="w-full py-3 bg-gray-900 hover:bg-gray-800 disabled:opacity-50 text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2">
                {quoteMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
                Build Quote
              </button>

              {/* Quote Breakdown */}
              {quote && (
                <div className="bg-white rounded-2xl border border-[var(--haip-border)] shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-[var(--haip-border)]">
                    <h3 className="text-sm font-semibold text-[var(--haip-fg)]">Quote Breakdown</h3>
                  </div>
                  <div className="px-4 py-3 space-y-2 text-sm">
                    <div className="flex justify-between text-[var(--haip-fg-muted)]">
                      <span>Accommodation</span>
                      <span>{fmt(quote.breakdown.subtotal_accommodation)}</span>
                    </div>
                    {quote.selected_addons.map(a => (
                      <div key={a.id} className="flex justify-between text-[var(--haip-fg-muted)]">
                        <span>{a.name}</span>
                        <span>{fmt(a.total)}</span>
                      </div>
                    ))}
                    <div className="flex justify-between text-[var(--haip-fg-subtle)] pt-2 border-t border-[var(--haip-border)]">
                      <span>GST (12%)</span>
                      <span>{fmt(quote.breakdown.gst)}</span>
                    </div>
                    <div className="flex justify-between font-bold text-[var(--haip-fg)] text-base pt-1">
                      <span>Total</span>
                      <span className="text-primary">{fmt(quote.breakdown.total)}</span>
                    </div>
                    <div className="flex justify-between text-[var(--haip-fg-muted)] bg-amber-50 rounded-lg px-3 py-2 mt-2">
                      <span className="font-medium">Advance ({quote.breakdown.advance_percent}%)</span>
                      <span className="font-bold">{fmt(quote.breakdown.advance_amount)}</span>
                    </div>
                  </div>

                  {/* Share section */}
                  <div className="px-4 pb-4 pt-2 space-y-3 border-t border-[var(--haip-border)]">
                    <p className="text-xs font-medium text-[var(--haip-fg-subtle)] uppercase tracking-wide">Send on WhatsApp</p>
                    <div className="grid grid-cols-2 gap-2">
                      <input value={guestName} onChange={e => setGuestName(e.target.value)}
                        placeholder="Guest name"
                        className="px-3 py-2 text-sm border border-[var(--haip-border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" />
                      <input value={guestPhone} onChange={e => setGuestPhone(e.target.value)}
                        placeholder="+91 98765 43210"
                        className="px-3 py-2 text-sm border border-[var(--haip-border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" />
                    </div>
                    <div className="flex gap-2">
                      <button onClick={handleCopy}
                        className="flex-1 py-2.5 border border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)] rounded-xl text-sm font-medium flex items-center justify-center gap-2 transition-colors">
                        {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                        {copied ? "Copied!" : "Copy"}
                      </button>
                      <button
                        onClick={() => shareMutation.mutate()}
                        disabled={!guestPhone || shareMutation.isPending}
                        className="flex-1 py-2.5 bg-green-500 hover:bg-green-600 disabled:opacity-50 text-white rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-colors">
                        {shareMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        Send on WhatsApp
                      </button>
                    </div>

                    {/* Message preview */}
                    <div className="bg-[var(--haip-surface)] rounded-xl p-3">
                      <p className="text-xs text-[var(--haip-fg-subtle)] font-medium mb-2">Preview</p>
                      <pre className="text-xs text-[var(--haip-fg-muted)] whitespace-pre-wrap font-sans leading-relaxed">
                        {quote.whatsapp_message}
                      </pre>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
