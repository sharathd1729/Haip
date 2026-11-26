"use client";
// Send new leads to a Google Sheet (backend google_sheets_service). No Google login: the owner deploys a short Apps Script
// as a web app and pastes its address; HAIP adds one row per new lead.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, FileSpreadsheet } from "@/lib/icons";
import api from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { errorMessage } from "@/lib/bookings";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

interface SheetStatus {
  enabled: boolean; connected: boolean; url_hint: string | null; last_sent_at: string | null; rows_sent: number;
  last_error: string | null; last_error_at: string | null;
}

const SCRIPT = `// HAIP: new leads -> this sheet. Paste into Extensions > Apps Script and save.
function doPost(e) {
  const lead = JSON.parse(e.postData.contents);
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Created", "Name", "Phone", "Source", "Stage", "First message"]);
  }
  sheet.appendRow([lead.created_at, lead.name, lead.phone, lead.source, lead.stage, lead.first_message]);
  return ContentService.createTextOutput("ok");
}

function doGet() {
  return ContentService.createTextOutput("HAIP lead sheet is ready");
}`;

const URL_RE = /^https:\/\/script\.google\.com\/macros\/s\/[A-Za-z0-9_-]{20,200}\/exec$/;
const btn = "min-h-11 px-4 rounded-lg text-sm font-semibold disabled:opacity-50";

function CodeBlock() {
  const [done, setDone] = useState(false);
  return (
    <div className="relative">
      <pre className="max-h-60 overflow-auto rounded-xl border border-[var(--haip-border)] bg-[var(--haip-surface)] p-3 pr-24 text-[12px] leading-relaxed font-mono text-[var(--haip-fg-2)] whitespace-pre-wrap break-words">{SCRIPT}</pre>
      <button type="button"
        onClick={async () => { try { await navigator.clipboard.writeText(SCRIPT); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* select by hand */ } }}
        className="absolute right-2 top-2 min-h-9 flex items-center gap-1 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-xs font-semibold">
        {done ? <Check size={12} /> : <Copy size={12} />} {done ? "Copied" : "Copy code"}
      </button>
    </div>
  );
}

