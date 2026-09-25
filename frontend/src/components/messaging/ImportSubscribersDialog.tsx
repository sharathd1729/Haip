"use client";
import { useRef, useState } from "react";
import { X, Upload, Download, Loader2, AlertCircle, CheckCircle2 } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface ImportResult {
  total_rows: number; added: number; updated: number; opted_out_skipped: number;
  duplicates_in_file: number; invalid_count: number;
  invalid: { row: number; value: string; reason: string }[];
}

const MAX_MB = 2;

function saveCsv(filename: string, rows: string[][]) {
  const csv = rows.map(r => r.map(c => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8;" }));
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

const today = () => new Date().toISOString().slice(0, 10);

export function ImportSubscribersDialog({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [tag, setTag] = useState(`import-${today()}`);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);

  const pick = (f: File | undefined) => {
    setError("");
    if (!f) return;
    if (f.size > MAX_MB * 1024 * 1024) { setError(`That file is ${(f.size / 1048576).toFixed(1)} MB. The limit is ${MAX_MB} MB — split it into smaller files.`); return; }
    setFile(f);
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("consent", String(consent));
      if (tag.trim()) fd.append("tag", tag.trim());
      const res = await api.post("/messaging/subscribers/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(res.data);
      onImported();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Import failed. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  const Stat = ({ label, value, tone }: { label: string; value: number; tone: string }) => (
    <div className="rounded-xl bg-gray-50 p-3">
      <p className={cn("text-2xl font-bold tabular-nums", tone)}>{value.toLocaleString()}</p>
      <p className="text-[10px] text-gray-500 mt-0.5">{label}</p>
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4" role="dialog" aria-modal="true" aria-label="Import contacts">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[92vh] flex flex-col overflow-hidden">
        <div className="px-6 pt-5 pb-4 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-base font-bold text-gray-900">Import contacts</h2>
            <p className="text-xs text-gray-400 mt-0.5">Add people to your WhatsApp list from a CSV file.</p>
          </div>
          <button onClick={onClose} aria-label="Close"><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>

        <div className="p-6 space-y-5 overflow-y-auto">
          {!result ? (
            <>
              <div>
                <input ref={fileRef} type="file" accept=".csv,text/csv" className="sr-only" onChange={e => { pick(e.target.files?.[0]); e.target.value = ""; }} />
                <button type="button" onClick={() => fileRef.current?.click()}
                  className="w-full flex flex-col items-center justify-center gap-1.5 py-7 border-2 border-dashed border-gray-200 rounded-xl text-gray-500 hover:border-teal-300 hover:bg-teal-50/40 transition-colors">
                  <Upload size={18} />
                  <span className="text-xs font-medium">{file ? file.name : "Choose a CSV file"}</span>
                  <span className="text-[10px] text-gray-400">{file ? `${(file.size / 1024).toFixed(0)} KB — click to change` : `Up to ${MAX_MB} MB · 20,000 contacts`}</span>
                </button>
                <div className="mt-2 flex items-center justify-between text-[11px] text-gray-500">
                  <span>One contact per row. Needs a <strong>phone</strong> column; <strong>name</strong> and <strong>tags</strong> are optional.</span>
                  <button type="button" onClick={() => saveCsv("contacts-sample.csv", [["phone", "name", "tags"], ["9876543210", "Priya Sharma", "vip|goa"], ["+91 98220 11111", "Arjun Rao", ""]])}
                    className="flex items-center gap-1 text-teal-600 hover:underline flex-shrink-0 ml-3"><Download size={11} /> Sample</button>
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5" htmlFor="import-tag">Tag for this file <span className="text-gray-400 font-normal">(optional)</span></label>
                <input id="import-tag" value={tag} maxLength={40} onChange={e => setTag(e.target.value)}
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
                <p className="text-[10px] text-gray-400 mt-1">Everyone in the file gets this tag, so you can pick exactly them as a campaign audience.</p>
              </div>

              <label className={cn("flex items-start gap-2.5 p-3 rounded-xl border cursor-pointer text-xs", consent ? "border-teal-300 bg-teal-50/50" : "border-gray-200")}>
                <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} className="mt-0.5 accent-teal-600" />
                <span className="text-gray-700 leading-snug">
                  I confirm these contacts have agreed to receive WhatsApp messages from us.
                  <span className="block text-[10px] text-gray-400 mt-0.5">Sending marketing to people who haven't is how numbers get blocked. Anyone who already opted out stays opted out.</span>
                </span>
              </label>

              {error && <p className="flex items-start gap-1.5 text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2"><AlertCircle size={13} className="mt-0.5 flex-shrink-0" />{error}</p>}
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 text-sm font-semibold text-green-700"><CheckCircle2 size={16} /> Import finished — {result.total_rows.toLocaleString()} rows read</div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <Stat label="Added" value={result.added} tone="text-teal-600" />
                <Stat label="Already on your list, updated" value={result.updated} tone="text-gray-900" />
                <Stat label="Skipped: opted out earlier" value={result.opted_out_skipped} tone="text-amber-600" />
                <Stat label="Repeated in the file" value={result.duplicates_in_file} tone="text-gray-500" />
                <Stat label="Rows with a problem" value={result.invalid_count} tone={result.invalid_count ? "text-red-600" : "text-gray-400"} />
              </div>
              {result.opted_out_skipped > 0 && (
                <p className="text-[11px] text-gray-500">People who opted out are not added back, even if they're in your file.</p>
              )}
              {result.invalid_count > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-semibold text-gray-700">Rows that couldn't be imported</p>
                    <button onClick={() => saveCsv("import-problems.csv", [["row", "value", "problem"], ...result.invalid.map(i => [String(i.row), i.value, i.reason])])}
                      className="flex items-center gap-1 text-[11px] text-teal-600 hover:underline"><Download size={11} /> Download list</button>
                  </div>
                  <ul className="border border-gray-100 rounded-xl divide-y divide-gray-50 max-h-44 overflow-y-auto text-[11px]">
                    {result.invalid.slice(0, 50).map(i => (
                      <li key={i.row} className="px-3 py-1.5 flex gap-2"><span className="text-gray-400 w-12 flex-shrink-0">Row {i.row}</span><span className="font-mono text-gray-700 truncate">{i.value || "—"}</span><span className="text-red-600 ml-auto text-right">{i.reason}</span></li>
                    ))}
                  </ul>
                  {result.invalid_count > 50 && <p className="text-[10px] text-gray-400 mt-1">Showing the first 50. Download the list for the rest.</p>}
                </div>
              )}
              {tag.trim() && result.added + result.updated > 0 && (
                <p className="text-xs text-gray-600 bg-teal-50 rounded-xl px-3 py-2">
                  Tagged <strong>{tag.trim()}</strong>. Pick that tag under <em>Audience</em> when you create a campaign to message just these contacts.
                </p>
              )}
            </>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2 flex-shrink-0">
          {!result ? (
            <>
              <button onClick={onClose} className="px-4 py-2 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
              <button onClick={submit} disabled={!file || !consent || busy}
                className="px-5 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">
                {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} Import
              </button>
            </>
          ) : (
            <button onClick={onClose} className="px-5 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600">Done</button>
          )}
        </div>
      </div>
    </div>
  );
}
