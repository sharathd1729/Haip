"use client";
// Settings › Security: every claim comes from GET /security/status (backend services/security_status.py), read from the
// running configuration. The page used to hard-code "AES-256 + KMS per tenant", "MFA required for Owner", a lockout and a
// device limit no code enforces, and key statuses that matched nothing.
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { CheckCircle, AlertCircle } from "@/lib/icons";

export interface SecurityStatus {
  storage: { provider: string; encryption: string; region?: string; text: string };
  transcription_provider: string;
  keys: { name: string; status: "set" | "missing" | "not_used"; note: string }[];
  session: { access_token_minutes: number; refresh_token_days: number; login_rate_limit: string; mfa_rule: string; mfa_enabled_for_you: boolean };
  legacy_webhook_verify_token_allowed: boolean;
}

const KEY_LABEL = { set: "Configured", missing: "Missing", not_used: "Not used" } as const;

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-b border-[var(--haip-border)] py-2 last:border-0">
      <span className="text-sm text-[var(--haip-fg-muted)]">{label}</span>
      <span className="text-sm font-medium text-[var(--haip-fg)]">{value}</span>
    </div>
  );
}

function Box({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="haip-card p-5">
      <h3 className="mb-3 text-sm font-bold text-[var(--haip-fg)]">{title}</h3>
      {children}
    </div>
  );
}

export function SecurityStatusCards() {
  const { data, isPending, isError, refetch } = useQuery<SecurityStatus>({
    queryKey: ["security-status"],
    queryFn: () => api.get("/security/status").then(r => r.data),
    staleTime: 60_000,
  });
  if (isPending) return <div className="space-y-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-32 rounded-2xl" />)}</div>;
  if (isError || !data) {
    return (
      <Box title="Security settings">
        <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load what this server is set up with.</p>
        <button type="button" onClick={() => refetch()} className="mt-2 min-h-11 text-sm font-semibold text-primary hover:underline">Try again</button>
      </Box>
    );
  }
  const s = data.session;
  return (
    <>
      <Box title="Sign-in and sessions">
        <Row label="Access token expiry" value={`${s.access_token_minutes} minutes`} />
        <Row label="Refresh token expiry" value={`${s.refresh_token_days} days`} />
        <Row label="Sign-in attempts" value={s.login_rate_limit} />
        <Row label="Two-step sign-in" value={s.mfa_rule} />
        <Row label="Two-step sign-in for you" value={s.mfa_enabled_for_you ? "On" : "Off: turn it on above"} />
      </Box>
      <Box title="Data & privacy (DPDP)">
        <Row label="Call recordings and files" value={data.storage.text} />
        <Row label="Call transcription" value={data.transcription_provider} />
        <Row label="Personal numbers in AI call analysis" value="Phone, Aadhaar, PAN and email removed from call transcripts first" />
        <Row label="Delete on request" value="Within 30 days" />
        <a href="/dashboard/compliance" className="mt-3 inline-block text-xs font-medium text-primary hover:underline">Open Compliance Centre →</a>
      </Box>
      <Box title="Server keys">
        <p className="mb-3 text-xs text-[var(--haip-fg-subtle)]">Names only: whether each key is set on this server. Values are never shown.</p>
        {data.keys.map(k => (
          <div key={k.name} className="flex items-center gap-2 border-b border-[var(--haip-border)] py-1.5 last:border-0">
            {k.status === "missing"
              ? <AlertCircle size={13} className="flex-shrink-0 text-[var(--haip-status-warning-fg)]" />
              : <CheckCircle size={13} className={k.status === "set" ? "flex-shrink-0 text-[var(--haip-status-success-fg)]" : "flex-shrink-0 text-[var(--haip-fg-subtle)]"} />}
            <code className="flex-1 text-xs text-[var(--haip-fg-2)]">{k.name}</code>
            <span className="hidden text-[11px] text-[var(--haip-fg-subtle)] sm:inline">{k.note}</span>
            <span className="text-[10px] font-semibold text-[var(--haip-fg-muted)]">{KEY_LABEL[k.status]}</span>
          </div>
        ))}
        {data.legacy_webhook_verify_token_allowed && (
          <p className="mt-3 text-xs text-[var(--haip-status-warning-fg)]">
            The old shared Meta webhook verify token is still accepted. Turn it off once every channel&apos;s own token is saved in Meta.
          </p>
        )}
      </Box>
    </>
  );
}
