"use client";
// Marketing › Website › Google: the Google connections (Search Console, Business Profile metrics, PageSpeed) and a
// guidance-only Business Profile checklist (website phase 3). HAIP doesn't change the owner's Google profile from here;
// ticks are remembered in this browser only.
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardBody, PageHeader } from "@/components/ui/kit";
import { GoogleConnections } from "@/components/website/GoogleConnections";
import { webApi } from "@/lib/website";

const ITEMS: { key: string; title: string; how: string }[] = [
  { key: "claim", title: "Claim and verify your profile", how: "Go to business.google.com, search your business name and verify by phone, email or video." },
  { key: "category", title: "Pick the right main category", how: "For example Vacation home rental agency, Resort hotel, Guest house, Serviced apartment or Travel agency. Add 2-3 extra categories." },
  { key: "nap", title: "Same name, address and phone everywhere", how: "Use exactly the name, address and phone on your website's contact section. Google trusts matching details." },
  { key: "website", title: "Add your website link", how: "Paste your website address below as the profile's website, and as the booking link if Google offers one." },
  { key: "hours", title: "Opening hours and check-in times", how: "Set reception or reply hours, and add check-in and check-out times under Hotel details if shown." },
  { key: "photos", title: "At least 10 good photos", how: "Exterior, rooms, bathroom, view, food and the team. Real photos, no text on them. Add new ones every month." },
  { key: "amenities", title: "Fill in every amenity", how: "Pool, Wi-Fi, parking, pets, breakfast, accessibility. Guests filter on these." },
  { key: "description", title: "A plain description (750 characters)", how: "What you are, where, who it suits and what is nearby. No prices, no links, no capital letters for shouting." },
  { key: "reviews", title: "Ask happy guests for a Google review", how: "Send your review link on WhatsApp after check-out. Reply to every review, good or bad, within two days." },
  { key: "posts", title: "Post an update every two weeks", how: "Offers, events, seasonal photos. Marketing Studio can publish these for you to Google." },
  { key: "messages", title: "Turn on messaging or show WhatsApp", how: "Answer questions fast; Google shows response time on your profile." },
  { key: "qa", title: "Add your own questions and answers", how: "Use the questions guests ask most (from your FAQ) so the right answer shows first." },
];
const KEY = "haip_gbp_checklist";

export default function GoogleProfilePage() {
  const site = useQuery({ queryKey: ["web-site"], queryFn: webApi.site, retry: false });
  const { data: session } = useSession();
  const role = String(session?.user?.role || "");
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [back, setBack] = useState<{ status: string; reason: string } | null>(null);
  useEffect(() => { try { setDone(JSON.parse(window.localStorage.getItem(KEY) || "{}")); } catch { /* private mode */ } }, []);
  useEffect(() => {      // Google's OAuth redirect lands here with ?search_console=connected|error&reason=
    const q = new URLSearchParams(window.location.search);
    if (q.get("search_console")) setBack({ status: q.get("search_console")!, reason: q.get("reason") || "" });
  }, []);
  const toggle = (k: string) => setDone(d => {
    const next = { ...d, [k]: !d[k] };
    try { window.localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* private mode */ }
    return next;
  });
  const count = ITEMS.filter(i => done[i.key]).length;
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[860px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Google" subtitle="Connect Google, follow your searches, and get found on Search and Maps" />
        {back && <p role="status" className={`rounded-xl border p-3 text-sm ${back.status === "connected" ? "border-[var(--haip-status-success-border)] bg-[var(--haip-status-success-bg)]" : "border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)]"}`}>
          {back.status === "connected" ? "Search Console is connected. HAIP reads the last 16 months over the next few hours." : `Search Console was not connected. ${back.reason}`}</p>}
        <GoogleConnections canManage={role === "owner" || role === "manager"} />
        <h2 className="pt-2 text-lg font-semibold">Business Profile checklist</h2>
        <Card><CardBody className="grid gap-2 text-[15px]">
          <p>Most guests find a stay on Google Maps before they visit a website. These steps help you show up and get the booking.</p>
          {site.data && <p>Your website: <a className="font-semibold underline underline-offset-4" href={site.data.url} target="_blank" rel="noopener noreferrer">{site.data.url}</a></p>}
          <p className="text-sm text-[var(--haip-fg-muted)]">{count} of {ITEMS.length} done. Ticks are saved on this device only.</p>
        </CardBody></Card>
        <Card><CardBody>
          <ul className="grid gap-1">{ITEMS.map(i => (
            <li key={i.key}><label className="grid min-h-11 cursor-pointer grid-cols-[auto_1fr] gap-3 rounded-xl p-2 hover:bg-[var(--haip-surface)]">
              <input type="checkbox" className="mt-1 h-5 w-5 accent-[var(--primary)]" checked={!!done[i.key]} onChange={() => toggle(i.key)} />
              <span><b className={`block font-semibold ${done[i.key] ? "line-through opacity-70" : ""}`}>{i.title}</b>
                <span className="block text-sm text-[var(--haip-fg-muted)]">{i.how}</span></span>
            </label></li>))}</ul>
        </CardBody></Card>
      </div>
    </div>
  );
}
