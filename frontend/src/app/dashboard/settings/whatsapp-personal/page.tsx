"use client";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { MessageCircle, QrCode, Loader2, CheckCircle2, XCircle, AlertCircle, LogOut, RefreshCw, Phone, Users } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface SessionOut {
  id: string;
  status: "pending_pairing" | "connected" | "disconnected" | "logged_out";
  phone_number: string | null;
  agent_name?: string | null;
  qr_code_data_url?: string | null;
  last_seen_at: string | null;
  created_at: string;
}

interface PairingOut {
  session_id: string;
  qr_code_data_url?: string | null;
  pairing_code?: string | null;
  status: string;
}

const STATUS_LABEL: Record<string, string> = {
  pending_pairing: "Waiting for scan",
  connected: "Connected",
  disconnected: "Disconnected",
  logged_out: "Not paired",
};

function StatusDot({ status }: { status: string }) {
  return (
    <span className={cn(
      "inline-block w-2 h-2 rounded-full flex-shrink-0",
      status === "connected" ? "bg-emerald-500" :
      status === "pending_pairing" ? "bg-amber-400" :
      status === "disconnected" ? "bg-red-400" : "bg-gray-300"
    )} />
  );
}

export default function WhatsAppPersonalPage() {
  const { data: authSession } = useSession();
  const role = authSession?.user?.role;
  const isOwnerOrManager = role === "owner" || role === "manager";
  const queryClient = useQueryClient();
  const [qr, setQr] = useState<string | null>(null);
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPhoneEntry, setShowPhoneEntry] = useState(false);
  const [phoneInput, setPhoneInput] = useState("");

  const { data: mySession, isLoading } = useQuery<SessionOut | null>({
    queryKey: ["whatsapp-personal", "me"],
    queryFn: () => api.get("/whatsapp-personal/sessions/me").then(r => r.data),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // Only poll while a scan is pending -- an agent watching the QR
      // needs to see "Connected" appear without refreshing; there's
      // nothing to wait for once it's settled either way.
      return status === "pending_pairing" ? 3000 : false;
    },
  });

  // Once the bridge reports "connected" (paired) or "logged_out" (WhatsApp
  // gave up rotating codes -- see the bridge's "timeout" handling), the
  // displayed QR is stale either way -- clear it so the success/expired
  // state renders instead of a scannable-looking code that no longer
  // does anything.
  useEffect(() => {
    if ((mySession?.status === "connected" || mySession?.status === "logged_out") && (qr || pairingCode)) {
      setQr(null);
      setPairingCode(null);
    }
  }, [mySession?.status, qr, pairingCode]);

  // WhatsApp rotates the QR roughly every 20-30s while unscanned -- a
  // real pairing attempt failed ("Couldn't link device, try again later")
  // because the displayed code had already expired by the time someone
  // actually scanned it. The bridge now pushes each rotation to the
  // backend, and polling picks it up here so the image on screen keeps
  // itself current instead of silently going stale.
  useEffect(() => {
    if (mySession?.status === "pending_pairing" && mySession.qr_code_data_url && mySession.qr_code_data_url !== qr) {
      setQr(mySession.qr_code_data_url);
    }
  }, [mySession?.status, mySession?.qr_code_data_url, qr]);

  const pairMutation = useMutation({
    mutationFn: (phone_number?: string) =>
      api.post<PairingOut>("/whatsapp-personal/sessions", phone_number ? { phone_number } : {}).then(r => r.data),
    onSuccess: (data) => {
      setQr(data.qr_code_data_url ?? null);
      setPairingCode(data.pairing_code ?? null);
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["whatsapp-personal", "me"] });
    },
    onError: () => setError("Couldn't reach the WhatsApp bridge. Try again shortly."),
  });

  const unpairMutation = useMutation({
    mutationFn: () => api.delete("/whatsapp-personal/sessions/me"),
    onSuccess: () => {
      setQr(null);
      queryClient.invalidateQueries({ queryKey: ["whatsapp-personal", "me"] });
    },
  });

  const { data: directory } = useQuery<SessionOut[]>({
    queryKey: ["whatsapp-personal", "directory"],
    queryFn: () => api.get("/whatsapp-personal/sessions").then(r => r.data),
    enabled: isOwnerOrManager,
  });

  const status = mySession?.status;

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-teal-50 flex items-center justify-center">
            <MessageCircle size={18} className="text-teal-600" />
          </div>
          <div>
            <h1 className="haip-page-title">Personal WhatsApp</h1>
            <p className="text-sm text-gray-400 mt-0.5">
              Bring guest conversations from your own WhatsApp into HAIP&apos;s Inbox.
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6 max-w-2xl w-full mx-auto space-y-6">
        <div className="flex gap-3 p-4 rounded-xl bg-amber-50 border border-amber-100">
          <AlertCircle size={16} className="text-amber-500 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-amber-800 leading-relaxed">
            <p className="font-semibold mb-1">Not an official WhatsApp integration</p>
            <p>
              This connects the way WhatsApp Web does, not through WhatsApp&apos;s official Business API.
              WhatsApp can restrict a number that uses this at high volume. Read-only for now — HAIP tracks
              your conversations here but never sends messages through this connection.
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
          <div className="text-sm font-semibold text-gray-800 mb-4">My WhatsApp</div>

          {isLoading && <p className="text-sm text-gray-400">Checking…</p>}

          {!isLoading && (!mySession || status === "logged_out" || status === "pending_pairing") && !qr && !pairingCode && !showPhoneEntry && (
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm text-gray-700">{status === "pending_pairing" ? "Code expired." : "Not connected yet."}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {status === "pending_pairing"
                    ? "The window closed before it was used. Generate a new one to try again."
                    : "Pair your phone to start tracking these conversations in HAIP."}
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => setShowPhoneEntry(true)}
                  className="text-xs font-medium text-gray-500 hover:text-gray-700"
                >
                  Use phone number
                </button>
                <button
                  onClick={() => pairMutation.mutate(undefined)}
                  disabled={pairMutation.isPending}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold text-white bg-teal-600 hover:bg-teal-700 disabled:opacity-60"
                >
                  {pairMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <QrCode size={13} />}
                  {status === "pending_pairing" ? "Generate new QR" : "Pair my WhatsApp"}
                </button>
              </div>
            </div>
          )}

          {!isLoading && (!mySession || status === "logged_out" || status === "pending_pairing") && !qr && !pairingCode && showPhoneEntry && (
            <div>
              <p className="text-sm text-gray-700">Enter your WhatsApp number</p>
              <p className="text-xs text-gray-400 mt-0.5 mb-3">Include country code, e.g. +919876543210. WhatsApp will show an 8-character code to enter on your phone instead of scanning.</p>
              <div className="flex items-center gap-2">
                <input
                  type="tel"
                  value={phoneInput}
                  onChange={(e) => setPhoneInput(e.target.value)}
                  placeholder="+919876543210"
                  className="flex-1 px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-400"
                />
                <button
                  onClick={() => setShowPhoneEntry(false)}
                  className="text-xs font-medium text-gray-500 hover:text-gray-700 px-2"
                >
                  Cancel
                </button>
                <button
                  onClick={() => pairMutation.mutate(phoneInput)}
                  disabled={pairMutation.isPending || phoneInput.trim().length < 8}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold text-white bg-teal-600 hover:bg-teal-700 disabled:opacity-60 flex-shrink-0"
                >
                  {pairMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Phone size={13} />}
                  Get code
                </button>
              </div>
            </div>
          )}

          {qr && status !== "connected" && (
            <div className="text-center py-2">
              <img src={qr} alt="Scan with WhatsApp" className="mx-auto rounded-lg border border-gray-100 w-56 h-56 object-contain" />
              <p className="text-sm text-gray-700 mt-3 font-medium">Scan with WhatsApp</p>
              <p className="text-xs text-gray-400 mt-1 max-w-xs mx-auto">
                On your phone: WhatsApp → Settings → Linked Devices → Link a Device, then scan this code.
              </p>
              <div className="flex items-center justify-center gap-1.5 mt-3 text-xs text-amber-600">
                <Loader2 size={12} className="animate-spin" /> Waiting for scan…
              </div>
            </div>
          )}

          {pairingCode && status !== "connected" && (
            <div className="text-center py-4">
              <p className="text-3xl font-bold tracking-[0.2em] text-gray-800">{pairingCode}</p>
              <p className="text-sm text-gray-700 mt-3 font-medium">Enter this code in WhatsApp</p>
              <p className="text-xs text-gray-400 mt-1 max-w-xs mx-auto">
                On your phone: WhatsApp → Settings → Linked Devices → Link a Device → Link with phone number instead.
              </p>
              <div className="flex items-center justify-center gap-1.5 mt-3 text-xs text-amber-600">
                <Loader2 size={12} className="animate-spin" /> Waiting for confirmation…
              </div>
            </div>
          )}

          {!qr && status === "connected" && (
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center flex-shrink-0">
                  <Phone size={15} />
                </div>
                <div>
                  <p className="text-sm text-gray-700 flex items-center gap-1.5">
                    <StatusDot status={status} /> Connected — {mySession?.phone_number}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">Guest messages here now appear in your Inbox.</p>
                </div>
              </div>
              <button
                onClick={() => unpairMutation.mutate()}
                disabled={unpairMutation.isPending}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-gray-600 border border-gray-200 hover:bg-gray-50 disabled:opacity-60 flex-shrink-0"
              >
                {unpairMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <LogOut size={12} />}
                Unpair
              </button>
            </div>
          )}

          {!qr && status === "disconnected" && (
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-gray-700 flex items-center gap-1.5">
                <StatusDot status={status} /> Disconnected — {mySession?.phone_number}
              </p>
              <button
                onClick={() => pairMutation.mutate(undefined)}
                disabled={pairMutation.isPending}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-gray-900 hover:bg-gray-800 disabled:opacity-60 flex-shrink-0"
              >
                {pairMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                Reconnect
              </button>
            </div>
          )}

          {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
        </div>

        {isOwnerOrManager && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-800 mb-1">
              <Users size={14} className="text-gray-400" /> Team status
            </div>
            <p className="text-xs text-gray-400 mb-4">
              Which agents have bridged their WhatsApp. Numbers are private to each agent — you see status, not the number.
            </p>
            {!directory || directory.length === 0 ? (
              <p className="text-sm text-gray-400 py-4 text-center">No one has paired yet.</p>
            ) : (
              <div className="space-y-1">
                {directory.map(s => (
                  <div key={s.id} className="flex items-center justify-between py-2.5 border-b border-gray-50 last:border-0">
                    <div className="flex items-center gap-2.5">
                      <StatusDot status={s.status} />
                      <div>
                        <p className="text-sm text-gray-800">{s.agent_name ?? "Unknown agent"}</p>
                        <p className="text-xs text-gray-400">{s.phone_number ?? "—"}</p>
                      </div>
                    </div>
                    <span className={cn(
                      "text-xs font-medium px-2 py-0.5 rounded-full",
                      s.status === "connected" ? "bg-emerald-50 text-emerald-700" :
                      s.status === "pending_pairing" ? "bg-amber-50 text-amber-700" :
                      s.status === "disconnected" ? "bg-red-50 text-red-700" : "bg-gray-50 text-gray-500"
                    )}>
                      {STATUS_LABEL[s.status] ?? s.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
