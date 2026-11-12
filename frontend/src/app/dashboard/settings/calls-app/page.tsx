"use client";
// Settings > Calls app phones (owner / manager). Every staff phone running the HAIP Calls app: whose it is, when it last
// synced, app version, whether recordings are arriving, and Remove (its token stops working at once; audited).
// Backend: GET /devices (with the last 30 days per phone), DELETE /devices/{id}. Contract: docs/CALLS_APP_API.md.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";

interface CallsAppDevice {
  id: string;
  user_name: string | null;
  model: string | null;
  android_version: string | null;
  app_version: string | null;
  last_seen_at: string | null;
  created_at: string | null;
  revoked: boolean;
  calls_30d: number;
  recordings_30d: number;
  last_call_at: string | null;
  last_recording_at: string | null;
}

const DAY_MIN = 24 * 60;

function minutesSince(iso: string | null): number | null {
  return iso ? Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000)) : null;
}

function ago(iso: string | null): string {
  const m = minutesSince(iso);
  if (m === null) return "never";
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  if (m < 2 * DAY_MIN) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / DAY_MIN)} days ago`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function loadError(e: unknown): string {
  const status = (e as { response?: { status?: number } })?.response?.status;
  if (status === 403) return "Only owners and managers can see staff phones.";
  if (status === 401) return "You are signed out. Sign in again.";
  return "Check your connection and try again.";
}

function DeviceRow({ d, onRemove, removing }: { d: CallsAppDevice; onRemove: () => void; removing: boolean }) {
  const stale = !d.revoked && (minutesSince(d.last_seen_at) ?? Infinity) > DAY_MIN;
  const phone = [d.model, d.android_version && `Android ${d.android_version}`].filter(Boolean).join(" · ") || "Phone";
  return (
    <li className="grid gap-2 rounded-xl border border-[var(--haip-border)] p-3 sm:grid-cols-[1fr_auto] sm:items-center">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-[15px] font-semibold">
          <span className="break-words">{d.user_name || "Unknown staff member"}</span>
          {d.revoked ? <StatusPill tone="neutral">Removed</StatusPill>
            : stale ? <StatusPill tone="warning">No sync in 24 h</StatusPill>
            : <StatusPill tone="success">Syncing</StatusPill>}
          {!d.revoked && (d.recordings_30d > 0
            ? <StatusPill tone="info">Recordings arriving</StatusPill>
            : <StatusPill tone="neutral">No recordings</StatusPill>)}
        </p>
        <p className="text-[13px] text-[var(--haip-fg-subtle)]">
          {phone} · app {d.app_version || "unknown"} · last sync {ago(d.last_seen_at)}
        </p>
        <p className="text-[13px] text-[var(--haip-fg-subtle)]">
          Last 30 days: {plural(d.calls_30d, "call")}, {plural(d.recordings_30d, "recording")}
          {d.last_call_at && ` · last call ${ago(d.last_call_at)}`}
        </p>
      </div>
      {!d.revoked && (
        <button type="button" className="haip-btn-secondary min-h-11 justify-self-start" disabled={removing} onClick={() => {
          if (window.confirm(`Remove ${d.user_name || "this"}'s phone? It stops sending calls at once. They can link it again by signing in on the phone.`)) onRemove();
        }}>
          {removing ? "Removing…" : "Remove"}
        </button>
      )}
    </li>
  );
}

export default function CallsAppPhonesPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const devices = useQuery<CallsAppDevice[]>({
    queryKey: ["calls-app-devices"],
    queryFn: () => api.get("/devices").then(r => r.data.devices),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/devices/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calls-app-devices"] });
      toast({ variant: "success", title: "Phone removed · logged" });
    },
    onError: () => toast({ variant: "error", title: "Not removed", description: "Check your connection and try again." }),
  });

  const active = (devices.data ?? []).filter(d => !d.revoked);
  const removed = (devices.data ?? []).filter(d => d.revoked);
  const syncedToday = active.filter(d => (minutesSince(d.last_seen_at) ?? Infinity) <= DAY_MIN).length;

  return (
    <div className="grid gap-4">
      <PageHeader title="Calls app phones" subtitle="Staff phones that send their calls and recordings to HAIP." />

      <Card>
        <CardHeader
          title="Phones"
          description={devices.data ? `${plural(active.length, "phone")} · ${syncedToday} synced in the last 24 hours` : undefined}
        />
        <CardBody className="grid gap-3">
          {devices.isPending ? (
            <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading…</p>
          ) : devices.isError ? (
            <EmptyState title="Couldn't load the phones" hint={loadError(devices.error)}
              action={<button type="button" onClick={() => devices.refetch()} className="haip-btn-primary min-h-11">Try again</button>} />
          ) : active.length === 0 && removed.length === 0 ? (
            <EmptyState title="No phones yet" hint="When a staff member installs the HAIP Calls app and signs in, their phone appears here." />
          ) : (
            <>
              {active.length === 0 && <p className="text-[14px] text-[var(--haip-fg-subtle)]">No phones are linked right now.</p>}
              <ul className="grid gap-2">
                {active.map(d => (
                  <DeviceRow key={d.id} d={d} removing={remove.isPending && remove.variables === d.id} onRemove={() => remove.mutate(d.id)} />
                ))}
              </ul>
              {removed.length > 0 && (
                <details className="text-[14px]">
                  <summary className="min-h-11 cursor-pointer py-2 text-[var(--haip-fg-muted)]">Removed phones ({removed.length})</summary>
                  <ul className="mt-2 grid gap-2">
                    {removed.map(d => <DeviceRow key={d.id} d={d} removing={false} onRemove={() => undefined} />)}
                  </ul>
                </details>
              )}
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Add a phone" description="Android only. iPhones don't let apps read calls." />
        <CardBody>
          <ol className="grid list-decimal gap-1.5 pl-5 text-[14px] text-[var(--haip-fg-muted)]">
            <li>Install the HAIP Calls app on the staff member&apos;s Android phone.</li>
            <li>Open it and sign in with their own HAIP account. The phone appears here.</li>
            <li>In the app&apos;s settings: allow the call log, pick the recordings folder, and set battery to Unrestricted.</li>
            <li>Make a test call to a guest. It shows on the guest&apos;s lead page within a few minutes.</li>
          </ol>
        </CardBody>
      </Card>
    </div>
  );
}
