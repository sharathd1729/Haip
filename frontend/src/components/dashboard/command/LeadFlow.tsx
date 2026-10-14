"use client";
// Conversations, contacts, leads and enquiries side by side, each saying exactly what it counts. They are DIFFERENT things and
// are never added up: a conversation is a chat thread, a contact is a person we have no phone number for yet, a lead is a person we
// hold a phone number for, an enquiry is a record (one person can have several). Lead numbers are unique people.
import type { ReactNode } from "react";
import Link from "next/link";
import { Info } from "@/lib/icons";
import { ChangePill, SectionTitle } from "./parts";
import { num, pct, type BusinessOverview, type Change } from "./types";

function Item({ label, value, change, basis, href }: { label: string; value: ReactNode; change?: Change | null; basis: string; href: string }) {
  return (
    <li className="min-w-0 bg-[var(--haip-card)]">
      <Link href={href} className="flex h-full min-h-11 flex-col gap-1 px-3.5 py-3 transition-colors hover:bg-[var(--haip-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/40">
        <span className="text-[12px] font-medium leading-tight text-[var(--haip-fg-subtle)]">{label}</span>
        <span className="flex items-baseline gap-2">
          <span className="font-[family-name:var(--font-display)] text-[22px] font-semibold leading-none tabular-nums text-[var(--haip-fg)]">{value}</span>
          <ChangePill change={change ?? null} />
        </span>
        <span className="text-[11.5px] leading-snug text-[var(--haip-fg-subtle)]">{basis}</span>
      </Link>
    </li>
  );
}

export function LeadFlow({ data }: { data: BusinessOverview }) {
  const { leads } = data;
  return (
    <section aria-labelledby="leadflow-title" className="haip-card px-4 py-4 sm:px-6 sm:py-5">
      <SectionTitle sub="Each figure counts something different; none of them is a sum of the others">
        <span id="leadflow-title">Conversations and leads</span>
      </SectionTitle>
      <ul className="grid grid-cols-1 gap-px overflow-hidden rounded-[var(--radius)] border border-[var(--haip-border)] bg-[var(--haip-border)] sm:grid-cols-2 xl:grid-cols-3">
        <Item label="New conversations" value={num(leads.conversations_new.count)} change={leads.conversations_new.change} href="/dashboard/inbox"
          basis="Chat threads opened in the period. One person can have several." />
        <Item label="Contacts without a number" value={num(leads.unidentified_contacts.count)} change={leads.unidentified_contacts.change} href="/dashboard/inbox"
          basis="New people with no phone number yet. Not leads until we have one." />
        <Item label="New leads" value={num(leads.identified_new.count)} change={leads.identified_new.change} href="/dashboard/leads"
          basis="People whose phone number was captured in the period. Each counted once, across every channel." />
        <Item label="Leads active in the period" value={num(leads.identified_active.count)} href="/dashboard/leads"
          basis="Unique leads who messaged, called or enquired in the period, new or not." />
        <Item label="Qualified leads" value={num(leads.qualified_new.count)} change={leads.qualified_new.change} href="/dashboard/leads"
          basis={leads.qualified_new.rate_of_new == null ? "Of the new leads, those with a real enquiry." : `${pct(leads.qualified_new.rate_of_new)} of the new leads have a real enquiry.`} />
        <Item label="Enquiries" value={num(leads.enquiries.created)} href="/dashboard/leads"
          basis={`Enquiry records created. ${num(leads.enquiries.repeat)} came from someone who had enquired before.`} />
      </ul>
      <p className="mt-3 flex items-start gap-2 text-[12px] leading-relaxed text-[var(--haip-fg-subtle)]">
        <Info size={14} className="mt-0.5 shrink-0" aria-hidden />
        <span>{leads.definition}</span>
      </p>
    </section>
  );
}
