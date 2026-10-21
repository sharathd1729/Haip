"use client";
// The website editor (AI developer / Builder / phone quick edit). See components/website/Editor.tsx.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Card, EmptyState } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn } from "@/components/marketing/studio/types";
import { Editor } from "@/components/website/Editor";
import { webApi, webError } from "@/lib/website";
import "@/site-blocks/site.css";
import { FONTS_HREF } from "@/site-blocks/packs";

export default function WebsiteEditPage() {
  const { data: session } = useSession();
  const role = String(session?.user?.role || "");
  const [mounted, setMounted] = useState(false);
  const [initialPage, setInitialPage] = useState<string | null>(null);
  useEffect(() => { setMounted(true); setInitialPage(new URLSearchParams(window.location.search).get("page")); }, []);
  const site = useQuery({ queryKey: ["web-site"], queryFn: webApi.site, retry: false });
  useEffect(() => {
    if (document.querySelector(`link[href="${FONTS_HREF}"]`)) return;
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = FONTS_HREF;
    document.head.appendChild(l);
  }, []);
  if (!mounted || site.isLoading) return <div className="p-6"><Skeleton className="h-[60vh] w-full" /></div>;
  if (site.isError || !site.data) {
    return (
      <div className="mx-auto max-w-[720px] p-6"><Card><EmptyState title="The editor can't open" hint={webError(site.error, "Create the website first.")}
        action={<Link className={btn} href="/dashboard/marketing/website">Back to Website</Link>} /></Card></div>
    );
  }
  return <Editor site={site.data} role={role} initialPage={initialPage} />;
}
