"use client";
// Dev-only gallery of the shared UI kit with worst-case data (long names, huge numbers, empty, error,
// loading). Not linked in the nav and 404s in production. Use it to check a component in light/dark and
// at phone width before putting it on a real page.
import { useState } from "react";
import { notFound } from "next/navigation";
import { AlertTriangle, CalendarCheck, Clock, IndianRupee, MessageSquare, Sparkles, Users } from "@/lib/icons";
import {
  Card, CardBody, CardHeader, DataTable, Drawer, EmptyState, FilterBar, FilterChip, FilterSearch,
  PageHeader, SectionNav, Stat, StatusPill, Tabs, Timeline, type Column, type Density,
} from "@/components/ui/kit";
import { PhoneKit } from "./PhoneKit";

interface Row { id: string; guest: string; property: string; nights: number; amount: string; status: "Confirmed" | "Pending" | "Cancelled" }

const ROWS: Row[] = [
  { id: "1", guest: "Priya Subramaniam-Venkataraghavan Iyer", property: "Ratha Caravan — Riverside Deluxe Suite With Private Deck", nights: 3, amount: "₹1,25,000", status: "Confirmed" },
  { id: "2", guest: "Vividh Singh", property: "Caravan 2", nights: 1, amount: "₹25,000", status: "Pending" },
  { id: "3", guest: "Al", property: "Caravan 1", nights: 12, amount: "₹12,34,56,789", status: "Cancelled" },
];

const TONE = { Confirmed: "success", Pending: "warning", Cancelled: "danger" } as const;

const COLUMNS: Column<Row>[] = [
  { key: "guest", header: "Guest", cell: r => <span className="font-semibold">{r.guest}</span> },
  { key: "property", header: "Property", hideBelow: "md", cell: r => r.property },
  { key: "nights", header: "Nights", align: "right", hideBelow: "sm", cell: r => r.nights },
  { key: "amount", header: "Amount", align: "right", cell: r => r.amount },
  { key: "status", header: "Status", cell: r => <StatusPill tone={TONE[r.status]}>{r.status}</StatusPill> },
];

type TableMode = "data" | "loading" | "empty" | "error";

export default function DevKitPage() {
  if (process.env.NODE_ENV === "production") notFound();

  const [tab, setTab] = useState("upcoming");
  const [q, setQ] = useState("");
  const [chip, setChip] = useState(false);
  const [section, setSection] = useState("profile");
  const [mode, setMode] = useState<TableMode>("data");
  const [density, setDensity] = useState<Density>("comfortable");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState(false);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-4 sm:p-6">
      <PageHeader title="UI kit" icon={Sparkles} subtitle="Shared building blocks, with worst-case data. Development only."
        actions={<>
          <button type="button" className="haip-btn-secondary">Export</button>
          <button type="button" className="haip-btn-primary">New booking</button>
        </>} />

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Bookings" value="128" hint="next 30 days" icon={CalendarCheck} change={{ text: "+12%", tone: "success" }} />
        <Stat label="Revenue collected" value="₹12,34,56,78,901" hint="all time" icon={IndianRupee} variant="dark" />
        <Stat label="Conversion" value="0%" hint="last 7 days" icon={Users} variant="olive" change={null} />
        <Stat label="Money due" value="₹1,25,000" hint="3 bookings, part paid" icon={AlertTriangle} variant="accent" />
        <Stat label="Replies waiting" value="7" hint="right now" icon={MessageSquare} />
        <Stat label="Avg first reply" value="4 min" hint="last 7 days" icon={Clock} />
        <Stat label="No icon" value="42" hint="this month" />
        <Stat label="Loading" value="—" loading />
      </section>

      <Card>
        <CardHeader title="Tabs, filters and chips" icon={Sparkles} description="Search keeps the widest slot; chips wrap."
          actions={<StatusPill tone="brand">Live</StatusPill>} />
        <CardBody className="flex flex-col gap-3">
          <Tabs label="Bookings view" value={tab} onChange={setTab}
            items={[{ value: "upcoming", label: "Upcoming", count: 14 }, { value: "past", label: "Past", count: 212 }, { value: "cancelled", label: "Cancelled", count: 3 }, { value: "holds", label: "Holds" }]} />
          <FilterBar>
            <FilterSearch value={q} onChange={setQ} placeholder="Search guest, phone, booking id" />
            <FilterChip active={chip} onClick={() => setChip(v => !v)} count={5}>Needs payment</FilterChip>
            <FilterChip onClick={() => undefined}>This month</FilterChip>
          </FilterBar>
          <div className="flex flex-wrap gap-2">
            {(["neutral", "info", "success", "warning", "danger", "brand", "highlight"] as const).map(t => <StatusPill key={t} tone={t}>{t}</StatusPill>)}
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="haip-btn-primary">Collect payment</button>
            <button type="button" className="haip-btn-secondary">Send reminder</button>
            <button type="button" className="haip-btn-primary" disabled>Disabled</button>
            <button type="button" className="h-10 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground">Page-style bg-primary</button>
            <a href="#kit" className="inline-flex items-center text-sm font-semibold text-primary underline-offset-4 hover:underline">A link stays green</a>
          </div>
        </CardBody>
      </Card>

      <section className="flex flex-col gap-2">
        <Tabs label="Table state" value={mode} onChange={v => setMode(v as TableMode)}
          items={[{ value: "data", label: "Data" }, { value: "loading", label: "Loading" }, { value: "empty", label: "Empty" }, { value: "error", label: "Error" }]} />
        <DataTable columns={COLUMNS} rows={mode === "data" ? ROWS : []} rowKey={r => r.id}
          loading={mode === "loading"} error={mode === "error" ? "The server did not answer in time." : null} onRetry={() => setMode("data")}
          empty={{ title: "No bookings yet", hint: "Bookings from your channels and the Add booking button show up here." }}
          selectedKeys={selected} onSelectionChange={setSelected}
          density={density} onDensityChange={setDensity} onRowClick={() => setOpen(true)} />
      </section>

      <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
        <SectionNav label="Settings sections" value={section} onChange={setSection}
          items={[{ value: "profile", label: "Profile", hint: "Name, timezone" }, { value: "team", label: "Team", hint: "Roles and invites" }, { value: "billing", label: "Billing" }]} />
        <Card>
          <CardHeader title="History" tone="olive" icon={Clock} description="Olive header band" />
          <CardBody>
            <Timeline entries={[
              { id: "a", title: "Call answered", detail: "Anita · 4 min 12 s · outcome: site visit booked", time: "10:42", badge: <StatusPill tone="success">Answered</StatusPill> },
              { id: "b", title: "WhatsApp reply sent", detail: "https://example.com/a/very/long/link/that/should/wrap/instead/of/overflowing/the/card/in/a/narrow/viewport", time: "Yesterday" },
              { id: "c", title: "Enquiry created", time: "9 Oct" },
            ]} />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Plain header (opt-out)" tone="plain" description="Opt-out: the old borderless title" />
        <EmptyState title="Nothing waiting on you" hint="New enquiries and replies will show up here." />
      </Card>

      <PhoneKit />

      <Drawer open={open} onOpenChange={setOpen} title="Booking detail" description="Priya S. · 3 nights"
        footer={<button type="button" onClick={() => setOpen(false)} className="h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground">Done</button>}>
        <Timeline entries={[{ id: "x", title: "Deposit received", time: "11 Oct" }]} />
      </Drawer>
    </div>
  );
}
