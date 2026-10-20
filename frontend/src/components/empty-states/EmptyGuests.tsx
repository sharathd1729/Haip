import Link from "next/link";
import { Users, Upload, ArrowRight } from "@/lib/icons";

export function EmptyGuests() {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60dvh] px-6 py-16 text-center">
      <div className="w-20 h-20 rounded-3xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center mb-6">
        <Users size={32} className="text-purple-400/60" />
      </div>
      <h2 className="text-xl font-bold text-[var(--haip-fg)] mb-2">No guests yet</h2>
      <p className="text-[var(--haip-fg-subtle)] text-sm max-w-sm leading-relaxed mb-8">
        Guest profiles are created automatically when you receive WhatsApp messages or calls.
        You can also import your existing guest list.
      </p>
      <div className="flex flex-col sm:flex-row gap-3">
        <button className="inline-flex items-center gap-2 px-5 py-2.5 bg-purple-500 hover:bg-purple-600 text-white text-sm font-semibold rounded-xl transition-colors">
          <Upload size={15} /> Import guests (CSV)
        </button>
        <Link
          href="/dashboard/settings/integrations"
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-[var(--haip-status-neutral-bg)] hover:bg-[var(--haip-border)] text-[var(--haip-fg-2)] text-sm font-medium rounded-xl transition-colors"
        >
          Connect WhatsApp <ArrowRight size={15} />
        </Link>
      </div>
    </div>
  );
}
