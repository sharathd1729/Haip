"use client";
// Website › Tracking: the Google Ads part (website growth #5, backend google_ads_conversions). Browser tag id + the
// "enquiry" / "begin checkout" labels, and the booking upload: customer id, conversion action id, the Google sign-in
// (Data Manager API, OAuth; HAIP keeps only encrypted tokens, never a password) and the switch.
import { btn, inputCls, openOAuth } from "@/components/marketing/studio/types";
import type { GadsSettings, GadsStatus } from "@/lib/websiteGrowth";

export type GadsForm = { [K in keyof GadsSettings]: K extends "gads_upload_enabled" ? boolean : string };

export const gadsForm = (t: GadsSettings): GadsForm => ({
  gads_id: t.gads_id || "", gads_enquiry_label: t.gads_enquiry_label || "", gads_checkout_label: t.gads_checkout_label || "",
  gads_customer_id: t.gads_customer_id || "", gads_login_customer_id: t.gads_login_customer_id || "",
  gads_booking_action_id: t.gads_booking_action_id || "", gads_upload_enabled: t.gads_upload_enabled,
});

const digits = (s: string) => s.replace(/\D/g, "") || null;

export const gadsPayload = (f: GadsForm): GadsSettings => ({
  gads_id: f.gads_id.trim().toUpperCase() || null, gads_enquiry_label: f.gads_enquiry_label.trim() || null,
  gads_checkout_label: f.gads_checkout_label.trim() || null, gads_customer_id: digits(f.gads_customer_id),
  gads_login_customer_id: digits(f.gads_login_customer_id), gads_booking_action_id: digits(f.gads_booking_action_id),
  gads_upload_enabled: f.gads_upload_enabled,
});

type Props = { v: GadsForm; set: (k: keyof GadsForm, val: string | boolean) => void; status?: GadsStatus };

function Field({ label, value, onChange, placeholder, hint }: { label: string; value: string; onChange: (v: string) => void;
  placeholder: string; hint?: string }) {
  return (
    <label className="grid gap-1"><span className="text-sm font-semibold">{label}</span>
      <input className={inputCls} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
      {hint && <span className="text-xs text-[var(--haip-fg-muted)]">{hint}</span>}</label>
  );
}

export function GoogleAdsFields({ v, set, status }: Props) {
  const connected = status?.connected && status.status === "active";
  return (
    <div className="grid gap-3 border-t border-[var(--haip-border)] pt-4">
      <p className="font-semibold">Google Ads</p>
      <Field label="Google Ads tag id" value={v.gads_id} onChange={x => set("gads_id", x)} placeholder="AW-123456789" />
      {v.gads_id.trim() && <>
        <Field label="Enquiry conversion label" value={v.gads_enquiry_label} onChange={x => set("gads_enquiry_label", x)}
          placeholder="From the conversion action's tag setup" />
        <Field label="Begin checkout conversion label" value={v.gads_checkout_label} onChange={x => set("gads_checkout_label", x)}
          placeholder="From the conversion action's tag setup" />
      </>}
      <p className="text-sm text-[var(--haip-fg-muted)]">Bookings: HAIP sends each booking to Google Ads itself (website, WhatsApp, phone and
        manual bookings), with its value, so Google learns which ads bring real stays. Only for guests who agreed to offers.</p>
      <Field label="Google Ads customer id" value={v.gads_customer_id} onChange={x => set("gads_customer_id", x)} placeholder="123-456-7890" />
      <Field label="Manager account id (optional)" value={v.gads_login_customer_id} onChange={x => set("gads_login_customer_id", x)}
        placeholder="Only if you sign in through a manager account" />
      <Field label="Booking conversion action id" value={v.gads_booking_action_id} onChange={x => set("gads_booking_action_id", x)}
        placeholder="Digits" hint={'A conversion action of type "Import from clicks". Its id is in the URL of the action (ctId=...).'} />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="mr-auto">{connected ? "Google account connected."
          : status?.status === "error" ? `Google stopped accepting HAIP's login: ${status.last_error || "connect again"}.`
          : "Not connected to Google yet."}</span>
        {status?.available === false ? <span className="text-[var(--haip-fg-muted)]">Ask your HAIP admin to set up Google sign-in.</span>
          : <button type="button" className={btn} onClick={() => void openOAuth("/websites/google-ads/oauth-start")}>
            {connected ? "Connect again" : "Connect Google"}</button>}
      </div>
      {connected && status?.last_error && <p className="text-sm text-[var(--haip-status-danger-fg)]">Last upload failed: {status.last_error}</p>}
      <label className="flex min-h-11 items-center gap-3"><input type="checkbox" className="h-5 w-5 accent-[var(--primary)]"
        checked={v.gads_upload_enabled} onChange={e => set("gads_upload_enabled", e.target.checked)} />
        <span className="font-semibold">Send bookings to Google Ads</span></label>
    </div>
  );
}
