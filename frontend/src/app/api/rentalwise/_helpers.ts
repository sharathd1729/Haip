/**
 * Shared helper for RentalWise proxy routes.
 *
 * Credential resolution order (first match wins):
 *   1. RENTALWISE_TOKEN env var — fastest path, single-tenant / dev mode
 *   2. HAIP backend integrations table — multi-tenant production path
 *      (calls GET /v1/integrations with the tenant's JWT, cached 60s)
 *
 * Set RENTALWISE_TOKEN + RENTALWISE_URL in frontend/.env.local (or VPS env)
 * to bypass the backend lookup entirely during development or when running
 * a single-tenant setup.
 */

const BACKEND     = (process.env.BACKEND_URL   || "http://localhost:8000").replace(/\/$/, "");
const ENV_RW_URL  = (process.env.RENTALWISE_URL || "").replace(/\/$/, "");
const ENV_RW_TOKEN = process.env.RENTALWISE_TOKEN || "";
const DEFAULT_RW_URL = "https://app.rentalwise.io";

export interface RWCredentials {
  rwUrl:  string;
  rwAuth: string;   // value to put in the Authorization header
}

export async function getRWCredentials(authHeader: string | null): Promise<RWCredentials> {
  // ── Path 1: env var fast-path (dev / single-tenant) ────────────────────────
  if (ENV_RW_TOKEN) {
    return {
      rwUrl:  ENV_RW_URL || DEFAULT_RW_URL,
      rwAuth: `Bearer ${ENV_RW_TOKEN}`,
    };
  }

  // ── Path 2: per-tenant lookup from HAIP integrations table ─────────────────
  if (!authHeader) {
    throw new Error("RentalWise not configured — add RENTALWISE_TOKEN to env or connect in Settings → Integrations");
  }

  // Skip backend lookup for demo/bypass tokens (they aren't real JWTs)
  const tokenValue = authHeader.replace(/^Bearer\s+/i, "");
  if (tokenValue === "demo" || tokenValue === "owner-bypass" || !tokenValue.includes(".")) {
    throw new Error("RentalWise not connected — add it in Settings → Integrations");
  }

  let integrations: Array<{ kind: string; status: string; config: Record<string, string> }>;

  try {
    const res = await fetch(`${BACKEND}/api/v1/integrations`, {
      headers: {
        Authorization: authHeader,
        Accept: "application/json",
      },
      // Cache for 60 s to avoid a DB hit on every message
      next: { revalidate: 60 },
    });

    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`);
    }

    integrations = await res.json();
  } catch (err: any) {
    throw new Error(`Could not fetch integrations: ${err.message} — add RENTALWISE_TOKEN to env or connect in Settings → Integrations`);
  }

  // Accept "rentalwise" or legacy typo "retalwise"
  const rw = integrations.find(
    i => i.kind === "rentalwise" || i.kind === "retalwise"
  );

  if (!rw) {
    throw new Error("RentalWise integration not connected — add it in Settings → Integrations");
  }

  const cfg   = rw.config ?? {};
  const rwUrl = (cfg.base_url || DEFAULT_RW_URL).replace(/\/$/, "");

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
