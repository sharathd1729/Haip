/**
 * Shared helper for RentalWise proxy routes.
 *
 * Calls GET /api/v1/integrations/retalwise/credentials on the HAIP backend,
 * which decrypts and returns the tenant's RentalWise credentials server-to-server.
 * Credentials are NEVER exposed to the browser — this runs only in Next.js API routes.
 *
 * Fallback: if RENTALWISE_TOKEN env var is set (dev / single-tenant mode),
 * it is used directly without hitting the backend.
 */

const BACKEND      = (process.env.BACKEND_URL   || "http://localhost:8000").replace(/\/$/, "");
const ENV_RW_URL   = (process.env.RENTALWISE_URL || "").replace(/\/$/, "");
const ENV_RW_TOKEN = process.env.RENTALWISE_TOKEN || "";
const DEFAULT_RW_URL = "https://app.rentalwise.io";

export interface RWCredentials {
  rwUrl:  string;
  rwAuth: string;
}

export async function getRWCredentials(authHeader: string | null): Promise<RWCredentials> {
  // ── Fast-path: env var override (dev / single-tenant) ──────────────────────
  if (ENV_RW_TOKEN) {
    return {
      rwUrl:  ENV_RW_URL || DEFAULT_RW_URL,
      rwAuth: `Bearer ${ENV_RW_TOKEN}`,
    };
  }

  // ── Require a real JWT ──────────────────────────────────────────────────────
  if (!authHeader) {
    throw new Error("RentalWise not configured — not authenticated");
  }

  // Demo/bypass tokens are not real JWTs — skip the backend call
  const tokenValue = authHeader.replace(/^Bearer\s+/i, "");
  if (tokenValue === "demo" || tokenValue === "owner-bypass" || !tokenValue.includes(".")) {
    throw new Error("RentalWise not connected — add it in Settings → Integrations");
  }

  // ── Fetch decrypted credentials from HAIP backend ──────────────────────────
  let creds: { api_token?: string | null; username?: string | null; password?: string | null; base_url?: string };

  try {
    const res = await fetch(`${BACKEND}/api/v1/integrations/retalwise/credentials`, {
      headers: {
        Authorization: authHeader,
        Accept: "application/json",
      },
      // Cache for 60 s — avoids a DB hit on every message
      next: { revalidate: 60 },
    });

    if (res.status === 404) {
      throw new Error("RentalWise integration not connected — add it in Settings → Integrations");
    }
    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`);
    }

    creds = await res.json();
  } catch (err: any) {
    // Re-throw "not connected" messages as-is (they become 503)
    if (err.message?.includes("not connected")) throw err;
    throw new Error(`Could not fetch RentalWise credentials: ${err.message}`);
  }

  const rwUrl = (creds.base_url || DEFAULT_RW_URL).replace(/\/$/, "");

  let rwAuth: string;
  if (creds.api_token) {
    rwAuth = `Bearer ${creds.api_token}`;
  } else if (creds.username && creds.password) {
    const encoded = Buffer.from(`${creds.username}:${creds.password}`).toString("base64");
    rwAuth = `Basic ${encoded}`;
  } else {
    throw new Error("RentalWise credentials missing — reconnect in Settings → Integrations");
  }

  return { rwUrl, rwAuth };
}
