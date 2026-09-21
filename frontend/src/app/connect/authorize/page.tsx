"use client";
// OAuth consent screen for the MCP connector (HAIP_MCP_Connector_Plan.md §8).
//
// The backend's GET /oauth/authorize validates the request and sends the
// browser here with the OAuth params in the query string. Middleware has
// already forced a normal HAIP login (MFA included) before this renders.
// Approve/Deny posts to /oauth/consent, which re-validates every param --
// nothing in this URL is trusted -- and returns where to send the browser.
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { Bot, ShieldCheck, Loader2, AlertCircle, Check } from "@/lib/icons";
import api from "@/lib/api";

const OAUTH_PARAMS = [
  "client_id", "redirect_uri", "response_type", "code_challenge",
  "code_challenge_method", "state", "scope", "resource",
] as const;

type Access = "read_write" | "read_only";

function hostOf(uri: string | null): string {
  if (!uri) return "";
  try {
    return new URL(uri).host || uri;
  } catch {
    return uri;
  }
}

function isSessionExpired(err: unknown): boolean {
  return (err as { response?: { status?: number } })?.response?.status === 401;
}

/** A 401 here means the HAIP session behind this page is stale (e.g. its
 *  token refresh failed during an API restart). Clear it and log in again,
 *  returning to this exact screen with the OAuth params intact. Signing out
 *  first matters: middleware bounces a still-"logged-in" user away from
 *  /login straight to the dashboard. */
function isForbidden(err: unknown): boolean {
  return (err as { response?: { status?: number } })?.response?.status === 403;
}

function reauthenticate() {
  const back = window.location.pathname + window.location.search;
  signOut({ callbackUrl: `/login?callbackUrl=${encodeURIComponent(back)}` }).catch(() => {
    window.location.href = `/login?callbackUrl=${encodeURIComponent(back)}`;
  });
}

function errorText(err: unknown, fallback: string): string {
  const e = err as { response?: { status?: number; data?: { detail?: string } } };
  if (e?.response?.status === 403) {
    return "Only owners and managers can connect AI assistants to HAIP. Ask your workspace owner to connect it.";
  }
  return e?.response?.data?.detail || fallback;
}

