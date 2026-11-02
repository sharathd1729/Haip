"use client";
// Ops map: where every vehicle is right now (phone first: map on top, one row per vehicle below). One read,
// GET /ops/gps/live, refreshed every 30 s. A vehicle with an open GPS alert shows red on the map and in its row.
import { useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useHydrated } from "@/lib/bookingAgenda";
import { vehicleLine, type GpsLive, type LiveVehicle } from "@/lib/gps";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";
import { GpsMap, type MapMarker } from "@/components/ops/GpsMap";

const short = (name: string) => name.replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/).map(w => w[0]).join("").slice(0, 3).toUpperCase() || "?";

function VehicleRow({ v }: { v: LiveVehicle }) {
  const red = v.alerts.length > 0;
  const body = (
    <>
      <span className="flex items-center gap-2">
        <span className="truncate text-[16px] font-semibold text-[var(--haip-fg)]">{v.name}</span>
        {red ? <StatusPill tone="danger">{v.alerts.length} alert{v.alerts.length === 1 ? "" : "s"}</StatusPill>
          : v.file_id ? <StatusPill tone="brand">On a trip</StatusPill> : null}
      </span>
      <span className="mt-0.5 block text-[14px] text-[var(--haip-fg-muted)]">{vehicleLine(v)}{v.guest_name ? ` · ${v.guest_name}` : ""}</span>
      {v.alerts.map(a => (
        <span key={a.id} className="mt-1 block text-[13.5px] leading-snug text-[var(--haip-status-danger-fg)]">
          {a.title.charAt(0).toUpperCase() + a.title.slice(1)}
        </span>
      ))}
    </>
  );
  const cls = cn("block min-h-[64px] border-t border-[var(--haip-border)] px-4 py-3 first:border-t-0",
    red && "border-l-4 border-l-[var(--haip-status-danger-fg)]");
  return v.file_id ? <Link href={`/dashboard/ops/files/${v.file_id}`} className={cls}>{body}</Link> : <div className={cls}>{body}</div>;
}

export default function OpsMapPage() {
  const hydrated = useHydrated();
  const router = useRouter();
  const { data, isPending, isError, refetch } = useQuery<GpsLive>({
    queryKey: ["ops-gps-live"],
    queryFn: () => api.get("/ops/gps/live").then(r => r.data),
    staleTime: 10_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const markers = useMemo<MapMarker[]>(() => (data?.vehicles ?? [])
    .filter(v => v.lat !== null && v.lng !== null)
    .map(v => ({
      id: v.property_id, lat: v.lat!, lng: v.lng!, label: short(v.name),
      title: `${v.name}: ${vehicleLine(v)}`,
      tone: v.alerts.length ? "alert" : v.state === "moving" ? "moving" : "parked",
      onClick: v.file_id ? () => router.push(`/dashboard/ops/files/${v.file_id}`) : undefined,
    })), [data, router]);
  const alerts = data?.vehicles.reduce((n, v) => n + v.alerts.length, 0) ?? 0;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 sm:p-6">
      <Link href="/dashboard/ops" className="text-[14px] font-semibold text-primary">← Ops today</Link>
      <PageHeader title="Vehicle map"
        subtitle={!data ? "Where every vehicle is now" : alerts ? `${alerts} GPS alert${alerts === 1 ? "" : "s"} open` : "No GPS alerts"} />
      {!hydrated || isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true"><Skeleton className="h-[55vh]" /><Skeleton className="h-20" /></div>
      ) : isError || !data ? (
        <Card>
          <EmptyState title="Couldn't load the map" hint="Check your connection, then try again."
            action={<button type="button" className="haip-btn-primary min-h-12" onClick={() => refetch()}>Try again</button>} />
        </Card>
      ) : data.vehicles.length === 0 ? (
        <Card>
          <EmptyState title="No trackers yet" hint="Add each vehicle's tracker on the GPS settings page, then its position shows here."
            action={<Link href="/dashboard/settings/gps" className="haip-btn-primary min-h-12">GPS settings</Link>} />
        </Card>
      ) : (
        <>
          <GpsMap label="Map of vehicles" markers={markers} className="h-[55vh] min-h-[280px]" />
          <section aria-label="Vehicles" className="haip-card overflow-hidden p-0">
            {data.vehicles.map(v => <VehicleRow key={v.property_id} v={v} />)}
          </section>
        </>
      )}
    </div>
  );
}
