"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserCircle, Camera, Save, Lock, Bell, Trash2, CheckCircle, AlertCircle, Loader2, Eye, EyeOff, Shield } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { UserAvatar } from "@/components/crm/UserAvatar";

export default function ProfilePage() {
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-surface)]">
      <div className="px-6 py-5 bg-white border-b border-[var(--haip-border)]">
        <h1 className="haip-page-title">Your Profile</h1>
        <p className="text-sm text-[var(--haip-fg-subtle)] mt-0.5">Manage your personal information, password, and preferences</p>
      </div>
      <div className="p-6 max-w-2xl space-y-6">
        <PersonalInfoCard />
        <ChangePasswordCard />
        <PreferencesCard />
        <DangerZoneCard />
      </div>
    </div>
  );
}

/* ── Personal Info ──────────────────────────────────────────────────────────── */
function PersonalInfoCard() {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  // Real bug this replaces: a useState initializer only runs once, on the
  // first render. Seeding it from useSession() -- which is commonly still
  // `undefined` on that very first render -- baked the hardcoded fallback
  // literals ("Sharath D." / "sharath@ratha.in") in permanently for
  // whoever happened to load the page before the session resolved,
  // regardless of who was actually logged in. `phone` was worse: hardcoded
  // outright, never read from anywhere real. The actual backend fetch
  // (`me`, below) was already correct -- its result just never made it
  // into this form. Fixed by starting blank and syncing from `me` once it
  // loads (the effect further down), so the form always reflects the
  // real, current user.
  const [form, setForm] = useState({ name: "", email: "", phone: "", role: "", bio: "" });
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(false);

  const { data: me } = useQuery({
    queryKey: ["users", "me"],
    queryFn: () => api.get("/users/me").then(r => r.data),
  });

  useEffect(() => {
    if (!me) return;
    setForm(f => ({ ...f, name: me.name ?? "", email: me.email ?? "", phone: me.phone ?? "", role: me.role ?? "" }));
  }, [me]);

  const uploadAvatar = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api.post("/users/me/avatar", body, {
        headers: { "Content-Type": "multipart/form-data" },
      }).then(r => r.data);
    },
    onSuccess: () => {
      setAvatarError(null);
      qc.invalidateQueries({ queryKey: ["users", "me"] });
    },
    onError: (err: any) => {
      setAvatarError(err?.response?.data?.detail || "Upload failed. Try a JPEG/PNG/WebP under 5 MB.");
    },
  });

  async function handleSave() {
    setLoading(true);
    try {
      await api.patch("/users/me", { name: form.name, phone: form.phone, bio: form.bio });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch { /* silent */ }
    finally { setLoading(false); }
  }

  return (
    <Card title="Personal information">
      <div className="flex items-start gap-6 mb-6">
        {/* Avatar */}
        <div className="relative flex-shrink-0">
          <UserAvatar
            name={form.name}
            photoUrl={me?.avatar_url}
            size="xl"
            className="shadow-lg shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadAvatar.isPending}
            className="absolute -bottom-1 -right-1 w-7 h-7 bg-white border border-[var(--haip-border)] rounded-lg flex items-center justify-center shadow-sm hover:bg-[var(--haip-surface)] transition-colors disabled:opacity-50"
          >
            {uploadAvatar.isPending
              ? <Loader2 size={13} className="text-[var(--haip-fg-subtle)] animate-spin" />
              : <Camera size={13} className="text-[var(--haip-fg-subtle)]" />}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={e => {
              const file = e.target.files?.[0];
              if (file) uploadAvatar.mutate(file);
              e.target.value = "";
            }}
          />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-base font-bold text-[var(--haip-fg)]">{form.name}</p>
          <p className="text-sm text-[var(--haip-fg-subtle)] mt-0.5">{form.email}</p>
          <span className="mt-1.5 inline-block text-[11px] bg-[var(--haip-primary-tint)] text-primary px-2 py-0.5 rounded-full font-semibold capitalize">
            {form.role}
          </span>
          {avatarError && (
            <p className="text-xs text-red-600 mt-1.5 flex items-center gap-1">
              <AlertCircle size={12} /> {avatarError}
            </p>
          )}
        </div>
      </div>

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Full name" value={form.name} onChange={v => { setForm(f => ({...f, name: v})); setSaved(false); }} />
          <Field label="Email address" value={form.email} onChange={() => {}} disabled hint="Contact support to change your email" />
        </div>
        <Field label="Phone number" value={form.phone} onChange={v => { setForm(f => ({...f, phone: v})); setSaved(false); }} placeholder="+91 98765 43210" />
        <div>
          <label className="block text-sm font-medium text-[var(--haip-fg-2)] mb-1">Bio <span className="text-[var(--haip-fg-subtle)] font-normal">(optional)</span></label>
          <textarea
            value={form.bio}
            onChange={e => { setForm(f => ({...f, bio: e.target.value})); setSaved(false); }}
            placeholder="Short description visible to your team…"
            rows={2}
            className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 bg-white resize-none"
          />
        </div>
      </div>

      <button
        onClick={handleSave}
        disabled={loading}
        className={cn(
          "mt-5 flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-colors",
          saved ? "bg-green-50 text-green-700 border border-green-200" : "bg-primary text-white hover:bg-primary disabled:opacity-50"
        )}
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : saved ? <CheckCircle size={14} /> : <Save size={14} />}
        {saved ? "Saved!" : "Save profile"}
      </button>
    </Card>
  );
}

