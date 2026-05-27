// ─── RentalWise types ─────────────────────────────────────────────────────────

export type RWProvider = "email" | "airbnb" | "booking-com" | "homeaway";

export interface RWThread {
  id: number;
  thread_identifier: string;
  subject: string;
  account: string;
  first_name: string;
  last_name:  string;
  email:      string;
  phone:      string | null;
  last_message_excerpt: string | null;
  last_message_at:      string | null;
  requires_attention:   boolean;
  messages_count:       number;
  default_message_provider: RWProvider;
}

export interface RWMessage {
  id:                 number;
  direction:          "inbound" | "outbound";
  provider:           RWProvider;
  sent_at:            string;
  content:            string;
  subject:            string | null;
  translated_content: string | null;
  sent_by_name:       string | null;
  is_sent:            boolean;
}

// All status values from the RentalWise API
export type RWBookingStatus =
  | "cancelled"
  | "confirmed"
  | "completed"
  | "expired_hold"
  | "expired_host_confirmation"
  | "hold"
  | "pending_host_confirmation"
  | "pending_payment"
  | "rejected_by_host"
  | "voided_by_customer"
  | "relocated";

export type RWPaymentStatus = "paid" | "partial_paid" | "unpaid" | "refunded";

export interface RWProperty {
  id:    number;
  name:  string;
  type?: string | null;
  image?: string | null;
}

export interface RWGuestAccount {
  id:         number;
  first_name: string;
  last_name:  string;
  email:      string;
  phone:      string | null;
}

export interface RWCurrency {
  code:    string;
  symbol?: string | null;
}

export interface RWBooking {
  id:           number;
  // Dates — actual API uses "checkin" / "checkout" (no underscore)
  checkin:      string;   // YYYY-MM-DD
  checkout:     string;   // YYYY-MM-DD
  adults:       number;
  children:     number;
  babies?:      number;
  pets?:        boolean;
  confirmed_at: string | null;
  cancelled_at: string | null;
  rejected_at:  string | null;
  created_at:   string;
  updated_at:   string;
  external_id:  string | null;
  notes:        string | null;
  status:       RWBookingStatus;
  expiration_hours: number | null;
  expires_at:   string | null;
  cancel_reason: string | null;
  reject_reason: string | null;
  source_name:  string | null;   // formerly "source"
  total:                    number;
  total_accommodation:      number;
  total_fees:               number;
  total_pretax:             number;
  total_accommodation_pretax?: number;
  total_fees_pretax?:       number;
  total_taxes:              number;
  payment_status:     RWPaymentStatus;
  total_outstanding:  number;
  total_paid:         number;
  total_refunded:     number;
  next_payment_due_date: string | null;
  next_payment_amount:   number;
  handles_payment:       boolean;
  // Relations (returned when requested via `with`)
  property:    RWProperty | null;
  currency:    RWCurrency | string | null;
  main_guest:  RWGuestAccount | null;
  // Channel can be a plain string, an object, or null
  channel:              unknown;
  channel_external_id:  string | null;
  sub_channel_name?:    string | null;
  booking_category?:    string | null;
  guest_message?:       string | null;
}

export interface RWPaginationMeta {
  current_page: number;
  last_page:    number;
  per_page:     number;
  from:         number;
  to:           number;
  total:        number;
}

export interface RWThreadsResponse {
  data: RWThread[];
  meta?: RWPaginationMeta;
}

export interface RWMessagesResponse {
  data: RWMessage[];
  meta?: RWPaginationMeta;
}

export interface RWBookingsResponse {
  data: RWBooking[];
  meta: RWPaginationMeta;
}

// ─── Filter types ─────────────────────────────────────────────────────────────

export interface RWThreadFilters {
  search?:             string;
  provider?:           RWProvider | "";
  requires_attention?: boolean;
  page?:               number;
  per_page?:           number;
}

export interface RWBookingFilters {
  search?:         string;
  status?:         RWBookingStatus | "";
  payment_status?: RWPaymentStatus | "";
  property_id?:    number | "";
  channel?:        string;
  check_in_from?:  string;
  check_in_to?:    string;
  check_out_from?: string;
  check_out_to?:   string;
  source?:         string;
  sort?:           "newest" | "oldest" | "check_in" | "check_out" | "total_desc" | "total_asc";
  page?:           number;
  per_page?:       number;
}

// ─── Service ──────────────────────────────────────────────────────────────────

/**
 * Fetch the HAIP JWT from the NextAuth session so the proxy routes can
 * look up the tenant's RentalWise credentials.
 */
async function getAuthHeader(): Promise<string | null> {
  try {
    const { getSession } = await import("next-auth/react");
    const session = await getSession();
    const token   = (session as any)?.accessToken as string | undefined;
    return token ? `Bearer ${token}` : null;
  } catch {
    return null;
  }
}

