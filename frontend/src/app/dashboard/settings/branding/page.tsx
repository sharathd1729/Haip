"use client";

import { useState, useCallback, useRef } from "react";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import {
  BrandTheme, DEFAULT_THEME, PRESET_THEMES, FONT_OPTIONS,
  brightness, hexToRgb,
} from "@/lib/brandTheme";
import { cn } from "@/lib/utils";
import {
  Palette, Upload, RefreshCw, Check, Loader2, Eye,
  Type, Sliders, Image as ImageIcon, Sparkles, AlertCircle,
  ChevronRight, LayoutDashboard, Phone, MessageSquare,
  Star, Inbox, Zap,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Live sidebar mini-preview
// ---------------------------------------------------------------------------

function SidebarPreview({ t }: { t: BrandTheme }) {
  const bright = brightness(t.primaryColor) > 160;
  const logoText = (t.companyName || "HAIP").slice(0, 2).toUpperCase();
  const r = hexToRgb(t.primaryColor);
  const primaryRgba = (a: number) => r ? `rgba(${r.r},${r.g},${r.b},${a})` : `rgba(20,184,166,${a})`;

  const radius = t.radiusScale === "sharp" ? "2px" : t.radiusScale === "pill" ? "999px" : "8px";

  const navItems = [
    { icon: <LayoutDashboard size={11} />, label: "Dashboard", active: true },
    { icon: <Inbox size={11} />,           label: "Inbox",     active: false },
    { icon: <Phone size={11} />,           label: "Calls",     active: false },
    { icon: <Zap size={11} />,             label: "Inquiries", active: false },
    { icon: <MessageSquare size={11} />,   label: "Templates", active: false },
    { icon: <Star size={11} />,            label: "QA Scores", active: false },
  ];

  return (
    <div
      className="flex h-full"
      style={{ fontFamily: `"${t.fontFamily}", ui-sans-serif, system-ui, sans-serif` }}
    >
      {/* Sidebar */}
      <div
        className="w-28 flex flex-col py-2 flex-shrink-0"
        style={{ backgroundColor: t.sidebarColor }}
      >
        {/* Logo */}
        <div className="px-2.5 pb-2 mb-1" style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
          {t.logoUrl ? (
            <img src={t.logoUrl} alt={t.companyName} className="h-5 w-auto object-contain" />
          ) : (
            <div className="flex items-center gap-1.5">
              <div
                className="w-5 h-5 rounded flex items-center justify-center text-[8px] font-bold"
                style={{
                  backgroundColor: t.primaryColor,
                  color: bright ? "#111" : "#fff",
                  borderRadius: radius,
                }}
              >
                {logoText}
              </div>
              <span className="text-white text-[10px] font-bold truncate">
                {t.companyName || "HAIP"}
              </span>
            </div>
          )}
        </div>

        {/* Nav items */}
        <div className="px-1.5 space-y-0.5 flex-1">
          {navItems.map(item => (
            <div
              key={item.label}
              className="flex items-center gap-1.5 px-1.5 py-1 text-[9px]"
              style={{
                backgroundColor: item.active ? primaryRgba(0.15) : "transparent",
                color: item.active ? "#fff" : "rgba(255,255,255,0.45)",
                borderRadius: radius,
              }}
            >
              <span style={{ color: item.active ? t.primaryColor : "rgba(255,255,255,0.3)" }}>
                {item.icon}
              </span>
              {item.label}
            </div>
          ))}
        </div>

        {/* User */}
        <div className="px-2 pt-2" style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }}>
          <div className="flex items-center gap-1.5">
            <div
              className="w-4 h-4 rounded-full flex items-center justify-center text-[7px] font-bold"
              style={{ backgroundColor: t.primaryColor, color: bright ? "#111" : "#fff" }}
            >
              S
            </div>
            <span className="text-[8px] text-white/50 truncate">Sharath</span>
          </div>
        </div>
      </div>

      {/* Main area */}
      <div className="flex-1 bg-gray-50 p-2 flex flex-col gap-2 overflow-hidden">
        {/* Topbar */}
        <div
          className="rounded flex items-center justify-between px-2 py-1"
          style={{ backgroundColor: t.sidebarColor, borderRadius: radius }}
        >
          <span className="text-[8px] text-white/50">Dashboard</span>
          <div
            className="px-1.5 py-0.5 rounded text-[7px] font-semibold"
            style={{
              backgroundColor: primaryRgba(0.15),
              color: t.primaryColor,
              borderRadius: radius,
            }}
          >
            AI active
          </div>
        </div>

        {/* KPI cards */}
        <div className="grid grid-cols-2 gap-1.5">
          {["Calls", "Inquiries", "QA Avg", "Revenue"].map((kpi, i) => (
            <div key={kpi} className="bg-white rounded p-1.5" style={{ borderRadius: radius, border: "1px solid #f0f0f0" }}>
              <p className="text-[7px] text-gray-400">{kpi}</p>
              <p className="text-[11px] font-bold text-gray-800 mt-0.5">
                {["847", "34", "78%", "₹2.1L"][i]}
              </p>
            </div>
          ))}
        </div>

        {/* Primary button */}
        <button
          className="text-[8px] font-semibold px-2 py-1 w-full"
          style={{
            backgroundColor: t.primaryColor,
            color: bright ? "#111" : "#fff",
            borderRadius: radius,
          }}
        >
          + New Inquiry
        </button>

        {/* Card */}
        <div className="bg-white rounded p-1.5 flex-1" style={{ borderRadius: radius, border: "1px solid #f0f0f0" }}>
          <p className="text-[7px] text-gray-400 mb-1">Recent Calls</p>
          {["Priya S.", "Arjun R.", "Meera D."].map(name => (
            <div key={name} className="flex items-center gap-1 py-0.5">
              <div
                className="w-3 h-3 rounded-full text-[6px] font-bold flex items-center justify-center"
                style={{ backgroundColor: primaryRgba(0.15), color: t.primaryColor }}
              >
                {name[0]}
              </div>
              <span className="text-[7px] text-gray-600">{name}</span>
              <span
                className="ml-auto text-[6px] px-1 rounded"
                style={{ backgroundColor: primaryRgba(0.1), color: t.primaryColor }}
              >
                Inquiry
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Color swatch
// ---------------------------------------------------------------------------

function ColorSwatch({
  color, label, selected, onClick,
}: {
  color: string; label: string; selected?: boolean; onClick: () => void;
}) {
  return (
    <button
      title={label}
      onClick={onClick}
      className={cn(
        "w-8 h-8 rounded-xl transition-all flex items-center justify-center",
        selected ? "ring-2 ring-offset-2 ring-gray-700 scale-110" : "hover:scale-105"
      )}
      style={{ backgroundColor: color }}
    >
      {selected && (
        <Check
          size={12}
          style={{ color: brightness(color) > 160 ? "#000" : "#fff", opacity: 0.9 }}
        />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({
  icon, title, sub, children,
}: {
  icon: React.ReactNode; title: string; sub?: string; children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-8 h-8 rounded-lg bg-gray-50 flex items-center justify-center text-gray-500">
          {icon}
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900">{title}</p>
          {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function BrandingPage() {
  const { theme, setTheme, saveTheme, isSaving } = useBrandTheme();
  const [local, setLocal] = useState<BrandTheme>({ ...theme });
  const [saved, setSaved] = useState(false);
  const logoInputRef = useRef<HTMLInputElement>(null);

  // Update local + instant preview
  const update = useCallback((patch: Partial<BrandTheme>) => {
    const next = { ...local, ...patch };
    setLocal(next);
    setTheme(next);       // live preview
    setSaved(false);
  }, [local, setTheme]);

  async function handleSave() {
    await saveTheme(local);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  }

  function handleReset() {
    setLocal({ ...DEFAULT_THEME });
    setTheme(DEFAULT_THEME);
    setSaved(false);
  }

  // Logo upload (base64 preview — in production, upload to S3)
  function handleLogoUpload(e: React.ChangeEvent<HTMLInputElement>, variant: "logoUrl" | "logoDarkUrl") {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => update({ [variant]: ev.target?.result as string });
    reader.readAsDataURL(file);
  }

  const bright = brightness(local.primaryColor) > 160;

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Brand & Theme</h1>
            <p className="text-sm text-gray-400 mt-0.5">
              Tailor HAIP's look to match your brand — colours, logo, fonts, and shape. Changes apply instantly.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-xl text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <RefreshCw size={12} /> Reset to default
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className={cn(
                "flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold transition-colors",
                saved
                  ? "bg-green-50 text-green-700 border border-green-200"
                  : "bg-indigo-500 text-white hover:bg-indigo-600 disabled:opacity-50"
              )}
              style={!saved ? { backgroundColor: local.primaryColor, color: bright ? "#111" : "#fff" } : {}}
            >
              {isSaving ? <Loader2 size={14} className="animate-spin" /> : saved ? <Check size={14} /> : <Palette size={14} />}
              {saved ? "Saved!" : "Save brand"}
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex gap-0">
        {/* Controls */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5 max-w-xl">

          {/* Preset themes */}
          <Section icon={<Sparkles size={16} />} title="Quick presets" sub="One click to apply a complete brand palette">
            <div className="flex flex-wrap gap-2">
              {PRESET_THEMES.map(p => {
                const isActive = local.primaryColor === p.primaryColor && local.sidebarColor === p.sidebarColor;
                return (
                  <button
                    key={p.name}
                    onClick={() => update({ primaryColor: p.primaryColor, sidebarColor: p.sidebarColor })}
                    className={cn(
                      "flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-medium transition-all",
                      isActive ? "border-gray-700 shadow-sm" : "border-gray-200 hover:border-gray-300 bg-white"
                    )}
                  >
                    {/* Mini dual swatch */}
                    <div className="flex -space-x-1">
                      <div className="w-4 h-4 rounded-full border border-white shadow-sm" style={{ backgroundColor: p.sidebarColor }} />
                      <div className="w-4 h-4 rounded-full border border-white shadow-sm" style={{ backgroundColor: p.primaryColor }} />
                    </div>
                    {p.name}
                    {isActive && <Check size={10} className="text-gray-600" />}
                  </button>
                );
              })}
            </div>
          </Section>

          {/* Logo */}
          <Section icon={<ImageIcon size={16} />} title="Logo & brand name" sub="Shown in the sidebar header">
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs font-medium text-gray-700 mb-2">
                    Light logo <span className="text-gray-400 font-normal">(for any bg)</span>
                  </p>
                  {local.logoUrl ? (
                    <div className="relative bg-gray-100 rounded-xl p-3 flex items-center justify-center h-16">
                      <img src={local.logoUrl} alt="Logo" className="max-h-10 max-w-full object-contain" />
                      <button
                        onClick={() => update({ logoUrl: "" })}
                        className="absolute top-1 right-1 w-5 h-5 bg-red-100 text-red-600 rounded-full text-[10px] flex items-center justify-center hover:bg-red-200"
                      >✕</button>
                    </div>
                  ) : (
                    <button
                      onClick={() => logoInputRef.current?.click()}
                      className="w-full h-16 border-2 border-dashed border-gray-200 rounded-xl flex flex-col items-center justify-center gap-1 hover:border-indigo-400 transition-colors"
                    >
                      <Upload size={14} className="text-gray-400" />
                      <span className="text-[10px] text-gray-400">Upload PNG/SVG</span>
                    </button>
                  )}
                  <input ref={logoInputRef} type="file" accept="image/*" className="hidden"
                    onChange={e => handleLogoUpload(e, "logoUrl")} />
                </div>

                <div>
                  <p className="text-xs font-medium text-gray-700 mb-2">
                    Dark logo <span className="text-gray-400 font-normal">(sidebar variant)</span>
                  </p>
                  {local.logoDarkUrl ? (
                    <div
                      className="relative rounded-xl p-3 flex items-center justify-center h-16"
                      style={{ backgroundColor: local.sidebarColor }}
                    >
                      <img src={local.logoDarkUrl} alt="Dark logo" className="max-h-10 max-w-full object-contain" />
                      <button
                        onClick={() => update({ logoDarkUrl: "" })}
                        className="absolute top-1 right-1 w-5 h-5 bg-red-800/50 text-red-300 rounded-full text-[10px] flex items-center justify-center hover:bg-red-800"
                      >✕</button>
                    </div>
                  ) : (
                    <button
                      onClick={() => {
                        const inp = document.createElement("input");
                        inp.type = "file"; inp.accept = "image/*";
                        inp.onchange = (ev) => handleLogoUpload(ev as any, "logoDarkUrl");
                        inp.click();
                      }}
                      className="w-full h-16 border-2 border-dashed border-gray-200 rounded-xl flex flex-col items-center justify-center gap-1 hover:border-indigo-400 transition-colors"
                    >
                      <Upload size={14} className="text-gray-400" />
                      <span className="text-[10px] text-gray-400">Upload for dark bg</span>
                    </button>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Company name</label>
                  <input
                    type="text" value={local.companyName ?? ""}
                    onChange={e => update({ companyName: e.target.value })}
                    placeholder="HAIP"
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Tagline <span className="text-gray-400 font-normal">(optional)</span></label>
                  <input
                    type="text" value={local.tagline ?? ""}
                    onChange={e => update({ tagline: e.target.value })}
                    placeholder="Hospitality AI"
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                  />
                </div>
              </div>
            </div>
          </Section>

          {/* Colors */}
          <Section icon={<Palette size={16} />} title="Brand colours" sub="Primary accent and sidebar/navigation background">
            <div className="space-y-5">
              {/* Primary */}
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-2">
                  Primary colour <span className="text-gray-400 font-normal">— buttons, active nav, badges</span>
                </label>
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex items-center gap-2 border border-gray-200 rounded-xl px-3 py-2 bg-white">
                    <input
                      type="color"
                      value={local.primaryColor}
                      onChange={e => update({ primaryColor: e.target.value })}
                      className="w-6 h-6 rounded cursor-pointer border-0 bg-transparent p-0"
                    />
                    <span className="text-xs font-mono text-gray-700 w-16">{local.primaryColor}</span>
                  </div>
                  <div className="flex gap-1.5 flex-wrap">
                    {PRESET_THEMES.map(p => (
                      <ColorSwatch
                        key={p.primaryColor}
                        color={p.primaryColor}
                        label={p.name}
                        selected={local.primaryColor === p.primaryColor}
                        onClick={() => update({ primaryColor: p.primaryColor })}
                      />
                    ))}
                  </div>
                </div>

                {/* Derived palette preview */}
                <div className="mt-3 flex items-center gap-2">
                  {[
                    { label: "Light (bg)", mix: 0.88 },
                    { label: "Muted (hover)", mix: 0.75 },
                    { label: "Primary", mix: 0 },
                    { label: "Dark (press)", mix: -0.2 },
                  ].map(({ label, mix }) => {
                    const r2 = hexToRgb(local.primaryColor);
                    if (!r2) return null;
                    const makeColor = (m: number) => {
                      if (m === 0) return local.primaryColor;
                      if (m > 0) {
                        const rv = Math.round(r2.r + (255 - r2.r) * m);
                        const gv = Math.round(r2.g + (255 - r2.g) * m);
                        const bv = Math.round(r2.b + (255 - r2.b) * m);
                        return `#${rv.toString(16).padStart(2,"0")}${gv.toString(16).padStart(2,"0")}${bv.toString(16).padStart(2,"0")}`;
                      }
                      const a = Math.abs(m);
                      const rv = Math.round(r2.r * (1 - a));
                      const gv = Math.round(r2.g * (1 - a));
                      const bv = Math.round(r2.b * (1 - a));
                      return `#${rv.toString(16).padStart(2,"0")}${gv.toString(16).padStart(2,"0")}${bv.toString(16).padStart(2,"0")}`;
                    };
                    return (
                      <div key={label} className="flex-1 text-center">
                        <div className="w-full h-6 rounded-lg" style={{ backgroundColor: makeColor(mix) }} />
                        <p className="text-[9px] text-gray-400 mt-1">{label}</p>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Sidebar */}
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-2">
                  Sidebar & navigation background
                </label>
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex items-center gap-2 border border-gray-200 rounded-xl px-3 py-2 bg-white">
                    <input
                      type="color"
                      value={local.sidebarColor}
                      onChange={e => update({ sidebarColor: e.target.value })}
                      className="w-6 h-6 rounded cursor-pointer border-0 bg-transparent p-0"
                    />
                    <span className="text-xs font-mono text-gray-700 w-16">{local.sidebarColor}</span>
                  </div>
                  <div className="flex gap-1.5 flex-wrap">
                    {[
                      "#0D1B4B", "#1e3a5f", "#1e1b4b", "#052e16", "#1c0a00",
                      "#0f172a", "#111827", "#1c1400", "#000000", "#1a1a1a",
                    ].map(c => (
                      <ColorSwatch
                        key={c} color={c} label={c}
                        selected={local.sidebarColor === c}
                        onClick={() => update({ sidebarColor: c })}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </Section>

          {/* Typography */}
          <Section icon={<Type size={16} />} title="Typography" sub="Font applied across the entire platform">
            <div className="grid grid-cols-2 gap-3">
              {FONT_OPTIONS.map(font => (
                <button
                  key={font}
                  onClick={() => update({ fontFamily: font })}
                  className={cn(
                    "px-4 py-3 rounded-xl border-2 text-left transition-all",
                    local.fontFamily === font
                      ? "border-gray-700 bg-gray-50 shadow-sm"
                      : "border-gray-200 bg-white hover:border-gray-300"
                  )}
                  style={{ fontFamily: `"${font}", ui-sans-serif, system-ui, sans-serif` }}
                >
                  <p className="text-sm font-semibold text-gray-900">{font}</p>
                  <p className="text-xs text-gray-500 mt-0.5">The quick brown fox</p>
                </button>
              ))}
            </div>
            {local.fontFamily !== "Inter" && (
              <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-xl text-xs text-blue-700 flex gap-2">
                <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
                The font will load from Google Fonts on next page refresh.
              </div>
            )}
          </Section>

          {/* Shape / radius */}
          <Section icon={<Sliders size={16} />} title="Shape" sub="Border radius applied to cards, buttons, and inputs">
            <div className="grid grid-cols-3 gap-3">
              {[
                { id: "sharp",   label: "Sharp",   radius: "2px",     preview: "w-full h-10 bg-gray-200" },
                { id: "rounded", label: "Rounded", radius: "10px",    preview: "w-full h-10 bg-gray-200" },
                { id: "pill",    label: "Pill",    radius: "9999px",  preview: "w-full h-10 bg-gray-200" },
              ].map(opt => (
                <button
                  key={opt.id}
                  onClick={() => update({ radiusScale: opt.id as BrandTheme["radiusScale"] })}
                  className={cn(
                    "flex flex-col items-center gap-3 p-4 rounded-2xl border-2 transition-all",
                    local.radiusScale === opt.id
                      ? "border-gray-700 bg-gray-50"
                      : "border-gray-200 bg-white hover:border-gray-300"
                  )}
                >
                  {/* Visual representation */}
                  <div
                    className="w-full h-8 flex items-center justify-center text-[11px] font-semibold text-gray-600"
                    style={{
                      backgroundColor: local.primaryColor,
                      borderRadius: opt.radius,
                      color: brightness(local.primaryColor) > 160 ? "#111" : "#fff",
                    }}
                  >
                    Button
                  </div>
                  <div className="text-xs font-semibold text-gray-700">{opt.label}</div>
                  {local.radiusScale === opt.id && <Check size={12} className="text-gray-600" />}
                </button>
              ))}
            </div>
          </Section>

          {/* Save footer */}
          <div className="flex items-center justify-between bg-white rounded-2xl border border-gray-100 p-4">
            <p className="text-xs text-gray-400">Changes are previewed instantly. Click Save to persist across sessions.</p>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors disabled:opacity-50"
              style={{
                backgroundColor: saved ? undefined : local.primaryColor,
                color: saved ? undefined : brightness(local.primaryColor) > 160 ? "#111" : "#fff",
                ...(saved ? { backgroundColor: "#f0fdf4", color: "#15803d", border: "1px solid #bbf7d0" } : {})
              }}
            >
              {isSaving ? <Loader2 size={14} className="animate-spin" /> : saved ? <Check size={14} /> : <Palette size={14} />}
              {saved ? "Saved!" : "Save brand settings"}
            </button>
          </div>
        </div>

        {/* Live Preview panel */}
        <div className="w-80 flex-shrink-0 border-l border-gray-100 bg-white flex flex-col">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
            <Eye size={14} className="text-gray-400" />
            <p className="text-xs font-semibold text-gray-700">Live preview</p>
            <span className="ml-auto text-[10px] text-gray-400">Updates in real time</span>
          </div>
          <div className="flex-1 p-4">
            <div className="rounded-2xl overflow-hidden border border-gray-200 shadow-sm h-full" style={{ minHeight: "460px" }}>
              <SidebarPreview t={local} />
            </div>
          </div>
          <div className="px-4 pb-4">
            <div className="bg-gray-50 rounded-xl p-3 text-xs text-gray-500 space-y-1">
              <p className="font-semibold text-gray-700 mb-1.5">Applied to</p>
              {[
                "Sidebar background & icons",
                "Top navigation bar",
                "Primary buttons & CTAs",
                "Active nav indicators",
                "Badges & status pills",
                "Focus rings & borders",
                "Font across all pages",
              ].map(item => (
                <div key={item} className="flex items-center gap-2">
                  <Check size={9} className="text-green-500 flex-shrink-0" />
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
