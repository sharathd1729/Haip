"use client";
// Marketing › Website › Launch report (website phase 6): the agency-style handover in one page, and as a PDF.
// Backend website_launch: pages, speed/accessibility/search, structured data, domain, tracking, a DRY-RUN booking test.
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Card, CardBody, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn, btnPrimary } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { downloadErrorMessage, saveBlob } from "@/lib/download";
import { webError } from "@/lib/website";
import { growthApi } from "@/lib/websiteGrowth";

function Row({ k, v }: { k: string; v: ReactNode }) {
  return <div className="grid grid-cols-[minmax(0,10rem)_1fr] gap-3 border-t border-[var(--haip-border)] py-2 text-[15px]"><span className="text-[var(--haip-fg-muted)]">{k}</span><span className="min-w-0 break-words">{v}</span></div>;
}

export default function LaunchReportPage() {
  const { toast } = useToast();
  const r = useQuery({ queryKey: ["web-launch"], queryFn: growthApi.launch, retry: false });
  const [busy, setBusy] = useState(false);
  const pdf = async () => {
    setBusy(true);
    try { await saveBlob(await growthApi.launchPdf(), "website-launch-report.pdf"); }
    catch (e) { toast({ variant: "error", title: "Download failed", description: await downloadErrorMessage(e) }); }
    finally { setBusy(false); }
  };
  const d = r.data;
  const yes = (b: boolean | null | undefined, on = "On", off = "Off") => <StatusPill tone={b ? "success" : "neutral"}>{b ? on : off}</StatusPill>;
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[900px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Launch report" subtitle="Everything about your website in one place"
          actions={d && !d.problem ? <button className={btnPrimary} disabled={busy} onClick={pdf}>{busy ? "Making PDF…" : "Download PDF"}</button> : undefined} />
        {r.isLoading ? <Skeleton className="h-64 w-full" />
          : r.isError ? <Card><EmptyState title="Couldn't make the report" hint={webError(r.error, "Try again in a moment.")}
            action={<button className={btn} onClick={() => r.refetch()}>Try again</button>} /></Card>
          : d?.problem ? <Card><EmptyState title={d.problem} hint={d.site.url} /></Card>
          : d && <>
            <Card><CardBody>
              <p className="font-semibold">{d.site.name}</p>
              <Row k="Address" v={<a className="underline underline-offset-4" href={d.site.url} target="_blank" rel="noopener noreferrer">{d.site.url}</a>} />
              <Row k="Published" v={d.published ? `Version ${d.published.version}${d.published.at ? `, ${new Date(d.published.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}` : ""}` : "Not yet"} />
              {(d.domain || []).map(x => <Row key={x.host} k={x.kind === "custom" ? "Your domain" : "Free address"} v={<>{x.host} {yes(x.https, "Secure (HTTPS)", x.status)}</>} />)}
            </CardBody></Card>
            {d.quality && <Card><CardBody>
              <p className="font-semibold">Speed, accessibility, search</p>
              <Row k="Scores" v={`Speed ${d.quality.scores.performance} · Accessibility ${d.quality.scores.accessibility} · Search ${d.quality.scores.seo} (out of 100)`} />
              {d.quality.to_improve.map(x => <Row key={x} k="To improve" v={x} />)}
            </CardBody></Card>}
            <Card><CardBody>
              <p className="font-semibold">Pages</p>
              {(d.pages || []).map(p => <Row key={p.path} k={p.path} v={`${p.title}: ${p.sections.join(", ")}`} />)}
              {!!d.extra_pages?.length && <Row k="Also" v={d.extra_pages.join(", ")} />}
              {d.schema && <Row k="Google data" v={Object.entries(d.schema).map(([k, v]) => `${k}: ${v.join(", ")}`).join(" · ")} />}
            </CardBody></Card>
            {d.tracking && <Card><CardBody>
              <p className="font-semibold">Tracking</p>
              <Row k="Meta Pixel" v={yes(d.tracking.meta_pixel)} /><Row k="Google Analytics 4" v={yes(d.tracking.ga4)} />
              <Row k="Conversions API" v={yes(d.tracking.conversions_api)} /><Row k="Cookie banner" v={yes(d.tracking.cookie_banner, "Shown", "Not needed")} />
              <Row k="Last event sent" v={d.tracking.last_event_sent_at ? new Date(d.tracking.last_event_sent_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "None yet"} />
            </CardBody></Card>}
            {d.booking && <Card><CardBody>
              <p className="font-semibold">Booking test (dry run: nothing is booked)</p>
              <Row k="Guests can" v={d.booking.mode} /><Row k="Prices shown" v={yes(d.booking.prices_shown, "Yes", "No")} />
              {d.booking.razorpay_connected !== null && <Row k="Razorpay" v={yes(d.booking.razorpay_connected, "Connected", "Not connected")} />}
              {d.booking.dry_run.map(x => <Row key={x.stay} k={x.stay} v={<>{yes(x.ok, "OK", "Problem")} {x.result}</>} />)}
              <Row k="Last website booking" v={d.booking.last_booking_at ? new Date(d.booking.last_booking_at).toLocaleDateString("en-IN") : "None yet"} />
            </CardBody></Card>}
            {d.content && <Card><CardBody>
              <p className="font-semibold">Content</p>
              <Row k="Guides live" v={d.content.guides_live} /><Row k="Reviews shown" v={d.content.reviews_shown} />
              <Row k="Promo codes on" v={d.content.promo_codes_on} /><Row k="Languages" v={d.content.languages.join(", ")} />
            </CardBody></Card>}
            {!!d.open_items?.length && <Card><CardBody>
              <p className="font-semibold">Still to do</p>{d.open_items.map(x => <Row key={x} k="•" v={x} />)}
            </CardBody></Card>}
          </>}
      </div>
    </div>
  );
}
