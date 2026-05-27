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

export type RWBookingStatus =
  | "confirmed" | "pending" | "cancelled" | "completed" | "rejected" | "hold";

export type RWPaymentStatus = "paid" | "partial_paid" | "unpaid" | "refunded";

export interface RWBooking {
  id:             number;
  booking_id:     string;
  main_guest: {
    id:         number;
    first_name: string;
    last_name:  string;
    email:      string;
    phone:      string | null;
  } | null;
  property: {
    id:    number;
    name:  string;
    type:  string;
    image: string | null;
  } | null;
  check_in:       string;
  check_out:      string;
  adults:         number;
  children:       number;
  status:         RWBookingStatus;
  payment_status: RWPaymentStatus;
  source:         string | null;
  total:          number;
  channel:        string | null;
  created_at:     string;
  updated_at:     string;
}

export interface RWPaginationMeta {
  current_page: number;
  last_page:    number;
  per_page:     number;
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
  data:   RWBooking[];
  meta:   RWPaginationMeta;
}

// ─── Filter types ─────────────────────────────────────────────────────────────

export interface RWThreadFilters {
  search?:           string;
  provider?:         RWProvider | "";
  requires_attention?: boolean;
  page?:             number;
  per_page?:         number;
}

export interface RWBookingFilters {
  search?:        string;
  status?:        RWBookingStatus | "";
  payment_status?: RWPaymentStatus | "";
  property_id?:   number | "";
  channel?:       string;
  check_in_from?: string;
  check_in_to?:   string;
  check_out_from?: string;
  check_out_to?:   string;
  source?:        string;
  sort?:          "newest" | "oldest" | "check_in" | "check_out" | "total_desc" | "total_asc";
  page?:          number;
  per_page?:      number;
}

// ─── Service ──────────────────────────────────────────────────────────────────

async function rwFetch<T>(path: string, body: object): Promise<T> {
  const res = await fetch(path, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as any).error || `RentalWise error ${res.status}`);
  }

  return res.json() as Promise<T>;
}

export const rentalwiseService = {
  /**
   * List conversation threads
   */
  getThreads(filters: RWThreadFilters = {}): Promise<RWThreadsResponse> {
    const body: Record<string, unknown> = {};
    if (filters.search)             body.search             = filters.search;
    if (filters.provider)           body.provider           = filters.provider;
    if (filters.requires_attention) body.requires_attention = true;
    if (filters.page)               body.page               = filters.page;
    if (filters.per_page)           body.per_page           = filters.per_page ?? 30;
    return rwFetch<RWThreadsResponse>("/api/rentalwise/threads", body);
  },

  /**
   * Fetch all messages for a thread
   */
  getThreadMessages(threadId: number): Promise<RWMessagesResponse> {
    return rwFetch<RWMessagesResponse>("/api/rentalwise/thread-messages", { thread: threadId });
  },

  /**
   * Query bookings with filters + pagination
   */
  getBookings(filters: RWBookingFilters = {}): Promise<RWBookingsResponse> {
    const body: Record<string, unknown> = {};
    if (filters.search)          body.search          = filters.search;
    if (filters.status)          body.status          = filters.status;
    if (filters.payment_status)  body.payment_status  = filters.payment_status;
    if (filters.property_id)     body.property_id     = filters.property_id;
    if (filters.channel)         body.channel         = filters.channel;
    if (filters.check_in_from)   body.check_in_from   = filters.check_in_from;
    if (filters.check_in_to)     body.check_in_to     = filters.check_in_to;
    if (filters.check_out_from)  body.check_out_from  = filters.check_out_from;
    if (filters.check_out_to)    body.check_out_to    = filters.check_out_to;
    if (filters.source)          body.source          = filters.source;
    if (filters.sort)            body.sort            = filters.sort;
    body.page     = filters.page     ?? 1;
    body.per_page = filters.per_page ?? 25;
    return rwFetch<RWBookingsResponse>("/api/rentalwise/bookings", body);
  },
};