/* ── Change Password ─────────────────────────────────────────────────────────── */
function ChangePasswordCard() {
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [show, setShow] = useState({ current: false, next: false, confirm: false });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const strength = (() => {
    const p = form.next;
    if (!p) return 0;
    let s = 0;
    if (p.length >= 8) s++;
    if (/[A-Z]/.test(p)) s++;
    if (/[0-9]/.test(p)) s++;
    if (/[^A-Za-z0-9]/.test(p)) s++;
    return s;
  })();

  const strengthLabel = ["", "Weak", "Fair", "Good", "Strong"][strength];
  const strengthColor = ["", "bg-red-400", "bg-amber-400", "bg-blue-400", "bg-green-500"][strength];

  async function handleSubmit() {
    setError("");
    if (form.next !== form.confirm) return setError("Passwords do not match");
    if (form.next.length < 8) return setError("Password must be at least 8 characters");
    setLoading(true);
    try {
      await api.post("/auth/change-password", { current_password: form.current, new_password: form.next });
      setSuccess(true);
      setForm({ current: "", next: "", confirm: "" });
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "Failed to change password");
    } finally { setLoading(false); }
  }

  return (
    <Card title="Change password">
      {success ? (
        <div className="flex items-center gap-3 p-4 bg-green-50 border border-green-200 rounded-xl text-green-700">
          <CheckCircle size={16} />
          <div>
            <p className="text-sm font-semibold">Password updated successfully</p>
            <p className="text-xs mt-0.5 text-green-600">You'll be asked to sign in on other devices.</p>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <PasswordField label="Current password" value={form.current} onChange={v => { setForm(f => ({...f, current: v})); setError(""); }}
            show={show.current} onToggle={() => setShow(s => ({...s, current: !s.current}))} />
          <PasswordField label="New password" value={form.next} onChange={v => { setForm(f => ({...f, next: v})); setError(""); }}
            show={show.next} onToggle={() => setShow(s => ({...s, next: !s.next}))} />

          {form.next && (
            <div>
              <div className="flex gap-1 mb-1">
                {[1,2,3,4].map(i => (
                  <div key={i} className={cn("h-1 flex-1 rounded-full transition-colors", i <= strength ? strengthColor : "bg-[var(--haip-border)]")} />
                ))}
              </div>
              <p className={cn("text-[11px] font-medium", strength <= 1 ? "text-red-500" : strength === 2 ? "text-amber-500" : strength === 3 ? "text-blue-500" : "text-green-500")}>
                {strengthLabel}
              </p>
            </div>
          )}

          <PasswordField label="Confirm new password" value={form.confirm} onChange={v => { setForm(f => ({...f, confirm: v})); setError(""); }}
            show={show.confirm} onToggle={() => setShow(s => ({...s, confirm: !s.confirm}))} />

          {error && (
            <div className="flex items-center gap-2 text-xs text-red-600">
              <AlertCircle size={13} /> {error}
            </div>
          )}

          <button
            onClick={handleSubmit}
            disabled={loading || !form.current || !form.next || !form.confirm}
            className="flex items-center gap-2 px-5 py-2 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-[var(--haip-primary-hover)] disabled:opacity-50 transition-colors"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />}
            Update password
          </button>
        </div>
      )}
    </Card>
  );
}

