"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import {
  Home, Building2, UmbrellaOff, Car, Globe, HelpCircle,
  MessageSquare, Phone, Users, ArrowRight, ArrowLeft,
  CheckCircle2, Sparkles, Loader2, Check, X, Upload,
  Mic, Zap, Shield, ToggleLeft, Bell, ChevronRight, Plus,
  Truck, Key, RefreshCw,
} from "lucide-react";

// ─── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 9;

const SEGMENTS = [
  { id: "villa",            icon: <Home size={20} />,        label: "Luxury Villa" },
  { id: "resort",           icon: <UmbrellaOff size={20} />, label: "Resort" },
  { id: "hotel",            icon: <Building2 size={20} />,   label: "Boutique Hotel" },
  { id: "rental_apartment", icon: <Key size={20} />,         label: "Rental / Airbnb" },
  { id: "travel",           icon: <Globe size={20} />,       label: "Travel Operator" },
  { id: "caravan",          icon: <Truck size={20} />,       label: "Caravan / Glamping" },
  { id: "other",            icon: <HelpCircle size={20} />,  label: "Other" },
];

const PLANS = [
  { id: "starter", label: "Starter", price: "₹3,999/mo", desc: "1 property, up to 500 calls" },
  { id: "growth",  label: "Growth",  price: "₹6,999/mo", desc: "5 properties, 2,000 calls" },
  { id: "pro",     label: "Pro",     price: "₹9,999/mo", desc: "Unlimited properties" },
];

// O3 — IVR providers ranked by Indian market share with help links
const IVR_PROVIDERS = [
  { id: "acefone",    label: "Acefone",       desc: "Most widely used for Indian hospitality — virtual numbers, IVR, call recording", badge: "Popular" },
  { id: "callerdesk", label: "CallerDesk",    desc: "Simple API, quick setup, good for smaller operations" },
  { id: "myoperator", label: "MyOperator",    desc: "Enterprise call management — contact sales for API access", badge: "Enterprise" },
  { id: "skip",       label: "Set up later",  desc: "You can connect an IVR provider from Settings → Integrations" },
];

// O3 — Channel managers ranked by Indian market share with help links
const CHANNEL_MANAGERS = [
  { id: "hostaway",   label: "Hostaway",        desc: "Account ID + API Secret — top OTA channel manager" },
  { id: "cloudbeds",  label: "Cloudbeds",        desc: "Property Management System + channel manager", badge: "Coming soon" },
  { id: "ezee",       label: "eZee Centrix",     desc: "Popular in Indian hotels — API key required", badge: "Coming soon" },
  { id: "retalwise",  label: "RentalWise",       desc: "Username + password + API URL" },
  { id: "manual",     label: "Add manually",     desc: "Enter properties by hand — no PMS needed" },
];

const VEHICLE_TYPES = [
  { id: "luxury_caravan", label: "Luxury Caravan" },
  { id: "campervan",      label: "Campervan" },
  { id: "glamping_pod",   label: "Glamping Pod / Tent" },
  { id: "sleeper_bus",    label: "Sleeper Bus" },
  { id: "other",          label: "Other" },
];

const ROOM_TYPES = [
  { id: "standard",  label: "Standard" },
  { id: "deluxe",    label: "Deluxe" },
  { id: "suite",     label: "Suite" },
  { id: "penthouse", label: "Penthouse" },
  { id: "dormitory", label: "Dormitory" },
];

// ─── Types ────────────────────────────────────────────────────────────────────

interface StandardProperty { name: string; type: string; city: string; }
interface CaravanVehicle {
  vehicle_name: string; vehicle_type: string; home_base: string;
  seats: string; price_per_day: string; driver_included: boolean;
}
interface HotelProperty { name: string; city: string; }
interface HotelRoom { room_number: string; room_type: string; floor: string; capacity: string; }

// ─── Shared components ────────────────────────────────────────────────────────

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} className={cn(
          "h-1 rounded-full transition-all duration-300",
          i < current ? "bg-teal-500 w-6" : i === current ? "bg-teal-500/70 w-10" : "bg-white/10 w-6"
        )} />
      ))}
    </div>
  );
}

// O1 — Prominent "Set up later" button for optional steps (4-9)
function SetupLaterButton({ onSkip, label = "Set up later" }: { onSkip: () => void; label?: string }) {
  return (
    <button
      onClick={onSkip}
      className="w-full py-2.5 rounded-2xl border border-white/10 text-white/40 hover:text-white/70 hover:border-white/20 text-xs font-medium transition-all flex items-center justify-center gap-1.5"
    >
      {label} — I&apos;ll finish this from Settings
    </button>
  );
}

// Legacy alias kept for backward-compat within this file
function SkipButton({ onSkip }: { onSkip: () => void }) {
  return <SetupLaterButton onSkip={onSkip} />;
}

// O4 — Inline field error hint
function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null;
  return <p className="text-xs text-red-400 mt-1 flex items-center gap-1"><X size={10} />{msg}</p>;
}

function BackButton({ onBack }: { onBack: () => void }) {
  return (
    <button onClick={onBack}
      className="flex items-center gap-1.5 text-xs text-white/30 hover:text-white/60 mb-6 transition-colors">
      <ArrowLeft size={14} /> Back
    </button>
  );
}

function ContinueButton({ label = "Continue", disabled = false, loading = false, onClick }: {
  label?: string; disabled?: boolean; loading?: boolean; onClick?: () => void;
}) {
  return (
    <button onClick={onClick} disabled={disabled || loading}
      type={onClick ? "button" : "submit"}
      className="w-full py-3.5 bg-teal-500 hover:bg-teal-400 disabled:opacity-40 text-white font-bold rounded-2xl transition-all flex items-center justify-center gap-2">
      {loading ? <Loader2 size={18} className="animate-spin" /> : null}
      {label} {!loading && <ArrowRight size={18} />}
    </button>
  );
}

function FieldInput({ label, value, onChange, placeholder, type = "text", required = false }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; required?: boolean;
}) {
  return (
    <div>
      <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">
        {label} {required && <span className="text-red-400">*</span>}
      </label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
    </div>
  );
}

