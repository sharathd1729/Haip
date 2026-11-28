"use client";
// Call / WhatsApp, two ways (owner, 28 Nov 2026): agents also use their own phone and their own WhatsApp.
//   Call     = My phone (opens the dialer with the guest's number) | Office line (click-to-call: the IVR rings you, then the guest)
//   WhatsApp = My WhatsApp (opens the chat in WhatsApp, no saving the contact) | HAIP WhatsApp (the business number, in HAIP)
// "My ..." needs the real number, so it goes through the audited reveal (POST /leads/{id}/contact/reveal, guests.pii.reveal):
// a role without that permission is offered the office line / HAIP WhatsApp only. The number can also be shown and copied here.
// "Remember my choice" is kept on this device (a convenience, not a setting): the next tap acts at once; forgetChoices() asks again.
import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { Building, Check, Copy, Eye, Loader2, Phone } from "@/lib/icons";
import { ChannelIcon } from "@/components/inbox/ChannelIcon";
import { BottomSheet } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

export type ContactKind = "call" | "whatsapp";
export type Via = "mine" | "office";

const KEY = (kind: ContactKind) => `haip:contact-via:${kind}`;

/** The roles that hold guests.pii.reveal by default (backend authz_service; the lead pages use the same list). A workspace
 *  can change a role's permission: the server then refuses and the sheet says so. */
export function canRevealNumbers(role: string | null | undefined): boolean {
  return ["owner", "manager", "reservations", "concierge", "compliance"].includes(role ?? "");
}

export function rememberedVia(kind: ContactKind): Via | null {
  try { const v = window.localStorage.getItem(KEY(kind)); return v === "mine" || v === "office" ? v : null; } catch { return null; }
}
function remember(kind: ContactKind, via: Via) { try { window.localStorage.setItem(KEY(kind), via); } catch { /* private window: ask each time */ } }
/** True when a Call or WhatsApp choice is remembered on this device. */
export function hasRememberedChoice(): boolean { return !!(rememberedVia("call") || rememberedVia("whatsapp")); }
export function forgetChoices() { try { window.localStorage.removeItem(KEY("call")); window.localStorage.removeItem(KEY("whatsapp")); } catch { /* nothing kept */ } }

/** tel: keeps the leading +; wa.me wants digits only (country code first). */
export function contactHref(kind: ContactKind, phone: string): string {
  return kind === "call" ? `tel:${phone.replace(/[^\d+]/g, "")}` : `https://wa.me/${phone.replace(/\D/g, "")}`;
}

const WORDS = {
  call: {
    title: (name: string) => `Call ${name}`,
    mine: "My phone", mineHint: "Opens your dialer with the number",
    office: "Office line", officeHint: "Your phone rings first, then the guest",
    noReveal: "Your role cannot see guest numbers, so calls go through the office line.",
  },
  whatsapp: {
    title: (name: string) => `WhatsApp ${name}`,
    mine: "My WhatsApp", mineHint: "Opens the chat in WhatsApp, no saving the contact",
    office: "HAIP WhatsApp", officeHint: "The business number, kept in HAIP",
    noReveal: "Your role cannot see guest numbers, so messages go from HAIP WhatsApp.",
  },
} as const;

const choice = "flex min-h-16 w-full cursor-pointer items-center gap-3 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3.5 py-2.5 text-left transition-colors active:scale-[0.98] hover:bg-[var(--haip-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-55";
const small = "inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-semibold text-primary hover:bg-[var(--haip-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-60";

/** `start()` is what a Call / WhatsApp button runs; render `sheet` once beside it. `onOffice` is the existing HAIP action
 *  (click-to-call, or opening the HAIP WhatsApp composer). */
