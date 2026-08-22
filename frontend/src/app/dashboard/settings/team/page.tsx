"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Users, UserPlus, Mail, Shield, Crown, Eye,
  Clock, CheckCircle2, XCircle, ChevronDown,
  Copy, Trash2, Loader2, AlertCircle, X,
  Settings, RefreshCw, MoreHorizontal, MessageSquare, PhoneCall,
} from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TeamMember {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  role: string;
  is_active: boolean;
  is_mfa_enabled: boolean;
  property_scope: string[];
  ivr_call_routing_enabled: boolean;
}

interface Invitation {
  id: string;
  email: string;
  name: string;
  role: string;
  token: string;
  is_accepted: boolean;
  is_revoked: boolean;
  expires_at: string;
  invited_by_name: string | null;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const ROLES = [
  { value: "owner",        label: "Owner",        description: "Full access to all features and billing", icon: <Crown size={13} className="text-amber-500" /> },
  { value: "manager",      label: "Manager",       description: "Manage team, guests, and operations", icon: <Shield size={13} className="text-blue-500" /> },
  { value: "concierge",    label: "Concierge",     description: "Handle calls, inbox, and guest requests", icon: <Users size={13} className="text-teal-500" /> },
  { value: "reservations", label: "Reservations",  description: "Manage inquiries and guest bookings", icon: <Settings size={13} className="text-purple-500" /> },
  { value: "marketing",    label: "Marketing",     description: "Campaigns, templates, and messaging", icon: <Mail size={13} className="text-pink-500" /> },
  { value: "compliance",   label: "Compliance",    description: "Audit logs and data compliance only", icon: <Eye size={13} className="text-gray-500" /> },
  { value: "read_only",    label: "Read Only",     description: "View-only access to all data", icon: <Eye size={13} className="text-gray-400" /> },
];

const ROLE_COLORS: Record<string, string> = {
  owner:        "bg-amber-50 text-amber-700 border-amber-200",
  manager:      "bg-blue-50 text-blue-700 border-blue-200",
  concierge:    "bg-teal-50 text-teal-700 border-teal-200",
  reservations: "bg-purple-50 text-purple-700 border-purple-200",
  marketing:    "bg-pink-50 text-pink-700 border-pink-200",
  compliance:   "bg-gray-50 text-gray-700 border-gray-200",
  read_only:    "bg-gray-50 text-gray-500 border-gray-200",
  foh:          "bg-indigo-50 text-indigo-700 border-indigo-200",
};

// ─── Role badge ───────────────────────────────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  const cls = ROLE_COLORS[role] ?? "bg-gray-50 text-gray-600 border-gray-200";
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border capitalize", cls)}>
      {role.replace("_", " ")}
    </span>
  );
}

// ─── Avatar ───────────────────────────────────────────────────────────────────

function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  const initials = name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
  const colors = ["bg-teal-500", "bg-blue-500", "bg-purple-500", "bg-amber-500", "bg-pink-500"];
  const color = colors[name.charCodeAt(0) % colors.length];
  return (
    <div className={cn(
      "rounded-full flex items-center justify-center text-white font-bold flex-shrink-0",
      color,
      size === "sm" ? "w-7 h-7 text-[10px]" : "w-9 h-9 text-xs"
    )}>
      {initials}
    </div>
  );
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn(
      "fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-green-50 text-green-800 border-green-200" : "bg-red-50 text-red-800 border-red-200"
    )}>
      {type === "success" ? <CheckCircle2 size={15} className="text-green-600" /> : <AlertCircle size={15} className="text-red-600" />}
      <span className="flex-1">{msg}</span>
      <button onClick={onClose}><X size={13} className="opacity-60 hover:opacity-100" /></button>
    </div>
  );
}

// ─── Invite Modal ─────────────────────────────────────────────────────────────

function InviteModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (inv: Invitation) => void }) {
  const [form, setForm] = useState({ name: "", email: "", role: "concierge" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.email.trim()) { setError("Name and email are required."); return; }
    setError("");
    setSubmitting(true);
    try {
      const res = await api.post("/users/invitations", form);
      onSuccess(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to send invitation.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-900">Invite team member</h2>
            <p className="text-xs text-gray-400 mt-0.5">They'll receive an invitation link to join your workspace.</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-700 block mb-1.5">Full name <span className="text-red-500">*</span></label>
              <input
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="Ravi Kumar"
                className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-700 block mb-1.5">Work email <span className="text-red-500">*</span></label>
              <input
                type="email"
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                placeholder="ravi@villaname.com"
                className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Role <span className="text-red-500">*</span></label>
            <div className="grid grid-cols-1 gap-1.5">
              {ROLES.map(r => (
                <label
                  key={r.value}
                  className={cn(
                    "flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-all",
                    form.role === r.value
                      ? "border-teal-400 bg-teal-50/50"
                      : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                  )}
                >
                  <input type="radio" name="role" value={r.value} checked={form.role === r.value}
                    onChange={() => setForm(f => ({ ...f, role: r.value }))} className="sr-only" />
                  <div className={cn("w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0",
                    form.role === r.value ? "border-teal-500" : "border-gray-300"
                  )}>
                    {form.role === r.value && <div className="w-2 h-2 rounded-full bg-teal-500" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      {r.icon}
                      <span className="text-xs font-semibold text-gray-800">{r.label}</span>
                    </div>
                    <p className="text-[10px] text-gray-400 mt-0.5">{r.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 text-xs text-red-700 bg-red-50 rounded-lg px-3 py-2">
              <AlertCircle size={13} /> {error}
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors">
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 py-2.5 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
              Send Invitation
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Invitation Link Modal ────────────────────────────────────────────────────

function buildWaLink(inviteLink: string, name: string, role: string, tenantName = "our team"): string {
  const roleLabel = role.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  const msg =
    `Hi ${name || "there"} 👋\n\nYou've been invited to join *${tenantName}* on HAIP as a *${roleLabel}*.\n\nClick the link to accept:\n${inviteLink}\n\nThis link expires in 24 hours. See you on the platform! 🙌`;
  return `https://wa.me/?text=${encodeURIComponent(msg)}`;
}

function InvitationLinkModal({ invitation, onClose }: { invitation: Invitation; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const link = typeof window !== "undefined"
    ? `${window.location.origin}/join?token=${invitation.token}`
    : `https://yourapp.com/join?token=${invitation.token}`;

  const waLink = buildWaLink(link, invitation.name, invitation.role);

  const copy = () => {
    navigator.clipboard.writeText(link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-900">Invitation created!</h2>
            <p className="text-xs text-gray-400 mt-0.5">Share this link with {invitation.name}</p>
          </div>
          <button onClick={onClose}><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <div className="bg-teal-50 rounded-xl p-4 text-center">
            <CheckCircle2 size={28} className="text-teal-500 mx-auto mb-2" />
            <p className="text-sm font-semibold text-gray-800">{invitation.name} has been invited as <span className="capitalize">{invitation.role.replace("_", " ")}</span></p>
            <p className="text-xs text-gray-500 mt-1">Link expires in 7 days</p>
          </div>

          {/* O10 — WhatsApp share button */}
          <a
            href={waLink}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl bg-green-500 hover:bg-green-600 text-white text-sm font-semibold transition-colors"
          >
            <MessageSquare size={15} />
            Send via WhatsApp
          </a>

          <div>
            <p className="text-xs font-semibold text-gray-700 mb-1.5">Or copy the link</p>
            <div className="flex items-center gap-2 bg-gray-50 rounded-xl border border-gray-200 px-3 py-2.5">
              <code className="text-[11px] text-gray-600 flex-1 truncate font-mono">{link}</code>
              <button
                onClick={copy}
                className={cn("flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-lg transition-colors flex-shrink-0",
                  copied ? "text-green-600 bg-green-50" : "text-teal-600 hover:bg-teal-50"
                )}
              >
                {copied ? <CheckCircle2 size={12} /> : <Copy size={12} />}
                {copied ? "Copied!" : "Copy"}
              </button>
            </div>
            <p className="text-[10px] text-gray-400 mt-1.5">
              You can also find this link in the Pending Invitations section below.
            </p>
          </div>
        </div>
        <div className="px-6 pb-5">
          <button onClick={onClose} className="w-full py-2.5 bg-[#0F766E] text-white rounded-xl text-sm font-semibold hover:bg-[#0d6660] transition-colors">
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Role Dropdown ────────────────────────────────────────────────────────────

function RoleDropdown({ currentRole, userId, onChanged }: {
  currentRole: string;
  userId: string;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [roleError, setRoleError] = useState("");

  const changeRole = async (role: string) => {
    if (role === currentRole) { setOpen(false); return; }
    setLoading(true);
    setRoleError("");
    try {
      await api.patch(`/users/${userId}`, { role });
      onChanged();
    } catch (err: any) {
      const msg = err?.response?.data?.detail || "Failed to update role. Please try again.";
      setRoleError(msg);
    }
    setLoading(false);
    setOpen(false);
  };

  return (
    <div className="relative">
      <button
        onClick={() => { setOpen(v => !v); setRoleError(""); }}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
        disabled={loading}
      >
        <RoleBadge role={currentRole} />
        {loading ? <Loader2 size={11} className="animate-spin" /> : <ChevronDown size={11} />}
      </button>
      {roleError && (
        <p className="absolute right-0 top-full mt-1 text-[10px] text-red-500 bg-red-50 border border-red-200 rounded-lg px-2 py-1 z-30 whitespace-nowrap shadow">
          {roleError}
        </p>
      )}
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1.5 z-20 bg-white border border-gray-200 rounded-xl shadow-lg w-52 py-1 overflow-hidden">
            {ROLES.map(r => (
              <button
                key={r.value}
                onClick={() => changeRole(r.value)}
                className={cn(
                  "w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 transition-colors",
                  r.value === currentRole && "bg-teal-50"
                )}
              >
                {r.icon}
                <div>
                  <div className="font-semibold text-gray-800">{r.label}</div>
                  <div className="text-[10px] text-gray-400">{r.description}</div>
                </div>
                {r.value === currentRole && <CheckCircle2 size={11} className="text-teal-500 ml-auto" />}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TeamPage() {
  const queryClient = useQueryClient();
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [newInvitation, setNewInvitation] = useState<Invitation | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [tab, setTab] = useState<"members" | "invitations">("members");

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: members = [], isLoading: membersLoading } = useQuery<TeamMember[]>({
    queryKey: ["team-members"],
    queryFn: () => api.get("/users").then(r => r.data),
    staleTime: 30_000,
  });

  const { data: invitations = [], isLoading: invitationsLoading } = useQuery<Invitation[]>({
    queryKey: ["team-invitations"],
    queryFn: () => api.get("/users/invitations").then(r => r.data).catch(() => []),
    staleTime: 30_000,
  });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      api.patch(`/users/${id}`, { is_active: active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team-members"] });
      showToast("Member updated.", "success");
    },
  });

  const toggleIvrRoutingMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.patch(`/users/${id}`, { ivr_call_routing_enabled: enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team-members"] });
      showToast("Call routing updated.", "success");
    },
  });

  const revokeInviteMutation = useMutation({
    mutationFn: (token: string) => api.delete(`/users/invitations/${token}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team-invitations"] });
      showToast("Invitation revoked.", "success");
    },
  });

  const pendingInvitations = invitations.filter(i => !i.is_accepted && !i.is_revoked);
  const activeMembers = members.filter(m => m.is_active);
  const inactiveMembers = members.filter(m => !m.is_active);

  const handleInviteSuccess = (inv: Invitation) => {
    queryClient.invalidateQueries({ queryKey: ["team-invitations"] });
    setShowInviteModal(false);
    setNewInvitation(inv);
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="haip-page-title">Team</h1>
            <p className="text-sm text-gray-400 mt-0.5">
              {activeMembers.length} active member{activeMembers.length !== 1 ? "s" : ""}
              {pendingInvitations.length > 0 && ` · ${pendingInvitations.length} pending invite${pendingInvitations.length !== 1 ? "s" : ""}`}
            </p>
          </div>
          <button
            onClick={() => setShowInviteModal(true)}
            className="flex items-center gap-2 bg-teal-500 text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors shadow-sm shadow-teal-200"
          >
            <UserPlus size={15} /> Invite member
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mt-4">
          {(["members", "invitations"] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium capitalize transition-colors",
                tab === t ? "bg-[#0F766E] text-white" : "text-gray-500 hover:bg-gray-100"
              )}
            >
              {t === "invitations" ? `Pending Invites ${pendingInvitations.length > 0 ? `(${pendingInvitations.length})` : ""}` : "Members"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {/* Members tab */}
        {tab === "members" && (
          <div className="space-y-3">
            {membersLoading ? (
              Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-2xl" />)
            ) : members.length === 0 ? (
              <div className="py-16 text-center text-sm text-gray-400">
                <Users size={32} className="mx-auto mb-3 text-gray-300" />
                No team members yet — invite your first member above.
              </div>
            ) : (
              <>
                {activeMembers.length > 0 && (
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-gray-400 font-bold mb-2">Active ({activeMembers.length})</p>
                    <div className="space-y-2">
                      {activeMembers.map(member => (
                        <MemberRow
                          key={member.id}
                          member={member}
                          onRoleChanged={() => queryClient.invalidateQueries({ queryKey: ["team-members"] })}
                          onToggleActive={(active) => toggleActiveMutation.mutate({ id: member.id, active })}
                          onToggleIvrRouting={(enabled) => toggleIvrRoutingMutation.mutate({ id: member.id, enabled })}
                        />
                      ))}
                    </div>
                  </div>
                )}
                {inactiveMembers.length > 0 && (
                  <div className="mt-6">
                    <p className="text-[10px] uppercase tracking-widest text-gray-400 font-bold mb-2">Deactivated ({inactiveMembers.length})</p>
                    <div className="space-y-2">
                      {inactiveMembers.map(member => (
                        <MemberRow
                          key={member.id}
                          member={member}
                          onRoleChanged={() => queryClient.invalidateQueries({ queryKey: ["team-members"] })}
                          onToggleActive={(active) => toggleActiveMutation.mutate({ id: member.id, active })}
                          onToggleIvrRouting={(enabled) => toggleIvrRoutingMutation.mutate({ id: member.id, enabled })}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Invitations tab */}
        {tab === "invitations" && (
          <div>
            {invitationsLoading ? (
              Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-2xl mb-2" />)
            ) : invitations.length === 0 ? (
              <div className="py-16 text-center text-sm text-gray-400">
                <Mail size={32} className="mx-auto mb-3 text-gray-300" />
                No invitations sent yet.
              </div>
            ) : (
              <div className="space-y-2">
                {invitations.map(inv => (
                  <InvitationRow
                    key={inv.id}
                    invitation={inv}
                    onRevoke={() => revokeInviteMutation.mutate(inv.token)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Role guide */}
        <div className="mt-8 haip-card p-5">
          <p className="text-xs font-bold text-gray-700 mb-3">Role permissions guide</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {ROLES.map(r => (
              <div key={r.value} className="flex items-start gap-2.5 p-2.5 rounded-xl bg-gray-50">
                <div className="mt-0.5">{r.icon}</div>
                <div>
                  <p className="text-xs font-semibold text-gray-800">{r.label}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5 leading-relaxed">{r.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {showInviteModal && (
        <InviteModal onClose={() => setShowInviteModal(false)} onSuccess={handleInviteSuccess} />
      )}
      {newInvitation && (
        <InvitationLinkModal invitation={newInvitation} onClose={() => setNewInvitation(null)} />
      )}
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}

// ─── Member Row ───────────────────────────────────────────────────────────────

function MemberRow({ member, onRoleChanged, onToggleActive, onToggleIvrRouting }: {
  member: TeamMember;
  onRoleChanged: () => void;
  onToggleActive: (active: boolean) => void;
  onToggleIvrRouting: (enabled: boolean) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const hasPhone = !!member.phone;

  return (
    <div className={cn(
      "haip-card px-4 py-3.5 flex items-center gap-4 hover:shadow-sm transition-shadow",
      !member.is_active && "opacity-60"
    )}>
      <Avatar name={member.name} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-sm font-semibold text-gray-900 truncate">{member.name}</span>
          {member.is_mfa_enabled && (
            <span title="MFA enabled"><Shield size={11} className="text-teal-500 flex-shrink-0" /></span>
          )}
        </div>
        <span className="text-xs text-gray-400 truncate">{member.email}</span>
      </div>

      <button
        onClick={() => hasPhone && onToggleIvrRouting(!member.ivr_call_routing_enabled)}
        disabled={!hasPhone}
        title={
          !hasPhone
            ? "Add a phone number in this member's profile to enable call routing"
            : member.ivr_call_routing_enabled
              ? "Rings on inbound calls (round robin / parallel) — click to remove"
              : "Not in the call-routing pool — click to add"
        }
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors flex-shrink-0",
          !hasPhone
            ? "text-gray-300 border-gray-100 cursor-not-allowed"
            : member.ivr_call_routing_enabled
              ? "text-teal-700 bg-teal-50 border-teal-200 hover:bg-teal-100"
              : "text-gray-400 bg-white border-gray-200 hover:border-gray-300"
        )}
      >
        <PhoneCall size={12} />
        IVR calls
      </button>

      <RoleDropdown currentRole={member.role} userId={member.id} onChanged={onRoleChanged} />

      <div className="relative flex-shrink-0">
        <button
          onClick={() => setMenuOpen(v => !v)}
          className="text-gray-400 hover:text-gray-600 transition-colors p-1 rounded-lg hover:bg-gray-100"
        >
          <MoreHorizontal size={15} />
        </button>
        {menuOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            <div className="absolute right-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded-xl shadow-lg w-40 py-1 overflow-hidden">
              <button
                onClick={() => { onToggleActive(!member.is_active); setMenuOpen(false); }}
                className="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 transition-colors"
              >
                {member.is_active ? (
                  <><XCircle size={13} className="text-red-400" /> Deactivate</>
                ) : (
                  <><CheckCircle2 size={13} className="text-green-500" /> Reactivate</>
                )}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Invitation Row ───────────────────────────────────────────────────────────

function InvitationRow({ invitation, onRevoke }: { invitation: Invitation; onRevoke: () => void }) {
  const [copied, setCopied] = useState(false);
  const isExpired = new Date(invitation.expires_at) < new Date();
  const link = typeof window !== "undefined"
    ? `${window.location.origin}/join?token=${invitation.token}`
    : "";

  const copy = () => {
    navigator.clipboard.writeText(link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const statusInfo = invitation.is_accepted
    ? { label: "Accepted", cls: "bg-green-50 text-green-700 border-green-200", icon: <CheckCircle2 size={10} /> }
    : invitation.is_revoked
    ? { label: "Revoked", cls: "bg-gray-50 text-gray-500 border-gray-200", icon: <XCircle size={10} /> }
    : isExpired
    ? { label: "Expired", cls: "bg-red-50 text-red-600 border-red-200", icon: <Clock size={10} /> }
    : { label: "Pending", cls: "bg-amber-50 text-amber-700 border-amber-200", icon: <Clock size={10} /> };

  return (
    <div className="haip-card px-4 py-3.5 flex items-center gap-4 hover:shadow-sm transition-shadow">
      <div className="w-9 h-9 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0">
        <Mail size={14} className="text-gray-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-sm font-semibold text-gray-900 truncate">{invitation.name}</span>
          <RoleBadge role={invitation.role} />
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span className="truncate">{invitation.email}</span>
          {invitation.invited_by_name && <span>· invited by {invitation.invited_by_name}</span>}
        </div>
      </div>

      <span className={cn("inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border flex-shrink-0", statusInfo.cls)}>
        {statusInfo.icon} {statusInfo.label}
      </span>

      {!invitation.is_accepted && !invitation.is_revoked && (
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {/* O10 — Share via WhatsApp */}
          <a
            href={buildWaLink(link, invitation.name, invitation.role)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-green-600 hover:text-green-800 flex items-center gap-1 px-2 py-1 rounded-lg hover:bg-green-50 transition-colors"
            title="Share via WhatsApp"
          >
            <MessageSquare size={12} />
            <span className="hidden sm:inline">WhatsApp</span>
          </a>
          <button
            onClick={copy}
            className="text-xs text-teal-600 hover:text-teal-800 flex items-center gap-1 px-2 py-1 rounded-lg hover:bg-teal-50 transition-colors"
            title="Copy invitation link"
          >
            {copied ? <CheckCircle2 size={12} /> : <Copy size={12} />}
            {copied ? "Copied" : "Copy link"}
          </button>
          <button
            onClick={onRevoke}
            className="text-xs text-red-500 hover:text-red-700 flex items-center gap-1 px-2 py-1 rounded-lg hover:bg-red-50 transition-colors"
          >
            <Trash2 size={12} /> Revoke
          </button>
        </div>
      )}
    </div>
  );
}
