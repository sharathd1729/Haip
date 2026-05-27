// ─── RentalWise types ─────────────────────────────────────────────────────────

export type RWProvider = "email" | "airbnb" | "booking-com" | "homeaway";

/** Guest account attached to a thread */
export interface RWAccount {
  id:         number;
  first_name: string;
  last_name:  string;
  email:      string;
  phone:      string | null;
  company?:   string | null;
  address?:   string | null;
}

/** Available message provider on a thread */
export interface RWMessageProvider {
  id:       RWProvider;
  name:     string;
  icon_url: string;
}

export interface RWThread {
  id:                         number;
  thread_identifier:          string;
  thread_external_id?:        string | null;
  default_message_provider:   RWProvider;
  available_message_providers: RWMessageProvider[];
  /** Email subject — only populated for email provider */
  subject?:                   string | null;
  account:                    RWAccount;
  last_message_excerpt:       string | null;
  last_message_at:            string | null;
  requires_attention:         boolean;
  messages_count:             number;
}

/** Message (id is a string in the RentalWise API) */
export interface RWMessage {
  id:              string;
  direction:       "inbound" | "outbound";
  provider:        RWProvider;
  provider_info?:  RWMessageProvider;
  provider_message_id?: string | null;
  sent_at:         string;
  content:         string;
  subject?:        string | null;
  language?:       string | null;
  translated_subject?:  string | null;
  translated_content?:  string | null;
  translated_language?: string | null;
  sent_by_name?:   string | null;
  sent_by_workflow?: { id: number; name: string } | null;
  is_sent:         boolean;
  message_type:    "message" | "special_offer";
  content_type:    "text/plain" | "text/html";
  error_message?:  string | null;
  /** The full thread object returned on message queries */
  thread?:         RWThread;
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
  resource_type?:      "booking" | "inquiry" | "property";
  resource_id?:        number;
  page?:               number;
  per_page?:           number;
}

export interface RWSendMessagePayload {
  /** thread_identifier (string) of the target thread */
  thread:        string;
  provider:      RWProvider;
  content:       string;
  content_type?: "text/plain" | "text/html";
  subject?:      string;
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
  /**
   * List conversation threads using the proper RentalWise query format:
   * {
   *   paginate: { page, perpage },
   *   sort: [{ field: "last_message_at", direction: "desc" }],
   *   where: { conditions: [...] },
   *   with: ["account"],
   *   resource_type?: [...],
   *   resource_id?: number,
   *   search?: string
   * }
   */
  getThreads(filters: RWThreadFilters = {}): Promise<RWThreadsResponse> {
    const body: Record<string, unknown> = {
      paginate: {
        page:    filters.page    ?? 1,
        perpage: filters.per_page ?? 40,
      },
      sort: [{ field: "last_message_at", direction: "desc" }],
      with: ["account"],
    };

    // Build where conditions
    const conditions: Array<{ field: string; operator: string; value: unknown }> = [];
    if (filters.provider) {
      conditions.push({ field: "default_message_provider", operator: "=", value: filters.provider });
    }
    if (filters.requires_attention) {
      conditions.push({ field: "requires_attention", operator: "=", value: true });
    }
    if (conditions.length > 0) {
      body.where = { conditions };
    }

    // Resource scoping
    if (filters.resource_type) body.resource_type = [filters.resource_type];
    if (filters.resource_id)   body.resource_id   = filters.resource_id;

    // Full-text search (top-level per some RentalWise versions)
    if (filters.search) body.search = filters.search;

    return rwFetch<RWThreadsResponse>("/api/rentalwise/threads", body);
  },

  /**
   * Fetch all messages for a thread using paginate + sort format
   */
  getThreadMessages(threadId: number): Promise<RWMessagesResponse> {
    return rwFetch<RWMessagesResponse>("/api/rentalwise/thread-messages", {
      thread:  threadId,
      paginate: { page: 1, perpage: 100 },
      sort:     [{ field: "sent_at", direction: "asc" }],
    });
  },

  /**
   * Send a reply message in a thread
   * POST /rest/thread-message/send
   */
  sendMessage(payload: RWSendMessagePayload): Promise<RWMessage> {
    return rwFetch<RWMessage>("/api/rentalwise/send-message", {
      thread:       payload.thread,
      provider:     payload.provider,
      content:      payload.content,
      content_type: payload.content_type ?? "text/plain",
      ...(payload.subject ? { subject: payload.subject } : {}),
    });
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
