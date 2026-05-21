"use client";
/**
 * useInboxStream
 *
 * Subscribes to GET /api/v1/sse/inbox (Server-Sent Events backed by Redis pub/sub).
 * Calls the supplied handler for each incoming event, and reconnects automatically
 * on disconnect (exponential back-off, capped at 30s).
 *
 * Usage:
 *   useInboxStream(accessToken, (event) => {
 *     if (event.event === "wrap_up_ready") { invalidate calls query … }
 *     if (event.event === "ai_draft_ready") { show notification … }
 *   });
 */

import { useEffect, useRef, useCallback } from "react";

export type SSEEventName =
  | "connected"
  | "wrap_up_ready"
  | "ai_draft_ready"
  | "message_received"
  | "call_scored"
  | string; // forward-compat for future event types

export interface SSEPayload {
  event: SSEEventName;
  tenant_id?: string;
  call_id?: string;
  conversation_id?: string;
  message_id?: string;
  [key: string]: unknown;
}

type Handler = (payload: SSEPayload) => void;

// Normalize so BASE_URL always ends with /api/v1 (matches lib/api.ts logic)
const _rawBase = typeof window !== "undefined"
  ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "")
  : "";
const BASE_URL = _rawBase && !_rawBase.endsWith("/api/v1") ? `${_rawBase}/api/v1` : _rawBase;

const MIN_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;

export function useInboxStream(
  accessToken: string | undefined | null,
  onEvent: Handler
) {
  const esRef = useRef<EventSource | null>(null);
  const retryMsRef = useRef(MIN_RETRY_MS);
  const mountedRef = useRef(true);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent; // always call the latest callback

  const connect = useCallback(() => {
    if (!accessToken || !mountedRef.current) return;

    // EventSource doesn't support custom headers natively — pass token as query param
    const url = `${BASE_URL}/sse/inbox?token=${encodeURIComponent(accessToken)}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      retryMsRef.current = MIN_RETRY_MS; // reset back-off on success
    };

    es.onmessage = (e: MessageEvent) => {
      try {
        const payload: SSEPayload = JSON.parse(e.data);
        onEventRef.current(payload);
      } catch {
        // Malformed JSON — ignore
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      if (!mountedRef.current) return;

      // Exponential back-off reconnect
      const delay = retryMsRef.current;
      retryMsRef.current = Math.min(delay * 2, MAX_RETRY_MS);
      setTimeout(connect, delay);
    };
  }, [accessToken]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      esRef.current?.close();
      esRef.current = null;
    };
  }, [connect]);
}