async function rwFetch<T>(path: string, body: object): Promise<T> {
  const authHeader = await getAuthHeader();

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (authHeader) headers["Authorization"] = authHeader;

  const res = await fetch(path, {
    method:  "POST",
    headers,
    body:    JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as any).error || `RentalWise error ${res.status}`);
  }

  return res.json() as Promise<T>;
}

/** Map our friendly sort key to the actual API sort field + direction */
function buildSort(sort?: RWBookingFilters["sort"]): Array<{ field: string; direction: "asc" | "desc" }> {
  switch (sort) {
    case "oldest":    return [{ field: "created_at", direction: "asc"  }];
    case "check_in":  return [{ field: "checkin",    direction: "asc"  }];
    case "check_out": return [{ field: "checkout",   direction: "asc"  }];
    case "total_desc":return [{ field: "total",      direction: "desc" }];
    case "total_asc": return [{ field: "total",      direction: "asc"  }];
    case "newest":
    default:          return [{ field: "created_at", direction: "desc" }];
  }
}

/** Map our internal filters to the `where.conditions` array format */
function buildConditions(filters: RWBookingFilters): Array<{ field: string; operator: string; value: unknown }> {
  const conds: Array<{ field: string; operator: string; value: unknown }> = [];

  if (filters.status)          conds.push({ field: "status",         operator: "=",    value: filters.status });
  if (filters.payment_status)  conds.push({ field: "payment_status", operator: "=",    value: filters.payment_status });
  if (filters.property_id)     conds.push({ field: "property_id",    operator: "=",    value: filters.property_id });
  if (filters.channel)         conds.push({ field: "channel",        operator: "=",    value: filters.channel });
  if (filters.check_in_from)   conds.push({ field: "checkin",        operator: ">=",   value: filters.check_in_from });
  if (filters.check_in_to)     conds.push({ field: "checkin",        operator: "<=",   value: filters.check_in_to });
  if (filters.check_out_from)  conds.push({ field: "checkout",       operator: ">=",   value: filters.check_out_from });
  if (filters.check_out_to)    conds.push({ field: "checkout",       operator: "<=",   value: filters.check_out_to });
  if (filters.source)          conds.push({ field: "source_name",    operator: "like", value: `%${filters.source}%` });

  return conds;
}

export const rentalwiseService = {
  /** List conversation threads */
  getThreads(filters: RWThreadFilters = {}): Promise<RWThreadsResponse> {
    const body: Record<string, unknown> = {};
    if (filters.search)             body.search             = filters.search;
    if (filters.provider)           body.provider           = filters.provider;
    if (filters.requires_attention) body.requires_attention = true;
    if (filters.page)               body.page               = filters.page;
    if (filters.per_page)           body.per_page           = filters.per_page ?? 30;
    return rwFetch<RWThreadsResponse>("/api/rentalwise/threads", body);
  },

  /** Fetch all messages for a thread */
  getThreadMessages(threadId: number): Promise<RWMessagesResponse> {
    return rwFetch<RWMessagesResponse>("/api/rentalwise/thread-messages", { thread: threadId });
  },

  /**
   * Query bookings using the RentalWise POST /rest/booking/query format:
   * {
   *   paginate: { page, perpage },
   *   sort: [{ field, direction }],
   *   where: { conditions: [...] },
   *   with: ["property", "main_guest", "currency"],
   *   search: "..."   // optional full-text search
   * }
   */
  getBookings(filters: RWBookingFilters = {}): Promise<RWBookingsResponse> {
    const body: Record<string, unknown> = {
      paginate: {
        page:    filters.page    ?? 1,
        perpage: filters.per_page ?? 25,
      },
      sort: buildSort(filters.sort),
      with: ["property", "main_guest", "currency"],
    };

    const conditions = buildConditions(filters);
    if (conditions.length > 0) {
      body.where = { conditions };
    }

    // Full-text search (supported by some RentalWise versions as top-level param)
    if (filters.search) {
      body.search = filters.search;
    }

    return rwFetch<RWBookingsResponse>("/api/rentalwise/bookings", body);
  },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Extract a display-safe channel name from the booking's `channel` field (which can be any shape) */
export function getChannelName(booking: RWBooking): string | null {
  const c = booking.channel;
  if (!c) return booking.sub_channel_name ?? null;
  if (typeof c === "string") return c;
  if (typeof c === "object" && c !== null) {
    const obj = c as Record<string, unknown>;
    return (obj.name as string) ?? (obj.slug as string) ?? null;
  }
  return null;
}

/** Extract the currency symbol or code for display */
export function getCurrencySymbol(booking: RWBooking): string {
  const cur = booking.currency;
  if (!cur) return "₹";
  if (typeof cur === "string") return cur;
  if (typeof cur === "object" && cur !== null) {
    return cur.symbol ?? cur.code ?? "₹";
  }
  return "₹";
}
