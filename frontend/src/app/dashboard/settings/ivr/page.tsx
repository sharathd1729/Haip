"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Phone, Loader2, CheckCircle2, AlertCircle,
  RefreshCw, Upload, Shuffle, GitBranch,
  ListOrdered, Hourglass, UserCheck, Users,
} from "lucide-react";

// This page used to also carry a "Vobiz SIP Credentials" / DTMF-menu /
// Dograh-webhook config form (GET/PUT /api/v1/ivr/config), writing to a
// separate ivr_configs table the live Vobiz answer webhook never read --
// confirmed dead, and the frontend calls were doubly broken on top of that
// (hardcoded "/api/v1/..." paths against a client whose baseURL already
// includes /api/v1, so every save 404'd). Removed rather than fixed: there
// was no live path for it to plug into. Real Vobiz auth (Auth ID/Auth
// Secret/forward number) lives on the Vobiz card under Settings >
// Integrations. This page is now only the routing that actually runs.

// ── Call routing ───────────────────────────────────────────────────────────────
// Reads/writes /tenants/me/ivr-routing + /tenants/me/ivr-greeting-audio --
// what webhooks_vobiz.py's answer webhook actually consults.

interface EligibleAgent {
  id: string;
  name: string;
  phone: string | null;
}

interface IVRRoutingSettings {
  ivr_routing_strategy: string;
  has_greeting_audio: boolean;
  eligible_agents: EligibleAgent[];
}

const ROUTING_STRATEGIES = [
  {
    id: "single", label: "Single number", icon: <Phone size={14} />,
    desc: "Ring one agent (today's behaviour). Falls back here automatically if no one is opted into routing.",
  },
  {
    id: "round_robin", label: "Round robin", icon: <RefreshCw size={14} />,
    desc: "Rotate through opted-in agents one call at a time, so the same person doesn't take every call.",
  },
  {
    id: "parallel", label: "Parallel ring", icon: <Shuffle size={14} />,
    desc: "Ring every opted-in agent's phone at once. Whoever picks up first gets the call, the rest stop ringing.",
  },
  {
    id: "fixed_order", label: "Fixed order", icon: <ListOrdered size={14} />,
    desc: "Always try agents in the same order (e.g. by who joined the team first). If the first doesn't answer, it moves to the next.",
  },
  {
    id: "longest_idle", label: "Longest idle", icon: <Hourglass size={14} />,
    desc: "Ring whoever's gone the longest since their last call — spreads calls out instead of favouring whoever answers fastest.",
  },
  {
    id: "sticky_agent", label: "Sticky agent", icon: <UserCheck size={14} />,
    desc: "A repeat caller rings the same agent they reached last time, when that agent is still available. New callers get round robin.",
  },
];

export default function IVRPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-teal-50 flex items-center justify-center">
          <Phone size={18} className="text-teal-600" />
        </div>
        <div>
          <h1 className="haip-page-title">IVR Call Routing</h1>
          <p className="text-xs text-gray-500">Who calls ring, and what plays before they connect</p>
        </div>
      </div>

      <CallRoutingSection />
    </div>
  );
}