export function GoogleSheetsCard({ isOwner, canView }: { isOwner: boolean; canView: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [setup, setSetup] = useState(false);
  const [url, setUrl] = useState("");
  const key = ["google-sheets"];
  const { data, isLoading, isError, refetch } = useQuery<SheetStatus>({
    queryKey: key, enabled: canView, queryFn: () => api.get("/google-sheets").then(r => r.data),
  });
  const save = useMutation({
    mutationFn: (body: { url?: string; enabled: boolean }) => api.put<SheetStatus>("/google-sheets", body).then(r => r.data),
    onSuccess: (res, body) => {
      qc.setQueryData(key, res);
      setUrl("");
      if (body.url) setSetup(false);
      toast({ variant: "success", title: res.enabled ? "New leads will go to your sheet" : "Stopped sending leads to the sheet" });
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not save") }),
  });
  const test = useMutation({
    mutationFn: () => api.post<SheetStatus & { ok: boolean; message: string }>("/google-sheets/test").then(r => r.data),
    onSuccess: res => {
      qc.setQueryData(key, res);
      toast({ variant: res.ok ? "success" : "error", title: res.ok ? "Test row sent" : "The sheet did not accept the test row", description: res.message });
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not send the test row") }),
  });

  if (!canView) return null;
  const urlOk = URL_RE.test(url.trim());
  const showSetup = setup || (data && !data.connected);

  return (
    <Card>
      <CardHeader icon={FileSpreadsheet} title="Send new leads to a Google Sheet"
        description="Every new lead becomes a row: name, phone, source, time, stage and their first message."
        actions={data?.connected ? <StatusPill tone={data.enabled ? "success" : "neutral"}>{data.enabled ? "On" : "Off"}</StatusPill> : undefined} />
      <CardBody className="space-y-4">
        {isLoading ? <Skeleton className="h-20 rounded-xl" /> : isError ? (
          <div className="flex flex-wrap items-center gap-3 text-sm text-[var(--haip-status-danger-fg)]">
            Could not load this setting.
            <button type="button" onClick={() => refetch()} className={cn(btn, "border border-[var(--haip-border)] text-[var(--haip-fg)]")}>Try again</button>
          </div>
        ) : data && (
          <>
            {data.connected && (
              <div className="space-y-3">
                <label className="flex items-start gap-3 text-sm cursor-pointer">
                  <input type="checkbox" role="switch" checked={data.enabled} disabled={!isOwner || save.isPending}
                    onChange={e => save.mutate({ enabled: e.target.checked })} className="mt-0.5 size-5 shrink-0 accent-[var(--primary)]" />
                  <span>
                    <span className="font-semibold text-[var(--haip-fg)]">Send new leads to the sheet</span>
                    <span className="block text-[13px] text-[var(--haip-fg-subtle)]">A row is added the moment someone shares their phone number.</span>
                  </span>
                </label>
                <p className="text-[13px] text-[var(--haip-fg-subtle)]">
                  {data.last_sent_at ? `Last row sent ${timeAgo(data.last_sent_at)}` : "No rows sent yet"}
                  {data.rows_sent ? ` · ${data.rows_sent} lead${data.rows_sent === 1 ? "" : "s"} so far` : ""}
                  {data.url_hint ? <> · <span className="font-mono">{data.url_hint}</span></> : null}
                </p>
                {data.last_error && (
                  <p className="rounded-lg border border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] px-3 py-2 text-[13px] text-[var(--haip-status-danger-fg)]">
                    Last try {timeAgo(data.last_error_at)} failed: {data.last_error}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => test.mutate()} disabled={test.isPending}
                    className={cn(btn, "border border-[var(--haip-border)] text-[var(--haip-fg)] hover:bg-[var(--haip-surface)]")}>
                    {test.isPending ? "Sending..." : "Send a test row"}
                  </button>
                  {isOwner && !setup && (
                    <button type="button" onClick={() => setSetup(true)} className={cn(btn, "text-primary hover:underline")}>Change sheet</button>
                  )}
                </div>
              </div>
            )}

            {showSetup && !isOwner && <p className="text-[13px] text-[var(--haip-fg-subtle)]">Ask the account owner to connect a sheet.</p>}
            {showSetup && isOwner && (
              !setup && !data.connected ? (
                <div className="flex flex-col items-start gap-2">
                  <p className="text-[13px] text-[var(--haip-fg-subtle)]">Takes about 3 minutes. No Google login needed in HAIP.</p>
                  <button type="button" onClick={() => setSetup(true)} className={cn(btn, "bg-primary text-white")}>Connect a sheet</button>
                </div>
              ) : (
                <ol className="list-decimal space-y-3 pl-5 text-sm text-[var(--haip-fg-2)]">
                  <li>Open the Google Sheet you want, then <b>Extensions &gt; Apps Script</b>.</li>
                  <li>Delete what is there, paste this code and press <b>Save</b>.
                    <div className="mt-2 -ml-5"><CodeBlock /></div>
                  </li>
                  <li><b>Deploy &gt; New deployment</b>, type <b>Web app</b>. Execute as <b>Me</b>, who has access <b>Anyone</b>. Press Deploy and allow access.</li>
                  <li>Copy the <b>Web app URL</b> and paste it here.
                    <div className="mt-2 -ml-5 space-y-2">
                      <input value={url} onChange={e => setUrl(e.target.value)} inputMode="url" autoComplete="off"
                        placeholder="https://script.google.com/macros/s/.../exec"
                        className="w-full min-h-11 rounded-lg border border-[var(--haip-border)] px-3 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-primary" />
                      {url.trim() && !urlOk && (
                        <p className="text-[13px] text-[var(--haip-status-danger-fg)]">This should start with https://script.google.com/macros/s/ and end with /exec.</p>
                      )}
                      <div className="flex flex-wrap gap-2">
                        <button type="button" disabled={!urlOk || save.isPending} onClick={() => save.mutate({ url: url.trim(), enabled: true })}
                          className={cn(btn, "bg-primary text-white")}>
                          {save.isPending ? "Saving..." : "Save and turn on"}
                        </button>
                        {data.connected && (
                          <button type="button" onClick={() => { setSetup(false); setUrl(""); }} className={cn(btn, "text-[var(--haip-fg-subtle)]")}>Cancel</button>
                        )}
                      </div>
                    </div>
                  </li>
                  <li>Press <b>Send a test row</b> and check the sheet.</li>
                </ol>
              )
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
