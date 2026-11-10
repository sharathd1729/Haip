"use client";
// The guest's details form (names, ID, Form C) and their add-ons (upsell) link on the booking page (owner, 10 Nov 2026):
// the same cards as Ops -> the stay's file, so staff need not open Ops for them. Shown only to roles with Ops access and
// only when the booking has an ops file (GET /ops/files/by-stay answers 404 when the business has no ops pack yet).
import { useSession } from "next-auth/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { AddonsCard } from "@/components/ops/AddonsCard";
import { GuestFormCard } from "@/components/ops/TripCards";
import { OPS_READ_ROLES, canManageOps, canWriteOps, type OpsFileFull } from "@/lib/ops";

export function BookingGuestCards({ bookingId }: { bookingId: string }) {
  const role = useSession().data?.user?.role;
  const allowed = OPS_READ_ROLES.includes(role ?? "");
  const qc = useQueryClient();
  const link = useQuery<{ id: string }>({
    queryKey: ["ops-file-by-stay", bookingId],
    queryFn: () => api.get(`/ops/files/by-stay/${bookingId}`).then(r => r.data),
    enabled: allowed,
    retry: false,
    staleTime: 300_000,
  });
  const fileId = link.data?.id;
  const file = useQuery<OpsFileFull>({            // same key as the Ops file page, so a change in one shows in the other
    queryKey: ["ops-file", fileId],
    queryFn: () => api.get(`/ops/files/${fileId}`).then(r => r.data),
    enabled: !!fileId,
  });
  if (!allowed || !file.data) return null;       // no ops file for this booking (or no access): nothing to show
  return (
    <>
      <GuestFormCard f={file.data} canWrite={canWriteOps(role)} canManage={canManageOps(role)}
        onSent={() => qc.invalidateQueries({ queryKey: ["ops-file", fileId] })} />
      <AddonsCard fileId={file.data.id} canWrite={canWriteOps(role)} />
    </>
  );
}
