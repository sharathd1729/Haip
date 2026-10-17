"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Phone, Loader2, CheckCircle2, AlertCircle, RefreshCw, Upload, Shuffle, ListOrdered, Users, Sparkles, Play } from "@/lib/icons";
import { GitBranch, Hourglass, UserCheck } from "lucide-react";
import { useToast } from "@/components/ui/toast";

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
  has_voicemail_audio: boolean;
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
  {
    id: "sticky_agent_parallel", label: "Sticky agent + parallel", icon: <UserCheck size={14} />,
    desc: "A repeat caller always rings the specific agent who last answered them — never round robin'd elsewhere. First-time callers (or if that agent is no longer available) ring every opted-in agent at once.",
  },
];

// Sarvam bulbul:v2 female voices. anushka is Sarvam's flagship/default.
const TTS_VOICES = [
  { id: "anushka", label: "Anushka (female)" },
  { id: "manisha", label: "Manisha (female)" },
  { id: "vidya", label: "Vidya (female)" },
  { id: "arya", label: "Arya (female)" },
  { id: "ritu", label: "Ritu (female)" },
  { id: "priya", label: "Priya (female)" },
  { id: "neha", label: "Neha (female)" },
  { id: "pooja", label: "Pooja (female)" },
  { id: "simran", label: "Simran (female)" },
  { id: "kavya", label: "Kavya (female)" },
  { id: "abhilash", label: "Abhilash (male)" },
  { id: "karun", label: "Karun (male)" },
  { id: "hitesh", label: "Hitesh (male)" },
];

export default function IVRPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-[var(--haip-primary-tint)] flex items-center justify-center">
          <Phone size={18} className="text-primary" />
        </div>
        <div>
          <h1 className="haip-page-title">IVR Call Routing</h1>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Who calls ring, and what plays before they connect</p>
        </div>
      </div>

      <CallRoutingSection />
    </div>
  );
}

