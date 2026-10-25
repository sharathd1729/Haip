"use client";
// One trip's ops file. The layout lives in components/ops/TripFile.tsx.
import { useParams } from "next/navigation";
import { TripFile } from "@/components/ops/TripFile";

export default function OpsFilePage() {
  const { id } = useParams<{ id: string }>();
  return <TripFile id={id} />;
}
