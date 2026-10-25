"use client";
// Marketing › Website: the client-facing website HAIP builds and hosts (website builder). Server gates: module
// "website" + website.* capabilities; this page mirrors them for what it shows.
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Card, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn, btnPrimary } from "@/components/marketing/studio/types";
import { NoSite, Overview } from "@/components/website/Overview";
import { SimpleWebsite } from "@/components/website/SimpleWebsite";
import api from "@/lib/api";
import { errorCode, statusOf, webApi, webError } from "@/lib/website";

export default function WebsitePage() {
  const { data: session } = useSession();
  const role = String(session?.user?.role || "");
  const [mounted, setMounted] = useState(false);
  const [more, setMore] = useState(false);       // "More options": the classic pages / versions / editor view
  useEffect(() => setMounted(true), []);
  const site = useQuery({ queryKey: ["web-site"], queryFn: webApi.site, retry: false });
  const code = errorCode(site.error), status = statusOf(site.error);
  const moduleOff = status === 403 && (code === "module_not_enabled" || JSON.stringify((site.error as { response?: { data?: unknown } })?.response?.data ?? "").includes("module_not_enabled"));
  const activate = useMutation({ mutationFn: () => api.post("/workspace/modules/website/activate"), onSuccess: () => { [3000, 8000, 20000].forEach(ms => setTimeout(() => site.refetch(), ms)); } });
  const s = site.data;

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1280px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Website" subtitle="Your website, made and hosted by HAIP"
          actions={s && more && <div className="flex flex-wrap items-center gap-2">
            <button className={btn} onClick={() => setMore(false)}>Back to simple view</button>
            <a className={btnPrimary} href="/dashboard/marketing/website/edit">Open editor</a></div>} />
        {!mounted || site.isLoading ? <Skeleton className="h-48 w-full" /> : site.isError ? (
          code === "no_site" ? <NoSite canCreate={role === "owner" || role === "manager"} /> : (
            <Card><EmptyState
              title={moduleOff ? "Website is not switched on" : status === 403 ? "Your role can't open the website" : "Couldn't load the website"}
              hint={moduleOff ? (role === "owner" ? "Switch it on to build your bookable website." : "Ask the workspace owner to switch it on.") : webError(site.error, "Try again in a moment.")}
              action={moduleOff && role === "owner" ? <button type="button" className={btnPrimary} disabled={activate.isPending || activate.isSuccess} onClick={() => activate.mutate()}>
                {activate.isSuccess ? "Switching on…" : "Switch on Website"}</button> : !moduleOff && status !== 403 ? <button className={btn} onClick={() => site.refetch()}>Try again</button> : null} /></Card>
          )
        ) : s ? (more ? <Overview site={s} role={role} /> : <SimpleWebsite site={s} role={role} onMore={() => setMore(true)} />) : null}
      </div>
    </div>
  );
}
