"use client";
// Google Sheets and Zapier on top of HAIP's signed webhooks and API keys (WhatsApp step 4). No extra login: the owner
// adds a webhook endpoint below with the Apps Script or Zapier "Catch Hook" address and picks the events.
import { useMemo, useState } from "react";
import { Check, Copy } from "@/lib/icons";
import { cn } from "@/lib/utils";

function randomKey(): string {
  const bytes = new Uint8Array(18);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
}

// Apps Script can't read request headers, so a private key in the address guards it instead of the signature.
function appsScript(key: string): string {
  return `// HAIP -> Google Sheets. Paste into Extensions > Apps Script, then Deploy > New deployment > Web app
// (Execute as: Me, Who has access: Anyone). One tab per event type; new columns are added as they appear.
const KEY = "${key}";

function doPost(e) {
  if ((e.parameter.key || "") !== KEY) return ContentService.createTextOutput("forbidden");
  const evt = JSON.parse(e.postData.contents);
  const book = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = book.getSheetByName(evt.type) || book.insertSheet(evt.type);
  const row = flatten({ event_id: evt.id, received_at: evt.created_at, ...evt.data });
  let headers = sheet.getLastRow() ? sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0] : [];
  Object.keys(row).forEach(k => { if (headers.indexOf(k) < 0) headers.push(k); });
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.appendRow(headers.map(h => row[h] === undefined ? "" : row[h]));
  return ContentService.createTextOutput("ok");
}

function flatten(obj, prefix, out) {
  out = out || {};
  Object.keys(obj || {}).forEach(k => {
    const v = obj[k], key = prefix ? prefix + "." + k : k;
    if (v && typeof v === "object" && !Array.isArray(v)) flatten(v, key, out);
    else out[key] = Array.isArray(v) ? JSON.stringify(v) : v;
  });
  return out;
}`;
}

function CopyBlock({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="relative">
      <pre className="max-h-64 overflow-auto rounded-xl bg-[var(--haip-surface)] border border-[var(--haip-border)] p-3 text-[11.5px] leading-relaxed font-mono text-[var(--haip-fg-2)] whitespace-pre-wrap break-words">{text}</pre>
      <button type="button" onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* select by hand */ } }}
        className="absolute right-2 top-2 min-h-9 flex items-center gap-1 text-xs font-semibold border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 rounded-lg">
        {done ? <Check size={12} /> : <Copy size={12} />} {done ? "Copied" : label}
      </button>
    </div>
  );
}

export function ConnectorGuides() {
  const [tab, setTab] = useState<"sheets" | "zapier">("sheets");
  const key = useMemo(randomKey, []);
  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-[var(--haip-fg)]">Google Sheets and Zapier</h2>
        <p className="text-xs text-[var(--haip-fg-subtle)]">Send new leads, bookings, payments and messages to a spreadsheet or any Zapier app, using the webhooks below.</p>
      </div>
      <div className="inline-flex rounded-xl bg-[var(--haip-status-neutral-bg)] p-0.5" role="tablist" aria-label="Connector">
        {([["sheets", "Google Sheets"], ["zapier", "Zapier"]] as const).map(([v, label]) => (
          <button key={v} type="button" role="tab" aria-selected={tab === v} onClick={() => setTab(v)}
            className={cn("min-h-9 px-3 rounded-[10px] text-xs font-medium", tab === v ? "bg-white text-[var(--haip-fg)] shadow-sm" : "text-[var(--haip-fg-subtle)]")}>
            {label}
          </button>
        ))}
      </div>
      {tab === "sheets" ? (
        <ol className="list-decimal pl-5 space-y-2 text-xs text-[var(--haip-fg-2)]">
          <li>Open a Google Sheet, then Extensions &gt; Apps Script. Replace everything with the code below and save.</li>
          <li>Deploy &gt; New deployment &gt; Web app. Execute as <b>Me</b>, access <b>Anyone</b>. Copy the web app address.</li>
          <li>Below, add a webhook endpoint with that address plus <span className="font-mono">?key={key.slice(0, 6)}…</span> (the full key is in the code), and tick <b>lead.created</b> and any other events.</li>
          <li className="list-none -ml-5"><CopyBlock text={appsScript(key)} label="Copy code" /></li>
          <li className="list-none -ml-5 text-[11.5px] text-[var(--haip-fg-subtle)]">Endpoint address: <span className="font-mono break-all">https://script.google.com/macros/s/…/exec?key={key}</span></li>
        </ol>
      ) : (
        <ol className="list-decimal pl-5 space-y-2 text-xs text-[var(--haip-fg-2)]">
          <li>In Zapier, start a Zap with <b>Webhooks by Zapier &gt; Catch Hook</b> and copy its address.</li>
          <li>Below, add a webhook endpoint with that address and tick the events you want (for example <b>lead.created</b>, <b>booking.created</b>).</li>
          <li>Press <b>Send test event</b> on the endpoint, then map the fields in Zapier (lead name, phone, booking dates and amount).</li>
          <li>For actions back into HAIP (send a WhatsApp template, list bookings), create an API key above and use <b>Webhooks by Zapier &gt; POST</b> against the public API docs.</li>
        </ol>
      )}
    </div>
  );
}
