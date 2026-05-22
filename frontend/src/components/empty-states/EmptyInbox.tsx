import Link from "next/link";
import { MessageSquare, Phone, ArrowRight, Plug2 } from "lucide-react";

export function EmptyInbox() {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60vh] px-6 py-16 text-center">
      <div className="w-20 h-20 rounded-3xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center mb-6">
        <MessageSquare size={32} className="text-teal-400/60" />
      </div>
      <h2 className="text-xl font-bold text-gray-900 mb-2">Your inbox is empty</h2>
      <p className="text-gray-400 text-sm max-w-sm leading-relaxed mb-8">
        Connect WhatsApp or Instagram to start receiving guest messages here. All channels appear in one unified view.
      </p>
      <div className="flex flex-col sm:flex-row gap-3">
        <Link
          href="/dashboard/settings/integrations"
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-teal-500 hover:bg-teal-600 text-white text-sm font-semibold rounded-xl transition-colors shadow-sm shadow-teal-200"
        >
          <Plug2 size={15} /> Connect WhatsApp
        </Link>
        <Link
          href="/dashboard/settings/integrations"
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium rounded-xl transition-colors"
        >
          View integrations <ArrowRight size={15} />
        </Link>
      </div>
      <p className="text-xs text-gray-300 mt-8 max-w-xs leading-relaxed">
        Using the official Meta WhatsApp Cloud API — takes less than 2 minutes to connect.
      </p>
    </div>
  );
}
