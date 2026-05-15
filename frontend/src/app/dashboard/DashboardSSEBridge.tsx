"use client";
import { useSession } from "next-auth/react";
import { useQueryClient } from "@tanstack/react-query";
import { useInboxStream, SSEPayload } from "@/hooks/useInboxStream";
import { useCallsStore } from "@/store/calls";
import { useInboxStore } from "@/store/inbox";

/**
 * Invisible component that lives in the dashboard layout.
 * Subscribes to /sse/inbox and fans events out to:
 *  – Zustand (useCallsStore, useInboxStore) for realtime badge/queue updates
 *  – React Query cache invalidation so list views auto-refresh
 */
export function DashboardSSEBridge() {
  const { data: session } = useSession();
  const queryClient = useQueryClient();
  const pushWrapUp = useCallsStore(s => s.pushWrapUp);
  const setAiDraft = useInboxStore(s => s.setAiDraft);
  const upsertConversation = useInboxStore(s => s.upsertConversation);

  // Extract raw JWT access token – shape depends on next-auth callbacks
  const accessToken =
    (session as unknown as { accessToken?: string })?.accessToken ?? null;

  useInboxStream(accessToken, (payload: SSEPayload) => {
    switch (payload.event) {
      case "wrap_up_ready": {
        // Push to the wrap-up notification queue in the calls store
        if (payload.call_id) {
          pushWrapUp(payload.call_id);
          // Invalidate call queries so the list refreshes
          queryClient.invalidateQueries({ queryKey: ["calls"] });
          queryClient.invalidateQueries({ queryKey: ["call", payload.call_id] });
        }
        break;
      }

      case "ai_draft_ready": {
        // Mark the conversation as having a pending AI draft
        if (payload.conversation_id) {
          setAiDraft(payload.conversation_id, true);
          queryClient.invalidateQueries({
            queryKey: ["conversation", payload.conversation_id],
          });
        }
        break;
      }

      case "message_received": {
        // Upsert the conversation summary into the inbox store
        if (payload.conversation_id) {
          const rawChannel = (payload.channel as string | undefined) ?? "web";
          const safeChannel = (["whatsapp", "instagram", "web", "sms"] as const).includes(
            rawChannel as "whatsapp" | "instagram" | "web" | "sms"
          )
            ? (rawChannel as "whatsapp" | "instagram" | "web" | "sms")
            : ("web" as const);

          upsertConversation({
            id: payload.conversation_id,
            guest_name: (payload.guest_name as string | undefined) ?? "Guest",
            guest_phone: (payload.guest_phone as string | undefined) ?? "",
            last_message: (payload.preview as string | undefined) ?? "",
            last_message_at: new Date().toISOString(),
            channel: safeChannel,
            unread_count: 1,
            has_ai_draft: false,
            status: "open",
          });
          queryClient.invalidateQueries({ queryKey: ["conversations"] });
          queryClient.invalidateQueries({
            queryKey: ["conversation", payload.conversation_id],
          });
        }
        break;
      }

      case "call_scored": {
        if (payload.call_id) {
          queryClient.invalidateQueries({ queryKey: ["calls"] });
          queryClient.invalidateQueries({ queryKey: ["call", payload.call_id] });
          queryClient.invalidateQueries({ queryKey: ["qa-leaderboard"] });
        }
        break;
      }

      case "connected":
        // Nothing to do — connection confirmed
        break;

      default:
        break;
    }
  });

  // Renders nothing — pure side-effect component
  return null;
}
