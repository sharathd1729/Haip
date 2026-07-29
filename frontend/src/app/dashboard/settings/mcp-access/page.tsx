"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bot, KeyRound, Copy, Trash2, Loader2, AlertCircle, X,
  CheckCircle2, Clock, Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface McpToken {
  id: string;
  name: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

interface CreatedToken extends McpToken {
  token: string;
}

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

function CreateTokenModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (t: CreatedToken) => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) { setError("Give this token a name, e.g. \"Perisclaw\"."); return; }
    setError("");
    setSubmitting(true);
    try {
      const res = await api.post("/mcp-tokens", { name });
      onSuccess(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to create token.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-900">New access token</h2>
            <p className="text-xs text-gray-400 mt-0.5">Lets an external assistant read and act on your HAIP data.</p>
          </div>
          <button onClick={onClose}><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1.5">Name <span className="text-red-500">*</span></label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Perisclaw"
              autoFocus
              className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30"
            />
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
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Create Token
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function TokenRevealModal({ token, mcpUrl, onClose }: { token: CreatedToken; mcpUrl: string; onClose: () => void }) {
  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);

  const copy = (value: string, setFlag: (v: boolean) => void) => {
    navigator.clipboard.writeText(value);
    setFlag(true);
    setTimeout(() => setFlag(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-900">Token created</h2>
            <p className="text-xs text-gray-400 mt-0.5">Copy this now — it won't be shown again.</p>
          </div>
          <button onClick={onClose}><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <div>
            <p className="text-xs font-semibold text-gray-700 mb-1.5">Access token</p>
            <div className="flex items-center gap-2 bg-gray-50 rounded-xl border border-gray-200 px-3 py-2.5">
              <code className="text-[11px] text-gray-600 flex-1 truncate font-mono">{token.token}</code>
              <button
                onClick={() => copy(token.token, setCopiedToken)}
                className={cn("flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-lg transition-colors flex-shrink-0",
                  copiedToken ? "text-green-600 bg-green-50" : "text-teal-600 hover:bg-teal-50"
                )}
              >
                {copiedToken ? <CheckCircle2 size={12} /> : <Copy size={12} />}
              </button>
            </div>
          </div>
          <div>
            <p className="text-xs font-semibold text-gray-700 mb-1.5">MCP endpoint URL</p>
            <div className="flex items-center gap-2 bg-gray-50 rounded-xl border border-gray-200 px-3 py-2.5">
              <code className="text-[11px] text-gray-600 flex-1 truncate font-mono">{mcpUrl}</code>
              <button
                onClick={() => copy(mcpUrl, setCopiedUrl)}
                className={cn("flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-lg transition-colors flex-shrink-0",
                  copiedUrl ? "text-green-600 bg-green-50" : "text-teal-600 hover:bg-teal-50"
                )}
              >
                {copiedUrl ? <CheckCircle2 size={12} /> : <Copy size={12} />}
              </button>
            </div>
          </div>
          <div className="bg-teal-50 rounded-xl p-4 text-xs text-gray-600 leading-relaxed">
            In Perisclaw, add a custom connector with the URL above and paste this token as its access token. Perisclaw will confirm with you before taking any real action (sending a message, moving a lead, adding a note) — reading data doesn't need confirmation.
          </div>
        </div>
      </div>
    </div>
  );
}

function timeAgo(iso: string | null): string {
  if (!iso) return "Never used";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function TokenRow({ token, onRevoke, revoking }: { token: McpToken; onRevoke: () => void; revoking: boolean }) {
  const isRevoked = !!token.revoked_at;
  return (
    <div className={cn(
      "flex items-center justify-between px-4 py-3 rounded-xl border",
      isRevoked ? "border-gray-100 bg-gray-50 opacity-60" : "border-gray-200 bg-white"
    )}>
      <div className="flex items-center gap-3 min-w-0">
        <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0",
          isRevoked ? "bg-gray-200 text-gray-400" : "bg-teal-50 text-teal-600"
        )}>
          <KeyRound size={14} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-800 truncate">{token.name}</p>
          <p className="text-xs text-gray-400 flex items-center gap-1">
            <Clock size={11} />
            {isRevoked ? "Revoked" : timeAgo(token.last_used_at)}
          </p>
        </div>
      </div>
      {!isRevoked && (
        <button
          onClick={onRevoke}
          disabled={revoking}
          className="flex items-center gap-1 text-xs font-medium text-red-500 hover:bg-red-50 px-2.5 py-1.5 rounded-lg transition-colors disabled:opacity-50"
        >
          {revoking ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
          Revoke
        </button>
      )}
    </div>
  );
}

export default function McpAccessPage() {
  const queryClient = useQueryClient();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [revealedToken, setRevealedToken] = useState<CreatedToken | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: tokens = [], isLoading } = useQuery<McpToken[]>({
    queryKey: ["mcp-tokens"],
    queryFn: () => api.get("/mcp-tokens").then(r => r.data),
    staleTime: 10_000,
  });

  const { data: endpointInfo } = useQuery<{ mcp_url: string }>({
    queryKey: ["mcp-endpoint-info"],
    queryFn: () => api.get("/mcp-tokens/mcp-endpoint-info").then(r => r.data),
    staleTime: 300_000,
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/mcp-tokens/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-tokens"] });
      showToast("Token revoked.", "success");
    },
    onError: () => showToast("Failed to revoke token.", "error"),
  });

  const activeTokens = tokens.filter(t => !t.revoked_at);
  const revokedTokens = tokens.filter(t => t.revoked_at);

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-50 flex items-center justify-center">
              <Bot size={18} className="text-teal-600" />
            </div>
            <div>
              <h1 className="haip-page-title">External Assistant Access</h1>
              <p className="text-sm text-gray-400 mt-0.5">
                Connect Perisclaw or another AI assistant to your HAIP data via MCP.
              </p>
            </div>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2.5 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors"
          >
            <Plus size={15} />
            New Token
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6 max-w-2xl w-full mx-auto">
        {isLoading ? (
          <p className="text-sm text-gray-400">Loading...</p>
        ) : tokens.length === 0 ? (
          <div className="text-center py-16">
            <Bot size={32} className="text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No access tokens yet.</p>
            <p className="text-xs text-gray-400 mt-1">Create one to connect an external AI assistant.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {activeTokens.map(t => (
              <TokenRow
                key={t.id}
                token={t}
                onRevoke={() => revokeMutation.mutate(t.id)}
                revoking={revokeMutation.isPending && revokeMutation.variables === t.id}
              />
            ))}
            {revokedTokens.length > 0 && (
              <div className="pt-2 space-y-2">
                {revokedTokens.map(t => (
                  <TokenRow key={t.id} token={t} onRevoke={() => {}} revoking={false} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {showCreateModal && (
        <CreateTokenModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={(t) => {
            queryClient.invalidateQueries({ queryKey: ["mcp-tokens"] });
            setShowCreateModal(false);
            setRevealedToken(t);
          }}
        />
      )}
      {revealedToken && (
        <TokenRevealModal
          token={revealedToken}
          mcpUrl={endpointInfo?.mcp_url || ""}
          onClose={() => setRevealedToken(null)}
        />
      )}
      {toast && <Toast msg={toast.msg} type={toast.type} onDismiss={() => setToast(null)} />}
    </div>
  );
}
