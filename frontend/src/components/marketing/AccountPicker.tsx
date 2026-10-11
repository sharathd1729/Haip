"use client";
// First-run: choose which Meta ad account to show. Only accounts the workspace's Meta token can read are offered.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState } from "@/components/ui/kit";
import { errorText, type AdAccount } from "./ads";

export function AccountPicker({ canChoose, hasToken }: { canChoose: boolean; hasToken: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [picked, setPicked] = useState("");
  const accounts = useQuery<{ accounts: AdAccount[] }>({
    queryKey: ["ads-accounts"], enabled: canChoose && hasToken, retry: false,
    queryFn: () => api.get("/marketing/ads/accounts").then(r => r.data),
  });
  const choose = useMutation({
    mutationFn: (id: string) => api.put("/marketing/ads/account", { ad_account_id: id }).then(r => r.data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["ads-status"] });
      toast({ variant: "success", title: "Ad account chosen", description: "Pulling the last 30 days now." });
      // The first pull runs right after choosing; refresh both the totals and the "updated" time when it ends.
      api.post("/marketing/ads/sync").finally(() => {
        qc.invalidateQueries({ queryKey: ["ads-summary"] });
        qc.invalidateQueries({ queryKey: ["ads-status"] });
      });
    },
    onError: e => toast({ variant: "error", title: "Could not choose that account", description: errorText(e, "Try again.") }),
  });

  if (!hasToken) {
    return <EmptyState title="Connect WhatsApp first" hint="Meta ads use the same Meta access token as your WhatsApp connection, and none is saved yet. Add it under Settings, Integrations." />;
  }
  if (!canChoose) {
    return <EmptyState title="No ad account chosen yet" hint="Ask an owner or manager to choose which Meta ad account to show here." />;
  }
  return (
    <Card>
      <CardHeader title="Choose your ad account" description="These are the ad accounts your Meta access token can read. Nothing is changed in Meta." />
      <CardBody className="space-y-3">
        {accounts.isLoading && <Skeleton className="h-16 w-full" />}
        {accounts.isError && <p className="text-sm text-[var(--haip-status-danger-fg)]">{errorText(accounts.error, "Could not load ad accounts.")}</p>}
        {accounts.data?.accounts.length === 0 && (
          <p className="text-sm text-[var(--haip-fg-subtle)]">This token cannot see any ad account. In Meta Business Settings, assign the ad account to the system user that owns the token.</p>
        )}
        <div role="radiogroup" aria-label="Ad accounts" className="space-y-2">
          {accounts.data?.accounts.map(a => (
            <label key={a.id} className={cn("flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors",
              picked === a.id ? "border-primary bg-primary/10" : "border-[var(--haip-border)] hover:bg-[var(--haip-surface)]")}>
              <input type="radio" name="ad-account" checked={picked === a.id} onChange={() => setPicked(a.id)} className="accent-primary" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold text-[var(--haip-fg)]">{a.name || a.id}</span>
                <span className="block text-xs text-[var(--haip-fg-subtle)]">{a.id} · {a.currency}</span>
              </span>
            </label>
          ))}
        </div>
        <button type="button" disabled={!picked || choose.isPending} onClick={() => choose.mutate(picked)}
          className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          {choose.isPending ? "Saving…" : "Use this account"}
        </button>
      </CardBody>
    </Card>
  );
}
