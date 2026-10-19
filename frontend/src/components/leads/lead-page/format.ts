// Lead page formatting: money in lakh grouping, every time in the workspace timezone (IST).
const TZ = "Asia/Kolkata";

export const inr = (n?: number | null) => (n == null || !Number.isFinite(n) ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`);

const dayKey = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: TZ });

export function istTime(iso?: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-IN", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
}

/** "Mon 19 Oct" (adds the year when it is not this year). */
export function istDate(iso?: string | null, now = new Date()): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00+05:30` : iso);
  const sameYear = d.toLocaleDateString("en-CA", { timeZone: TZ, year: "numeric" }) === now.toLocaleDateString("en-CA", { timeZone: TZ, year: "numeric" });
  return d.toLocaleDateString("en-GB", { timeZone: TZ, weekday: "short", day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) })
    .replace(",", "");
}

/** The day separator in the thread: "Today · Mon 19 Oct", "Yesterday · Sun 18 Oct", else the date. */
export function dayLabel(iso: string, now = new Date()): string {
  const k = dayKey(new Date(iso));
  if (k === dayKey(now)) return `Today · ${istDate(iso, now)}`;
  if (k === dayKey(new Date(now.getTime() - 86_400_000))) return `Yesterday · ${istDate(iso, now)}`;
  return istDate(iso, now);
}

export const sameDay = (a: string, b: string) => dayKey(new Date(a)) === dayKey(new Date(b));

export function when(iso?: string | null, now = new Date()): string {
  if (!iso) return "";
  const k = dayKey(new Date(iso));
  if (k === dayKey(now)) return `today ${istTime(iso)}`;
  if (k === dayKey(new Date(now.getTime() - 86_400_000))) return `yesterday ${istTime(iso)}`;
  return `${istDate(iso, now)}, ${istTime(iso)}`;
}

export function durationText(s?: number | null): string {
  const n = Math.max(0, Math.round(s ?? 0));
  return n >= 60 ? `${Math.floor(n / 60)} min ${n % 60} s` : `${n} s`;
}

export function nights(checkIn?: string | null, checkOut?: string | null): number | null {
  if (!checkIn || !checkOut) return null;
  const n = Math.round((Date.parse(`${checkOut.slice(0, 10)}T00:00:00Z`) - Date.parse(`${checkIn.slice(0, 10)}T00:00:00Z`)) / 86_400_000);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

export const firstName = (name?: string | null) => (name || "").trim().split(/\s+/)[0] || "Guest";

const CHANNEL: Record<string, string> = {
  whatsapp: "WhatsApp", instagram: "Instagram", call: "Phone call", phone: "Phone call", voice: "Phone call", webchat: "Website chat",
  email: "Email", website: "Website", walk_in: "Walk-in", referral: "Referral",
};
export const channelName = (c?: string | null) => (c ? CHANNEL[c.toLowerCase()] ?? c.replace(/_/g, " ") : "");

const SOURCE: Record<string, string> = {
  meta_ig: "Instagram ad", meta_fb: "Facebook ad", click_to_wa: "WhatsApp ad", wa_direct: "WhatsApp", phone: "Phone call",
  organic_call: "Phone call, no ad", website: "Website", google: "Google", email: "Email", walk_in: "Walk-in", referral: "Referral",
  travel_agent: "Travel agent", ota_airbnb: "Airbnb", ota_booking: "Booking.com", ota_vrbo: "Vrbo", channel_manager: "Channel manager",
};
export const sourceName = (s?: string | null) => (s ? SOURCE[s.toLowerCase()] ?? s.replace(/_/g, " ") : "Not recorded");