function ConsentCard() {
  const params = useSearchParams();
  const { data: session } = useSession();
  const [access, setAccess] = useState<Access>("read_write");
  const [submitting, setSubmitting] = useState<"approve" | "deny" | null>(null);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);

  const clientId = params.get("client_id");
  const redirectHost = hostOf(params.get("redirect_uri"));

  const { data: client, isLoading, error: clientError } = useQuery<{ client_id: string; client_name: string }>({
    queryKey: ["oauth-client", clientId],
    queryFn: () => api.get(`/oauth/clients/${encodeURIComponent(clientId || "")}`).then(r => r.data),
    enabled: !!clientId,
    retry: false,
  });

  const sessionExpired = isSessionExpired(clientError);
  useEffect(() => {
    if (sessionExpired) reauthenticate();
  }, [sessionExpired]);

  const decide = async (decision: "approve" | "deny") => {
    setError("");
    setSubmitting(decision);
    const body: Record<string, string> = { decision, access };
    for (const key of OAUTH_PARAMS) {
      const value = params.get(key);
      if (value !== null) body[key] = value;
    }
    try {
      const { redirect_to } = await api.post("/oauth/consent", body).then(r => r.data);
      // Full navigation, not router.push: the target is the AI app's own
      // callback URL on another origin (or a localhost port for CLI tools).
      window.location.assign(redirect_to);
    } catch (err) {
      if (isSessionExpired(err)) {
        reauthenticate();
        return;
      }
      setForbidden(isForbidden(err));
      setError(errorText(err, "Couldn't complete the connection. Start again from the app."));
      setSubmitting(null);
    }
  };

  if (!clientId) {
    return (
      <Notice
        title="This link is incomplete"
        body="Open HAIP's connector from Claude, ChatGPT or your AI app again — it will bring you back here with the right details."
      />
    );
  }

  if (sessionExpired) {
    return <Notice title="Your HAIP session expired" body="Taking you to sign in — you'll come straight back here." />;
  }

  if (clientError) {
    return <Notice title="Unknown app" body={errorText(clientError, "This app isn't registered. Start the connection again from the app.")} />;
  }

  const appName = client?.client_name || "An AI assistant";
  const user = session?.user as { name?: string | null; email?: string | null } | undefined;

  return (
    <div className="w-full max-w-md rounded-2xl p-6 sm:p-8 flex flex-col gap-6" style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)" }}>
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 bg-teal-50 text-teal-600">
          <Bot size={20} />
        </div>
        <div className="min-w-0">
          <h1 className="text-lg font-semibold leading-snug" style={{ color: "var(--haip-fg)", textWrap: "balance" }}>
            {isLoading ? "Loading…" : `${appName} wants to connect to HAIP`}
          </h1>
          {redirectHost && (
            <p className="text-xs mt-0.5 truncate" style={{ color: "var(--haip-fg-subtle)" }}>
              Returns to {redirectHost}
            </p>
          )}
        </div>
      </div>

      <div className="text-sm leading-relaxed flex flex-col gap-2" style={{ color: "var(--haip-fg)" }}>
        <p>It will act as you{user?.name ? <> (<strong>{user.name}</strong>)</> : null} and see what you can see in HAIP:</p>
        {user?.name && (
          <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>
            Not {user.name}?{" "}
            {/* The screen always uses whoever is signed in to HAIP in this
                browser -- this is how an owner connects from a shared
                machine an agent last used. */}
            <button type="button" onClick={reauthenticate} className="font-medium text-teal-700 underline underline-offset-2">
              Use a different HAIP account
            </button>
          </p>
        )}
        <ul className="flex flex-col gap-1.5 pl-1">
          {[
            "Leads, pipeline stages and notes",
            "Guest conversations and call summaries",
            "Bookings, revenue and team scorecards",
          ].map(item => (
            <li key={item} className="flex items-start gap-2">
              <Check size={14} className="text-teal-600 mt-0.5 flex-shrink-0" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>
          Guest phone numbers and emails stay masked. It can never message a guest.
        </p>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-[11px] uppercase tracking-wider font-semibold mb-1" style={{ color: "var(--haip-fg-subtle)" }}>
          Access
        </legend>
        {([
          ["read_write", "Read and update", "Can also move lead stages, assign leads and add notes — it asks you first."],
          ["read_only", "Read only", "Reports and answers only. Can't change anything."],
        ] as const).map(([value, label, hint]) => (
          <label
            key={value}
            className="flex items-start gap-3 rounded-xl px-3 py-2.5 cursor-pointer"
            style={{
              border: `1px solid ${access === value ? "var(--haip-accent)" : "var(--haip-border)"}`,
            }}
          >
            <input
              type="radio"
              name="access"
              value={value}
              checked={access === value}
              onChange={() => setAccess(value)}
              className="mt-1 accent-teal-600"
            />
            <span className="flex flex-col">
              <span className="text-sm font-medium" style={{ color: "var(--haip-fg)" }}>{label}</span>
              <span className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>{hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {error && (
        <div className="flex items-start gap-2 rounded-xl px-3 py-2.5 text-sm bg-red-50 text-red-700">
          <AlertCircle size={15} className="mt-0.5 flex-shrink-0" />
          <span className="flex flex-col gap-1.5 items-start">
            <span>{error}</span>
            {forbidden && (
              <button type="button" onClick={reauthenticate} className="font-semibold underline underline-offset-2">
                Switch to an owner or manager account
              </button>
            )}
          </span>
        </div>
      )}

      <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
        <button
          type="button"
          onClick={() => decide("deny")}
          disabled={!!submitting || isLoading}
          className="px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50"
          style={{ border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
        >
          {submitting === "deny" ? "Cancelling…" : "Cancel"}
        </button>
        <button
          type="button"
          onClick={() => decide("approve")}
          disabled={!!submitting || isLoading}
          className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-teal-600 text-white hover:bg-teal-700 disabled:opacity-50"
        >
          {submitting === "approve" ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
          Allow access
        </button>
      </div>

      <p className="text-[11px] leading-relaxed" style={{ color: "var(--haip-fg-subtle)" }}>
        Every action it takes is recorded in the audit log. Disconnect any time from Settings → AI Assistants.
      </p>
    </div>
  );
}

function Notice({ title, body }: { title: string; body: string }) {
  return (
    <div className="w-full max-w-md rounded-2xl p-6 flex flex-col gap-2" style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)" }}>
      <h1 className="text-lg font-semibold" style={{ color: "var(--haip-fg)" }}>{title}</h1>
      <p className="text-sm" style={{ color: "var(--haip-fg-subtle)" }}>{body}</p>
    </div>
  );
}

export default function ConnectAuthorizePage() {
  return (
    <main className="min-h-dvh flex items-center justify-center px-4 py-10" style={{ background: "var(--haip-app-bg)" }}>
      <Suspense fallback={<Loader2 size={20} className="animate-spin" />}>
        <ConsentCard />
      </Suspense>
    </main>
  );
}