export function useContactChoice({ kind, inquiryId, name, onOffice, canReveal, phoneMasked, phone }: {
  kind: ContactKind; inquiryId: string; name: string; onOffice: () => void; canReveal: boolean; phoneMasked?: string | null;
  /** The number, when this screen already shows it to this person (the Inbox does): used as is, with no reveal call. */
  phone?: string | null;
}): { start: () => void; sheet: ReactNode } {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [keep, setKeep] = useState(false);
  const [revealed, setShown] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const shown = revealed ?? phone ?? null;
  canReveal = canReveal || !!phone;
  const w = WORDS[kind];

  const reveal = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/contact/reveal`).then(r => (r.data as { phone?: string | null }).phone ?? null),
    onError: () => toast({ variant: "error", title: "Couldn't get the number", description: "Your role may not be allowed to see it. Use the other option." }),
  });

  const mine = async () => {
    let phone = shown;
    if (!phone) { try { phone = await reveal.mutateAsync(); } catch { return; } }
    if (!phone) { toast({ variant: "error", title: `${name} has no phone number yet` }); return; }
    const href = contactHref(kind, phone);
    // A new tab for WhatsApp on a computer; on a phone (or when the browser blocks the tab) hand over in place.
    if (kind === "whatsapp" && window.matchMedia?.("(pointer: fine)").matches && window.open(href, "_blank", "noopener,noreferrer")) return;
    window.location.href = href;
  };
  const go = (via: Via) => {
    if (keep) remember(kind, via);
    setOpen(false);
    if (via === "office") onOffice(); else void mine();
  };
  const start = () => {
    const usual = rememberedVia(kind);
    if (usual === "office" || (usual === "mine" && canReveal)) { if (usual === "office") onOffice(); else void mine(); return; }
    setKeep(false); setCopied(false); setOpen(true);
  };
  const show = async () => { try { setShown(await reveal.mutateAsync()); } catch { /* the toast said why */ } };
  const copy = async () => {
    if (!shown) return;
    try { await navigator.clipboard.writeText(shown); setCopied(true); }
    catch { toast({ variant: "error", title: "Couldn't copy", description: "Press and hold the number to copy it." }); }
  };

  const sheet = (
    <BottomSheet open={open} onOpenChange={o => { if (!o) { setOpen(false); setShown(null); } }} title={w.title(name)}>
      <div className="grid gap-2.5">
        <button type="button" className={choice} disabled={!canReveal || reveal.isPending} onClick={() => go("mine")}>
          <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[var(--haip-dom-lead-bg)] text-[var(--haip-dom-lead-ink)]">
            {kind === "call" ? <Phone size={18} /> : <ChannelIcon channel="whatsapp" showBg={false} />}
          </span>
          <span className="grid min-w-0 gap-0.5">
            <span className="text-[15px] font-bold text-[var(--haip-fg)]">{w.mine}</span>
            <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{w.mineHint}</span>
          </span>
        </button>
        <button type="button" className={choice} onClick={() => go("office")}>
          <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[var(--haip-dom-call-bg)] text-[var(--haip-dom-call-ink)]"><Building size={18} /></span>
          <span className="grid min-w-0 gap-0.5">
            <span className="text-[15px] font-bold text-[var(--haip-fg)]">{w.office}</span>
            <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{w.officeHint}</span>
          </span>
        </button>

        {canReveal ? (
          <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-2 rounded-xl bg-[var(--haip-surface)] pl-3 pr-1">
            <span className="min-w-0 text-[14px] font-semibold tabular-nums text-[var(--haip-fg)]">{shown ?? phoneMasked ?? "Number hidden"}</span>
            {shown ? (
              <button type="button" className={small} onClick={copy}>{copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}{copied ? "Copied" : "Copy"}</button>
            ) : (
              <button type="button" className={small} onClick={show} disabled={reveal.isPending}>
                {reveal.isPending ? <Loader2 size={14} className="motion-safe:animate-spin" aria-hidden /> : <Eye size={14} aria-hidden />}Show number
              </button>
            )}
          </div>
        ) : (
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">{w.noReveal}</p>
        )}
        {canReveal && !phone && <p className="-mt-1 text-[12px] text-[var(--haip-fg-subtle)]">Using or showing the number is logged.</p>}

        <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[14px] text-[var(--haip-fg-2)]">
          <input type="checkbox" checked={keep} onChange={e => setKeep(e.target.checked)} className={cn("size-5 cursor-pointer accent-[var(--primary)]")} />
          Remember my choice on this device
        </label>
      </div>
    </BottomSheet>
  );
  return { start, sheet };
}
