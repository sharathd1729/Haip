/**
 * Shared helper for RentalWise proxy routes.
 *
 * Flow:
 *   1. Read the HAIP JWT from the incoming Authorization header
 *   2. Call HAIP backend GET /v1/integrations to fetch the tenant's RentalWise config
 *   3. Return { rwUrl, rwAuth } — ready to make RentalWise API calls
 *
 * The token is stored per-tenant in the integrations table when the client
 * connects RentalWise from Settings → Integrations.
 */

const BACKEND = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
const DEFAULT_RW_URL = "https://app.rentalwise.in";

export interface RWCredentials {
  rwUrl:  string;
  rwAuth: string;   // value to put in the Authorization header
}

export async function getRWCredentials(authHeader: string | null): Promise<RWCredentials> {
  if (!authHeader) {
    throw new Error("No Authorization header — not authenticated");
  }

  // Fetch all integrations for this tenant
  const res = await fetch(`${BACKEND}/api/v1/integrations`, {
    headers: {
      Authorization: authHeader,
      Accept: "application/json",
    },
    next: { revalidate: 60 }, // cache for 60s to avoid a DB hit on every message
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch integrations: ${res.status}`);
  }

  const integrations: Array<{
    kind: string;
    status: string;
    config: Record<string, string>;
  }> = await res.json();

  // Match provider: integrations page saves kind as "retalwise" (legacy typo)
  // or "rentalwise" — accept both
  const rw = integrations.find(
    i => i.kind === "rentalwise" || i.kind === "retalwise"
  );

  if (!rw) {
    throw new Error("RentalWise integration not connected — add it in Settings → Integrations");
  }

  const cfg    = rw.config ?? {};
  const rwUrl  = (cfg.base_url || DEFAULT_RW_URL).replace(/\/$/, "");

  // Build the Authorization value
  let rwAuth: string;
  if (cfg.api_token) {
    rwAuth = `Bearer ${cfg.api_token}`;
  } else if (cfg.username && cfg.password) {
    const encoded = Buffer.from(`${cfg.username}:${cfg.password}`).toString("base64");
    rwAuth = `Basic ${encoded}`;
  } else {
    throw new Error("RentalWise credentials missing — reconnect in Settings → Integrations");
  }

  return { rwUrl, rwAuth };
}