function CallRoutingSection() {
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data, isLoading } = useQuery<IVRRoutingSettings>({
    queryKey: ["ivr-routing"],
    queryFn: () => api.get("/tenants/me/ivr-routing").then(r => r.data),
  });

  const saveStrategy = useMutation({
    mutationFn: (strategy: string) =>
      api.patch("/tenants/me/ivr-routing", { ivr_routing_strategy: strategy }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ivr-routing"] }),
    // Without this, a rejected strategy (backend validation, stale deploy,
    // network blip) left the radio silently unchanged with zero feedback --
    // confirmed live: felt exactly like the option "wasn't clickable".
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't change routing mode", description: typeof msg === "string" ? msg : "Please try again." });
    },
  });

  if (isLoading) {
    return (
      <div className="haip-card p-5 flex items-center justify-center">
        <Loader2 className="animate-spin text-primary" size={20} />
      </div>
    );
  }

  return (
    <Section title="Call Routing" icon={<GitBranch size={14} />}>
      <p className="text-xs text-[var(--haip-fg-subtle)] -mt-1">
        Who an inbound call rings, and what plays before it connects. Agents
        opt in from{" "}
        <Link href="/dashboard/settings/team" className="text-primary hover:underline">
          Settings → Team
        </Link>
        {" "}(needs a phone number on file). Your Vobiz auth (Auth ID, Auth
        Secret, forward number) is set separately on the{" "}
        <Link href="/dashboard/settings/integrations" className="text-primary hover:underline">
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
          <div className="bg-[var(--haip-primary-tint)] border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] rounded-xl p-3 flex items-start gap-2.5">
            <Users size={14} className="text-primary mt-0.5 flex-shrink-0" />
            <div className="text-xs text-[var(--accent-foreground)]">
              <span className="font-medium">
                {data.eligible_agents.length} agent{data.eligible_agents.length === 1 ? "" : "s"} in the routing pool:
              </span>{" "}
              {data.eligible_agents.map(a => a.name).join(", ")}
              {" · "}
              <Link href="/dashboard/settings/team" className="underline hover:text-[var(--accent-foreground)]">
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
              data?.ivr_routing_strategy === s.id ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)] hover:border-[var(--haip-border-strong)]"
            )}
          >
            <input
              type="radio" name="ivr_strategy" className="mt-0.5 accent-primary"
              checked={data?.ivr_routing_strategy === s.id}
              disabled={saveStrategy.isPending}
              onChange={() => saveStrategy.mutate(s.id)}
            />
            <span className="text-primary mt-0.5">{s.icon}</span>
            <div>
              <div className="text-sm font-semibold text-[var(--haip-fg)]">{s.label}</div>
              <div className="text-xs text-[var(--haip-fg-subtle)]">{s.desc}</div>
            </div>
          </label>
        ))}
      </div>

      <AudioSlotEditor
        slot="greeting"
        title="Greeting played before the call connects"
        uploadLabel="recording"
        description="Plays once the call is answered, before the agent's phone starts ringing. MP3, WAV, M4A or MP4, up to 10 MB. No recording uploaded means the call rings straight through, same as today."
        actionLabel="Generate & set as greeting"
        placeholder="What the caller hears before the agent's phone rings…"
        hasAudio={!!data?.has_greeting_audio}
        defaultText={
          "Welcome to Ratha, our Retreat on the move — caravan rentals in Bangalore. " +
          "Please leave your name and number and we shall connect to you suitably to " +
          "curate your itinerary. Thank you for calling Ratha Retreats. Namaskara."
        }
      />

      <AudioSlotEditor
        slot="voicemail"
        title="Message when no one answers (or outside business hours)"
        uploadLabel="voicemail message"
        description="Plays instead of ringing agents — either after everyone's Dial leg times out, or immediately if the call comes in outside your business hours (Workspace settings). The whole call is already recorded, so whatever the caller says here lands on the Calls page like any other call."
        actionLabel="Generate & set as voicemail message"
        placeholder="What the caller hears when nobody's available to answer…"
        hasAudio={!!data?.has_voicemail_audio}
        defaultText={
          "Namaskara, and thank you for calling Ratha Retreats. We're sorry we couldn't take your " +
          "call at the moment. Please leave your name, phone number, and a brief message after the " +
          "tone. Our team will get back to you as soon as possible to help curate your perfect " +
          "caravan retreat. Thank you, and have a wonderful day."
        }
      />
    </Section>
  );
}

// ── One audio slot: manual upload + AI-voice generation + playback ─────────
// Shared by the greeting slot (plays before dialing) and the voicemail slot
// (plays instead of dialing) -- same three actions, different endpoints/
// tenant column underneath.