function CallRoutingSection() {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const { data, isLoading } = useQuery<IVRRoutingSettings>({
    queryKey: ["ivr-routing"],
    queryFn: () => api.get("/tenants/me/ivr-routing").then(r => r.data),
  });

  const saveStrategy = useMutation({
    mutationFn: (strategy: string) =>
      api.patch("/tenants/me/ivr-routing", { ivr_routing_strategy: strategy }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ivr-routing"] }),
  });

  const uploadGreeting = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api.post("/tenants/me/ivr-greeting-audio", body, {
        headers: { "Content-Type": "multipart/form-data" },
      }).then(r => r.data);
    },
    onSuccess: () => {
      setUploadError(null);
      qc.invalidateQueries({ queryKey: ["ivr-routing"] });
    },
    onError: (err: any) => {
      setUploadError(err?.response?.data?.detail || "Upload failed. Try an MP3 under 10 MB.");
    },
  });

  if (isLoading) {
    return (
      <div className="haip-card p-5 flex items-center justify-center">
        <Loader2 className="animate-spin text-teal-500" size={20} />
      </div>
    );
  }

  return (
    <Section title="Call Routing" icon={<GitBranch size={14} />}>
      <p className="text-xs text-gray-400 -mt-1">
        Who an inbound call rings, and what plays before it connects. Agents
        opt in from{" "}
        <Link href="/dashboard/settings/team" className="text-teal-600 hover:underline">
          Settings → Team
        </Link>
        {" "}(needs a phone number on file). Your Vobiz auth (Auth ID, Auth
        Secret, forward number) is set separately on the{" "}
        <Link href="/dashboard/settings/integrations" className="text-teal-600 hover:underline">
          Vobiz card under Integrations
        </Link>.
      </p>

      {/* Confirmed live gap: a strategy could be selected (e.g. round robin)
          with zero agents actually opted into the pool, silently falling
          back to the single Vobiz number with no visible sign anything was
          wrong. This makes the current pool impossible to miss. */}
      {data && data.ivr_routing_strategy !== "single" && (
        data.eligible_agents.length === 0 ? (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 flex items-start gap-2.5">
            <AlertCircle size={14} className="text-amber-500 mt-0.5 flex-shrink-0" />
            <p className="text-xs text-amber-800 leading-relaxed">
              No one's in the routing pool yet, so calls still ring your
              single Vobiz number — this strategy isn't doing anything until
              someone is. Go to{" "}
              <Link href="/dashboard/settings/team" className="underline font-medium hover:text-amber-900">
                Settings → Team
              </Link>
              {" "}and turn on "IVR calls" for each agent (they need a phone
              number on their profile first).
            </p>
          </div>
        ) : (
          <div className="bg-teal-50 border border-teal-200 rounded-xl p-3 flex items-start gap-2.5">
            <Users size={14} className="text-teal-600 mt-0.5 flex-shrink-0" />
            <div className="text-xs text-teal-800">
              <span className="font-medium">
                {data.eligible_agents.length} agent{data.eligible_agents.length === 1 ? "" : "s"} in the routing pool:
              </span>{" "}
              {data.eligible_agents.map(a => a.name).join(", ")}
              {" · "}
              <Link href="/dashboard/settings/team" className="underline hover:text-teal-900">
                manage in Team
              </Link>
            </div>
          </div>
        )
      )}

      <div className="space-y-2">
        {ROUTING_STRATEGIES.map(s => (
          <label
            key={s.id}
            className={cn(
              "flex items-start gap-3 p-3 rounded-xl border-2 cursor-pointer transition-colors",
              data?.ivr_routing_strategy === s.id ? "border-teal-500 bg-teal-50" : "border-gray-200 hover:border-gray-300"
            )}
          >
            <input
              type="radio" name="ivr_strategy" className="mt-0.5 accent-teal-500"
              checked={data?.ivr_routing_strategy === s.id}
              onChange={() => saveStrategy.mutate(s.id)}
            />
            <span className="text-teal-500 mt-0.5">{s.icon}</span>
            <div>
              <div className="text-sm font-semibold text-gray-900">{s.label}</div>
              <div className="text-xs text-gray-500">{s.desc}</div>
            </div>
          </label>
        ))}
      </div>

      <div className="pt-2 border-t border-gray-100">
        <Field label="Greeting played before the call connects">
          <div className="flex items-center gap-3">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadGreeting.isPending}
              className="flex items-center gap-1.5 text-xs font-medium text-gray-600 bg-white hover:bg-gray-50 border border-gray-200 px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
            >
              {uploadGreeting.isPending ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
              {data?.has_greeting_audio ? "Replace recording" : "Upload recording"}
            </button>
            <input
              ref={fileInputRef} type="file"
              accept="audio/mpeg,audio/mp3,audio/wav,audio/m4a,audio/mp4,video/mp4,.mp3,.wav,.m4a,.mp4"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) uploadGreeting.mutate(f); e.target.value = ""; }}
            />
            {data?.has_greeting_audio && !uploadGreeting.isPending && (
              <span className="flex items-center gap-1 text-xs text-teal-600">
                <CheckCircle2 size={13} /> Configured
              </span>
            )}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Plays once the call is answered, before the agent's phone starts
            ringing. MP3, WAV, M4A or MP4, up to 10 MB. No recording uploaded
            means the call rings straight through, same as today.
          </p>
          {uploadError && (
            <p className="text-xs text-red-600 mt-1 flex items-center gap-1">
              <AlertCircle size={12} /> {uploadError}
            </p>
          )}
        </Field>
      </div>
    </Section>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="haip-card p-5 space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-teal-500">{icon}</span>
        <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-500">{label}</label>
      {children}
    </div>
  );
}
