"use client";
// The cards on Automations > Hours and welcome (page: app/dashboard/automations/whatsapp-hours). Each guest-facing text has a
// live WhatsApp-bubble preview with {first_name} filled in. State lives in the page; these only render and report changes.
import { useState } from "react";
import Link from "next/link";
import { Clock, MapPin, MessageCircle, Plus, Shield, Trash2 } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { Switch } from "@/components/workflows/Switch";
import { BTN, BTN_GHOST, Field, INPUT, LABEL } from "@/components/quotes/ui";
import { addHoliday, buttonProblem, copyToAll, dayHint, DAY_NAME, DAYS, fillPreview, locationPreview,
  type Hours, type LocationReply, type OptConfirm, type Welcome } from "./waBot";

const TEXTAREA = cn(INPUT, "min-h-24 py-2 leading-snug");
const HINT = "text-[11.5px] leading-snug text-[var(--haip-fg-subtle)]";

/** How the guest sees it in WhatsApp: one incoming bubble, reply buttons under it. */
export function Bubble({ text, buttons = [], label = "Guest sees" }: { text: string; buttons?: string[]; label?: string }) {
  const shown = buttons.map(b => b.trim()).filter(Boolean);
  return (
    <div aria-label={label}>
      <p className={cn(LABEL, "mb-1")}>{label}</p>
      <div className="rounded-2xl bg-[var(--haip-surface)] p-3">
        <div className="max-w-[300px]">
          <div className="rounded-lg rounded-tl-none bg-[var(--haip-card)] p-2 shadow-sm">
            <p className="whitespace-pre-wrap break-words text-[13px] leading-snug text-[var(--haip-fg)]">
              {text.trim() ? text : <span className="italic text-[var(--haip-fg-subtle)]">Your message appears here as you type…</span>}
            </p>
            <p className="mt-1 text-right text-[11px] text-[var(--haip-fg-subtle)]">10:42 AM</p>
          </div>
          {shown.length > 0 && (
            <div className="mt-1 space-y-1">
              {shown.map(b => <div key={b} className="truncate rounded-lg bg-[var(--haip-card)] py-2 text-center text-[12px] font-medium text-primary shadow-sm">{b}</div>)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function fmtDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

export function HoursCard({ hours, onChange, timezone, openNow, awayRule, disabled }: {
  hours: Hours; onChange: (h: Hours) => void; timezone: string; openNow: boolean; awayRule: string | null | undefined; disabled: boolean;
}) {
  const [date, setDate] = useState("");
  const [label, setLabel] = useState("");
  const setDay = (d: (typeof DAYS)[number], patch: Partial<Hours["weekly"]["mon"]>) =>
    onChange({ ...hours, weekly: { ...hours.weekly, [d]: { ...hours.weekly[d], ...patch } } });
  return (
    <Card>
      <CardHeader icon={Clock} title="Business hours"
        description={`When your team answers WhatsApp. Times in ${timezone}. Right now you are ${openNow ? "open" : "closed"}.`} />
      <CardBody className="space-y-4">
        <p className={HINT}>Guests who write on a closed day or a holiday get your away message, and the AI&apos;s &ldquo;we&apos;ll check with the team&rdquo; reply promises the next opening time.</p>
        <ul className="divide-y divide-[var(--haip-border)]">
          {DAYS.map(d => {
            const day = hours.weekly[d];
            return (
              <li key={d} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 py-2 sm:grid-cols-[7.5rem_auto_1fr]">
                <span className="text-sm font-medium text-[var(--haip-fg)]">{DAY_NAME[d]}</span>
                <span className="flex items-center gap-1 text-[12px] text-[var(--haip-fg-subtle)]">
                  {day.closed ? "Closed" : "Open"}
                  <Switch on={!day.closed} label={`${DAY_NAME[d]} open`} disabled={disabled} onChange={v => setDay(d, { closed: !v })} />
                </span>
                {!day.closed ? (
                  <div className="col-span-2 flex flex-wrap items-center gap-2 sm:col-span-1">
                    <input type="time" aria-label={`${DAY_NAME[d]} opens`} className={cn(INPUT, "w-32")} value={day.open} disabled={disabled}
                      onChange={e => setDay(d, { open: e.target.value })} />
                    <span className="text-[12px] text-[var(--haip-fg-subtle)]">to</span>
                    <input type="time" aria-label={`${DAY_NAME[d]} closes`} className={cn(INPUT, "w-32")} value={day.close} disabled={disabled}
                      onChange={e => setDay(d, { close: e.target.value })} />
                    {dayHint(day) && <span className={HINT}>{dayHint(day)}</span>}
                  </div>
                ) : <span className="hidden sm:block" />}
              </li>
            );
          })}
        </ul>
        {!disabled && <button type="button" className={BTN_GHOST} onClick={() => onChange({ ...hours, weekly: copyToAll(hours.weekly, "mon") })}>Use Monday&apos;s hours for every day</button>}

        <div className="space-y-2 border-t border-[var(--haip-border)] pt-4">
          <p className="text-sm font-semibold text-[var(--haip-fg)]">Holidays</p>
          <p className={HINT}>Closed all day, whatever the weekly hours say. Example: Diwali, 8 Nov.</p>
          {hours.holidays.length === 0
            ? <p className="text-[13px] text-[var(--haip-fg-subtle)]">No holidays yet.</p>
            : (
              <ul className="space-y-1">
                {hours.holidays.map(h => (
                  <li key={h.date} className="flex min-h-11 items-center justify-between gap-2 rounded-lg bg-[var(--haip-surface)] px-3">
                    <span className="min-w-0 truncate text-[13px] text-[var(--haip-fg)]"><span className="font-medium">{fmtDate(h.date)}</span>{h.label && ` · ${h.label}`}</span>
                    {!disabled && (
                      <button type="button" aria-label={`Remove ${h.label || h.date}`} className="inline-flex min-h-11 min-w-11 items-center justify-center text-[var(--haip-fg-subtle)] hover:text-[var(--haip-status-danger-fg)]"
                        onClick={() => onChange({ ...hours, holidays: hours.holidays.filter(x => x.date !== h.date) })}><Trash2 size={15} /></button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          {!disabled && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Date" htmlFor="hol-date" className="w-44"><input id="hol-date" type="date" className={INPUT} value={date} onChange={e => setDate(e.target.value)} /></Field>
              <Field label="Name (optional)" htmlFor="hol-label" className="min-w-0 flex-1 basis-40">
                <input id="hol-label" className={INPUT} maxLength={40} placeholder="Diwali" value={label} onChange={e => setLabel(e.target.value)} /></Field>
              <button type="button" className={BTN} disabled={!date}
                onClick={() => { onChange({ ...hours, holidays: addHoliday(hours.holidays, date, label) }); setDate(""); setLabel(""); }}>
                <Plus size={14} /> Add holiday
              </button>
            </div>
          )}
        </div>

        <div className="rounded-lg bg-[var(--haip-surface)] p-3 text-[13px] text-[var(--haip-fg-2)]">
          <span className="font-semibold">Replies when you&apos;re away: </span>
          {awayRule === undefined ? "checking…" : awayRule
            ? <>on (&ldquo;{awayRule}&rdquo;). </>
            : <>not set up yet. </>}
          <Link href="/dashboard/automations" className="font-semibold text-primary underline">{awayRule ? "Edit it in WhatsApp and rules" : "Set up an away message"}</Link>
          {!awayRule && awayRule !== undefined && <span className={cn(HINT, "block mt-1")}>In WhatsApp and rules, tap &ldquo;Away message&rdquo;: it uses the hours above.</span>}
        </div>
      </CardBody>
    </Card>
  );
}

export function WelcomeCard({ value, onChange, disabled }: { value: Welcome; onChange: (w: Welcome) => void; disabled: boolean }) {
  const set = (p: Partial<Welcome>) => onChange({ ...value, ...p });
  const buttons = [...value.buttons, "", "", ""].slice(0, 3);
  const problem = buttonProblem(value.buttons);
  return (
    <Card>
      <CardHeader icon={MessageCircle} title="Welcome message"
        description="The very first time someone writes to you, they get this once. Never twice to the same person."
        actions={<Switch on={value.enabled} label="Send a welcome message" disabled={disabled} onChange={v => set({ enabled: v })} />} />
      <CardBody className="space-y-3">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <Field label="Message" htmlFor="wb-text" hint="{first_name} becomes the guest's first name.">
              <textarea id="wb-text" className={TEXTAREA} maxLength={1024} value={value.text} disabled={disabled} onChange={e => set({ text: e.target.value })} /></Field>
            <div className="space-y-1">
              <span className={LABEL}>Quick buttons (optional, up to 3)</span>
              {buttons.map((b, i) => (
                <input key={i} aria-label={`Button ${i + 1}`} className={INPUT} maxLength={20} placeholder={["Check dates", "See photos", "Talk to us"][i]}
                  value={b} disabled={disabled}
                  onChange={e => set({ buttons: buttons.map((x, j) => (j === i ? e.target.value : x)).filter((x, j, all) => x.trim() || all.slice(j + 1).some(y => y.trim())) })} />
              ))}
              {problem && <p className="text-[12px] text-[var(--haip-status-danger-fg)]">{problem}</p>}
            </div>
          </div>
          <Bubble text={fillPreview(value.text)} buttons={value.buttons} />
        </div>
        <label className="flex min-h-11 items-start gap-2 text-sm text-[var(--haip-fg)]">
          <input type="checkbox" className="mt-1 accent-primary" checked={value.also_when_ai_replies} disabled={disabled}
            onChange={e => set({ also_when_ai_replies: e.target.checked })} />
          <span>Send even when the AI replies
            <span className={cn(HINT, "block")}>{value.also_when_ai_replies
              ? "The guest gets the welcome first, then the AI answers their question a few seconds later."
              : "Only when the AI is not answering by itself (AI off or drafts waiting for your team). Otherwise the AI's answer is the first reply."}</span>
          </span>
        </label>
        <p className={HINT}>A shared location gets the location reply instead, and a welcome replaces keyword replies for that first message.</p>
      </CardBody>
    </Card>
  );
}

export function LocationCard({ value, onChange, disabled }: { value: LocationReply; onChange: (l: LocationReply) => void; disabled: boolean }) {
  const set = (p: Partial<LocationReply>) => onChange({ ...value, ...p });
  const badLink = !!value.map_link.trim() && !value.map_link.trim().startsWith("https://");
  return (
    <Card>
      <CardHeader icon={MapPin} title="Location reply"
        description="When a guest shares their location pin. Example: “Thanks! We're 45 minutes from you. Here's the route: …”"
        actions={<Switch on={value.enabled} label="Reply to a shared location" disabled={disabled} onChange={v => set({ enabled: v })} />} />
      <CardBody>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <Field label="Message" htmlFor="lr-text" hint="{first_name} becomes the guest's first name. The AI stays out of this one message; your team sees the pin in the Inbox.">
              <textarea id="lr-text" className={TEXTAREA} maxLength={1024} value={value.text} disabled={disabled} onChange={e => set({ text: e.target.value })} /></Field>
            <Field label="Our map link (optional)" htmlFor="lr-map" hint="Paste your Google Maps link. It goes on its own line under the message.">
              <input id="lr-map" type="url" inputMode="url" className={INPUT} placeholder="https://maps.app.goo.gl/…" maxLength={500} value={value.map_link} disabled={disabled}
                onChange={e => set({ map_link: e.target.value })} /></Field>
            {badLink && <p className="text-[12px] text-[var(--haip-status-danger-fg)]">The link must start with https://</p>}
          </div>
          <Bubble text={locationPreview(value)} />
        </div>
      </CardBody>
    </Card>
  );
}

export function OptCard({ value, onChange, disabled }: { value: OptConfirm; onChange: (o: OptConfirm) => void; disabled: boolean }) {
  const set = (p: Partial<OptConfirm>) => onChange({ ...value, ...p });
  return (
    <Card>
      <CardHeader icon={Shield} title="STOP and START replies"
        description="A guest who writes STOP gets no more offers; START brings them back. This is the confirmation they get."
        actions={<Switch on={value.custom} label="Use my own words" disabled={disabled} onChange={v => set({ custom: v })} />} />
      <CardBody className="space-y-3">
        {!value.custom ? (
          <p className="text-[13px] text-[var(--haip-fg-2)]">Off: the guest gets your approved confirmation templates (haip_optout_confirm_v1 / haip_optin_confirm_v1). Turn on to write your own words.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-3">
              <Field label="After STOP" htmlFor="oc-stop"><textarea id="oc-stop" className={TEXTAREA} maxLength={1024} value={value.stop_text} disabled={disabled} onChange={e => set({ stop_text: e.target.value })} /></Field>
              <Field label="After START" htmlFor="oc-start"><textarea id="oc-start" className={TEXTAREA} maxLength={1024} value={value.start_text} disabled={disabled} onChange={e => set({ start_text: e.target.value })} /></Field>
            </div>
            <div className="space-y-3">
              <Bubble text={value.stop_text} label="After STOP, guest sees" />
              <Bubble text={value.start_text} label="After START, guest sees" />
            </div>
          </div>
        )}
        <p className={HINT}>Sent as a normal reply (the guest just wrote to you). If WhatsApp refuses it, the approved template goes instead. Booking and payment messages still reach a guest who wrote STOP.</p>
      </CardBody>
    </Card>
  );
}
