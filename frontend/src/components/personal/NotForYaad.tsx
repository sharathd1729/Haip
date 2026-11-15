"use client";
// Business-only shell parts (live inbox stream, health bar polling every 30 s, sample-data banner) are not mounted for a
// personal workspace: Yaad has no inbox, integrations or sample data, and each one cost a request or a held connection.
import { usePathname } from "next/navigation";
import { PERSONAL_HOME } from "@/components/layout/nav";
import { usePersonalMode } from "@/components/providers/WorkspaceProvider";

export function NotForYaad({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const personal = usePersonalMode() || pathname === PERSONAL_HOME || pathname.startsWith(PERSONAL_HOME + "/");
  return personal ? null : <>{children}</>;
}
