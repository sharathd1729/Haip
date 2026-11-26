"use client";
// Automations > Hours and welcome: business hours + holidays, the first-message welcome, the location reply and the STOP /
// START confirmation (GET/PUT /whatsapp/bot-settings, owner + manager, audited). One Save sends only the changed sections.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/ui/page";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { BTN, BTN_PRIMARY } from "@/components/quotes/ui";
import { HoursCard, LocationCard, OptCard, WelcomeCard } from "@/components/whatsapp-bot/WaBotCards";
import { buttonProblem, changedSections, type BotSettings, type Sections } from "@/components/whatsapp-bot/waBot";

type Rule = { name: string; trigger: string; is_active: boolean; trigger_config?: { hours?: string } };

const pick = (s: BotSettings): Sections => ({ hours: s.hours, welcome: s.welcome, location_reply: s.location_reply, opt_confirm: s.opt_confirm });

export default function WhatsAppHoursPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data, isPending, isError, error, refetch } = useQuery<BotSettings>({
    queryKey: ["wa-bot-settings"],
    queryFn: () => api.get("/whatsapp/bot-settings").then(r => r.data),
    retry: (n, e) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 1,
  });
  const { data: rules } = useQuery<Rule[]>({
    queryKey: ["automations"],
    queryFn: () => api.get("/automations").then(r => r.data).catch(() => []),
    staleTime: 60_000,
  });
  const away = rules?.find(r => r.is_active && r.trigger === "wa_message_received" && r.trigger_config?.hours === "closed");
  const [draft, setDraft] = useState<Sections | null>(null);
  useEffect(() => { if (data) setDraft(pick(data)); }, [data]);

  const save = useMutation({
    mutationFn: (body: Partial<Sections>) => api.put("/whatsapp/bot-settings", body).then(r => r.data as BotSettings),
    onSuccess: (res) => {
      qc.setQueryData(["wa-bot-settings"], res);
      qc.invalidateQueries({ queryKey: ["consult-settings"] });
      toast({ variant: "success", title: "Saved", description: "New WhatsApp messages follow these settings from now on." });
    },
    onError: (e) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const msg = Array.isArray(detail) ? String((detail[0] as { msg?: string })?.msg ?? "") : typeof detail === "string" ? detail : "";
      toast({ variant: "error", title: "Couldn't save", description: msg.replace(/^Value error, /, "") || "Check the times, texts and buttons, then try again." });
    },
  });

  const header = <PageHeader icon={Clock} title="Hours and welcome" subtitle="Your WhatsApp opening hours and the automatic replies guests get when they first write, share a location or reply STOP." />;
  if (isPending || (data && !draft)) {
    return <div className="h-full overflow-y-auto p-4 sm:p-6"><div className="mx-auto max-w-3xl space-y-4">{header}<Skeleton className="h-64 w-full rounded-2xl" /><Skeleton className="h-48 w-full rounded-2xl" /></div></div>;
  }
  if (isError || !data || !draft) {
    const forbidden = (error as { response?: { status?: number } })?.response?.status === 403;
    return (
      <div className="h-full overflow-y-auto p-4 sm:p-6"><div className="mx-auto max-w-3xl space-y-4">{header}
        <EmptyState title={forbidden ? "Only the owner or a manager can see this" : "Couldn't load these settings"}
          hint={forbidden ? "Ask your owner or manager to change the hours and automatic replies." : "Check your connection and try again."}
          action={forbidden ? undefined : <button type="button" className={BTN} onClick={() => refetch()}>Try again</button>} />
      </div></div>
    );
  }

  const changes = changedSections(pick(data), draft);
  const dirty = Object.keys(changes).length > 0;
  const problem = (draft.welcome.enabled && !draft.welcome.text.trim() && "Write the welcome message.")
    || buttonProblem(draft.welcome.buttons)
    || (draft.location_reply.enabled && !draft.location_reply.text.trim() && "Write the location reply.")
    || (draft.location_reply.map_link.trim() && !draft.location_reply.map_link.trim().startsWith("https://") && "The map link must start with https://")
    || (draft.opt_confirm.custom && (!draft.opt_confirm.stop_text.trim() || !draft.opt_confirm.start_text.trim()) && "Write both STOP and START replies.")
    || null;
  const set = <K extends keyof Sections>(k: K) => (v: Sections[K]) => setDraft({ ...draft, [k]: v });

  return (
    <div className="h-full overflow-y-auto p-4 pb-28 sm:p-6 sm:pb-28">
      <div className="mx-auto max-w-3xl space-y-4">
        {header}
        <HoursCard hours={draft.hours} onChange={set("hours")} timezone={data.timezone} openNow={data.open_now}
          awayRule={rules === undefined ? undefined : away?.name ?? null} disabled={save.isPending} />
        <WelcomeCard value={draft.welcome} onChange={set("welcome")} disabled={save.isPending} />
        <LocationCard value={draft.location_reply} onChange={set("location_reply")} disabled={save.isPending} />
        <OptCard value={draft.opt_confirm} onChange={set("opt_confirm")} disabled={save.isPending} />
      </div>
      {dirty && (
        <div role="region" aria-label="Unsaved changes"
          className="fixed inset-x-0 bottom-[calc(60px+env(safe-area-inset-bottom))] z-30 border-t border-[var(--haip-border)] bg-[var(--haip-card)] px-4 py-3 shadow-lg md:bottom-0">
          <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2">
            <p className="text-[13px] text-[var(--haip-fg-2)]">{problem ?? "You have unsaved changes."}</p>
            <div className="flex gap-2">
              <button type="button" className={BTN} disabled={save.isPending} onClick={() => setDraft(pick(data))}>Undo</button>
              <button type="button" className={BTN_PRIMARY} disabled={!!problem || save.isPending} onClick={() => save.mutate(changes)}>
                {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