// ─── Step 2 variants ──────────────────────────────────────────────────────────

// Standard (villa / resort / travel / other)
function StandardPropertyStep({
  properties, setProperties, saving, onSubmit,
}: {
  properties: StandardProperty[];
  setProperties: (p: StandardProperty[]) => void;
  saving: boolean;
  onSubmit: () => void;
}) {
  const update = (idx: number, field: keyof StandardProperty, value: string) =>
    setProperties(properties.map((p, i) => i === idx ? { ...p, [field]: value } : p));

  return (
    <>
      <h2 className="text-2xl font-black text-white mb-1">Add your properties</h2>
      <p className="text-white/40 text-sm mb-7">Add at least one property to continue.</p>

      <div className="space-y-4 mb-6">
        {properties.map((prop, idx) => (
          <div key={idx} className="bg-white/3 border border-white/8 rounded-2xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-white/50 uppercase tracking-wider">Property {idx + 1}</span>
              {properties.length > 1 && (
                <button onClick={() => setProperties(properties.filter((_, i) => i !== idx))}
                  className="text-white/20 hover:text-red-400 transition-colors"><X size={14} /></button>
              )}
            </div>
            <input value={prop.name} onChange={e => update(idx, "name", e.target.value)}
              placeholder="Property name (e.g. Jade Beach Villa)"
              className="w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
            <div className="grid grid-cols-2 gap-2">
              <select value={prop.type} onChange={e => update(idx, "type", e.target.value)}
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:border-teal-500/50 transition-all">
                {["villa", "resort", "apartment", "hostel", "camp", "other"].map(t => (
                  <option key={t} value={t} className="bg-[#0f2744]">{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                ))}
              </select>
              <input value={prop.city} onChange={e => update(idx, "city", e.target.value)}
                placeholder="City"
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
            </div>
          </div>
        ))}
        <button
          onClick={() => setProperties([...properties, { name: "", type: "villa", city: "" }])}
          className="w-full py-3 border border-dashed border-white/15 rounded-2xl text-sm text-white/40 hover:text-white/60 hover:border-white/25 transition-all flex items-center justify-center gap-2">
          <Plus size={14} /> Add another property
        </button>
      </div>

      <ContinueButton
        disabled={!properties.some(p => p.name.trim() && p.city.trim())}
        loading={saving}
        onClick={onSubmit}
      />
    </>
  );
}

// Caravan / glamping
function CaravanStep({
  vehicles, setVehicles, saving, onSubmit,
}: {
  vehicles: CaravanVehicle[];
  setVehicles: (v: CaravanVehicle[]) => void;
  saving: boolean;
  onSubmit: () => void;
}) {
  const update = (idx: number, field: keyof CaravanVehicle, value: string | boolean) =>
    setVehicles(vehicles.map((v, i) => i === idx ? { ...v, [field]: value } : v));

  const emptyVehicle: CaravanVehicle = {
    vehicle_name: "", vehicle_type: "luxury_caravan", home_base: "",
    seats: "4", price_per_day: "", driver_included: true,
  };

  return (
    <>
      <h2 className="text-2xl font-black text-white mb-1">Add your vehicles</h2>
      <p className="text-white/40 text-sm mb-7">
        Each caravan, van, or glamping unit is a separate vehicle in HAIP.
      </p>

      <div className="space-y-5 mb-6">
        {vehicles.map((v, idx) => (
          <div key={idx} className="bg-white/3 border border-white/8 rounded-2xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-white/50 uppercase tracking-wider">Vehicle {idx + 1}</span>
              {vehicles.length > 1 && (
                <button onClick={() => setVehicles(vehicles.filter((_, i) => i !== idx))}
                  className="text-white/20 hover:text-red-400 transition-colors"><X size={14} /></button>
              )}
            </div>

            <input value={v.vehicle_name} onChange={e => update(idx, "vehicle_name", e.target.value)}
              placeholder="Vehicle name (e.g. Ratha Caravan #1)"
              className="w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />

            <div className="grid grid-cols-2 gap-2">
              <select value={v.vehicle_type} onChange={e => update(idx, "vehicle_type", e.target.value)}
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:border-teal-500/50 transition-all">
                {VEHICLE_TYPES.map(t => (
                  <option key={t.id} value={t.id} className="bg-[#0f2744]">{t.label}</option>
                ))}
              </select>
              <input value={v.home_base} onChange={e => update(idx, "home_base", e.target.value)}
                placeholder="Home base city"
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30 text-xs">₹</span>
                <input type="number" value={v.price_per_day} onChange={e => update(idx, "price_per_day", e.target.value)}
                  placeholder="Price / day"
                  className="w-full pl-6 pr-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
              </div>
              <input type="number" value={v.seats} onChange={e => update(idx, "seats", e.target.value)}
                placeholder="Seats / capacity"
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
            </div>

            <label className="flex items-center gap-2.5 cursor-pointer">
              <input type="checkbox" checked={v.driver_included}
                onChange={e => update(idx, "driver_included", e.target.checked)}
                className="w-4 h-4 rounded border-white/20 text-teal-500" />
              <span className="text-xs text-white/60">Driver included in price</span>
            </label>
          </div>
        ))}

        <button onClick={() => setVehicles([...vehicles, emptyVehicle])}
          className="w-full py-3 border border-dashed border-white/15 rounded-2xl text-sm text-white/40 hover:text-white/60 hover:border-white/25 transition-all flex items-center justify-center gap-2">
          <Plus size={14} /> Add another vehicle
        </button>
      </div>

      <ContinueButton
        disabled={!vehicles.some(v => v.vehicle_name.trim() && v.home_base.trim())}
        loading={saving}
        onClick={onSubmit}
      />
    </>
  );
}

// Hotel with rooms
function HotelStep({
  hotel, setHotel, rooms, setRooms, saving, onSubmit,
}: {
  hotel: HotelProperty;
  setHotel: (h: HotelProperty) => void;
  rooms: HotelRoom[];
  setRooms: (r: HotelRoom[]) => void;
  saving: boolean;
  onSubmit: () => void;
}) {
  const updateRoom = (idx: number, field: keyof HotelRoom, value: string) =>
    setRooms(rooms.map((r, i) => i === idx ? { ...r, [field]: value } : r));

  const emptyRoom: HotelRoom = { room_number: "", room_type: "standard", floor: "", capacity: "2" };

  return (
    <>
      <h2 className="text-2xl font-black text-white mb-1">Your hotel & rooms</h2>
      <p className="text-white/40 text-sm mb-7">
        Add your property and at least one room type to continue.
      </p>

      {/* Hotel property */}
      <div className="bg-white/3 border border-white/8 rounded-2xl p-4 space-y-3 mb-4">
        <span className="text-xs font-bold text-white/50 uppercase tracking-wider">Hotel details</span>
        <input value={hotel.name} onChange={e => setHotel({ ...hotel, name: e.target.value })}
          placeholder="Hotel name (e.g. The Sapphire Boutique)"
          className="w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
        <input value={hotel.city} onChange={e => setHotel({ ...hotel, city: e.target.value })}
          placeholder="City"
          className="w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
      </div>

      {/* Rooms */}
      <div className="space-y-3 mb-4">
        <span className="text-xs font-bold text-white/50 uppercase tracking-wider block">Rooms</span>
        {rooms.map((r, idx) => (
          <div key={idx} className="bg-white/3 border border-white/8 rounded-2xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-white/40">Room {idx + 1}</span>
              {rooms.length > 1 && (
                <button onClick={() => setRooms(rooms.filter((_, i) => i !== idx))}
                  className="text-white/20 hover:text-red-400 transition-colors"><X size={14} /></button>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input value={r.room_number} onChange={e => updateRoom(idx, "room_number", e.target.value)}
                placeholder="Room no. / name (101)"
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
              <select value={r.room_type} onChange={e => updateRoom(idx, "room_type", e.target.value)}
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white focus:outline-none focus:border-teal-500/50 transition-all">
                {ROOM_TYPES.map(t => (
                  <option key={t.id} value={t.id} className="bg-[#0f2744]">{t.label}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input type="number" value={r.floor} onChange={e => updateRoom(idx, "floor", e.target.value)}
                placeholder="Floor (optional)"
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
              <input type="number" value={r.capacity} onChange={e => updateRoom(idx, "capacity", e.target.value)}
                placeholder="Capacity (guests)"
                className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
            </div>
          </div>
        ))}
        <button onClick={() => setRooms([...rooms, emptyRoom])}
          className="w-full py-3 border border-dashed border-white/15 rounded-2xl text-sm text-white/40 hover:text-white/60 hover:border-white/25 transition-all flex items-center justify-center gap-2">
          <Plus size={14} /> Add another room
        </button>
      </div>

      <ContinueButton
        disabled={!hotel.name.trim() || !hotel.city.trim() || !rooms.some(r => r.room_number.trim())}
        loading={saving}
        onClick={onSubmit}
      />
    </>
  );
}

// Rental apartment — channel manager first
function RentalApartmentStep({
  channelManager, setChannelManager,
  cmCredentials, setCmCredentials,
  syncStatus, setSyncStatus,
  saving, onSubmit,
}: {
  channelManager: string;
  setChannelManager: (v: string) => void;
  cmCredentials: Record<string, string>;
  setCmCredentials: (v: Record<string, string>) => void;
  syncStatus: "idle" | "syncing" | "done" | "error";
  setSyncStatus: (s: "idle" | "syncing" | "done" | "error") => void;
  saving: boolean;
  onSubmit: () => void;
}) {
  const handleConnect = async () => {
    if (channelManager === "manual") { onSubmit(); return; }
    setSyncStatus("syncing");
    try {
      if (channelManager === "retalwise") {
        await api.post("/integrations/retalwise/connect-key", cmCredentials);
      } else if (channelManager === "hostaway") {
        await api.post("/integrations/hostaway/connect-key", cmCredentials);
      }
      setSyncStatus("done");
    } catch {
      setSyncStatus("error");
    }
  };

  const creds = channelManager === "retalwise"
    ? [
        { key: "username", label: "Username", placeholder: "your@rentalwise.com" },
        { key: "password", label: "Password", placeholder: "••••••••", type: "password" },
        { key: "base_url", label: "API URL (optional)", placeholder: "https://partners-api.rentalwise.com" },
      ]
    : channelManager === "hostaway"
    ? [
        { key: "account_id", label: "Account ID", placeholder: "12345" },
        { key: "api_secret", label: "API Secret", placeholder: "hs_live_..." },
      ]
    : [];

  return (
    <>
      <h2 className="text-2xl font-black text-white mb-1">Connect your channel manager</h2>
      <p className="text-white/40 text-sm mb-7">
        HAIP will automatically import your listings, calendar, and bookings.
      </p>

      <div className="space-y-2 mb-6">
        {CHANNEL_MANAGERS.map(cm => (
          <button key={cm.id} onClick={() => { setChannelManager(cm.id); setSyncStatus("idle"); }}
            disabled={(cm as any).badge === "Coming soon"}
            className={cn(
              "w-full flex items-center gap-3 p-4 rounded-2xl border text-left transition-all",
              channelManager === cm.id ? "bg-teal-500/10 border-teal-500/30" : "bg-white/3 border-white/8 hover:bg-white/5",
              (cm as any).badge === "Coming soon" && "opacity-40 cursor-not-allowed"
            )}>
            <div className={cn("w-4 h-4 rounded-full border-2 flex-shrink-0 flex items-center justify-center",
              channelManager === cm.id ? "border-teal-400" : "border-white/20")}>
              {channelManager === cm.id && <div className="w-2 h-2 rounded-full bg-teal-400" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={cn("text-sm font-bold", channelManager === cm.id ? "text-teal-300" : "text-white/60")}>{cm.label}</span>
                {(cm as any).badge && (
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-white/10 text-white/40 border border-white/10">{(cm as any).badge}</span>
                )}
              </div>
              {cm.desc && <div className="text-[11px] text-white/30 mt-0.5">{cm.desc}</div>}
            </div>
          </button>
        ))}
      </div>

      {/* Credential inputs for supported providers */}
      {creds.length > 0 && (
        <div className="space-y-3 mb-6">
          {creds.map(f => (
            <input key={f.key} type={f.type || "text"}
              value={cmCredentials[f.key] || ""}
              onChange={e => setCmCredentials({ ...cmCredentials, [f.key]: e.target.value })}
              placeholder={f.placeholder}
              className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
          ))}
        </div>
      )}

      {/* Sync status feedback */}
      {syncStatus === "done" && (
        <div className="flex items-center gap-2 p-3 bg-teal-500/10 border border-teal-500/20 rounded-xl text-sm text-teal-400 mb-4">
          <CheckCircle2 size={16} /> Connected! Your properties are being imported in the background.
        </div>
      )}
      {syncStatus === "error" && (
        <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400 mb-4">
          <X size={16} /> Could not connect — check your credentials and try again.
        </div>
      )}

      {syncStatus === "done" ? (
        <ContinueButton label="Continue" onClick={onSubmit} />
      ) : channelManager === "manual" ? (
        <ContinueButton label="Add manually →" onClick={onSubmit} />
      ) : (
        <button onClick={handleConnect}
          disabled={
            saving ||
            syncStatus === "syncing" ||
            (channelManager === "retalwise" && (!cmCredentials.username || !cmCredentials.password)) ||
            (channelManager === "hostaway" && (!cmCredentials.account_id || !cmCredentials.api_secret))
          }
          className="w-full py-3.5 bg-teal-500 hover:bg-teal-400 disabled:opacity-40 text-white font-bold rounded-2xl transition-all flex items-center justify-center gap-2">
          {syncStatus === "syncing"
            ? <><Loader2 size={18} className="animate-spin" /> Connecting…</>
            : <><RefreshCw size={18} /> Connect & import properties</>
          }
        </button>
      )}
      <SkipButton onSkip={onSubmit} />
    </>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // O4 — per-field validation errors (keyed by field name)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const clearFieldError = (key: string) => setFieldErrors(e => { const n = { ...e }; delete n[key]; return n; });
  // O1 — track skipped steps so checklist (O5) can surface them
  const [skippedSteps, setSkippedSteps] = useState<Set<number>>(new Set());
  const skipStep = async (stepNum: number) => {
    setSkippedSteps(s => new Set(s).add(stepNum));
    try { await api.patch("/tenants/me", { config: { [`step_${stepNum}_skipped`]: true } }); } catch { /* non-fatal */ }
    const next = Math.min(stepNum + 1, TOTAL_STEPS - 1);
    setStep(next);
    await persistStep(next);
  };

  // Step 0 — Brand basics
  const [brandName, setBrandName] = useState("");
  const [brandSlug, setBrandSlug] = useState("");
  const [brandCity, setBrandCity] = useState("");
  const [segment, setSegment] = useState("");
  const [plan, setPlan] = useState("starter");

  // Step 1 — Properties (standard / villa / resort / travel / other)
  const [properties, setProperties] = useState<StandardProperty[]>([
    { name: "", type: "villa", city: "" },
  ]);

  // Step 1 — Caravan vehicles
  const [vehicles, setVehicles] = useState<CaravanVehicle[]>([
    { vehicle_name: "", vehicle_type: "luxury_caravan", home_base: "", seats: "4", price_per_day: "", driver_included: true },
  ]);

  // Step 1 — Hotel
  const [hotel, setHotel] = useState<HotelProperty>({ name: "", city: "" });
  const [hotelRooms, setHotelRooms] = useState<HotelRoom[]>([
    { room_number: "", room_type: "standard", floor: "", capacity: "2" },
  ]);

  // Step 1 — Rental apartment
  const [channelManager, setChannelManager] = useState("retalwise");
  const [cmCredentials, setCmCredentials] = useState<Record<string, string>>({});
  const [syncStatus, setSyncStatus] = useState<"idle" | "syncing" | "done" | "error">("idle");

  // Step 2 — Brand voice
  const [brandVoice, setBrandVoice] = useState("");
  const [brandPersonality, setBrandPersonality] = useState("");

  // Step 3 — Telephony
  const [ivrProvider, setIvrProvider] = useState("callerdesk");
  const [ivrApiKey, setIvrApiKey] = useState("");
  const [ivrPhoneNumber, setIvrPhoneNumber] = useState("");

  // Step 4 — WhatsApp
  const [waConnected, setWaConnected] = useState(false);

  // Step 5 — Team invites
  const [inviteEmails, setInviteEmails] = useState<string[]>([]);
  const [inviteInput, setInviteInput] = useState("");

  // Step 6 — Concierge mode
  const [conciergeMode, setConciergeMode] = useState<"shadow" | "autonomous">("shadow");

  // Step 7 — DPDP consent
  const [dpdpAcknowledged, setDpdpAcknowledged] = useState(false);

  const accessToken = (session as any)?.accessToken;
  useEffect(() => {
    if (status === "loading") return;
    if (status === "unauthenticated" || !accessToken || accessToken === "demo") {
      router.replace("/login");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, accessToken]);

  const persistStep = useCallback(async (nextStep: number) => {
    try { await api.patch("/tenants/me", { config: { onboarding_step: nextStep } }); } catch { /* non-fatal */ }
  }, []);

  const goNext = useCallback(async () => {
    const next = Math.min(step + 1, TOTAL_STEPS - 1);
    setStep(next);
    await persistStep(next);
  }, [step, persistStep]);

  const goBack = () => setStep(s => Math.max(s - 1, 0));

  // ── Step 0 submit ──────────────────────────────────────────────────────────
  const handleBrandSubmit = useCallback(async () => {
    // O4 — field-level validation
    const errs: Record<string, string> = {};
    if (!brandName.trim()) errs.brandName = "Business name is required";
    if (!brandCity.trim()) errs.brandCity = "City is required";
    if (!segment) errs.segment = "Please select your business segment";
    if (Object.keys(errs).length) { setFieldErrors(errs); return; }
    setSaving(true); setError(""); setFieldErrors({});
    try {
      await api.patch("/tenants/me", {
        name: brandName,
        slug: brandSlug || brandName.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        brand_config: { city: brandCity, segment, plan },
      });
      await goNext();
    } catch (err: any) {
      const s = err?.response?.status;
      if (s === 401 || s === 403) { router.replace("/login?reason=session_expired"); return; }
      setError(err?.response?.data?.detail ? `Save failed: ${err.response.data.detail}` : "Could not save brand details. Please try again.");
    } finally { setSaving(false); }
  }, [brandName, brandSlug, brandCity, segment, plan, goNext, router]);

  // ── Step 1 submit — standard properties ───────────────────────────────────
  const handlePropertiesSubmit = useCallback(async () => {
    const valid = properties.filter(p => p.name.trim() && p.city.trim());
    if (valid.length === 0) return;
    setSaving(true);
    try {
      for (const p of valid) {
        await api.post("/properties", { name: p.name, city: p.city, type: p.type });
      }
      await goNext();
    } catch { setError("Could not save properties. Please try again."); }
    finally { setSaving(false); }
  }, [properties, goNext]);

  // ── Step 1 submit — caravan vehicles ──────────────────────────────────────
  const handleCaravanSubmit = useCallback(async () => {
    const valid = vehicles.filter(v => v.vehicle_name.trim() && v.home_base.trim());
    if (valid.length === 0) return;
    setSaving(true);
    try {
      for (const v of valid) {
        await api.post("/properties", {
          name: v.vehicle_name,
          type: "caravan",
          city: v.home_base,
          vehicle_name: v.vehicle_name,
          vehicle_type: v.vehicle_type,
          home_base: v.home_base,
          seats: v.seats ? parseInt(v.seats) : undefined,
          price_per_day: v.price_per_day ? parseFloat(v.price_per_day) : undefined,
          driver_included: v.driver_included,
        });
      }
      await goNext();
    } catch { setError("Could not save vehicles. Please try again."); }
    finally { setSaving(false); }
  }, [vehicles, goNext]);

  // ── Step 1 submit — hotel + rooms ─────────────────────────────────────────
  const handleHotelSubmit = useCallback(async () => {
    if (!hotel.name.trim() || !hotel.city.trim()) return;
    setSaving(true);
    try {
      const res = await api.post("/properties", { name: hotel.name, city: hotel.city, type: "hotel" });
      const propertyId = res.data.id;
      const validRooms = hotelRooms.filter(r => r.room_number.trim());
      for (const r of validRooms) {
        await api.post(`/properties/${propertyId}/rooms`, {
          room_number: r.room_number,
          room_type: r.room_type,
          floor: r.floor ? parseInt(r.floor) : undefined,
          capacity: r.capacity ? parseInt(r.capacity) : 2,
        });
      }
      await goNext();
    } catch { setError("Could not save hotel. Please try again."); }
    finally { setSaving(false); }
  }, [hotel, hotelRooms, goNext]);

  // ── Step 4 submit ──────────────────────────────────────────────────────────
  const handleIvrSubmit = useCallback(async () => {
    if (ivrProvider === "skip") { await goNext(); return; }
    if (!ivrApiKey.trim()) return;
    setSaving(true);
    try {
      await api.post(`/integrations/${ivrProvider}/connect`, {
        api_key: ivrApiKey, phone_number: ivrPhoneNumber,
      });
      await goNext();
    } catch { setError("Could not connect IVR. Check your API key and try again."); }
    finally { setSaving(false); }
  }, [ivrProvider, ivrApiKey, ivrPhoneNumber, goNext]);

  // ── Step 5 submit ──────────────────────────────────────────────────────────
  const handleInviteSubmit = useCallback(async () => {
    if (inviteEmails.length > 0) {
      try { for (const email of inviteEmails) { await api.post("/users", { email, role: "concierge" }); } }
      catch { /* non-fatal */ }
    }
    await goNext();
  }, [inviteEmails, goNext]);

  // ── Finish ─────────────────────────────────────────────────────────────────
  const handleFinish = useCallback(async () => {
    setSaving(true);
    try { await api.patch("/tenants/me", { config: { onboarding_complete: true } }); router.push("/dashboard"); }
    catch { router.push("/dashboard"); }
    finally { setSaving(false); }
  }, [router]);

  const addEmail = () => {
    const email = inviteInput.trim().toLowerCase();
    if (email.includes("@") && !inviteEmails.includes(email)) {
      setInviteEmails(prev => [...prev, email]);
      setInviteInput("");
    }
  };
  const removeEmail = (email: string) => setInviteEmails(prev => prev.filter(e => e !== email));

  if (status === "unauthenticated") { router.replace("/login"); return null; }

  return (
    <div className="min-h-screen bg-[#0B1F3A] flex flex-col items-center justify-center p-5">
      {/* Brand */}
      <div className="flex items-center gap-2.5 mb-8">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center text-[#0a1f3a] font-bold text-sm">H</div>
        <span className="text-white font-bold text-xl tracking-tight">HA<span className="text-teal-400">IP</span></span>
      </div>

      <div className="w-full max-w-xl">
        {/* Progress */}
        <div className="flex items-center justify-between mb-6 px-1">
          <StepIndicator current={step} total={TOTAL_STEPS} />
          <span className="text-xs text-white/30 font-medium">Step {step + 1} of {TOTAL_STEPS}</span>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400 flex items-start gap-2">
            <X size={14} className="mt-0.5 flex-shrink-0" />
            {error}
            <button onClick={() => setError("")} className="ml-auto text-red-400/50 hover:text-red-400"><X size={12} /></button>
          </div>
        )}

        {/* Card */}
        <div className="bg-[#0f2744] rounded-3xl border border-white/8 shadow-2xl shadow-black/40 overflow-hidden">

          {/* ── Step 0: Brand basics ─────────────────────────────────────────── */}
          {step === 0 && (
            <div className="p-8">
              <div className="text-center mb-8">
                <Sparkles size={28} className="text-teal-400 mx-auto mb-3" />
                <h1 className="text-2xl font-black text-white mb-2">Welcome to HAIP!</h1>
                <p className="text-white/45 text-sm">Let&apos;s set up your workspace in 9 quick steps.</p>
              </div>

              <div className="space-y-5 mb-7">
                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">Business / brand name *</label>
                  <input value={brandName}
                    onChange={e => {
                      setBrandName(e.target.value);
                      setBrandSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
                      clearFieldError("brandName");
                    }}
                    placeholder="Ratha Travels"
                    className={cn("w-full px-4 py-3 bg-white/5 border rounded-xl text-sm text-white placeholder-white/25 focus:outline-none transition-all",
                      fieldErrors.brandName ? "border-red-500/60 focus:border-red-500/80" : "border-white/10 focus:border-teal-500/50")} />
                  <FieldError msg={fieldErrors.brandName} />
                </div>

                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">City / headquarters *</label>
                  <input value={brandCity} onChange={e => { setBrandCity(e.target.value); clearFieldError("brandCity"); }} placeholder="Goa"
                    className={cn("w-full px-4 py-3 bg-white/5 border rounded-xl text-sm text-white placeholder-white/25 focus:outline-none transition-all",
                      fieldErrors.brandCity ? "border-red-500/60 focus:border-red-500/80" : "border-white/10 focus:border-teal-500/50")} />
                  <FieldError msg={fieldErrors.brandCity} />
                </div>

                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-3">Business segment *</label>
                  <div className="grid grid-cols-4 gap-2">
                    {SEGMENTS.map(s => (
                      <button key={s.id} onClick={() => { setSegment(s.id); clearFieldError("segment"); }}
                        className={cn(
                          "flex flex-col items-center p-3 rounded-xl border text-center transition-all",
                          segment === s.id ? "bg-teal-500/15 border-teal-500/40 text-teal-300" : "bg-white/3 border-white/8 text-white/40 hover:bg-white/6 hover:text-white/70"
                        )}>
                        <div className={cn("mb-1", segment === s.id ? "text-teal-400" : "text-white/25")}>{s.icon}</div>
                        <div className="text-[10px] font-bold leading-tight">{s.label}</div>
                      </button>
                    ))}
                  </div>
                </div>

                  <FieldError msg={fieldErrors.segment} />
                </div>

                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-3">Plan</label>
                  <div className="grid grid-cols-3 gap-2">
                    {PLANS.map(p => (
                      <button key={p.id} onClick={() => setPlan(p.id)}
                        className={cn(
                          "p-3 rounded-xl border text-left transition-all",
                          plan === p.id ? "bg-teal-500/15 border-teal-500/40" : "bg-white/3 border-white/8 hover:bg-white/6"
                        )}>
                        <div className={cn("text-xs font-bold mb-0.5", plan === p.id ? "text-teal-300" : "text-white/60")}>{p.label}</div>
                        <div className={cn("text-[11px] font-semibold", plan === p.id ? "text-teal-400" : "text-white/40")}>{p.price}</div>
                        <div className="text-[10px] text-white/25 mt-0.5">{p.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <ContinueButton
                disabled={!brandName.trim() || !brandCity.trim() || !segment}
                loading={saving}
                onClick={handleBrandSubmit}
              />
            </div>
          )}

          {/* ── Step 1: Segment-aware property/vehicle/hotel/channel step ────── */}
          {step === 1 && (
            <div className="p-8">
              <BackButton onBack={goBack} />

              {/* Caravan */}
              {segment === "caravan" && (
                <CaravanStep
                  vehicles={vehicles} setVehicles={setVehicles}
                  saving={saving} onSubmit={handleCaravanSubmit}
                />
              )}

              {/* Hotel */}
              {segment === "hotel" && (
                <HotelStep
                  hotel={hotel} setHotel={setHotel}
                  rooms={hotelRooms} setRooms={setHotelRooms}
                  saving={saving} onSubmit={handleHotelSubmit}
                />
              )}

              {/* Rental apartment — channel manager first */}
              {segment === "rental_apartment" && (
                <RentalApartmentStep
                  channelManager={channelManager} setChannelManager={setChannelManager}
                  cmCredentials={cmCredentials} setCmCredentials={setCmCredentials}
                  syncStatus={syncStatus} setSyncStatus={setSyncStatus}
                  saving={saving} onSubmit={goNext}
                />
              )}

                      {/* Standard segments */}
              {(segment !== "caravan" && segment !== "hotel" && segment !== "rental_apartment") && (
                <StandardPropertyStep
                  properties={properties} setProperties={setProperties}
                  saving={saving} onSubmit={handlePropertiesSubmit}
                />
              )}

              {/* Skip — shown for caravan, hotel, and standard segments only
                  (rental_apartment manages its own navigation flow) */}
              {segment !== "rental_apartment" && (
                <div className="mt-3">
                  <SkipButton onSkip={goNext} />
                </div>
              )}
            </div>
          )}

          {/* ── Step 2: Brand voice ───────────────────────────────────────── */}
          {step === 2 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center">
                  <Mic size={18} className="text-purple-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">Brand voice & personality</h2>
                  <p className="text-white/40 text-xs">How should your AI concierge speak to guests?</p>
                </div>
              </div>

              <div className="space-y-5 mb-7">
                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">Brand personality (2-3 words)</label>
                  <input value={brandPersonality} onChange={e => setBrandPersonality(e.target.value)}
                    placeholder="e.g. warm, professional, luxurious"
                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-white/50 uppercase tracking-wider mb-2">Brand voice guide (optional)</label>
                  <textarea value={brandVoice} onChange={e => setBrandVoice(e.target.value)} rows={4}
                    placeholder="Describe how your team communicates. E.g. 'We speak formally but warmly. We always use the guest's first name.'"
                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all resize-none" />
                </div>
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton onClick={async () => {
                  if (brandPersonality || brandVoice) {
                    await api.patch("/tenants/me", { brand_config: { voice_guide: brandVoice, personality: brandPersonality } }).catch(() => {});
                  }
                  goNext();
                }} />
                <SkipButton onSkip={goNext} />
              </div>
            </div>
          )}

          {/* ── Step 3: Telephony ─────────────────────────────────────────── */}
          {step === 3 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-blue-500/20 border border-blue-500/30 flex items-center justify-center">
                  <Phone size={18} className="text-blue-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">Connect your IVR</h2>
                  <p className="text-white/40 text-xs">HAIP works with CallerDesk and Acefone (BYOC)</p>
                </div>
              </div>

              <div className="space-y-2 mb-5">
                {IVR_PROVIDERS.map(p => (
                  <button key={p.id} onClick={() => setIvrProvider(p.id)}
                    className={cn(
                      "w-full flex items-center gap-3 p-4 rounded-2xl border text-left transition-all",
                      ivrProvider === p.id ? "bg-teal-500/10 border-teal-500/30" : "bg-white/3 border-white/8 hover:bg-white/5"
                    )}>
                    <div className={cn("w-4 h-4 rounded-full border-2 flex-shrink-0 flex items-center justify-center",
                      ivrProvider === p.id ? "border-teal-400" : "border-white/20")}>
                      {ivrProvider === p.id && <div className="w-2 h-2 rounded-full bg-teal-400" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={cn("text-sm font-bold", ivrProvider === p.id ? "text-teal-300" : "text-white/60")}>{p.label}</span>
                        {(p as any).badge && (
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-teal-500/20 text-teal-400 border border-teal-500/20">{(p as any).badge}</span>
                        )}
                      </div>
                      {p.desc && <div className="text-[11px] text-white/30 mt-0.5">{p.desc}</div>}
                    </div>
                    {p.id !== "skip" && (
                      <a
                        href={`https://wa.me/919999999999?text=I+need+help+choosing+an+IVR+provider+for+HAIP.+I+am+considering+${p.label}.`}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={e => e.stopPropagation()}
                        className="text-[10px] text-teal-400/60 hover:text-teal-400 transition-colors flex-shrink-0 underline underline-offset-2"
                      >
                        Not sure?
                      </a>
                    )}
                  </button>
                ))}
              </div>

              {ivrProvider !== "skip" && (
                <div className="space-y-3 mb-6">
                  <input value={ivrApiKey} onChange={e => setIvrApiKey(e.target.value)}
                    placeholder={`${ivrProvider === "callerdesk" ? "CallerDesk" : "Acefone"} API Key`}
                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
                  <input value={ivrPhoneNumber} onChange={e => setIvrPhoneNumber(e.target.value)}
                    placeholder="Virtual phone number (e.g. +91-8800XXXXXX)"
                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
                </div>
              )}

              <ContinueButton
                disabled={ivrProvider !== "skip" && !ivrApiKey.trim()}
                loading={saving}
                onClick={handleIvrSubmit}
                label={ivrProvider === "skip" ? "Set up later" : "Connect & Continue"}
              />
              {ivrProvider !== "skip" && (
                <SetupLaterButton onSkip={() => skipStep(3)} />
              )}
            </div>
          )}

          {/* ── Step 4: WhatsApp ──────────────────────────────────────────── */}
          {step === 4 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-green-500/20 border border-green-500/30 flex items-center justify-center">
                  <MessageSquare size={18} className="text-green-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">Connect WhatsApp</h2>
                  <p className="text-white/40 text-xs">Meta Business Cloud API via embedded signup</p>
                </div>
              </div>

              <div className="bg-white/3 border border-white/8 rounded-2xl p-5 mb-6">
                <p className="text-sm text-white/60 leading-relaxed mb-4">
                  Click <strong className="text-white/80">Connect WhatsApp</strong> to launch Meta&apos;s embedded signup flow. You&apos;ll connect your WhatsApp Business number in under 3 minutes.
                </p>
                {waConnected ? (
                  <div className="flex items-center gap-2 text-teal-400 text-sm font-semibold">
                    <CheckCircle2 size={18} /> WhatsApp connected successfully
                  </div>
                ) : (
                  <button onClick={() => setWaConnected(true)}
                    className="w-full py-3 bg-green-500/20 hover:bg-green-500/30 border border-green-500/30 text-green-400 font-bold rounded-xl text-sm transition-all flex items-center justify-center gap-2">
                    <MessageSquare size={16} /> Connect WhatsApp Business
                  </button>
                )}
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton onClick={goNext} label={waConnected ? "Continue" : "Continue anyway"} />
                {!waConnected && <SetupLaterButton onSkip={() => skipStep(4)} />}
              </div>
            </div>
          )}

          {/* ── Step 5: Team ──────────────────────────────────────────────── */}
          {step === 5 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center">
                  <Users size={18} className="text-purple-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">Invite your team</h2>
                  <p className="text-white/40 text-xs">Add concierge, reservations, and manager roles</p>
                </div>
              </div>

              <div className="space-y-3 mb-6">
                <div className="flex gap-2">
                  <input type="email" value={inviteInput} onChange={e => setInviteInput(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addEmail(); } }}
                    placeholder="colleague@company.com"
                    className="flex-1 px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none focus:border-teal-500/50 transition-all" />
                  <button onClick={addEmail} disabled={!inviteInput.trim()}
                    className="px-4 py-3 bg-teal-500/20 hover:bg-teal-500/30 disabled:opacity-40 text-teal-400 rounded-xl text-sm font-bold transition-all border border-teal-500/20">
                    Add
                  </button>
                </div>
                {inviteEmails.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {inviteEmails.map(email => (
                      <div key={email} className="flex items-center gap-1.5 bg-teal-500/15 border border-teal-500/20 rounded-lg px-2.5 py-1.5">
                        <span className="text-xs text-teal-300">{email}</span>
                        <button onClick={() => removeEmail(email)} className="text-teal-400/50 hover:text-teal-400 transition-colors"><X size={11} /></button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton loading={saving} onClick={handleInviteSubmit}
                  label={inviteEmails.length > 0 ? `Invite ${inviteEmails.length} & Continue` : "Continue"} />
                <SetupLaterButton onSkip={() => skipStep(5)} />
              </div>
            </div>
          )}

          {/* ── Step 6: Concierge mode ────────────────────────────────────── */}
          {step === 6 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center">
                  <Zap size={18} className="text-teal-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">AI Concierge mode</h2>
                  <p className="text-white/40 text-xs">Choose how the AI replies to guests</p>
                </div>
              </div>

              <div className="space-y-3 mb-7">
                {[
                  { id: "shadow", color: "teal", title: "Shadow mode (recommended)", desc: "AI drafts a reply and waits for agent approval before sending. Safe to start with." },
                  { id: "autonomous", color: "amber", title: "Autonomous mode", desc: "AI sends replies directly when confidence is high (≥78%). Enable after KB is trained." },
                ].map(opt => (
                  <button key={opt.id} onClick={() => setConciergeMode(opt.id as "shadow" | "autonomous")}
                    className={cn(
                      "w-full p-5 rounded-2xl border text-left transition-all",
                      conciergeMode === opt.id
                        ? opt.color === "teal" ? "bg-teal-500/10 border-teal-500/30" : "bg-amber-500/10 border-amber-500/30"
                        : "bg-white/3 border-white/8 hover:bg-white/5"
                    )}>
                    <div className="flex items-start gap-3">
                      <div className={cn("w-4 h-4 rounded-full border-2 flex-shrink-0 mt-0.5 flex items-center justify-center",
                        conciergeMode === opt.id
                          ? opt.color === "teal" ? "border-teal-400" : "border-amber-400"
                          : "border-white/20")}>
                        {conciergeMode === opt.id && (
                          <div className={cn("w-2 h-2 rounded-full", opt.color === "teal" ? "bg-teal-400" : "bg-amber-400")} />
                        )}
                      </div>
                      <div>
                        <div className={cn("font-bold text-sm mb-1",
                          conciergeMode === opt.id
                            ? opt.color === "teal" ? "text-teal-300" : "text-amber-300"
                            : "text-white/70")}>{opt.title}</div>
                        <p className="text-xs text-white/40 leading-relaxed">{opt.desc}</p>
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton onClick={async () => {
                  await api.patch("/tenants/me", { brand_config: { concierge_mode: conciergeMode } }).catch(() => {});
                  goNext();
                }} />
                <SetupLaterButton onSkip={() => skipStep(6)} />
              </div>
            </div>
          )}

          {/* ── Step 7: DPDP consent ──────────────────────────────────────── */}
          {step === 7 && (
            <div className="p-8">
              <BackButton onBack={goBack} />
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-blue-500/20 border border-blue-500/30 flex items-center justify-center">
                  <Shield size={18} className="text-blue-400" />
                </div>
                <div>
                  <h2 className="text-xl font-black text-white">DPDP compliance</h2>
                  <p className="text-white/40 text-xs">India&apos;s Digital Personal Data Protection Act</p>
                </div>
              </div>

              <div className="bg-white/3 border border-white/8 rounded-2xl p-5 mb-6 space-y-4">
                <p className="text-sm text-white/60 leading-relaxed">
                  HAIP processes guest personal data (name, phone, call recordings) on your behalf. As the data fiduciary, you must:
                </p>
                <ul className="space-y-2">
                  {[
                    "Notify guests that calls are recorded for quality purposes",
                    "Honour data deletion requests within 30 days",
                    "Not retain guest data beyond the retention window you configure",
                    "Obtain consent before using data for marketing",
                  ].map(item => (
                    <li key={item} className="flex items-start gap-2.5 text-xs text-white/50">
                      <CheckCircle2 size={14} className="text-teal-400 flex-shrink-0 mt-0.5" />
                      {item}
                    </li>
                  ))}
                </ul>
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" checked={dpdpAcknowledged} onChange={e => setDpdpAcknowledged(e.target.checked)}
                    className="w-4 h-4 mt-0.5 rounded border-white/20 text-teal-500 flex-shrink-0" />
                  <span className="text-xs text-white/60">
                    I acknowledge that I am the data fiduciary for my guests&apos; personal data and will comply with DPDP Act obligations.
                  </span>
                </label>
              </div>

              <div className="flex flex-col gap-3">
                <ContinueButton disabled={!dpdpAcknowledged} onClick={async () => {
                  await api.patch("/tenants/me", { brand_config: { dpdp_acknowledged: true } }).catch(() => {});
                  goNext();
                }} label="Acknowledge & Continue" />
                <SetupLaterButton onSkip={() => skipStep(7)} label="Review DPDP later" />
              </div>
            </div>
          )}

          {/* ── Step 8: All set ───────────────────────────────────────────── */}
          {step === 8 && (
            <div className="p-8">
              <div className="text-center mb-8">
                <div className="w-16 h-16 rounded-2xl bg-teal-500/20 border border-teal-500/30 flex items-center justify-center mx-auto mb-4">
                  <CheckCircle2 size={32} className="text-teal-400" />
                </div>
                <h2 className="text-2xl font-black text-white mb-2">You&apos;re all set!</h2>
                <p className="text-white/40 text-sm max-w-xs mx-auto">
                  {brandName || "Your workspace"} is ready. Make a test call to see HAIP in action.
                </p>
              </div>

              <div className="space-y-2 mb-8">
                {[
                  { icon: <Phone size={16} />, color: "text-blue-400", label: "Place a test call to your IVR number", desc: "See transcription + AI scoring in real time" },
                  { icon: <MessageSquare size={16} />, color: "text-green-400", label: "Send a WhatsApp message to your number", desc: "See AI concierge draft a reply" },
                  { icon: <Bell size={16} />, color: "text-amber-400", label: "Check your inbox in 2 minutes", desc: "Wrap-up card should appear within 90s" },
                ].map(item => (
                  <div key={item.label} className="flex items-start gap-3 p-4 bg-white/3 border border-white/6 rounded-2xl">
                    <div className={cn("w-8 h-8 rounded-xl bg-white/5 flex items-center justify-center flex-shrink-0", item.color)}>{item.icon}</div>
                    <div>
                      <div className="text-sm font-semibold text-white/80">{item.label}</div>
                      <div className="text-xs text-white/35 mt-0.5">{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>

              <button onClick={handleFinish} disabled={saving}
                className="w-full py-3.5 bg-teal-500 hover:bg-teal-400 disabled:opacity-60 text-white font-bold rounded-2xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-teal-500/25">
                {saving ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
                {saving ? "Setting up…" : "Go to dashboard"}
              </button>
            </div>
          )}
        </div>

        <p className="text-center text-xs text-white/20 mt-6">
          Already set up?{" "}
          <Link href="/dashboard" className="text-teal-400 hover:text-teal-300">Go to dashboard</Link>
        </p>
      </div>
    </div>
  );
}
