"use client";
// The Website screen for owners who have never built a website (owner, Oct 2026: "even a first-class student can build
// it"): the site shown big, exactly as guests will see it, and four big buttons. Everything else (pages, versions, the
// classic editor) lives behind "More options".
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, ExternalLink, MessageSquareText, Monitor, Phone, Rocket, Smartphone, Sparkles } from "lucide-react";
import { Card, CardBody, Drawer, StatusPill } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webApi, webError, type SiteOut, type SiteSettings } from "@/lib/website";
import { ChangeSheet } from "./ChangeSheet";
import { useDraft } from "./useDraft";

type Contact = { phone: string; whatsapp: string; email: string; address: string };
type Sheet = null | "change" | "contact" | "booking" | "publish";

export function SimpleWebsite({ site, role, onMore }: { site: SiteOut; role: string; onMore: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const draft = useDraft();
  const [sheet, setSheet] = useState<Sheet>(null);
  const [phone, setPhone] = useState(true);
  const canApprove = role === "owner" || role === "manager";
  const doc = draft.doc as unknown as { spec_version?: number; site: { contact: Contact } } | null;
  const isNew = doc?.spec_version === 2;
  const v = draft.version;
  const preview = useQuery({ queryKey: ["web-preview", v?.sha256], queryFn: webApi.preview, enabled: !!v, staleTime: 60 * 60 * 1000 });
  const missing = useQuery({ queryKey: ["web-missing", v?.sha256], queryFn: webApi.missing, enabled: canApprove && isNew });
  const fail = (title: string) => (e: unknown) => toast({ variant: "error", title, description: webError(e, "Try again.") });
  const refresh = (s?: SiteOut) => { if (s) qc.setQueryData(["web-site"], s); qc.invalidateQueries({ queryKey: ["web-versions"] }); draft.load(); };
  const make = useMutation({ mutationFn: webApi.make, onSuccess: s => { refresh(s); toast({ variant: "success", title: "Your website is ready to look at" }); },
    onError: fail("Couldn't make the website") });
  const publish = useMutation({ mutationFn: (id: string) => (role === "owner" ? webApi.publish(id) : webApi.submit(id)),
    onSuccess: s => { refresh(s); setSheet(null); toast({ variant: "success", title: role === "owner" ? "Your website is live" : "Sent to the owner to publish" }); },
    onError: fail("Not published") });

  const host = site.url.replace("https://", "");
  const blocking = draft.checks.filter(c => c.level === "block");
  const unpublished = !!v && v.status === "draft" && v.id !== site.live?.id;

  return (
    <div className="grid gap-4">
      <Card>
        <CardBody className="flex flex-wrap items-center gap-3">
          <StatusPill tone={site.status === "live" ? "success" : "warning"}>{site.status === "live" ? "Live" : "Not live yet"}</StatusPill>
          <p className="min-w-0 flex-1 text-[15px]">
            {site.live ? <>Guests can see your website at <a className="font-semibold underline underline-offset-4" href={site.url} target="_blank" rel="noopener noreferrer">{host}</a>.</>
              : <>Nobody can see your website yet. When you publish, it opens at <b className="font-semibold">{host}</b>.</>}
            {site.live && unpublished && <span className="block text-[var(--haip-fg-muted)]">You have changes guests can&apos;t see yet. Tap Publish to show them.</span>}
          </p>
        </CardBody>
      </Card>

      {!isNew && draft.doc && (
        <Card><CardBody className="grid gap-3 sm:flex sm:items-center sm:justify-between">
          <div><p className="font-semibold">Let HAIP make your website</p>
            <p className="text-sm text-[var(--haip-fg-muted)]">One tap. It uses your stays, photos, trips, reviews and contact details. Nobody sees it until you publish.</p></div>
          {canApprove && <button className={btnPrimary} disabled={make.isPending} onClick={() => make.mutate()}>{make.isPending ? "Making your website…" : "Make my website"}</button>}
        </CardBody></Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Card>
          <CardBody className="grid gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="mr-auto font-semibold">This is what guests see</p>
              <div className="inline-flex overflow-hidden rounded-full border border-[var(--haip-border)]" role="group" aria-label="Preview size">
                <button type="button" aria-pressed={phone} onClick={() => setPhone(true)} className={`flex min-h-11 items-center gap-1.5 px-3 text-sm ${phone ? "bg-[var(--haip-primary-tint)] font-semibold" : ""}`}><Smartphone size={16} aria-hidden="true" />Phone</button>
                <button type="button" aria-pressed={!phone} onClick={() => setPhone(false)} className={`flex min-h-11 items-center gap-1.5 px-3 text-sm ${!phone ? "bg-[var(--haip-primary-tint)] font-semibold" : ""}`}><Monitor size={16} aria-hidden="true" />Computer</button>
              </div>
              {preview.data && <a className={btn} href={preview.data.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={16} aria-hidden="true" />Open</a>}
            </div>
            <div className="flex justify-center rounded-2xl bg-[var(--haip-surface)] p-2 sm:p-4">
              {preview.isError ? <p className="p-8 text-sm">Couldn&apos;t load the preview. <button className="underline" onClick={() => preview.refetch()}>Try again</button></p>
                : !preview.data ? <div className="h-[560px] w-full animate-pulse rounded-xl bg-[var(--haip-border)]" />
                : <iframe key={`${v?.sha256}-${phone}`} title="Your website" src={preview.data.url}
                    className={`h-[640px] rounded-xl border border-[var(--haip-border)] bg-white ${phone ? "w-full max-w-[390px]" : "w-full"}`} />}
            </div>
          </CardBody>
        </Card>

        <div className="grid content-start gap-3">
          <BigButton icon={<MessageSquareText size={22} />} title="Change something" text="Tell HAIP in your own words." onClick={() => setSheet("change")}
            disabled={!canApprove || !isNew} />
          <BigButton icon={<Phone size={22} />} title="My phone & WhatsApp" text="The numbers guests use to reach you." onClick={() => setSheet("contact")} disabled={!canApprove || !draft.doc} />
          <BigButton icon={<CalendarCheck size={22} />} title="Bookings" text={MODE_TEXT[site.settings.booking_mode] || ""} onClick={() => setSheet("booking")} disabled={!canApprove} />
          <BigButton icon={<Rocket size={22} />} title={site.live && !unpublished ? "Published" : "Publish"} primary
            text={blocking.length ? `${blocking.length} thing${blocking.length > 1 ? "s" : ""} to fix first` : site.live && !unpublished ? "Guests see the latest version." : "Show it to guests."}
            onClick={() => setSheet("publish")} disabled={!canApprove || !unpublished} />
          <div className="flex flex-wrap gap-x-4 gap-y-1 px-1 pt-1 text-sm">
            {canApprove && isNew && <button className="flex min-h-11 items-center gap-1.5 underline underline-offset-4" disabled={make.isPending} onClick={() => make.mutate()}><Sparkles size={15} aria-hidden="true" />{make.isPending ? "Making…" : "Make it again from my HAIP data"}</button>}
            <button className="min-h-11 text-[var(--haip-fg-muted)] underline underline-offset-4" onClick={onMore}>More options</button>
          </div>
          {(missing.data?.length ?? 0) > 0 && (
            <Card><CardBody className="grid gap-2">
              <p className="text-sm font-semibold">Add these and your website shows more</p>
              <ul className="grid gap-2">{missing.data!.map(m => (
                <li key={m.section} className="text-sm"><a href={m.href} className="font-semibold underline underline-offset-4">{m.title}</a>
                  <span className="block text-[var(--haip-fg-muted)]">{m.how}</span></li>))}</ul>
              <p className="text-xs text-[var(--haip-fg-muted)]">Then tap &ldquo;Make it again from my HAIP data&rdquo;.</p>
            </CardBody></Card>
          )}
        </div>
      </div>

      {doc && <ContactSheet open={sheet === "contact"} onClose={() => setSheet(null)} contact={doc.site.contact}
        onSave={async c => { draft.update(d => { (d as unknown as { site: { contact: Contact } }).site.contact = c; }); await draft.flush(); setSheet(null); toast({ variant: "success", title: "Saved. Publish to show it to guests." }); }} />}
      <ChangeSheet open={sheet === "change"} onClose={() => setSheet(null)} onChanged={() => refresh()} />
      <BookingSheet open={sheet === "booking"} onClose={() => setSheet(null)} site={site} onSaved={s => { qc.setQueryData(["web-site"], s); setSheet(null); }} />
      <Drawer open={sheet === "publish"} onOpenChange={o => !o && setSheet(null)} title="Publish your website"
        footer={<div className="flex gap-2"><button className={btn} onClick={() => setSheet(null)}>Not now</button>
          <button className={btnPrimary} disabled={!v || blocking.length > 0 || publish.isPending} onClick={() => v && publish.mutate(v.id)}>
            {publish.isPending ? "Publishing…" : role === "owner" ? "Publish now" : "Send to the owner"}</button></div>}>
        {blocking.length ? (
          <div className="grid gap-3 text-[15px]"><p>Fix these first:</p>
            <ul className="grid gap-2">{blocking.map(c => <li key={c.key} className="rounded-xl border border-[var(--haip-border)] p-3"><b className="font-semibold">{c.title}</b><span className="block text-sm text-[var(--haip-fg-muted)]">{c.detail}</span></li>)}</ul></div>
        ) : <p className="text-[15px]">Guests will see this version at <b className="font-semibold">{host}</b>. You can change it and publish again any time.</p>}
      </Drawer>
    </div>
  );
}

const MODE_TEXT: Record<string, string> = {
  request: "Guests send a booking request. You confirm.",
  enquiry: "Guests message you. No booking form.",
  instant: "Guests pay online and it's booked.",
  deposit: "Guests pay a deposit online.",
};

function BigButton({ icon, title, text, onClick, disabled, primary }: { icon: ReactNode; title: string; text: string; onClick?: () => void; disabled?: boolean; primary?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className={`grid min-h-[76px] grid-cols-[auto_1fr] items-center gap-3 rounded-2xl border p-4 text-left transition-transform active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 ${primary ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)]"}`}>
      <span aria-hidden="true">{icon}</span>
      <span><b className="block text-base font-semibold">{title}</b><span className={`block text-sm ${primary ? "opacity-90" : "text-[var(--haip-fg-muted)]"}`}>{text}</span></span>
    </button>
  );
}

function ContactSheet({ open, onClose, contact, onSave }: { open: boolean; onClose: () => void; contact: Contact; onSave: (c: Contact) => Promise<void> }) {
  const [c, setC] = useState<Contact>(contact);
  const [busy, setBusy] = useState(false);
  const field = (k: keyof Contact, label: string, type = "text", hint?: string) => (
    <label className="grid gap-1"><span className="text-sm font-semibold">{label}</span>
      <input className={inputCls} type={type} inputMode={type === "tel" ? "tel" : undefined} value={c[k] || ""} onChange={e => setC({ ...c, [k]: e.target.value })} />
      {hint && <span className="text-xs text-[var(--haip-fg-muted)]">{hint}</span>}</label>
  );
  return (
    <Drawer open={open} onOpenChange={o => { if (o) setC(contact); else onClose(); }} title="My phone & WhatsApp"
      footer={<div className="flex gap-2"><button className={btn} onClick={onClose}>Cancel</button>
        <button className={btnPrimary} disabled={busy} onClick={async () => { setBusy(true); try { await onSave(c); } finally { setBusy(false); } }}>{busy ? "Saving…" : "Save"}</button></div>}>
      <div className="grid gap-4">
        {field("whatsapp", "WhatsApp number", "tel", "Every WhatsApp button on your website opens a chat with this number.")}
        {field("phone", "Phone number", "tel", "For the Call us button.")}
        {field("email", "Email", "email")}
        {field("address", "Address", "text", "Shown with a Get directions link.")}
      </div>
    </Drawer>
  );
}

function BookingSheet({ open, onClose, site, onSaved }: { open: boolean; onClose: () => void; site: SiteOut; onSaved: (s: SiteOut) => void }) {
  const { toast } = useToast();
  const [mode, setMode] = useState<SiteSettings["booking_mode"]>(site.settings.booking_mode);
  const save = useMutation({ mutationFn: () => webApi.settings({ ...site.settings, booking_mode: mode }),
    onSuccess: s => { onSaved(s); toast({ variant: "success", title: "Saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: webError(e, "Try again.") }) });
  const choice = (k: SiteSettings["booking_mode"], title: string, text: string) => (
    <label className={`grid cursor-pointer grid-cols-[auto_1fr] gap-3 rounded-2xl border p-4 ${mode === k ? "border-[var(--primary)] bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)]"}`}>
      <input type="radio" name="booking" className="mt-1 h-5 w-5 accent-[var(--primary)]" checked={mode === k} onChange={() => setMode(k)} />
      <span><b className="block font-semibold">{title}</b><span className="block text-sm text-[var(--haip-fg-muted)]">{text}</span></span>
    </label>
  );
  return (
    <Drawer open={open} onOpenChange={o => { if (o) setMode(site.settings.booking_mode); else onClose(); }} title="Bookings on your website"
      footer={<div className="flex gap-2"><button className={btn} onClick={onClose}>Cancel</button>
        <button className={btnPrimary} disabled={save.isPending || mode === site.settings.booking_mode} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save"}</button></div>}>
      <div className="grid gap-3">
        {choice("request", "Guests send a booking request", "They pick dates. It comes to HAIP as a lead; you confirm and send a payment link.")}
        {choice("enquiry", "Guests just message you", "No booking form. Every button opens WhatsApp.")}
        <p className="text-sm text-[var(--haip-fg-muted)]">Taking payment on the website is coming soon.</p>
      </div>
    </Drawer>
  );
}
