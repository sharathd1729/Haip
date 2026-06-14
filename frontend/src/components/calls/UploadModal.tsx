"use client";
import { useState } from "react";
import { Phone, Upload, X } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface UploadModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

type UploadTab = "file" | "transcript";

export function UploadModal({ onClose, onSuccess }: UploadModalProps) {
  const [tab, setTab] = useState<UploadTab>("file");

  // File-upload state
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [guestPhone, setGuestPhone] = useState("");
  const [agentName, setAgentName] = useState("");
  const [direction, setDirection] = useState<"inbound" | "outbound">("inbound");
  const [progress, setProgress] = useState(0);
  const [uploading, setUploading] = useState(false);

  // Transcript-paste state
  const [transcript, setTranscript] = useState("");
  const [agentNameTxt, setAgentNameTxt] = useState("");
  const [analyzingTxt, setAnalyzingTxt] = useState(false);

  // Shared
  const [callId, setCallId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const ACCEPTED = ".mp3,.wav,.m4a,.ogg,.aac,.flac,.webm";

  function pickFile(f: File) {
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["mp3","wav","m4a","ogg","aac","flac","webm"].includes(ext)) {
      setError("Unsupported format. Use MP3, WAV, M4A, OGG, AAC, FLAC or WebM."); return;
    }
    if (f.size > 200 * 1024 * 1024) { setError("File too large (max 200 MB)."); return; }
    setError(""); setFile(f);
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true); setError(""); setProgress(0);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("guest_phone", guestPhone || "+910000000000");
    fd.append("agent_name", agentName);
    fd.append("direction", direction);
    try {
      const res = await api.post("/calls/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (evt: any) => {
          if (evt.total) setProgress(Math.round((evt.loaded / evt.total) * 100));
        },
      });
      setCallId(res.data.call_id);
      setTimeout(onSuccess, 3000);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(Array.isArray(detail)
        ? detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join(", ")
        : detail ?? err?.message ?? "Upload failed — is the backend running?");
      setUploading(false);
    }
  }

  async function handleTranscript(e: React.FormEvent) {
    e.preventDefault();
    setAnalyzingTxt(true); setError("");
    try {
      const fd = new FormData();
      fd.append("transcript", transcript);
      fd.append("agent_name", agentNameTxt || "Unknown Agent");
      const res = await api.post("/analyze/transcript", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setCallId(res.data?.call_id ?? "queued");
      setTimeout(onSuccess, 2000);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Analysis failed.");
      setAnalyzingTxt(false);
    }
  }

  // ── Success screen ────────────────────────────────────────────────────────
  if (callId) {
    return (
      <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
        <div className="rounded-2xl shadow-2xl w-full max-w-md p-8 text-center" style={{ background: "var(--haip-card)" }}>
          <div className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4"
            style={{ background: "color-mix(in srgb, var(--primary) 10%, transparent)" }}>
            <Phone size={24} style={{ color: "var(--primary)" }} />
          </div>
          <h2 className="text-base font-semibold mb-1" style={{ color: "var(--haip-fg)" }}>Pipeline started!</h2>
          <p className="text-xs mb-6" style={{ color: "var(--haip-fg-subtle)" }}>
            Results will appear in the calls list within ~60 seconds.
          </p>
          <div className="space-y-2 text-left mb-6">
            {["Recording saved", "Transcription queued", "AI scoring queued"].map((label, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0"
                  style={{ background: i < 2 ? "var(--primary)" : "var(--muted)", color: i < 2 ? "var(--primary-foreground)" : "var(--haip-fg-subtle)" }}>
                  {i < 2 ? "✓" : i + 1}
                </div>
                <span className="text-sm" style={{ color: i < 2 ? "var(--haip-fg)" : "var(--haip-fg-subtle)" }}>{label}</span>
                {i === 1 && <span className="text-[10px] rounded-full px-2 py-0.5 font-medium animate-pulse"
                  style={{ background: "color-mix(in srgb, var(--primary) 10%, transparent)", color: "var(--primary)" }}>processing…</span>}
              </div>
            ))}
          </div>
          <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>Redirecting to calls list…</p>
        </div>
      </div>
    );
  }

  const inputCls = "w-full px-3 py-2 rounded-md text-sm focus:outline-none focus:ring-2 transition-shadow";
  const inputStyle = { background: "var(--input-bg)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="rounded-xl shadow-2xl w-full max-w-lg" style={{ background: "var(--haip-card)" }}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: "1px solid var(--haip-border)" }}>
          <div>
            <h2 className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>Upload call recording</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>MP3, WAV, M4A, OGG, AAC, FLAC · max 200 MB</p>
          </div>
          <button onClick={onClose} style={{ color: "var(--haip-fg-subtle)" }} className="hover:opacity-70 transition-opacity"><X size={18} /></button>
        </div>

        {/* Tabs */}
        <div className="flex" style={{ borderBottom: "1px solid var(--haip-border)" }}>
          {(["file", "transcript"] as UploadTab[]).map(t => (
            <button key={t} onClick={() => { setTab(t); setError(""); }}
              className="flex-1 py-2.5 text-xs font-medium transition-colors"
              style={{
                borderBottom: tab === t ? `2px solid var(--primary)` : "2px solid transparent",
                color: tab === t ? "var(--primary)" : "var(--haip-fg-subtle)",
              }}>
              {t === "file" ? "🎙 Audio file" : "📝 Paste transcript"}
            </button>
          ))}
        </div>

        {error && (
          <div className="mx-6 mt-4 p-3 rounded-lg text-xs" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "var(--haip-red)" }}>
            {error}
          </div>
        )}

        {/* File tab */}
        {tab === "file" && (
          <form onSubmit={handleUpload} className="p-6 space-y-4">
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) pickFile(f); }}
              onClick={() => document.getElementById("audio-file-input")?.click()}
              className="relative rounded-xl p-8 text-center cursor-pointer transition-all"
              style={{
                border: `2px dashed ${dragging || file ? "var(--primary)" : "var(--haip-border)"}`,
                background: dragging || file ? "color-mix(in srgb, var(--primary) 4%, transparent)" : "var(--muted)",
              }}
            >
              <input id="audio-file-input" type="file" accept={ACCEPTED} className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) pickFile(f); }} />
              {file ? (
                <div className="flex items-center justify-center gap-3">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ background: "color-mix(in srgb, var(--primary) 12%, transparent)" }}>
                    <Phone size={18} style={{ color: "var(--primary)" }} />
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-medium truncate max-w-[200px]" style={{ color: "var(--haip-fg)" }}>{file.name}</p>
                    <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
                  </div>
                  <button type="button" onClick={e => { e.stopPropagation(); setFile(null); }} style={{ color: "var(--haip-fg-subtle)" }} className="ml-auto"><X size={16} /></button>
                </div>
              ) : (
                <>
                  <Upload size={24} className="mx-auto mb-2" style={{ color: "var(--haip-fg-subtle)" }} />
                  <p className="text-sm font-medium" style={{ color: "var(--haip-fg-muted)" }}>Drop audio file here</p>
                  <p className="text-xs mt-1" style={{ color: "var(--haip-fg-subtle)" }}>or click to browse</p>
                </>
              )}
            </div>

            {uploading && (
              <div>
                <div className="flex justify-between text-xs mb-1" style={{ color: "var(--haip-fg-subtle)" }}>
                  <span>{progress < 100 ? "Uploading…" : "Processing…"}</span><span>{progress}%</span>
                </div>
                <div className="w-full h-1.5 rounded-full" style={{ background: "var(--muted)" }}>
                  <div className="h-1.5 rounded-full transition-all duration-300" style={{ width: `${progress}%`, background: "var(--primary)" }} />
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: "var(--haip-fg-muted)" }}>Guest phone</label>
                <input value={guestPhone} onChange={e => setGuestPhone(e.target.value)} placeholder="+91 98765 43210" className={inputCls} style={inputStyle} />
              </div>
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: "var(--haip-fg-muted)" }}>Agent name</label>
                <input value={agentName} onChange={e => setAgentName(e.target.value)} placeholder="Ravi Kumar" className={inputCls} style={inputStyle} />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: "var(--haip-fg-muted)" }}>Call direction</label>
              <div className="flex gap-2">
                {(["inbound", "outbound"] as const).map(d => (
                  <button key={d} type="button" onClick={() => setDirection(d)}
                    className="flex-1 py-2 rounded-lg text-xs font-medium border transition-colors capitalize"
                    style={direction === d
                      ? { background: "color-mix(in srgb, var(--primary) 8%, transparent)", borderColor: "var(--primary)", color: "var(--primary)" }
                      : { background: "transparent", borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}>
                    {d === "inbound" ? "↙ Inbound" : "↗ Outbound"}
                  </button>
                ))}
              </div>
            </div>

            <button type="submit" disabled={!file || uploading}
              className="w-full py-2.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-40"
              style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}>
              {uploading ? "Uploading…" : "Upload & analyze →"}
            </button>
          </form>
        )}

        {/* Transcript tab */}
        {tab === "transcript" && (
          <form onSubmit={handleTranscript} className="p-6 space-y-4">
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--haip-fg-muted)" }}>Agent name</label>
              <input value={agentNameTxt} onChange={e => setAgentNameTxt(e.target.value)} placeholder="Ravi Kumar" className={inputCls} style={inputStyle} />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--haip-fg-muted)" }}>Paste transcript</label>
              <textarea required value={transcript} onChange={e => setTranscript(e.target.value)} rows={8}
                placeholder={"Agent: Good morning, HAIP Villa. How can I help?\nGuest: Hi, I'd like to book…"}
                className={`${inputCls} font-mono resize-none`} style={inputStyle} />
            </div>
            <button type="submit" disabled={analyzingTxt}
              className="w-full py-2.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
              style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}>
              {analyzingTxt ? "Analyzing…" : "Analyze with AI →"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
