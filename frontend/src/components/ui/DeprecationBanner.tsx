import Link from "next/link";
import { ArrowLeft } from "lucide-react";

interface Props {
  message?: string;
  href?: string;
}

export function DeprecationBanner({
  message = "This view is now available as a dashboard widget.",
  href = "/dashboard",
}: Props) {
  return (
    <div
      className="flex items-center gap-2 px-4 py-2 text-[11px]"
      style={{ background: "color-mix(in srgb, var(--primary) 8%, transparent)", borderBottom: "1px solid var(--haip-border)" }}
    >
      <span style={{ color: "var(--haip-fg-subtle)" }}>{message}</span>
      <Link
        href={href}
        className="flex items-center gap-1 font-medium"
        style={{ color: "var(--primary)" }}
      >
        <ArrowLeft size={10} />
        Back to Dashboard
      </Link>
    </div>
  );
}
