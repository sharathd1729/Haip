"use client";
/**
 * W18 — Agent presence.
 * - Sends a heartbeat POST /users/me/heartbeat every 30 seconds while mounted.
 * - Polls GET /users/presence every 30 seconds to get the online user list.
 */
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import api from "@/lib/api";

export interface PresenceUser {
  id: string;
  name: string;
  email: string;
  role: string;
  last_seen_at: string;
}

export function usePresence(enabled = true) {
  const { data: session } = useSession();
  const [onlineUsers, setOnlineUsers] = useState<PresenceUser[]>([]);

  useEffect(() => {
    if (!enabled || !session) return;

    const beat = async () => {
      try {
        await api.post("/users/me/heartbeat");
      } catch {
        // silent — presence is non-critical
      }
    };

    const poll = async () => {
      try {
        const res = await api.get("/users/presence");
        setOnlineUsers(res.data ?? []);
      } catch {
        // silent
      }
    };

    // Immediate fire
    beat();
    poll();

    const interval = setInterval(() => {
      beat();
      poll();
    }, 30_000);

    return () => clearInterval(interval);
  }, [enabled, session]);

  return { onlineUsers };
}
