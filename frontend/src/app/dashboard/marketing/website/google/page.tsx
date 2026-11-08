"use client";
// Marketing › Website › Google: the Google connections (Search Console, Business Profile metrics, PageSpeed) and a
// pointer to the Business Profile checklist, which now lives in Get found (dynamic SOPs, tracked on the server).
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardBody, PageHeader } from "@/components/ui/kit";
import { GoogleConnections } from "@/components/website/GoogleConnections";
import { webApi } from "@/lib/website";

export default function GoogleProfilePage() {
  const site = useQuery({ queryKey: ["web-site"], queryFn: webApi.site, retry: false });
  const { data: session } = useSession();
  const role = String(session?.user?.role || "");
  const [back, setBack] = useState<{ status: string; reason: string } | null>(null);
  useEffect(() => {      // Google's OAuth redirect lands here with ?search_console=connected|error&reason=
    const q = new URLSearchParams(window.location.search);
    if (q.get("search_console")) setBack({ status: q.get("search_console")!, reason: q.get("reason") || "" });
  }, []);
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[860px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Google" subtitle="Connect Google, follow your searches, and get found on Search and Maps" />
        {back && <p role="status" className={`rounded-xl border p-3 text-sm ${back.status === "connected" ? "border-[var(--haip-status-success-border)] bg-[var(--haip-status-success-bg)]" : "border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)]"}`}>
          {back.status === "connected" ? "Search Console is connected. HAIP reads the last 16 months over the next few hours." : `Search Console was not connected. ${back.reason}`}</p>}
        <GoogleConnections canManage={role === "owner" || role === "manager"} />
        <Card><CardBody className="grid gap-2 text-[15px]">
          <p>Most guests find a stay on Google Maps before they visit a website. The Business Profile checklist is in Get found, with each step tracked for your team.</p>
          {site.data && <p>Your website: <a className="font-semibold underline underline-offset-4" href={site.data.url} target="_blank" rel="noopener noreferrer">{site.data.url}</a></p>}
          <Link href="/dashboard/marketing/sops" className="haip-btn-secondary inline-flex min-h-11 w-fit items-center">Open Get found</Link>
        </CardBody></Card>
      </div>
    </div>
  );
}
