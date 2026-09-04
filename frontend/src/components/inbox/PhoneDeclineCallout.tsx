"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { AlertTriangle } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import api from "@/lib/api";

/** Phone-decline alert plan: inline callout above the AI draft/composer
 * when the guest explicitly declined to share a phone number (see backend
 * concierge_draft.py's _maybe_alert_phone_decline). Renders whenever
 * ConversationDetail carries an open phone_decline_task -- both actions
 * clear it: "I'll handle this" marks the Task done (same PATCH
 * FollowUpTasksPanel already uses), "Assign to me" sets
 * Conversation.assigned_to via the conversations PATCH route. */

interface PhoneDeclineTask {
  id: string;
  title: string;
}

export function PhoneDeclineCallout({
  conversationId,
  task,
}: {
  conversationId: string;
  task: PhoneDeclineTask;
}) {
  const { data: session } = useSession();
  const qc = useQueryClient();
  const { toast } = useToast();
  const currentUserId = session?.user?.id;

  const handleTask = useMutation({
    mutationFn: () => api.patch(`/tasks/${task.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["conversation", conversationId] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      qc.invalidateQueries({ queryKey: ["tasks", conversationId] });
    },
    onError: () => toast({ variant: "error", title: "Could not update task", description: "Please try again." }),
  });

  const assignToMe = useMutation({
    mutationFn: () => api.patch(`/conversations/${conversationId}`, { assigned_to: currentUserId }),
    onSuccess: () => {
      toast({ title: "Assigned to you" });
      qc.invalidateQueries({ queryKey: ["conversation", conversationId] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: () => toast({ variant: "error", title: "Could not assign", description: "Please try again." }),
  });

  return (
    <div
      className="mx-4 mt-3 mb-1 flex-shrink-0 rounded-xl p-3.5 flex gap-3"
      style={{ background: "var(--haip-red-soft, #FEF2F2)", border: "1px solid color-mix(in srgb, var(--haip-red) 30%, var(--haip-border))" }}
    >
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
        style={{ background: "var(--haip-red)", color: "#fff" }}
      >
        <AlertTriangle size={14} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-bold" style={{ color: "#991B1B" }}>
          Guest declined to share their phone number
        </p>
        <p className="text-xs mt-0.5 leading-relaxed" style={{ color: "#7F1D1D" }}>
          They're asking for details directly in this DM instead. Reply here on Instagram — don't wait for a number that isn't coming.
        </p>
        <div className="flex gap-2 mt-2.5">
          <button
            type="button"
            onClick={() => handleTask.mutate()}
            disabled={handleTask.isPending}
            className="text-xs font-bold px-3 py-1.5 rounded-lg disabled:opacity-60"
            style={{ background: "var(--haip-red)", color: "#fff" }}
          >
            I'll handle this
          </button>
          {currentUserId && (
            <button
              type="button"
              onClick={() => assignToMe.mutate()}
              disabled={assignToMe.isPending}
              className="text-xs font-bold px-3 py-1.5 rounded-lg disabled:opacity-60"
              style={{ background: "transparent", color: "#991B1B", border: "1px solid color-mix(in srgb, var(--haip-red) 35%, transparent)" }}
            >
              Assign to me
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