function AudioSlotEditor({
  slot, title, uploadLabel, description, actionLabel, placeholder, hasAudio, defaultText,
}: {
  slot: "greeting" | "voicemail";
  title: string;
  uploadLabel: string;
  description: string;
  actionLabel: string;
  placeholder: string;
  hasAudio: boolean;
  defaultText: string;
}) {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [ttsText, setTtsText] = useState(defaultText);
  const [ttsSpeaker, setTtsSpeaker] = useState("anushka");
  const [ttsError, setTtsError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api.post(`/tenants/me/ivr-${slot}-audio`, body, {
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

  const generate = useMutation({
    mutationFn: () =>
      api.post(`/tenants/me/ivr-${slot}-tts`, { text: ttsText, speaker: ttsSpeaker }).then(r => r.data),
    onSuccess: () => {
      setTtsError(null);
      qc.invalidateQueries({ queryKey: ["ivr-routing"] });
    },
    onError: (err: any) => {
      setTtsError(err?.response?.data?.detail || "Voice generation failed. Try again.");
    },
  });

  return (
    <>
      <div className="pt-2 border-t border-[var(--haip-border)]">
        <Field label={title}>
          <div className="flex items-center gap-3">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={upload.isPending}
              className="flex items-center gap-1.5 text-xs font-medium text-[var(--haip-fg-muted)] bg-white hover:bg-[var(--haip-surface)] border border-[var(--haip-border)] px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
            >
              {upload.isPending ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
              {hasAudio ? `Replace ${uploadLabel}` : `Upload ${uploadLabel}`}
            </button>
            <input
              ref={fileInputRef} type="file"
              accept="audio/mpeg,audio/mp3,audio/wav,audio/m4a,audio/mp4,video/mp4,.mp3,.wav,.m4a,.mp4"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }}
            />
            {hasAudio && !upload.isPending && (
              <span className="flex items-center gap-1 text-xs text-primary">
                <CheckCircle2 size={13} /> Configured
              </span>
            )}
            {hasAudio && <PlayAudioButton slot={slot} />}
          </div>
          <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">{description}</p>
          {uploadError && (
            <p className="text-xs text-red-600 mt-1 flex items-center gap-1">
              <AlertCircle size={12} /> {uploadError}
            </p>
          )}
        </Field>
      </div>

      <div className="pt-2 border-t border-[var(--haip-border)]">
        <Field label="Or generate it with an AI voice">
          <textarea
            value={ttsText}
            onChange={e => setTtsText(e.target.value)}
            rows={4}
            maxLength={2000}
            placeholder={placeholder}
            className="w-full text-xs px-3 py-2 rounded-lg border border-[var(--haip-border)] focus:outline-none focus:ring-1 focus:ring-primary resize-y"
          />
          <div className="flex items-center gap-3 mt-2">
            <select
              value={ttsSpeaker}
              onChange={e => setTtsSpeaker(e.target.value)}
              className="text-xs px-2 py-2 rounded-lg border border-[var(--haip-border)] focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {TTS_VOICES.map(v => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
            <button
              onClick={() => generate.mutate()}
              disabled={generate.isPending || !ttsText.trim()}
              className="flex items-center gap-1.5 text-xs font-medium text-white bg-primary hover:bg-[var(--haip-primary-hover)] px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
            >
              {generate.isPending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              {actionLabel}
            </button>
          </div>
          <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">
            Generates with Sarvam AI and sets it as the recording above,
            replacing whatever's there. Takes a few seconds.
          </p>
          {generate.isSuccess && !ttsError && (
            <p className="text-xs text-primary mt-1 flex items-center gap-1">
              <CheckCircle2 size={12} /> Generated and set above — use "Play" to hear it.
            </p>
          )}
          {ttsError && (
            <p className="text-xs text-red-600 mt-1 flex items-center gap-1">
              <AlertCircle size={12} /> {ttsError}
            </p>
          )}
        </Field>
      </div>
    </>
  );
}

// ── Play current greeting ───────────────────────────────────────────────────
// The one real gap that made TTS generation look broken when it wasn't:
// it succeeded every time, there was just no way to hear it without a real
// phone call. Fetches a short-lived presigned URL on click and plays it
// inline instead.

function PlayAudioButton({ slot }: { slot: "greeting" | "voicemail" }) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fetchUrl = useMutation({
    mutationFn: () => api.get(`/tenants/me/ivr-${slot}-audio/url`).then(r => r.data.url as string),
    onSuccess: (url) => { setError(null); setAudioUrl(url); },
    onError: (err: any) => setError(err?.response?.data?.detail || "Couldn't load the recording."),
  });

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => fetchUrl.mutate()}
        disabled={fetchUrl.isPending}
        title={`Play the current ${slot}`}
        className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary transition-colors disabled:opacity-50"
      >
        {fetchUrl.isPending ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
        Play
      </button>
      {audioUrl && <audio src={audioUrl} controls autoPlay className="h-8" style={{ maxWidth: 220 }} />}
      {error && <span className="text-xs text-red-600">{error}</span>}
    </div>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="haip-card p-5 space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-primary">{icon}</span>
        <h2 className="text-sm font-semibold text-[var(--haip-fg)]">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-[var(--haip-fg-subtle)]">{label}</label>
      {children}
    </div>
  );
}
