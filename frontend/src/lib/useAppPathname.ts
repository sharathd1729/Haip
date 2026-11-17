"use client";
import { usePathname } from "next/navigation";
import { toAppPath } from "./workspacePath";

/** usePathname() in app terms: the same answer whether the address bar shows /w/<slug>/... or /dashboard/... */
export function useAppPathname(): string {
  return toAppPath(usePathname() ?? "");
}
