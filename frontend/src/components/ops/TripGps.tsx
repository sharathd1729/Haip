"use client";
// The trip file's GPS card: a small map with the road driven (solid) and the planned route + approved detours (dashed),
// and GPS distance beside the odometer. The odometer photo bills the trip; GPS distance is only a cross-check.
// Reads GET /ops/gps/files/{id}/track (planned route is set through PUT .../route; drawing it on the map comes later).
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { distanceCheck, type GpsTrack } from "@/lib/gps";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { GpsMap, type MapLine } from "./GpsMap";

export function TripGps({ fileId, live }: { fileId: string; live: boolean }) {
  const { data, isPending, isError } = useQuery<GpsTrack>({
    queryKey: ["ops-gps-track", fileId],
    queryFn: () => api.get(`/ops/gps/files/${fileId}/track`).then(r => r.data),
    staleTime: 20_000,
    refetchInterval: live ? 60_000 : false,
  });
  const lines = useMemo<MapLine[]>(() => {
    if (!data?.points) return [];
    const r = data.planned_route;
    return [
      ...(r?.points?.length ? [{ id: "planned", kind: "planned" as const, coords: r.points.map(p => [p.lat, p.lng] as [number, number]) }] : []),
      ...(r?.detours ?? []).map((d, i) => ({ id: `detour-${i}`, kind: "detour" as const, coords: d.points })),
      { id: "track", kind: "track" as const, coords: data.points },
    ];
  }, [data]);

  if (isPending || isError || !data?.points) return null;
  const check = distanceCheck(data);
  const empty = data.points.length === 0 && !data.planned_route?.points?.length;
  return (
    <Card>
      <CardHeader title="Where it went" tone="plain"
        description={check ?? (live ? "No GPS position on this trip yet" : "No GPS track for this trip")} />
      {!empty && (
        <CardBody className="px-4 pb-4">
          <GpsMap label="Map of this trip" lines={lines} className="h-64" />
          <p className="mt-2 text-[13px] text-[var(--haip-fg-subtle)]">
            Solid: road driven{data.planned_route?.points?.length ? " · dashed: planned route" : " · no planned route set"}.
            The odometer photo is what the guest is billed for.
          </p>
        </CardBody>
      )}
    </Card>
  );
}
