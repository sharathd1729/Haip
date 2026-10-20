"use client";
// "Connect an AI assistant" + "Connected apps" sections of the MCP Access
// settings page (HAIP_MCP_Connector_Plan.md §8). Claude.ai / ChatGPT connect
// through OAuth -- the user pastes one URL and logs in; no token to copy.
// CLI clients (Claude Code, Gemini CLI) can use the same URL.
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, CheckCircle2, Loader2, Trash2, Link2, Clock } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface OAuthGrant {
  id: string;
  client_name: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

type ClientKey = "claude" | "chatgpt" | "claude_code" | "gemini";

const CLIENTS: { key: ClientKey; label: string }[] = [
  { key: "claude", label: "Claude" },
  { key: "chatgpt", label: "ChatGPT" },
  { key: "claude_code", label: "Claude Code" },
  { key: "gemini", label: "Gemini" },
];

function Steps({ client, url }: { client: ClientKey; url: string }) {
  const li = "pl-1";
  if (client === "claude") {
    return (
      <ol className="list-decimal pl-5 space-y-1.5">
        <li className={li}>In Claude (web or desktop), open <b>Settings → Connectors</b>.</li>
        <li className={li}>Choose <b>Add custom connector</b>, name it <b>HAIP</b>, and paste the URL above.</li>
        <li className={li}>Click <b>Connect</b>. You'll land on HAIP's sign-in — log in and press <b>Allow access</b>.</li>
        <li className={li}>In a chat, enable HAIP from the tools menu and ask, e.g. <i>“How many leads came in this week, by source?”</i></li>
      </ol>
    );
  }
  if (client === "chatgpt") {
    return (
      <ol className="list-decimal pl-5 space-y-1.5">
        <li className={li}>In ChatGPT, open <b>Settings → Apps &amp; Connectors → Advanced</b> and turn on <b>Developer mode</b> (needs a Plus, Pro, Business or Enterprise plan).</li>
        <li className={li}>Back in <b>Apps &amp; Connectors</b>, choose <b>Create</b>, name it <b>HAIP</b>, paste the URL above, and pick <b>OAuth</b> as authentication.</li>
        <li className={li}>Sign in to HAIP when asked and press <b>Allow access</b>.</li>
        <li className={li}>In a new chat, add HAIP from the <b>+</b> menu before asking.</li>
      </ol>
    );
  }
  if (client === "claude_code") {
    return (
      <div className="space-y-2">
        <p>Run this once, then type <code className="font-mono">/mcp</code> in Claude Code and pick <b>haip → Authenticate</b>:</p>
        <CodeLine text={`claude mcp add --transport http haip ${url}`} />
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p>
        The Gemini app on the web and phone can't add custom connectors yet — that's a Google limitation.
        <b> Gemini CLI</b> can: add this to <code className="font-mono">~/.gemini/settings.json</code>, then run
        <code className="font-mono"> /mcp auth haip</code> inside Gemini CLI.
      </p>
      <CodeLine text={`{ "mcpServers": { "haip": { "httpUrl": "${url}" } } }`} />
    </div>
  );
}

function CodeLine({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 bg-[var(--haip-surface)] rounded-xl border border-[var(--haip-border)] px-3 py-2">
      <code className="text-[11px] text-[var(--haip-fg-2)] flex-1 overflow-x-auto whitespace-nowrap font-mono">{text}</code>
      <button
        onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
        className={cn("flex-shrink-0 p-1 rounded-lg", copied ? "text-green-600" : "text-primary hover:bg-[var(--haip-primary-tint)]")}
        aria-label="Copy"
      >
        {copied ? <CheckCircle2 size={13} /> : <Copy size={13} />}
      </button>
    </div>
  );
}

function ago(iso: string | null): string {
  if (!iso) return "Not used yet";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "Used just now";
  if (mins < 60) return `Used ${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `Used ${hours}h ago`;
  return `Used ${Math.floor(hours / 24)}d ago`;
}

export function McpConnectPanel({ mcpUrl, onToast }: { mcpUrl: string; onToast: (msg: string, type: "success" | "error") => void }) {
  const queryClient = useQueryClient();
  const [client, setClient] = useState<ClientKey>("claude");

  const { data: grants = [], isLoading } = useQuery<OAuthGrant[]>({
    queryKey: ["oauth-grants"],
    queryFn: () => api.get("/oauth/grants").then(r => r.data),
    staleTime: 10_000,
  });

  const disconnect = useMutation({
    mutationFn: (id: string) => api.delete(`/oauth/grants/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["oauth-grants"] });
      onToast("Disconnected. That app can no longer reach HAIP.", "success");
    },
    onError: () => onToast("Couldn't disconnect. Try again.", "error"),
  });

  const active = grants.filter(g => !g.revoked_at);

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--haip-fg)]">Connect an AI assistant</h2>
          <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">
            Ask Claude or ChatGPT about your leads, calls and bookings, get reports, and update the CRM from a chat.
          </p>
        </div>

        <CodeLine text={mcpUrl || "Loading…"} />

        <div role="tablist" className="flex gap-1 overflow-x-auto">
          {CLIENTS.map(c => (
            <button
              key={c.key}
              role="tab"
              aria-selected={client === c.key}
              onClick={() => setClient(c.key)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
                client === c.key ? "bg-[var(--haip-primary-tint)] text-primary" : "text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)]"
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
        <div className="text-xs text-[var(--haip-fg-muted)] leading-relaxed">
          <Steps client={client} url={mcpUrl} />
        </div>
        <p className="text-[11px] text-[var(--haip-fg-subtle)] leading-relaxed">
          Only owners and managers can connect. The assistant sees what you see, guest phone numbers stay masked,
          it asks before changing anything, and it can never message a guest.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-[var(--haip-fg)]">Connected apps</h2>
        {isLoading ? (
          <p className="text-xs text-[var(--haip-fg-subtle)]">Loading…</p>
        ) : active.length === 0 ? (
          <p className="text-xs text-[var(--haip-fg-subtle)]">Nothing connected yet.</p>
        ) : (
          active.map(g => (
            <div key={g.id} className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-[var(--haip-border)] bg-white">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 bg-[var(--haip-primary-tint)] text-primary">
                  <Link2 size={14} />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-[var(--haip-fg)] truncate">{g.client_name}</p>
                  <p className="text-xs text-[var(--haip-fg-subtle)] flex items-center gap-1.5">
                    <Clock size={11} />
                    <span>{ago(g.last_used_at)}</span>
                    <span className="text-[var(--haip-fg-subtle)]/70">·</span>
                    <span>{g.scopes.includes("write") ? "Read and update" : "Read only"}</span>
                  </p>
                </div>
              </div>
              <button
                onClick={() => disconnect.mutate(g.id)}
                disabled={disconnect.isPending && disconnect.variables === g.id}
                className="flex items-center gap-1 text-xs font-medium text-red-500 hover:bg-red-50 px-2.5 py-1.5 rounded-lg transition-colors disabled:opacity-50 flex-shrink-0"
              >
                {disconnect.isPending && disconnect.variables === g.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                Disconnect
              </button>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
