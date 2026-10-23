// The one valid-lead badge (lead_validity, KPI D-28): a person's review wins, else the workspace's automatic rule; B2B /
// partner enquiries are never valid guest leads. Shown on Leads cards and the table. Nothing when nobody reviewed it and
// the rule is off.
import { cn } from "@/lib/utils";

export interface LeadValidity {
  enabled: boolean; auto_valid: boolean | null; reasons: string[]; notes: string[]; location: string | null;
  location_field?: string; status: "valid" | "invalid" | null; source: "person" | "rule" | "type" | null;
}

export function validityLabel(v?: LeadValidity | null): string | null {
  if (!v?.status) return null;
  const who = v.source === "person" ? "reviewed" : v.source === "rule" ? "by rule" : "not a guest";
  return `${v.status === "valid" ? "Valid" : "Invalid"} · ${who}`;
}

export function ValidityBadge({ validity }: { validity?: LeadValidity | null }) {
  const label = validityLabel(validity);
  if (!label || !validity) return null;
  const title = validity.status === "invalid" && validity.reasons.length ? validity.reasons.join(", ") : validity.notes.join(", ") || undefined;
  return (
    <span title={title}
      className={cn("whitespace-nowrap rounded-full border px-1.5 py-0.5 text-[10px] font-semibold",
        validity.status === "valid"
          ? "border-[var(--haip-status-success-border)] bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]"
          : "border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]")}>
      {label}
    </span>
  );
}