/* ── Preferences ─────────────────────────────────────────────────────────────── */
function PreferencesCard() {
  const [prefs, setPrefs] = useState({ timezone: "Asia/Kolkata", language: "en", theme: "light" });
  const [saved, setSaved] = useState(false);

  return (
    <Card title="Display preferences">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-[var(--haip-fg-2)] mb-1">Timezone</label>
            <select value={prefs.timezone} onChange={e => { setPrefs(p => ({...p, timezone: e.target.value})); setSaved(false); }}
              className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 bg-white">
              <option value="Asia/Kolkata">Asia/Kolkata (IST)</option>
              <option value="Asia/Dubai">Asia/Dubai (GST)</option>
              <option value="Asia/Singapore">Asia/Singapore (SGT)</option>
              <option value="Europe/London">Europe/London</option>
              <option value="America/New_York">America/New_York</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--haip-fg-2)] mb-1">Language</label>
            <select value={prefs.language} onChange={e => { setPrefs(p => ({...p, language: e.target.value})); setSaved(false); }}
              className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 bg-white">
              <option value="en">English</option>
              <option value="hi">Hindi</option>
              <option value="ta">Tamil</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--haip-fg-2)] mb-2">Theme</label>
          <div className="flex gap-3">
            {[
              { id: "light", label: "Light", preview: "bg-white border-2 border-[var(--haip-border)]" },
              { id: "dark",  label: "Dark",  preview: "bg-[#0B1F3A] border-2 border-gray-600" },
              { id: "system",label: "System",preview: "bg-gradient-to-r from-white to-[#0B1F3A] border-2 border-[var(--haip-border-strong)]" },
            ].map(t => (
              <label key={t.id} className="cursor-pointer flex-1">
                <input type="radio" name="theme" value={t.id} checked={prefs.theme === t.id} onChange={() => { setPrefs(p => ({...p, theme: t.id})); setSaved(false); }} className="sr-only" />
                <div className={cn("rounded-xl p-3 flex flex-col items-center gap-2 transition-all",
                  prefs.theme === t.id ? "ring-2 ring-primary shadow-sm" : "hover:ring-1 ring-[var(--haip-border)]"
                )}>
                  <div className={cn("w-full h-8 rounded-lg", t.preview)} />
                  <span className="text-xs font-medium text-[var(--haip-fg-2)]">{t.label}</span>
                </div>
              </label>
            ))}
          </div>
          <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-1.5">Dark mode coming soon.</p>
        </div>
      </div>

      <button onClick={() => setSaved(true)} className={cn(
        "mt-5 flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-colors",
        saved ? "bg-green-50 text-green-700 border border-green-200" : "bg-primary text-white hover:bg-primary"
      )}>
        {saved ? <><CheckCircle size={14} /> Saved!</> : <><Save size={14} /> Save preferences</>}
      </button>
    </Card>
  );
}

/* ── Danger Zone ─────────────────────────────────────────────────────────────── */
function DangerZoneCard() {
  const [confirm, setConfirm] = useState("");

  return (
    <Card title="Danger zone">
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4 p-4 border border-red-200 rounded-xl bg-red-50">
          <div>
            <p className="text-sm font-semibold text-red-800">Delete my account</p>
            <p className="text-xs text-red-600 mt-0.5">
              Permanently removes your user account from this workspace. Workspace data is retained.
              This cannot be undone.
            </p>
          </div>
          <button className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 border border-red-300 text-red-700 rounded-lg text-xs font-medium hover:bg-red-100 transition-colors">
            <Trash2 size={12} />
            Delete account
          </button>
        </div>

        <div className="flex items-start justify-between gap-4 p-4 border border-amber-200 rounded-xl bg-amber-50">
          <div>
            <p className="text-sm font-semibold text-amber-800">Sign out all devices</p>
            <p className="text-xs text-amber-600 mt-0.5">Invalidates all refresh tokens and signs you out everywhere.</p>
          </div>
          <button className="flex-shrink-0 px-3 py-1.5 border border-amber-300 text-amber-700 rounded-lg text-xs font-medium hover:bg-amber-100 transition-colors">
            Sign out all
          </button>
        </div>
      </div>
    </Card>
  );
}

/* ── Shared ─────────────────────────────────────────────────────────────────── */
function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-[var(--haip-border)] shadow-sm p-5">
      {title && <p className="text-sm font-semibold text-[var(--haip-fg)] mb-4">{title}</p>}
      {children}
    </div>
  );
}

function Field({ label, value, onChange, placeholder, disabled, hint, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; disabled?: boolean; hint?: string; type?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-[var(--haip-fg-2)] mb-1">{label}</label>
      <input
        type={type} value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} disabled={disabled}
        className={cn(
          "w-full px-3 py-2 border border-[var(--haip-border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30",
          disabled ? "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)] cursor-not-allowed" : "bg-white"
        )}
      />
      {hint && <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">{hint}</p>}
    </div>
  );
}

function PasswordField({ label, value, onChange, show, onToggle }: {
  label: string; value: string; onChange: (v: string) => void;
  show: boolean; onToggle: () => void;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-[var(--haip-fg-2)] mb-1">{label}</label>
      <div className="relative">
        <input
          type={show ? "text" : "password"} value={value} onChange={e => onChange(e.target.value)}
          className="w-full px-3 py-2 pr-10 border border-[var(--haip-border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 bg-white"
        />
        <button type="button" onClick={onToggle} className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]">
          {show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
    </div>
  );
}
