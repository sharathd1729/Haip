"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import api from "@/lib/api";

export type BusinessType = "caravan" | "villa_resort" | "homestay" | "hotel";

export interface WorkspaceContext {
  workspace_id: string;
  active_modules: string[];
  flags: Record<string, boolean>;
  plan: string;
  business_type: BusinessType | null;
}

const Ctx = createContext<WorkspaceContext | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [ctx, setCtx] = useState<WorkspaceContext | null>(null);

  useEffect(() => {
    api.get("/workspace/context").then((r) => setCtx(r.data)).catch(() => {});
  }, []);

  return <Ctx.Provider value={ctx}>{children}</Ctx.Provider>;
}

export function useWorkspace(): WorkspaceContext | null {
  return useContext(Ctx);
}

export function useModule(...codes: string[]): boolean {
  const ctx = useWorkspace();
  if (!ctx) return true; // fail-open while loading
  return codes.every((c) => ctx.active_modules.includes(c));
}

export function useFlag(key: string): boolean {
  const ctx = useWorkspace();
  if (!ctx) return false;
  return ctx.flags[key] ?? false;
}

/** Tenant's business vertical, chosen at signup. null while loading or for
 *  pre-existing tenants not yet backfilled — callers must hide nothing on null. */
export function useBusinessType(): BusinessType | null {
  const ctx = useWorkspace();
  return ctx?.business_type ?? null;
}
